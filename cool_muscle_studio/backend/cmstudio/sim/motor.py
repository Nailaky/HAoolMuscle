"""Modèle d'un moteur CM1 simulé.

Le modèle travaille en interne en résolution 50 000 impulsions/tour (comme le
vrai moteur) et convertit selon K37 pour les registres. Le comportement
documenté est reproduit ; les formats de réponse viennent de ``formats.py``.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

from ..cml.model import Kind, ParsedLine, Statement
from ..cml.parser import parse_line
from ..reference import Reference, load_reference
from ..units import RESOLUTION_MAX, resolution, speed_unit
from . import formats as F
from .expr import ExprError, evaluate

INFINITE_POSITION = 1_000_000_000
STATE_VARS = {"Ux", "Px", "Sx", "Ix", "Tx", "Ex", "Pe", "Pt", "St", "Dx", "AIN4", "Fx", "Cx", "Cx2", "Cx3", "Cx4",
              "AO2", "IN", "INMK", "Tmr", "Cnt", "PTmr", "PV%", "PVal", "DPos", "MOP", "EEP1", "EEP2",
              "IN1R", "IN2R", "IN3R", "IN4R", "IN1F", "IN2F", "IN3F", "IN4F", "mop"}
ALARM_BITS = 1 | 2 | 4 | 128


@dataclass
class ProgramRun:
    """Exécution d'une banque de programme (pas à pas, une ligne après l'autre)."""

    bank: str
    lines: list[ParsedLine]
    pc: int = 0
    si: int = 0                                 # index d'instruction dans la ligne courante
    loops: list[tuple[int, int | None]] = field(default_factory=list)   # (pc du début, restant ou None=infini)
    calls: list[tuple[str, int]] = field(default_factory=list)          # (banque, pc de retour)
    wait: str | None = None                     # move | timer | cond
    timer_ms: float = 0.0
    paused: bool = False
    step_once: bool = False
    pause_after_line: bool = False
    speed: int = 0
    acc: int = 0
    torque: int = 100


@dataclass
class LogicRun:
    bank: str
    lines: list[ParsedLine]
    acc_ms: float = 0.0


class MotorSim:
    def __init__(
        self,
        motor_id: int = 1,
        model: str = "17L30",
        fw: str = "RT3.14.06",
        hw: str = "E",
        reference: Reference | None = None,
        resolver: Callable[[str, int], int] | None = None,
    ) -> None:
        self.ref = reference or load_reference()
        self.id = motor_id
        self.model = model
        self.fw = fw
        self.hw = hw
        self.k: dict[int, int] = self.ref.k_defaults()
        self.h: dict[int, int] = self._h_defaults()
        self.regs: dict[str, list] = {}
        for letter, fam in self.ref.registers.items():
            if letter in "PSAMTVNR":
                self.regs[letter] = [0] * (fam.index_max + 1)
        self.banks: dict[str, list[str]] = {}
        self.saved = False
        self.skh = 1
        self.mop = 0
        # état physique (résolution 50k)
        self.pos = 0.0
        self.vel = 0.0
        self.target: float | None = None
        self.vmax = 0.0
        self.acc50 = 0.0
        self.dec50 = 0.0
        self.moving = False
        self.infinite_dir = 0
        self.homing = False
        self.enabled = True
        self.manual_disabled = False
        self.alarms = 0
        self.estop = False
        self.temperature = 35
        self.inputs = 0
        self.outputs = 0
        self.analog = 0
        self.inmk = 15
        self.cnt = 0.0
        self.tmr = 0.0
        self.ao2 = 0
        self.eep = [0, 0]
        self.time_ms = 0.0
        self.reset_at: float | None = None
        self.recording: str | None = None
        self.prog: ProgramRun | None = None
        self.logic: LogicRun | None = None
        self.stream_acc = 0.0
        self.out: list[str] = []
        self.history: list[str] = []
        self.resolver = resolver  # pour les références à un autre moteur (P1.2)
        self.max_rpm = self._max_rpm()

    # ------------------------------------------------------------------ utilitaires
    def _h_defaults(self) -> dict[int, int]:
        out: dict[int, int] = {}
        key = self.model[:3].replace("L", "L").replace("S", "S")
        short = self.model[:2] + self.model[2]  # ex 17L
        for h in self.ref.data["parametres_h"]["liste"]:
            d = h.get("defaut", {})
            out[int(h["h"])] = int(d.get(short, next(iter(d.values()), 0)) if isinstance(d, dict) else 0)
        _ = key
        return out

    def _max_rpm(self) -> int:
        for m in self.ref.data["moteurs"]["modeles"]:
            if m["modele"] == self.model:
                return int(m["vitesse_max_rpm"])
        return 3000

    @property
    def ppr(self) -> int:
        return resolution(self.k.get(37, 3))

    @property
    def spu(self) -> int:
        return speed_unit(self.k.get(37, 3))

    def to50(self, user_pulses: float) -> float:
        return user_pulses * RESOLUTION_MAX / self.ppr

    def from50(self, p50: float) -> int:
        return int(round(p50 * self.ppr / RESOLUTION_MAX))

    @property
    def pos_user(self) -> int:
        return self.from50(self.pos)

    @property
    def vel_user(self) -> int:
        """Vitesse courante en impulsions/s (résolution K37)."""
        return self.from50(self.vel)

    def emit(self, line: str) -> None:
        self.out.append(line)
        self.history.append(line)

    def fmt(self, key: str, **kw) -> str:
        return F.FORMATS[key].format(id=self.id, **kw)

    # ------------------------------------------------------------------ état
    def ux(self) -> int:
        v = 0
        if self.estop:
            v |= 512
        v |= self.alarms
        if self.manual_disabled:
            v |= 16
        if v == 0:
            return 0 if self.moving else 8
        return v

    def emit_ux(self) -> None:
        if self.k.get(23, 1) & 1:
            self.emit(self.fmt("ux", v=self.ux()))

    @property
    def busy(self) -> bool:
        return self.moving or (self.prog is not None and not self.prog.paused)

    @property
    def in_alarm(self) -> bool:
        return bool(self.alarms) or self.estop

    def inject_alarm(self, bits: int) -> None:
        """Injecte une alarme (1, 2, 4, 128) : arrêt, moteur désactivé, Ux envoyé."""
        self.alarms |= bits & ALARM_BITS
        self._stop_motion()
        self.prog = None
        self.enabled = False
        self.emit_ux()

    def set_input(self, n: int, active: bool) -> None:
        bit = 1 << (n - 1)
        self.inputs = (self.inputs | bit) if active else (self.inputs & ~bit)

    # ------------------------------------------------------------------ enregistrement de banque
    def start_recording(self, name: str) -> None:
        self.recording = name.upper()
        self.banks[self.recording] = []

    def record(self, line: str) -> None:
        if self.recording is not None:
            self.banks[self.recording].append(line.strip())

    def end_recording(self) -> None:
        self.recording = None

    # ------------------------------------------------------------------ exécution d'une instruction
    def execute(self, st: Statement, in_bank: bool = False) -> str | None:
        """Exécute une instruction. Retourne un code d'attente pour l'interpréteur de banque."""
        k = st.kind
        if k is Kind.REG_WRITE:
            return self._write(st, in_bank)
        if k is Kind.REG_READ:
            self._read(st)
            return None
        if k is Kind.QUERY:
            self._query(st.arg or "")
            return None
        if k is Kind.COMMAND:
            return self._command(st)
        if k is Kind.STEP:
            return self._step(st)
        if k is Kind.BRANCH:
            try:
                cond = evaluate(st.condition or "0", self._resolve)
            except ExprError:
                self.emit(self.fmt("error"))
                return None
            branch = st.then if cond else st.otherwise
            result = None
            for sub in branch:
                r = self.execute(sub, in_bank)
                if r:
                    result = r
            if not cond and any(s.kind is Kind.STEP and s.command == "W" for s in branch):
                return "cond"
            return result
        if k is Kind.JUNCTION:
            result = None
            for sub in st.children:
                r = self.execute(sub, in_bank)
                result = r or result
            return result
        if k is Kind.BANK_START:
            self.start_recording(st.arg or "B0")
            return None
        if k is Kind.BANK_END:
            self.end_recording()
            return None
        self.emit(self.fmt("error"))
        return None

    # ------------------------------------------------------------------ registres
    def _resolve(self, token: str) -> int | float:
        if token.startswith('"'):
            return self._state_var(token.strip('"'))
        if token.startswith("I") and len(token) == 2 and token[1].isdigit():
            return 1 if self.inputs & (1 << (int(token[1]) - 1)) else 0
        letter, _, rest = token[0], token[1:], ""
        body, _, motor = token[1:].partition(".")
        if motor and int(motor) != self.id and self.resolver is not None:
            return self.resolver(f"{letter}{body}", int(motor))
        return self.reg_value(letter, int(body))

    def _state_var(self, name: str) -> int:
        table = {
            "Ux": self.ux, "Px": lambda: self.pos_user, "Sx": lambda: self.vel_user,
            "Ix": lambda: 0, "Tx": lambda: 0, "Ex": lambda: self.ux() & (ALARM_BITS | 512),
            "Pe": lambda: 0, "Pt": lambda: self.from50(self.target) if self.target is not None else self.pos_user,
            "AIN4": lambda: self.analog, "IN": lambda: self.inputs & self.inmk, "INMK": lambda: self.inmk,
            "Cnt": lambda: int(self.cnt), "Tmr": lambda: int(self.tmr), "AO2": lambda: self.ao2,
            "MOP": lambda: self.mop, "mop": lambda: self.mop, "EEP1": lambda: self.eep[0], "EEP2": lambda: self.eep[1],
        }
        fn = table.get(name)
        return int(fn()) if fn else 0

    def reg_value(self, letter: str, index: int) -> int:
        if letter == "K":
            return int(self.k.get(index, 0))
        if letter == "H":
            return int(self.h.get(index, 0))
        arr = self.regs.get(letter)
        if arr is None or not (0 <= index < len(arr)):
            return 0
        v = arr[index]
        if isinstance(v, str):
            return self._state_var(v) if v in STATE_VARS else 0
        return int(v)

    def _write(self, st: Statement, in_bank: bool) -> str | None:
        if st.reg is None or st.value is None:
            self.emit(self.fmt("error"))
            return None
        val = st.value
        if st.reg == "K":
            kp = self.ref.k(st.index or -1)
            if kp is None or val.kind != "int":
                self.emit(self.fmt("error"))
                return None
            if kp.documente and kp.check(val.int_value or 0):
                self.emit(self.fmt("error"))
                return None
            self.k[st.index or 0] = val.int_value or 0
            if st.index in (66, 67):
                self.stream_acc = 0.0
            return None
        if st.reg == "H":
            if val.kind == "int":
                self.h[st.index or 0] = val.int_value or 0
            return None
        arr = self.regs.get(st.reg)
        if arr is None or st.index is None or not (0 <= st.index < len(arr)):
            self.emit(self.fmt("error"))
            return None
        if val.kind == "int":
            if in_bank:  # constante interdite dans une banque (UG §10.3)
                self.emit(self.fmt("error"))
                return None
            arr[st.index] = val.int_value or 0
        elif val.kind == "str":
            text = val.text.strip('"')
            if st.reg == "V":
                arr[st.index] = text
                if text == "INMK":
                    pass
            else:
                self.emit(self.fmt("error"))
        else:
            try:
                result = evaluate(val.text, self._resolve)
            except ExprError:
                self.emit(self.fmt("error"))
                return None
            # écriture dans une variable d'état par l'intermédiaire d'un V ?
            cur = arr[st.index]
            if st.reg == "V" and isinstance(cur, str):
                self._write_state_var(cur, result)
            else:
                arr[st.index] = result
            if in_bank and not st.merge:
                self.emit(self.fmt("math_echo", reg=st.reg, n=st.index, v=result))
        return None

    def _write_state_var(self, name: str, value: int) -> None:
        if name == "Px":
            self.pos = self.to50(value)
            if not self.moving:
                self.target = None
        elif name == "INMK":
            self.inmk = value
        elif name == "Tmr":
            self.tmr = float(value)
        elif name == "Cnt":
            self.cnt = float(value)
        elif name == "AO2":
            self.ao2 = max(0, min(255, value))
        elif name in ("MOP", "mop"):
            self.mop = value
        elif name == "EEP1":
            self.eep[0] = value
        elif name == "EEP2":
            self.eep[1] = value

    def _read(self, st: Statement) -> None:
        if st.reg is None or st.index is None:
            return
        if st.reg == "K":
            if st.index in self.k:
                self.emit(self.fmt("k", n=st.index, v=self.k[st.index]))
            else:
                self.emit(self.fmt("error"))
            return
        if st.reg == "H":
            self.emit(self.fmt("reg", reg="H", n=st.index, v=self.h.get(st.index, 0)))
            return
        arr = self.regs.get(st.reg)
        if arr is None or not (0 <= st.index < len(arr)):
            self.emit(self.fmt("error"))
            return
        v = arr[st.index]
        shown = f'"{v}"' if isinstance(v, str) else v
        self.emit(self.fmt("reg", reg=st.reg, n=st.index, v=shown))

    # ------------------------------------------------------------------ requêtes
    def _query(self, arg: str) -> None:
        a = arg.upper()
        if a == "":
            for letter in ("P", "A", "S"):
                self.emit(self.fmt("reg", reg=letter, n=0, v=self.regs[letter][0]))
            return
        if a.isalpha() and len(a) == 1:
            if a == "K":
                self._dump_k()
                return
            arr = self.regs.get(a)
            if arr is None:
                self.emit(self.fmt("error"))
                return
            for i, v in enumerate(arr):
                self.emit(self.fmt("reg", reg=a, n=i, v=f'"{v}"' if isinstance(v, str) else v))
            return
        if not a.isdigit():
            self.emit(self.fmt("error"))
            return
        n = int(a)
        if 0 <= n <= 30:
            self._dump_bank(f"B{n}")
        elif n == 1000:
            for name in sorted(self.banks, key=lambda s: (s[0], int(s[1:]))):
                self._dump_bank(name)
            self.emit(self.fmt("steps", used=self.step_count()))
        elif n == 51:
            self.emit(self.fmt("query_generic", q=51, v=1 if self.outputs & 1 else 0))
        elif n == 52:
            self.emit(self.fmt("query_generic", q=52, v=1 if self.outputs & 2 else 0))
        elif n == 70:
            self.emit(self.fmt("query_generic", q=70, v=self.inputs))
        elif n == 71:
            self.emit(self.fmt("query_generic", q=71, v=self.temperature))
        elif n == 74:
            self.emit(self.fmt("query_generic", q=74, v=self.analog))
        elif n in (76, 79):
            self.emit(self.fmt("query_generic", q=n, v=0))
        elif n == 85:
            self.emit(self.fmt("banner", fw=self.fw, hw=self.hw))
        elif n == 90:
            self._dump_k()
        elif n in (91, 92, 93, 94):
            letter = {91: "P", 92: "S", 93: "A", 94: "T"}[n]
            for i, v in enumerate(self.regs[letter]):
                self.emit(self.fmt("reg", reg=letter, n=i, v=v))
        elif n == 95:
            self.emit(self.fmt("ex", v=0))
        elif n == 96:
            self.emit(self.fmt("px", v=self.pos_user))
        elif n == 97:
            self.emit(self.fmt("sx", v=self.vel_user))
        elif n == 98:
            self.emit(self.fmt("tx", v=self._torque_proxy()))
        elif n == 99:
            self.emit(self.fmt("ux", v=self.ux()))
        else:
            self.emit(self.fmt("error"))

    def _torque_proxy(self) -> int:
        # courant proportionnel à l'accélération en cours (hypothèse de simulation)
        if not self.moving or self.vmax == 0:
            return 0
        return int(min(110, abs(self.vel) / self.vmax * 60 + 10))

    def _dump_k(self) -> None:
        for n in sorted(self.k):
            self.emit(self.fmt("k", n=n, v=self.k[n]))

    def _dump_bank(self, name: str) -> None:
        lines = self.banks.get(name)
        if lines is None:
            return
        self.emit(self.fmt("bank_header", name=name))
        for ln in lines:
            self.emit(ln)
        self.emit(self.fmt("bank_end"))

    def step_count(self) -> int:
        return sum(len(v) for v in self.banks.values())

    # ------------------------------------------------------------------ commandes directes
    def _command(self, st: Statement) -> str | None:
        c = st.command
        if c == "^":
            n = int(st.arg) if st.arg else 0
            self.start_move(self.regs["P"][n], self.regs["S"][n], self.regs["A"][n], self.regs["M"][n])
        elif c == "~":
            if not self.estop and self.enabled:
                self._begin_motion(self.pos + float(self.regs["P"][0]), self.regs["S"][0], self.regs["A"][0], relative50=True)
        elif c == "|":
            self._origin(st.arg or "")
        elif c == "(":
            self.enabled = True
            self.manual_disabled = False
            self.alarms = 0
            self.emit_ux()
        elif c == ")":
            self._stop_motion()
            self.manual_disabled = True
            self.enabled = False
            self.emit_ux()
        elif c in ("O", "F"):
            out = int(st.arg or "1")
            digit = (self.k.get(34, 21) // (10 ** (out - 1))) % 10
            if digit in (3, 4):
                bit = 1 << (out - 1)
                self.outputs = (self.outputs | bit) if c == "O" else (self.outputs & ~bit)
        elif c == "$":
            self.saved = True
            self.emit(self.fmt("saved"))
        elif c == "[":
            self._run_bank(st.arg or "1")
        elif c == "]":
            if self.prog is not None and not self.prog.paused:
                self.prog.paused = True
                self._stop_motion()
                self.emit_ux()
            elif self.prog is not None:
                self.prog = None
            else:
                self._stop_motion()
                self.emit_ux()
        elif c == "]1":
            self._stop_motion()
            if self.prog:
                self.prog.paused = True
        elif c == "]L":
            self.logic = None
        elif c == "}":
            if self.prog is not None:
                if self.prog.paused:
                    self.prog = None
                else:
                    self.prog.pause_after_line = True
        elif c == ">":
            if self.prog is not None and self.prog.paused:
                self.prog.step_once = True
                self.prog.paused = False
            else:
                self.emit(self.fmt("end_bank"))
        elif c == "<":
            self.emit(self.fmt("cant_back"))
        elif c == "*":
            self.estop = True
            self._stop_motion()
            self.prog = None
            self.emit_ux()
        elif c == "*1":
            self.estop = False
            self.emit_ux()
        elif c == "_SKH":
            if st.value is None:
                self.emit(self.fmt("skh", v=self.skh))
            elif st.value.kind == "int" and st.value.int_value in (0, 1):
                self.skh = st.value.int_value or 0
            else:
                self.emit(self.fmt("error"))
        elif c == "_MOP":
            if st.value and st.value.kind == "int":
                self.mop = st.value.int_value or 0
        elif c == "B100":
            for name in [n for n in self.banks if n.startswith("B")]:
                del self.banks[name]
        elif c == "L100":
            for name in [n for n in self.banks if n.startswith("L")]:
                del self.banks[name]
        elif c in ("D", "{", "FFFFFFFFF"):
            pass
        else:
            self.emit(self.fmt("error"))
        return None

    def _origin(self, arg: str) -> None:
        if self.estop or not self.enabled:
            return
        if arg == "":
            self.homing = True
            direction = -1 if self.k.get(45, 1) in (1, 3) else 1
            self._begin_motion(self.pos + direction * RESOLUTION_MAX / 4, self.k.get(42, 10), self.k.get(43, 100), relative50=True)
        elif arg == "1":
            self._begin_motion(0.0, self.k.get(42, 10), self.k.get(43, 100), relative50=True)
        elif arg == "2":
            self.pos = 0.0
            if not self.moving:
                self.target = None
        elif arg == "4":
            self.soft_reset()
        elif arg == "11":
            self.pos = math.fmod(self.pos, RESOLUTION_MAX)

    def soft_reset(self) -> None:
        self._stop_motion()
        self.prog = None
        self.logic = None
        self.estop = False
        self.alarms = 0
        self.manual_disabled = self.k.get(46, 0) in (16, 17, 18, 19)
        self.enabled = not self.manual_disabled
        self.skh = 1
        self.reset_at = self.time_ms + 500.0

    # ------------------------------------------------------------------ mouvement
    def start_move(self, p: int, s: int, a: int, m: int = 100) -> None:
        if self.estop or not self.enabled:
            return
        if abs(p) >= INFINITE_POSITION:
            self.infinite_dir = 1 if s >= 0 else -1
            self._begin_motion(None, s, a)
            return
        self._begin_motion(self.to50(p), s, a)

    def _begin_motion(self, target50: float | None, s: int, a: int, relative50: bool = False) -> None:
        rpm = abs(s) * self.spu * 60.0 / self.ppr
        if rpm > self.max_rpm:
            self.inject_alarm(2)
            return
        if s == 0:
            self._stop_motion()
            return
        self.target = target50
        self.vmax = self.to50(abs(s) * self.spu)
        acc = a if a > 0 else 100
        self.acc50 = self.to50(acc * 1000.0)
        self.dec50 = self.acc50 * self.k.get(44, 100) / 100.0
        was_moving = self.moving
        self.moving = True
        if not was_moving:
            self.emit_ux()

    def _stop_motion(self) -> None:
        self.vel = 0.0
        self.target = None
        self.moving = False
        self.infinite_dir = 0
        self.homing = False

    def _finish_motion(self) -> None:
        self.vel = 0.0
        self.moving = False
        self.infinite_dir = 0
        if self.homing:
            self.homing = False
            self.pos = 0.0
            self.target = None
        self.emit_ux()

    def _tick_motion(self, dt: float) -> None:
        if not self.moving:
            return
        if self.target is None:  # mouvement infini
            direction = self.infinite_dir or 1
            self.vel = min(self.vmax, abs(self.vel) + self.acc50 * dt) * direction
            self.pos += self.vel * dt
            return
        remaining = self.target - self.pos
        direction = 1 if remaining >= 0 else -1
        dist = abs(remaining)
        speed = abs(self.vel)
        stop_dist = speed * speed / (2 * self.dec50) if self.dec50 > 0 else 0
        if dist <= stop_dist + speed * dt:
            speed = max(0.0, speed - self.dec50 * dt)
        else:
            speed = min(self.vmax, speed + self.acc50 * dt)
        step = speed * dt
        if step >= dist or (speed <= 0 and dist < 1):
            self.pos = self.target
            self._finish_motion()
            return
        self.vel = speed * direction
        self.pos += self.vel * dt

    # ------------------------------------------------------------------ banques
    def _run_bank(self, arg: str) -> None:
        if self.estop or self.in_alarm:
            return
        name = arg.upper()
        if name.startswith("L"):
            lines = self.banks.get(name)
            if lines is None:
                self.emit(self.fmt("error"))
                return
            self.logic = LogicRun(name, [parse_line(ln, i + 1, in_bank=True) for i, ln in enumerate(lines)])
            return
        name = "B" + name
        lines = self.banks.get(name)
        if lines is None:
            self.emit(self.fmt("error"))
            return
        if self.prog is not None and self.prog.paused:
            self.prog.paused = False
            return
        self.prog = ProgramRun(name, [parse_line(ln, i + 1, in_bank=True) for i, ln in enumerate(lines)],
                               speed=self.regs["S"][0] or 100, acc=self.regs["A"][0] or 100)

    def _step(self, st: Statement) -> str | None:
        """Exécute un pas de banque. Retourne 'move' ou 'timer' si une attente commence."""
        op, n = st.command, st.index
        run = self.prog
        if op in ("S", "A", "M") and n is not None:
            value = self.regs[op][n]
            if run is not None:
                if op == "S":
                    run.speed = value
                elif op == "A":
                    run.acc = value
                else:
                    run.torque = value
            else:
                self.regs[op][0] = value
            return None
        if op in ("P", "Y", "Q", "Z", "@") and n is not None:
            p = self.regs["P"][n]
            speed = run.speed if run else (self.regs["S"][0] or 100)
            acc = run.acc if run else (self.regs["A"][0] or 100)
            if st.plus:
                self._begin_motion(self.pos + self.to50(p), speed, acc, relative50=True)
            else:
                self.start_move(p, speed, acc)
            return "move" if op in ("P", "Q", "@") and self.moving else None
        if op == "T":
            if n and n > 0 and run is not None:
                run.timer_ms = float(self.regs["T"][n])
                return "timer"
            return None
        if op == "W":
            if n and n > 0 and run is not None:
                run.timer_ms = float(self.regs["T"][n])
                return "timer"
            return "cond"
        if op == "X":
            if run is None:
                return None
            if st.arg == "-":
                if run.loops:
                    start, remaining = run.loops[-1]
                    if remaining is None:
                        run.pc = start
                        run.si = 0
                        return "jump"
                    if remaining > 1:
                        run.loops[-1] = (start, remaining - 1)
                        run.pc = start
                        run.si = 0
                        return "jump"
                    run.loops.pop()
                return None
            count = n or 0
            run.loops.append((run.pc + 1, None if count == 0 else count))
            return None
        if op in ("C", "J") and n is not None and run is not None:
            target = f"B{n}"
            if target not in self.banks:
                self.emit(self.fmt("error"))
                return None
            if op == "C":
                run.calls.append((run.bank, run.pc + 1))
            run.bank = target
            run.lines = [parse_line(ln, i + 1, in_bank=True) for i, ln in enumerate(self.banks[target])]
            run.pc = 0
            run.si = 0
            return "jump"
        if op in ("CL", "JL") and n is not None:
            target = f"L{n}"
            lines = self.banks.get(target)
            if lines is None:
                self.emit(self.fmt("error"))
                return None
            parsed = [parse_line(ln, i + 1, in_bank=True) for i, ln in enumerate(lines)]
            if op == "JL":
                self.logic = LogicRun(target, parsed)
                return "jump"
            for pl in parsed:  # appel inline
                for sub in pl.statements:
                    self.execute(sub, in_bank=True)
            return None
        if op == "I":
            return None
        return None

    def _tick_program(self, dt_ms: float) -> None:
        run = self.prog
        if run is None:
            return
        if run.paused:
            return
        if run.wait == "move":
            if self.moving:
                return
            run.wait = None
        elif run.wait == "timer":
            run.timer_ms -= dt_ms
            if run.timer_ms > 0:
                return
            run.wait = None
        elif run.wait == "cond":
            run.wait = None  # la ligne est ré-évaluée
            run.si = 0
        budget = 50  # lignes par tick au maximum
        while run is self.prog and budget > 0:
            budget -= 1
            if run.pc >= len(run.lines):
                if run.calls:
                    run.bank, run.pc = run.calls.pop()
                    run.lines = [parse_line(ln, i + 1, in_bank=True) for i, ln in enumerate(self.banks[run.bank])]
                    run.si = 0
                    continue
                self.prog = None
                if run.step_once:
                    self.emit(self.fmt("end_bank"))
                return
            line = run.lines[run.pc]
            stmts = line.statements
            advanced = False
            while run.si < len(stmts):
                st = stmts[run.si]
                run.si += 1
                code = self.execute(st, in_bank=True)
                if code == "jump":
                    advanced = True
                    break
                if code in ("move", "timer", "cond"):
                    run.wait = code
                    if code == "cond":
                        run.si -= 1
                    return
            if advanced:
                continue
            run.pc += 1
            run.si = 0
            if run.step_once:
                run.step_once = False
                run.paused = True
                return
            if run.pause_after_line:
                run.pause_after_line = False
                run.paused = True
                self._stop_motion()
                self.emit_ux()
                return

    def _tick_logic(self, dt_ms: float) -> None:
        logic = self.logic
        if logic is None:
            return
        logic.acc_ms += dt_ms
        period = float(self.k.get(87, 0) or 10)
        if logic.acc_ms < period:
            return
        logic.acc_ms = 0.0
        for pl in logic.lines:
            if self.logic is not logic:  # JL a changé de banque
                break
            for st in pl.statements:
                self.execute(st, in_bank=True)

    def _tick_stream(self, dt_ms: float) -> None:
        k66 = self.k.get(66, 0)
        k67 = self.k.get(67, 0)
        if k66 <= 0 or k67 <= 0:
            return
        if k66 <= 10 and not self.moving:
            return
        self.stream_acc += dt_ms
        if self.stream_acc < k67:
            return
        self.stream_acc = 0.0
        name = F.STREAM_NAMES.get(k66, "K66")
        if k66 == 1:
            v = int(self.vmax * self.ppr / RESOLUTION_MAX)
        elif k66 in (2,):
            v = self.pos_user
        elif k66 == 3:
            v = self.vel_user
        elif k66 == 5:
            v = int(round(self.pos))
        elif k66 == 6:
            v = int(round(self.vel))
        else:
            v = self._torque_proxy()
        self.emit(self.fmt("stream", name=name, v=v))

    # ------------------------------------------------------------------ horloge
    def tick(self, dt_ms: float) -> None:
        self.time_ms += dt_ms
        self.cnt += dt_ms
        if self.tmr > 0:
            self.tmr = max(0.0, self.tmr - dt_ms)
        if self.reset_at is not None and self.time_ms >= self.reset_at:
            self.reset_at = None
            self.emit(self.fmt("banner", fw=self.fw, hw=self.hw))
            k85 = self.k.get(85, 0)
            if k85:
                self._run_bank(f"L{k85}")
        self._tick_motion(dt_ms / 1000.0)
        self._tick_program(dt_ms)
        self._tick_logic(dt_ms)
        self._tick_stream(dt_ms)
