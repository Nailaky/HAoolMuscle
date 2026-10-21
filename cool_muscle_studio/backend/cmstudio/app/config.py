"""Configuration de l'app : options Home Assistant (/data/options.json) ou ligne de commande."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

HA_OPTIONS = Path("/data/options.json")


@dataclass
class BridgeConfig:
    nom: str
    hote: str
    port: int = 6638

    @property
    def slug(self) -> str:
        return "".join(c.lower() if c.isalnum() else "-" for c in self.nom).strip("-") or "pont"


@dataclass
class AppConfig:
    ponts: list[BridgeConfig] = field(default_factory=list)
    dossier: Path = Path("/share/cool_muscle")
    sortie_auto_maintenance_s: int = 60
    mode_expert: bool = False
    host: str = "0.0.0.0"
    port: int = 8099
    ingress_only: bool = True   # n'accepter que la passerelle ingress (172.30.32.2)
    dev: bool = False           # simulateur en interne

    @classmethod
    def from_options(cls, data: dict) -> AppConfig:
        ponts = [BridgeConfig(str(p.get("nom", f"Pont {i + 1}")), str(p.get("hote", "")), int(p.get("port", 6638)))
                 for i, p in enumerate(data.get("ponts", []))]
        return cls(
            ponts=ponts,
            dossier=Path(str(data.get("dossier") or "/share/cool_muscle")),
            sortie_auto_maintenance_s=int(data.get("sortie_auto_maintenance_s", 60)),
            mode_expert=bool(data.get("mode_expert", False)),
        )

    @classmethod
    def load(cls) -> AppConfig:
        if HA_OPTIONS.is_file():
            with HA_OPTIONS.open(encoding="utf-8") as fh:
                cfg = cls.from_options(json.load(fh))
            cfg.ingress_only = bool(os.environ.get("SUPERVISOR_TOKEN"))
            return cfg
        return cls(dossier=Path("var") / "cool_muscle", ingress_only=False)
