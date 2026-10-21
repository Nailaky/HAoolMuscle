"""Téléchargement d'un fichier CML vers le moteur, ligne par ligne.

Chaque ligne est envoyée au pont puis confirmée par l'écho du moteur (ligne RX
identique). Sans écho dans le délai, ou sur une erreur du pont, le transfert
s'arrête et signale la dernière ligne confirmée : jamais d'état à moitié
écrit sans le dire. La relecture de vérification (?1000, ?90…) viendra à
l'étape 3.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from ..cml.cmp import compile_cmp
from ..cml.model import Diagnostic, Kind
from ..cml.parser import parse_program
from ..cml.validate import validate
from ..reference import Reference
from .bridge_client import BridgeClient, Event

ECHO_TIMEOUT = 2.0
SAVE_TIMEOUT = 3.0


@dataclass
class Analysis:
    nom: str
    lignes: list[tuple[int, str]]          # (numéro de ligne d'origine, texte à envoyer)
    diagnostics: list[Diagnostic]
    banques: list[str]
    ecritures_k: list[str]
    k37: bool
    sauvegarde: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "nom": self.nom,
            "nb_lignes": len(self.lignes),
            "lignes": [{"n": n, "texte": t} for n, t in self.lignes],
            "diagnostics": [{"severite": d.severity, "code": d.code, "ligne": d.line, "message": d.message} for d in self.diagnostics],
            "erreurs": sum(1 for d in self.diagnostics if d.severity == "erreur"),
            "banques": self.banques,
            "ecritures_k": self.ecritures_k,
            "k37": self.k37,
            "sauvegarde": self.sauvegarde,
        }


def sequence(nom: str, lignes: list[str]) -> Analysis:
    """Analyse minimale pour une séquence de commandes déjà construites (commandes rapides)."""
    clean = [(i + 1, l.strip()) for i, l in enumerate(lignes) if l.strip()]
    return Analysis(nom=nom, lignes=clean, diagnostics=[], banques=[], ecritures_k=[l for _, l in clean if l.upper().startswith("K")],
                    k37=any(l.upper().startswith("K37") for _, l in clean), sauvegarde=any(l.startswith("$") for _, l in clean))


def analyse(nom: str, contenu: str, reference: Reference) -> Analysis:
    """Prétraite (CMP), analyse et valide un fichier ; renvoie les lignes à envoyer."""
    res = compile_cmp(contenu)
    prog = parse_program(res.cml)
    diags = list(res.diagnostics) + validate(prog, reference)
    lignes: list[tuple[int, str]] = []
    for pl in prog.lines:
        if pl.code and not pl.is_comment:
            origine = res.line_map[pl.number - 1] if pl.number - 1 < len(res.line_map) else pl.number
            lignes.append((origine, pl.code))
    k_writes: list[str] = []
    k37 = False
    save = False
    for pl in prog.lines:
        for st in pl.statements:
            if st.kind is Kind.REG_WRITE and st.reg == "K":
                k_writes.append(st.raw)
                if st.index == 37:
                    k37 = True
            if st.kind is Kind.COMMAND and st.command == "$":
                save = True
    return Analysis(nom=nom, lignes=lignes, diagnostics=diags, banques=[b.name for b in prog.banks],
                    ecritures_k=k_writes, k37=k37, sauvegarde=save)


@dataclass
class TransferState:
    nom: str
    total: int
    index: int = 0                 # nombre de lignes confirmées
    etat: str = "en_attente"       # en_attente | en_cours | termine | annule | erreur
    ligne_courante: str = ""
    erreur: str | None = None
    debut: float = field(default_factory=time.time)
    fin: float | None = None
    attendre_echo: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "nom": self.nom, "total": self.total, "index": self.index, "etat": self.etat,
            "ligne_courante": self.ligne_courante, "erreur": self.erreur, "debut": self.debut, "fin": self.fin,
            "attendre_echo": self.attendre_echo,
        }


class Transfer:
    """Un transfert en cours vers un pont."""

    def __init__(self, bridge: BridgeClient, analysis: Analysis, attendre_echo: bool = True, journal=None, utilisateur: str | None = None, origine: str | None = None) -> None:
        self.bridge = bridge
        self.analysis = analysis
        self.origine = origine or f"fichier:{analysis.nom}"
        self.state = TransferState(nom=analysis.nom, total=len(analysis.lignes), attendre_echo=attendre_echo)
        self.journal = journal
        self.utilisateur = utilisateur
        self._task: asyncio.Task | None = None
        self._cancel = asyncio.Event()

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name=f"transfert-{self.bridge.name}")

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def running(self) -> bool:
        return self.state.etat in ("en_attente", "en_cours")

    async def wait(self) -> TransferState:
        if self._task:
            await self._task
        return self.state

    def _notify(self) -> None:
        ev = Event(0, time.time(), "transfert", line=self.state.ligne_courante, origin=self.state.etat, extra=self.state.to_dict())
        self.bridge._emit(ev)  # noqa: SLF001 - diffusion aux abonnés du pont (terminal, journal)

    async def _run(self) -> None:
        st = self.state
        q = self.bridge.subscribe()
        st.etat = "en_cours"
        self._notify()
        try:
            for n, line in self.analysis.lignes:
                if self._cancel.is_set():
                    st.etat = "annule"
                    st.erreur = f"annulé après {st.index} ligne(s) confirmée(s)"
                    break
                st.ligne_courante = line
                self._notify()
                # vide les événements précédents
                while not q.empty():
                    q.get_nowait()
                try:
                    await self.bridge.send(line)
                except ConnectionError as exc:
                    st.etat = "erreur"
                    st.erreur = f"ligne {n} : pont déconnecté ({exc}) ; {st.index} ligne(s) confirmée(s)"
                    break
                if self.journal is not None:
                    self.journal.write(self.bridge.name, line, self.utilisateur, origine=self.origine, ligne_fichier=n)
                ok, err = await self._wait_echo(q, line, SAVE_TIMEOUT if line.lstrip().startswith("$") else ECHO_TIMEOUT)
                if err:
                    st.etat = "erreur"
                    st.erreur = f"ligne {n} ({line}) : {err} ; {st.index} ligne(s) confirmée(s)"
                    break
                if not ok and st.attendre_echo:
                    st.etat = "erreur"
                    st.erreur = f"ligne {n} ({line}) : pas d'écho du moteur dans le délai ; {st.index} ligne(s) confirmée(s)"
                    break
                st.index += 1
                self._notify()
            else:
                st.etat = "termine"
        finally:
            self.bridge.unsubscribe(q)
            st.fin = time.time()
            st.ligne_courante = ""
            self._notify()

    async def _wait_echo(self, q: asyncio.Queue, line: str, timeout: float) -> tuple[bool, str | None]:
        """Attend l'écho de ``line`` ; renvoie (écho vu, message d'erreur du pont)."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        seen_echo = False
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return seen_echo, None
            try:
                ev = await asyncio.wait_for(q.get(), remaining)
            except asyncio.TimeoutError:
                return seen_echo, None
            if ev.type == "err" and ev.line == line:
                return seen_echo, {"FORBIDDEN": "écriture refusée par le pont (mode maintenance requis)",
                                   "TOOLONG": "ligne trop longue pour le pont", "QUEUE_FULL": "file du pont pleine"}.get(ev.code or "", f"erreur du pont {ev.code}")
            if ev.type == "rx" and ev.line == line:
                seen_echo = True
                if not self.state.attendre_echo:
                    return True, None
                # laisse passer une éventuelle réponse immédiate (ex. Saved.1) sans la bloquer
                return True, None
            if ev.type == "conn" and ev.origin == "deconnecte":
                return seen_echo, "pont déconnecté pendant le transfert"
            if not self.state.attendre_echo and ev.type == "tx" and ev.line == line:
                # sans attente d'écho, l'émission par le pont suffit
                return True, None
