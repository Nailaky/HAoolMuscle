"""Chaîne de 1 à 15 moteurs simulés : adressage, écho, enregistrement de banques."""

from __future__ import annotations

from collections.abc import Callable

from ..cml.model import Kind
from ..cml.parser import parse_line
from ..reference import Reference, load_reference
from . import formats as F
from .motor import MotorSim

MAX_MOTORS = 15


class MotorChain:
    def __init__(self, motors: list[MotorSim] | None = None, count: int = 1, reference: Reference | None = None, **motor_kwargs) -> None:
        ref = reference or load_reference()
        if motors is None:
            motors = [MotorSim(motor_id=i, reference=ref, **motor_kwargs) for i in range(1, min(count, MAX_MOTORS) + 1)]
        self.motors: dict[int, MotorSim] = {m.id: m for m in motors}
        for m in self.motors.values():
            m.resolver = self._resolve_other
        self.last_id = min(self.motors)
        self.recording: MotorSim | None = None
        self.listeners: list[Callable[[str], None]] = []
        self.received: list[str] = []
        self.time_ms = 0.0

    @property
    def master(self) -> MotorSim:
        return self.motors[min(self.motors)]

    @property
    def busy(self) -> bool:
        return any(m.busy for m in self.motors.values())

    @property
    def in_alarm(self) -> bool:
        return any(m.in_alarm for m in self.motors.values())

    def add_listener(self, fn: Callable[[str], None]) -> None:
        self.listeners.append(fn)

    def _resolve_other(self, reg: str, motor_id: int) -> int:
        m = self.motors.get(motor_id)
        if m is None:
            return 0
        return m.reg_value(reg[0], int(reg[1:]))

    def _emit(self, line: str) -> None:
        for fn in self.listeners:
            fn(line)

    def collect(self) -> None:
        for m in self.motors.values():
            if m.out:
                for line in m.out:
                    self._emit(line)
                m.out.clear()

    # ------------------------------------------------------------------
    def feed(self, line: str) -> None:
        """Traite une ligne reçue (sans CR). Les moteurs répondent via les listeners."""
        text = line.rstrip("\r\n")
        if not text.strip():
            return
        self.received.append(text)
        if not (self.master.k.get(23, 1) & 8):
            self._emit(F.FORMATS["echo"].format(line=text))
        if self.recording is not None:
            pl = parse_line(text, in_bank=True)
            if any(st.kind is Kind.BANK_END for st in pl.statements):
                self.recording.end_recording()
                self.recording = None
            else:
                self.recording.record(text)
            self.collect()
            return
        pl = parse_line(text)
        for st in pl.statements:
            self._dispatch(st)
        self.collect()

    def _dispatch(self, st) -> None:
        if st.kind is Kind.COMMAND and st.command in ("*", "*1"):
            for m in self.motors.values():
                m.execute(st)
            return
        motor_id = st.motor
        if motor_id is None and st.kind is Kind.BRANCH:
            for sub in st.then + st.otherwise:
                if sub.motor is not None:
                    motor_id = sub.motor
                    break
        if motor_id is not None:
            if motor_id not in self.motors:
                return  # moteur absent : pas de réponse (comme sur une vraie chaîne)
            self.last_id = motor_id
        motor = self.motors[self.last_id]
        if st.kind is Kind.BANK_START:
            motor.start_recording(st.arg or "B0")
            self.recording = motor
            return
        motor.execute(st)

    def tick(self, dt_ms: float) -> None:
        self.time_ms += dt_ms
        for m in self.motors.values():
            m.tick(dt_ms)
        self.collect()
