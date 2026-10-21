"""Décodage de l'état moteur (réponse à ?99 et messages Ux).

Les codes s'additionnent ; 0 signifie « en mouvement » seulement quand aucun
autre bit n'est présent. Source : page Status and Error States.
"""

from __future__ import annotations

from dataclasses import dataclass

# valeur -> (nom, alarme, désactive le moteur)
CODES: dict[int, tuple[str, bool, bool]] = {
    1: ("Dépassement d'erreur de position", True, True),
    2: ("Survitesse ou surtension", True, True),
    4: ("Surcharge / surintensité", True, True),
    8: ("En position / prêt", False, False),
    16: ("Désactivé", False, True),
    32: ("Limite de couple en mode poussée", False, False),
    64: ("Erreur de communication (à confirmer)", True, False),
    128: ("Surchauffe", True, True),
    256: ("Mode poussée : position atteinte avant la fin du temps", False, False),
    512: ("Arrêt d'urgence", True, False),
    16384: ("Nouveau démarrage requis (à confirmer)", False, False),
    32768: ("Origine atteinte (à confirmer)", False, False),
}

ALARM_MASK = sum(v for v, (_, alarme, _) in CODES.items() if alarme)


@dataclass(frozen=True)
class Flag:
    valeur: int
    nom: str
    alarme: bool


@dataclass(frozen=True)
class Status:
    valeur: int
    flags: tuple[Flag, ...]
    inconnus: int  # bits non documentés

    @property
    def en_mouvement(self) -> bool:
        return self.valeur == 0

    @property
    def en_position(self) -> bool:
        return bool(self.valeur & 8)

    @property
    def alarme(self) -> bool:
        return bool(self.valeur & ALARM_MASK)

    @property
    def desactive(self) -> bool:
        return bool(self.valeur & 16)

    @property
    def arret_urgence(self) -> bool:
        return bool(self.valeur & 512)

    @property
    def texte(self) -> str:
        if self.valeur == 0:
            return "En mouvement"
        parts = [f.nom for f in self.flags]
        if self.inconnus:
            parts.append(f"bits inconnus {self.inconnus}")
        return ", ".join(parts)


def decode(valeur: int) -> Status:
    """Décode une valeur Ux en drapeaux."""
    flags: list[Flag] = []
    rest = valeur
    for bit, (nom, alarme, _) in CODES.items():
        if valeur & bit:
            flags.append(Flag(bit, nom, alarme))
            rest &= ~bit
    return Status(valeur=valeur, flags=tuple(flags), inconnus=rest)
