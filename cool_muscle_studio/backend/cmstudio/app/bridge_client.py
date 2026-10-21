"""Client TCP d'un pont cm1_bridge : connexion, reconnexion, diffusion des événements."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any

from .. import protocol as P

log = logging.getLogger("cmstudio.bridge")

HISTORY = 2000
RECONNECT_MIN = 1.0
RECONNECT_MAX = 15.0
PING_INTERVAL = 10.0


@dataclass
class Event:
    """Événement diffusé aux abonnés (terminal, journal)."""

    seq: int
    t: float            # horloge murale (epoch, secondes)
    type: str           # rx | tx | state | refused | err | conn | pong
    ms: int | None = None
    line: str = ""
    origin: str = ""    # pour tx : LOCAL / C<n> ; pour conn : raison
    echo: bool = False  # rx identique à la dernière ligne envoyée
    mode: str | None = None
    busy: bool | None = None
    code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None and v != ""} | {"line": self.line}


@dataclass
class BridgeState:
    connected: bool = False
    mode: str = P.MODE_NORMAL
    busy: bool = False
    my_client: str | None = None
    protocol_version: int | None = None
    last_error: str | None = None
    reconnects: int = 0


class BridgeClient:
    def __init__(self, name: str, host: str, port: int) -> None:
        self.name = name
        self.host = host
        self.port = port
        self.state = BridgeState()
        self.history: deque[Event] = deque(maxlen=HISTORY)
        self._subscribers: list[asyncio.Queue[Event]] = []
        self._seq = 0
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._task: asyncio.Task | None = None
        self._last_tx: tuple[float, str] | None = None
        self._pending_echo: deque[tuple[float, str]] = deque(maxlen=8)
        self._lock = asyncio.Lock()
        self._maint_waiters: list[asyncio.Future] = []

    # ------------------------------------------------------------------ cycle de vie
    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name=f"bridge-{self.name}")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        await self._close()

    async def _close(self) -> None:
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
        self._writer = None
        self._reader = None
        if self.state.connected:
            self.state.connected = False
            self._emit(Event(0, time.time(), "conn", origin="deconnecte"))

    async def _run(self) -> None:
        delay = RECONNECT_MIN
        while True:
            try:
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port), timeout=5.0)
                delay = RECONNECT_MIN
                self.state.last_error = None
                await self._session()
            except asyncio.CancelledError:
                raise
            except (OSError, asyncio.TimeoutError) as exc:
                self.state.last_error = str(exc) or exc.__class__.__name__
                log.warning("pont %s : connexion impossible (%s)", self.name, self.state.last_error)
            except Exception as exc:  # pragma: no cover - défensif
                self.state.last_error = repr(exc)
                log.exception("pont %s : erreur de session", self.name)
            await self._close()
            self.state.reconnects += 1
            await asyncio.sleep(delay)
            delay = min(RECONNECT_MAX, delay * 2)

    async def _session(self) -> None:
        assert self._reader is not None
        self.state.connected = True
        self._emit(Event(0, time.time(), "conn", origin="connecte"))
        ping_task = asyncio.create_task(self._pinger())
        try:
            while True:
                raw = await self._reader.readline()
                if not raw:
                    raise ConnectionError("connexion fermée par le pont")
                self._handle(raw.decode("utf-8", "replace"))
        finally:
            ping_task.cancel()

    async def _pinger(self) -> None:
        while True:
            await asyncio.sleep(PING_INTERVAL)
            try:
                await self._write(P.ping())
            except ConnectionError:
                return

    # ------------------------------------------------------------------ réception
    def _handle(self, raw: str) -> None:
        try:
            msg = P.parse_bridge_line(raw)
        except P.ProtocolError as exc:
            log.warning("pont %s : %s", self.name, exc)
            return
        now = time.time()
        if isinstance(msg, P.Hello):
            self.state.protocol_version = msg.version
            self.state.mode = msg.mode
            self.state.busy = msg.busy
            self._emit(Event(0, now, "state", mode=msg.mode, busy=msg.busy, origin="hello"))
        elif isinstance(msg, P.RxLine):
            echo = self._is_echo(msg.line)
            self._emit(Event(0, now, "rx", ms=msg.ms, line=msg.line, echo=echo))
        elif isinstance(msg, P.TxLine):
            if msg.origin != "LOCAL" and self.state.my_client is None and self._pending_echo:
                # première ligne envoyée par nous et renvoyée par le pont : on apprend notre nom de client
                if any(line == msg.line for _, line in self._pending_echo):
                    self.state.my_client = msg.origin
            self._pending_echo.append((now, msg.line))
            self._emit(Event(0, now, "tx", ms=msg.ms, line=msg.line, origin=msg.origin))
        elif isinstance(msg, P.State):
            self.state.mode = msg.mode
            self.state.busy = msg.busy
            self._emit(Event(0, now, "state", ms=msg.ms, mode=msg.mode, busy=msg.busy))
            self._resolve_maint(msg.mode)
        elif isinstance(msg, P.MaintRefused):
            self._emit(Event(0, now, "refused", ms=msg.ms, origin=msg.reason, line=msg.reason))
            self._resolve_maint(None, msg.reason)
        elif isinstance(msg, P.Error):
            self._emit(Event(0, now, "err", ms=msg.ms, code=msg.code, line=msg.text))
        elif isinstance(msg, P.Pong):
            pass
        else:
            self._emit(Event(0, now, "err", code="UNKNOWN", line=msg.raw))

    def _is_echo(self, line: str) -> bool:
        now = time.time()
        for t, sent in self._pending_echo:
            if sent == line and now - t < 2.0:
                return True
        return False

    def _emit(self, ev: Event) -> None:
        self._seq += 1
        ev.seq = self._seq
        self.history.append(ev)
        for q in list(self._subscribers):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                pass

    # ------------------------------------------------------------------ abonnés
    def subscribe(self) -> asyncio.Queue[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue(maxsize=5000)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Event]) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    # ------------------------------------------------------------------ émission
    async def _write(self, text: str) -> None:
        if self._writer is None or self._writer.is_closing():
            raise ConnectionError(f"pont {self.name} non connecté")
        async with self._lock:
            self._writer.write(text.encode("utf-8"))
            await self._writer.drain()

    async def send(self, line: str) -> None:
        """Envoie une ligne CML (le pont décide d'accepter ou non)."""
        await self._write(P.tx(line))

    async def set_maintenance(self, on: bool, timeout: float = 3.0) -> tuple[bool, str]:
        """Demande le mode maintenance et attend la réponse du pont (état ou refus)."""
        if self.state.mode == (P.MODE_MAINT if on else P.MODE_NORMAL):
            return True, self.state.mode
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._maint_waiters.append(fut)
        try:
            await self._write(P.maint(on))
            mode, reason = await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            return False, "TIMEOUT"
        finally:
            if fut in self._maint_waiters:
                self._maint_waiters.remove(fut)
        if reason:
            return False, reason
        return mode == (P.MODE_MAINT if on else P.MODE_NORMAL), mode or ""

    def _resolve_maint(self, mode: str | None, reason: str | None = None) -> None:
        for fut in self._maint_waiters:
            if not fut.done():
                fut.set_result((mode, reason))
        self._maint_waiters.clear()

    async def wait_for_rx(self, predicate, timeout: float = 1.0) -> list[Event]:
        """Attend des lignes RX jusqu'à ce que ``predicate`` soit vrai ; renvoie les RX vues."""
        q = self.subscribe()
        seen: list[Event] = []
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        try:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return seen
                try:
                    ev = await asyncio.wait_for(q.get(), remaining)
                except asyncio.TimeoutError:
                    return seen
                if ev.type == "rx":
                    seen.append(ev)
                    if predicate(ev.line):
                        return seen
        finally:
            self.unsubscribe(q)

    def snapshot(self) -> dict[str, Any]:
        return {
            "nom": self.name,
            "hote": self.host,
            "port": self.port,
            **asdict(self.state),
        }
