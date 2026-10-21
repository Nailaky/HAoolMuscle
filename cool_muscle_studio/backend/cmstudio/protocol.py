"""Protocole TCP texte entre l'application et le pont ESP32 (composant cm1_bridge).

Une ligne = un message, terminée par LF. Voir docs/protocole-tcp.md.

Client -> pont :   TX <ligne> | MAINT ON | MAINT OFF | STATUS | PING
Pont -> client :   HELLO <version> <mode> <busy>
                   RX <ms> <ligne>
                   TX <ms> <origine> <ligne>
                   EVT <ms> STATE <mode> <busy>
                   EVT <ms> MAINT REFUSED <raison>
                   ERR <ms> <code> <texte>
                   PONG
"""

from __future__ import annotations

from dataclasses import dataclass

PROTOCOL_VERSION = 1
MODE_NORMAL = "NORMAL"
MODE_MAINT = "MAINT"
MAX_TX_LENGTH = 60  # comme le champ « Commande CML » du YAML actuel


# ----------------------------------------------------------------------------
# Messages du pont vers le client
@dataclass(frozen=True)
class Hello:
    version: int
    mode: str
    busy: bool


@dataclass(frozen=True)
class RxLine:
    ms: int
    line: str


@dataclass(frozen=True)
class TxLine:
    ms: int
    origin: str  # LOCAL ou C<n>
    line: str


@dataclass(frozen=True)
class State:
    ms: int
    mode: str
    busy: bool


@dataclass(frozen=True)
class MaintRefused:
    ms: int
    reason: str  # MOVING | STARTUP | ALARM


@dataclass(frozen=True)
class Error:
    ms: int
    code: str  # FORBIDDEN | TOOLONG | QUEUE_FULL | BADCMD
    text: str


@dataclass(frozen=True)
class Pong:
    pass


@dataclass(frozen=True)
class Unknown:
    raw: str


BridgeMessage = Hello | RxLine | TxLine | State | MaintRefused | Error | Pong | Unknown


class ProtocolError(ValueError):
    pass


def parse_bridge_line(raw: str) -> BridgeMessage:
    """Analyse une ligne reçue du pont."""
    line = raw.rstrip("\r\n")
    if line == "PONG":
        return Pong()
    head, _, rest = line.partition(" ")
    try:
        if head == "HELLO":
            v, mode, busy = rest.split(" ", 2)
            return Hello(int(v), mode, busy == "1")
        if head == "RX":
            ms, _, payload = rest.partition(" ")
            return RxLine(int(ms), payload)
        if head == "TX":
            ms, origin, payload = rest.split(" ", 2)
            return TxLine(int(ms), origin, payload)
        if head == "EVT":
            ms, kind, tail = rest.split(" ", 2)
            if kind == "STATE":
                mode, busy = tail.split(" ", 1)
                return State(int(ms), mode, busy == "1")
            if kind == "MAINT":
                sub, _, reason = tail.partition(" ")
                if sub == "REFUSED":
                    return MaintRefused(int(ms), reason)
        if head == "ERR":
            ms, code, text = rest.split(" ", 2)
            return Error(int(ms), code, text)
    except ValueError as exc:  # split/int ratés
        raise ProtocolError(f"ligne de pont invalide : {raw!r}") from exc
    return Unknown(line)


# ----------------------------------------------------------------------------
# Messages du client vers le pont
def tx(line: str) -> str:
    line = line.rstrip("\r\n")
    if "\r" in line or "\n" in line:
        raise ProtocolError("une commande CML ne doit pas contenir de retour à la ligne")
    if len(line) > MAX_TX_LENGTH:
        raise ProtocolError(f"commande trop longue ({len(line)} > {MAX_TX_LENGTH})")
    return f"TX {line}\n"


def maint(on: bool) -> str:
    return f"MAINT {'ON' if on else 'OFF'}\n"


def status() -> str:
    return "STATUS\n"


def ping() -> str:
    return "PING\n"


# ----------------------------------------------------------------------------
# Côté pont (utilisé par le simulateur ; le composant C++ produit les mêmes lignes)
def fmt_hello(mode: str, busy: bool) -> str:
    return f"HELLO {PROTOCOL_VERSION} {mode} {int(busy)}\n"


def fmt_rx(ms: int, line: str) -> str:
    return f"RX {ms} {line}\n"


def fmt_tx(ms: int, origin: str, line: str) -> str:
    return f"TX {ms} {origin} {line}\n"


def fmt_state(ms: int, mode: str, busy: bool) -> str:
    return f"EVT {ms} STATE {mode} {int(busy)}\n"


def fmt_maint_refused(ms: int, reason: str) -> str:
    return f"EVT {ms} MAINT REFUSED {reason}\n"


def fmt_err(ms: int, code: str, text: str) -> str:
    return f"ERR {ms} {code} {text}\n"


@dataclass(frozen=True)
class ClientCommand:
    kind: str  # TX | MAINT | STATUS | PING
    arg: str = ""


def parse_client_line(raw: str) -> ClientCommand:
    """Analyse une ligne reçue d'un client (côté pont / simulateur)."""
    line = raw.rstrip("\r\n")
    head, _, rest = line.partition(" ")
    if head == "TX":
        return ClientCommand("TX", rest)
    if head == "MAINT" and rest in ("ON", "OFF"):
        return ClientCommand("MAINT", rest)
    if head == "STATUS" and not rest:
        return ClientCommand("STATUS")
    if head == "PING" and not rest:
        return ClientCommand("PING")
    raise ProtocolError(f"commande client inconnue : {raw!r}")
