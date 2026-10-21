"""Modèle d'un programme CML analysé."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Kind(StrEnum):
    REG_WRITE = "reg_write"      # P5.1=1000, K37=10, V2="Px", nom_cmp=..., P1.1=P2.1+V1.1
    REG_READ = "reg_read"        # P15.1
    QUERY = "query"              # ?96.1, ?, ?P
    BANK_START = "bank_start"    # B1.1 / L3
    BANK_END = "bank_end"        # END
    COMMAND = "command"          # ^ ~ | |1 ( ) O1 $ [3 [L2 ] ]L } > < * *1 _SKH B100 L100 {0 D3= FFFFFFFFF
    STEP = "step"                # P4+ S6 A1 M8 X4 X- Y4 Q4 Z4 C2 J2 CL2 JL2 I1 W0 T3 @2+
    BRANCH = "branch"            # condition, si_vrai, si_faux
    JUNCTION = "junction"        # a:b
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Value:
    """Valeur à droite d'un « = »."""

    kind: str                 # int | str | expr
    text: str
    int_value: int | None = None
    refs: tuple[str, ...] = ()  # références de registres ou noms trouvés dans l'expression


@dataclass
class Statement:
    kind: Kind
    raw: str
    motor: int | None = None          # suffixe .id explicite
    reg: str | None = None            # lettre de registre (majuscule)
    name: str | None = None           # nom CMP (var) ou commande spéciale (_SKH, _MOP, D)
    index: int | None = None
    value: Value | None = None
    command: str | None = None        # nom canonique de la commande ou du pas
    arg: str | None = None            # argument : numéro, 'L3', '-', ...
    plus: bool = False                # P4+ / @2+
    minus: bool = False               # @2-
    merge: bool = False               # ';' en fin (merge motion / écho désactivé)
    condition: str | None = None
    then: list[Statement] = field(default_factory=list)
    otherwise: list[Statement] = field(default_factory=list)
    children: list[Statement] = field(default_factory=list)  # jonction a:b

    def describe(self) -> str:
        """Description courte, pour les messages."""
        if self.kind is Kind.REG_WRITE:
            tgt = f"{self.reg}{self.index}" if self.reg else (self.name or "?")
            return f"écriture {tgt}"
        if self.kind is Kind.REG_READ:
            return f"lecture {self.reg}{self.index}"
        if self.kind is Kind.QUERY:
            return f"requête ?{self.arg or ''}"
        if self.kind is Kind.BANK_START:
            return f"début de banque {self.arg}"
        if self.kind is Kind.BANK_END:
            return "fin de banque"
        if self.kind is Kind.COMMAND:
            return f"commande {self.command}{self.arg or ''}"
        if self.kind is Kind.STEP:
            return f"pas {self.command}{self.arg or ''}"
        if self.kind is Kind.BRANCH:
            return "branchement"
        if self.kind is Kind.JUNCTION:
            return "jonction"
        return "inconnu"


@dataclass
class ParsedLine:
    number: int               # numéro de ligne (1 = première)
    raw: str                  # texte original sans CR/LF
    code: str                 # texte utile (commentaire retiré, espaces en bout retirés)
    statements: list[Statement]
    is_comment: bool = False
    in_bank: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.code and not self.is_comment


@dataclass
class Bank:
    kind: str                 # 'B' (programme) ou 'L' (logique)
    number: int
    motor: int | None
    start_line: int
    end_line: int | None = None
    lines: list[ParsedLine] = field(default_factory=list)

    @property
    def name(self) -> str:
        return f"{self.kind}{self.number}"

    @property
    def closed(self) -> bool:
        return self.end_line is not None

    def code_lines(self) -> list[str]:
        return [ln.code for ln in self.lines if ln.code]


@dataclass(frozen=True)
class Diagnostic:
    severity: str   # erreur | avertissement | info
    code: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"ligne {self.line} : [{self.severity} {self.code}] {self.message}"


@dataclass
class Program:
    lines: list[ParsedLine]
    banks: list[Bank]
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "erreur"]

    @property
    def top_level(self) -> list[ParsedLine]:
        return [ln for ln in self.lines if not ln.in_bank and ln.statements]

    def bank(self, name: str) -> Bank | None:
        for b in self.banks:
            if b.name == name.upper():
                return b
        return None

    def step_count(self) -> int:
        """Estimation du nombre de pas (lignes de code dans les banques)."""
        return sum(len(b.code_lines()) for b in self.banks)
