"""Chargement de la base de référence CML (reference/cml_reference.yaml).

La base est le fichier YAML construit à partir de la documentation Myostat.
Ce module la charge une seule fois et expose des objets typés pour la
validation des paramètres K, des registres et le décodage des commandes.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ENV_VAR = "CMSTUDIO_REFERENCE"
FILE_NAME = "cml_reference.yaml"


def find_reference_path(start: Path | None = None) -> Path:
    """Localise le fichier de référence.

    Ordre : variable d'environnement CMSTUDIO_REFERENCE, puis un dossier
    ``reference/`` dans le répertoire courant ou l'un de ses parents, puis
    dans le dossier du paquet ou l'un de ses parents, puis ``cmstudio/data/``
    (copie faite dans l'image Docker).
    """
    env = os.environ.get(ENV_VAR)
    if env:
        p = Path(env)
        if p.is_file():
            return p
        raise FileNotFoundError(f"{ENV_VAR}={env} n'existe pas")
    here = Path(__file__).resolve().parent
    bases = [start or Path.cwd(), here]
    candidates: list[Path] = []
    for base in bases:
        for parent in [base, *base.parents]:
            candidates.append(parent / "reference" / FILE_NAME)
    candidates.append(here / "data" / FILE_NAME)
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError(f"Fichier {FILE_NAME} introuvable (essayé : {len(candidates)} emplacements)")


@dataclass(frozen=True)
class KParam:
    """Un paramètre K tel que décrit dans la référence."""

    num: int
    nom: str
    unite: str | None = None
    type: str | None = None  # int | enum | bits | digits2 | digits4
    min: int | None = None
    max: int | None = None
    defaut: int | None = None
    valeurs: dict[int, str] = field(default_factory=dict)
    bits: dict[int, str] = field(default_factory=dict)
    valeurs_chiffre: dict[int, str] | None = None
    min_chiffre: int | None = None
    max_chiffre: int | None = None
    statut: str = "documente"
    note: str | None = None
    avertissement: str | None = None

    @property
    def nb_chiffres(self) -> int | None:
        if self.type == "digits4":
            return 4
        if self.type == "digits2":
            return 2
        return None

    @property
    def documente(self) -> bool:
        """Vrai si le paramètre est assez documenté pour être validé (statut ≠ a_confirmer)."""
        return self.type is not None and self.statut != "a_confirmer"

    def check(self, value: int) -> list[str]:
        """Retourne la liste des problèmes (vide si la valeur est acceptable)."""
        problems: list[str] = []
        if self.defaut is not None and value == self.defaut:
            return problems  # la valeur d'usine est toujours acceptable, même hors plage documentée (K22, K60, K87, K88)
        if self.type == "int":
            if self.min is not None and value < self.min:
                problems.append(f"K{self.num} : {value} est inférieur au minimum {self.min}")
            if self.max is not None and value > self.max:
                problems.append(f"K{self.num} : {value} est supérieur au maximum {self.max}")
        elif self.type == "enum":
            if value not in self.valeurs:
                problems.append(f"K{self.num} : {value} n'est pas une valeur admise ({', '.join(str(v) for v in self.valeurs)})")
        elif self.type == "bits":
            mask = sum(self.bits)
            if value < 0 or value & ~mask:
                problems.append(f"K{self.num} : {value} contient des bits inconnus (masque admis {mask})")
        elif self.type in ("digits2", "digits4"):
            n = self.nb_chiffres or 0
            if value < 0 or value >= 10**n:
                problems.append(f"K{self.num} : {value} doit avoir au plus {n} chiffres")
            else:
                for pos, ch in enumerate(reversed(f"{value:0{n}d}"), start=1):
                    d = int(ch)
                    if self.valeurs_chiffre is not None and d not in self.valeurs_chiffre:
                        problems.append(f"K{self.num} : le chiffre N{pos} ({d}) n'est pas une fonction admise")
                    elif self.valeurs_chiffre is None and self.min_chiffre is not None and not (self.min_chiffre <= d <= (self.max_chiffre or 9)):
                        problems.append(f"K{self.num} : le chiffre N{pos} ({d}) doit être entre {self.min_chiffre} et {self.max_chiffre}")
        return problems


@dataclass(frozen=True)
class RegisterFamily:
    lettre: str
    nom: str
    index_min: int
    index_max: int
    unite: str | None = None
    min: int | None = None
    max: int | None = None

    def check_index(self, index: int) -> str | None:
        if not (self.index_min <= index <= self.index_max):
            return f"{self.lettre}{index} : indice hors plage {self.index_min}..{self.index_max}"
        return None

    def check_value(self, value: int) -> str | None:
        if self.min is not None and value < self.min:
            return f"{self.lettre} : {value} est inférieur au minimum {self.min}"
        if self.max is not None and value > self.max:
            return f"{self.lettre} : {value} est supérieur au maximum {self.max}"
        return None


@dataclass(frozen=True)
class StatusCode:
    valeur: int
    nom: str
    alarme: bool
    desactive_moteur: bool
    statut: str = "documente"


class Reference:
    """La base de référence chargée."""

    def __init__(self, data: dict[str, Any], path: Path | None = None):
        self.data = data
        self.path = path
        self.k_params: dict[int, KParam] = {}
        self._load_k()
        self.registers: dict[str, RegisterFamily] = {}
        self._load_registers()
        self.status_codes: list[StatusCode] = [
            StatusCode(
                valeur=int(c["valeur"]),
                nom=str(c["nom"]),
                alarme=bool(c.get("alarme", False)),
                desactive_moteur=bool(c.get("desactive_moteur", False)),
                statut=str(c.get("statut", "documente")),
            )
            for c in data["etats_ux"]["codes"]
        ]
        self.commands: list[dict[str, Any]] = list(data["commandes_directes"])
        self.queries: list[dict[str, Any]] = list(data["requetes"]["liste"])
        self.variables: list[dict[str, Any]] = list(data["variables_internes"]["liste"])

    # ------------------------------------------------------------------
    def _load_k(self) -> None:
        raw_list = self.data["parametres_k"]["liste"]
        by_num: dict[int, dict[str, Any]] = {int(e["k"]): e for e in raw_list}
        for num, e in by_num.items():
            vc = e.get("valeurs_chiffre")
            if isinstance(vc, str):
                # "comme K27" -> copie des valeurs du paramètre cité
                m = re.search(r"K(\d+)", vc)
                vc = by_num[int(m.group(1))].get("valeurs_chiffre") if m else None
            self.k_params[num] = KParam(
                num=num,
                nom=str(e.get("nom", f"K{num}")),
                unite=e.get("unite"),
                type=e.get("type"),
                min=e.get("min"),
                max=e.get("max"),
                defaut=e.get("defaut"),
                valeurs={int(k): str(v) for k, v in (e.get("valeurs") or {}).items()},
                bits={int(k): str(v) for k, v in (e.get("bits") or {}).items()},
                valeurs_chiffre={int(k): str(v) for k, v in vc.items()} if isinstance(vc, dict) else None,
                min_chiffre=e.get("min_chiffre"),
                max_chiffre=e.get("max_chiffre"),
                statut=str(e.get("statut", "documente")),
                note=e.get("note"),
                avertissement=e.get("avertissement"),
            )

    def _load_registers(self) -> None:
        for fam in self.data["registres"]["familles"]:
            lettre = str(fam["lettre"])
            m = re.search(r"(\d+)\.\.(\d+)", str(fam.get("indices", "")))
            if not m:
                continue
            lo, hi = int(m.group(1)), int(m.group(2))
            if lettre == "T":
                lo = 0  # T0 = no-op, accepté dans les banques
            self.registers[lettre] = RegisterFamily(
                lettre=lettre,
                nom=str(fam.get("nom", lettre)),
                index_min=lo,
                index_max=hi,
                unite=fam.get("unite"),
                min=fam.get("min"),
                max=fam.get("max"),
            )

    # ------------------------------------------------------------------
    def k(self, num: int) -> KParam | None:
        return self.k_params.get(num)

    def k_defaults(self) -> dict[int, int]:
        """Valeurs par défaut documentées (0 pour les paramètres sans défaut)."""
        return {num: (p.defaut if p.defaut is not None else 0) for num, p in self.k_params.items()}

    def status(self, valeur: int) -> StatusCode | None:
        for c in self.status_codes:
            if c.valeur == valeur:
                return c
        return None

    def command(self, cmd: str) -> dict[str, Any] | None:
        for c in self.commands:
            if c.get("cmd") == cmd:
                return c
        return None


@lru_cache(maxsize=4)
def _load(path_str: str) -> Reference:
    path = Path(path_str)
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return Reference(data, path)


def load_reference(path: Path | None = None) -> Reference:
    """Charge (avec cache) la référence depuis ``path`` ou l'emplacement par défaut."""
    p = path or find_reference_path()
    return _load(str(p.resolve()))
