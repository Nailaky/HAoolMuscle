"""Serveurs TCP du simulateur : face « moteur nu » et face « pont cm1_bridge »."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

from .. import protocol as P
from .chain import MotorChain

log = logging.getLogger("cm1sim")

TICK_MS = 10.0
RE_READ_ONLY = re.compile(r"^\s*(\?[A-Za-z0-9]*(\.\d+)?|[PSAMTVNRHK]\d+(\.\d+)?|_SKH(\.\d+)?|\*1?(\.\d+)?)\s*$", re.I)


def is_read_only(line: str) -> bool:
    """Vrai si toutes les instructions de la ligne sont des lectures ou l'arrêt d'urgence."""
    parts = [p for p in line.split(",") if p.strip()]
    return bool(parts) and all(RE_READ_ONLY.match(p) for p in parts)


@dataclass
class _Client:
    index: int
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter

    @property
    def name(self) -> str:
        return f"C{self.index}"

    def send(self, text: str) -> None:
        if self.writer.is_closing():
            return
        try:
            self.writer.write(text.encode("utf-8", "replace"))
        except (ConnectionError, RuntimeError):
            pass


class Simulator:
    """Un simulateur = une chaîne de moteurs + un serveur TCP (raw ou bridge)."""

    def __init__(
        self,
        mode: str = "bridge",
        host: str = "127.0.0.1",
        port: int = 0,
        chain: MotorChain | None = None,
        motors: int = 1,
        emulate_esp: bool = True,
        maint_timeout_s: float = 60.0,
        verbose: bool = False,
        **motor_kwargs,
    ) -> None:
        if mode not in ("raw", "bridge"):
            raise ValueError("mode doit être 'raw' ou 'bridge'")
        self.mode = mode
        self.host = host
        self.port = port
        self.chain = chain or MotorChain(count=motors, **motor_kwargs)
        self.emulate_esp = emulate_esp
        self.maint_timeout_s = maint_timeout_s
        self.verbose = verbose
        self.clients: list[_Client] = []
        self._next_client = 1
        self.server: asyncio.base_events.Server | None = None
        self._tasks: list[asyncio.Task] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._t0 = 0.0
        self.mode_maint = False
        self._was_busy = False
        self._maint_timer: asyncio.TimerHandle | None = None
        self.local_sent: list[str] = []
        self.chain.add_listener(self._on_motor_line)

    # ------------------------------------------------------------------ cycle de vie
    async def start(self) -> int:
        self._loop = asyncio.get_running_loop()
        self._t0 = self._loop.time()
        self.server = await asyncio.start_server(self._handle_client, self.host, self.port)
        self.port = self.server.sockets[0].getsockname()[1]
        self._tasks.append(asyncio.create_task(self._ticker()))
        if self.mode == "bridge" and self.emulate_esp:
            self._tasks.append(asyncio.create_task(self._esp_startup()))
        log.info("cm1sim %s en écoute sur %s:%d", self.mode, self.host, self.port)
        return self.port

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()
        for c in list(self.clients):
            c.writer.close()
        if self.server:
            self.server.close()
            await self.server.wait_closed()

    async def serve_forever(self) -> None:
        await self.start()
        assert self.server
        async with self.server:
            await self.server.serve_forever()

    def ms(self) -> int:
        if self._loop is None:
            return 0
        return int((self._loop.time() - self._t0) * 1000)

    # ------------------------------------------------------------------ horloge et logique ESP émulée
    async def _ticker(self) -> None:
        loop = asyncio.get_running_loop()
        last = loop.time()
        while True:
            await asyncio.sleep(TICK_MS / 1000.0)
            now = loop.time()
            dt = (now - last) * 1000.0
            last = now
            self.chain.tick(dt)
            busy = self.chain.busy
            if self.mode == "bridge":
                if busy != self._was_busy:
                    self._was_busy = busy
                    self._broadcast(P.fmt_state(self.ms(), self.current_mode, busy))
                    if not busy and self.emulate_esp and not self.mode_maint:
                        loop.call_later(0.2, self._send_local, "?96.1")

    async def _esp_startup(self) -> None:
        await asyncio.sleep(1.5)
        for line, delay in (("?85.1", 0.6), ("?90.1", 1.5), ("(.1", 0.05), ("|2.1", 0.0)):
            if self.mode_maint:
                return
            self._send_local(line)
            await asyncio.sleep(delay)

    def _send_local(self, line: str) -> None:
        if self.mode_maint:
            return
        self.local_sent.append(line)
        self._broadcast(P.fmt_tx(self.ms(), "LOCAL", line))
        self.chain.feed(line)

    @property
    def current_mode(self) -> str:
        return P.MODE_MAINT if self.mode_maint else P.MODE_NORMAL

    # ------------------------------------------------------------------ sorties moteur
    def _on_motor_line(self, line: str) -> None:
        if self.verbose:
            log.info("< %s", line)
        if self.mode == "raw":
            term = "\r\n" if self.chain.master.k.get(70, 1) == 1 else "\r"
            self._broadcast(line + term)
        else:
            self._broadcast(P.fmt_rx(self.ms(), line))

    def _broadcast(self, text: str) -> None:
        for c in self.clients:
            c.send(text)

    # ------------------------------------------------------------------ clients
    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        client = _Client(self._next_client, reader, writer)
        self._next_client += 1
        self.clients.append(client)
        if self._maint_timer:
            self._maint_timer.cancel()
            self._maint_timer = None
        log.info("client %s connecté", client.name)
        try:
            if self.mode == "bridge":
                client.send(P.fmt_hello(self.current_mode, self.chain.busy))
            buf = b""
            while True:
                data = await reader.read(256)
                if not data:
                    break
                buf += data
                while True:
                    idx = -1
                    for sep in (b"\r\n", b"\n", b"\r"):
                        i = buf.find(sep)
                        if i >= 0 and (idx < 0 or i < idx):
                            idx, seplen = i, len(sep)
                    if idx < 0:
                        break
                    line = buf[:idx].decode("utf-8", "replace")
                    buf = buf[idx + seplen:]
                    if self.mode == "raw":
                        if self.verbose:
                            log.info("> %s", line)
                        self.chain.feed(line)
                    else:
                        self._handle_bridge_line(client, line)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            if client in self.clients:
                self.clients.remove(client)
            writer.close()
            log.info("client %s déconnecté", client.name)
            if not self.clients and self.mode_maint and self.maint_timeout_s > 0:
                self._maint_timer = asyncio.get_running_loop().call_later(self.maint_timeout_s, self._auto_exit_maint)

    def _auto_exit_maint(self) -> None:
        self._maint_timer = None
        if self.mode_maint and not self.clients:
            self._set_maint(False)

    def _set_maint(self, on: bool) -> None:
        self.mode_maint = on
        self._broadcast(P.fmt_state(self.ms(), self.current_mode, self.chain.busy))
        if not on and self.emulate_esp:
            for line in ("?90.1", "?99.1", "?96.1"):
                self._send_local(line)

    def _handle_bridge_line(self, client: _Client, line: str) -> None:
        if not line.strip():
            return
        try:
            cmd = P.parse_client_line(line)
        except P.ProtocolError:
            client.send(P.fmt_err(self.ms(), "BADCMD", line))
            return
        if cmd.kind == "PING":
            client.send("PONG\n")
        elif cmd.kind == "STATUS":
            client.send(P.fmt_state(self.ms(), self.current_mode, self.chain.busy))
        elif cmd.kind == "MAINT":
            if cmd.arg == "ON":
                if self.mode_maint:
                    client.send(P.fmt_state(self.ms(), self.current_mode, self.chain.busy))
                elif self.chain.busy:
                    client.send(P.fmt_maint_refused(self.ms(), "MOVING"))
                elif self.chain.in_alarm:
                    client.send(P.fmt_maint_refused(self.ms(), "ALARM"))
                else:
                    self._set_maint(True)
            else:
                if self.mode_maint:
                    self._set_maint(False)
                else:
                    client.send(P.fmt_state(self.ms(), self.current_mode, self.chain.busy))
        elif cmd.kind == "TX":
            text = cmd.arg
            if len(text) > P.MAX_TX_LENGTH:
                client.send(P.fmt_err(self.ms(), "TOOLONG", text))
                return
            if not self.mode_maint and not is_read_only(text):
                client.send(P.fmt_err(self.ms(), "FORBIDDEN", text))
                return
            if self.verbose:
                log.info("> [%s] %s", client.name, text)
            self._broadcast(P.fmt_tx(self.ms(), client.name, text))
            self.chain.feed(text)
