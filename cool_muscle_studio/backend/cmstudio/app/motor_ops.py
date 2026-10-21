"""Opérations de lecture sur un moteur : K37, position, export complet de la configuration.

Tout ici n'envoie que des lectures (autorisées en mode normal par le pont).
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import units
from ..reference import Reference
from .bridge_client import BridgeClient

RE_K = re.compile(r"^K(\d+)\.(\d+)=(-?\d+)$")
RE_REG = re.compile(r"^([PSAMTVNRH])(\d+)\.(\d+)=(.*)$")
RE_BANK_START = re.compile(r"^([BL])(\d+)(?:\.(\d+))?$", re.I)
RE_END = re.compile(r"^END(?:\.(\d+))?$", re.I)
RE_UX = re.compile(r"^Ux\.")
RE_PX = re.compile(r"^Px\.(\d+)=(-?\d+)$")
RE_BANNER = re.compile(r"CM1\s+ID(\d+)\s+(.*)")

# K dont la restauration peut couper la liaison avec le pont : exportés en commentaire
LINK_K = {20, 23, 52, 62, 65, 70}


async def collect(bridge: BridgeClient, cmd: str, quiet: float = 0.35, timeout: float = 6.0) -> list[str]:
    """Envoie une lecture et rassemble les lignes RX de la réponse (écho et Ux exclus)."""
    q = bridge.subscribe()
    lines: list[str] = []
    loop = asyncio.get_running_loop()
    try:
        await bridge.send(cmd)
        deadline = loop.time() + timeout
        last = loop.time()
        while True:
            now = loop.time()
            if lines and now - last > quiet:
                break
            remaining = min(deadline - now, quiet if lines else timeout)
            if remaining <= 0:
                break
            try:
                ev = await asyncio.wait_for(q.get(), remaining)
            except asyncio.TimeoutError:
                if lines:
                    break
                continue
            if ev.type == "err" and ev.line == cmd:
                raise RuntimeError(f"lecture refusée par le pont ({ev.code})")
            if ev.type != "rx" or ev.echo or ev.line == cmd or RE_UX.match(ev.line):
                continue
            lines.append(ev.line)
            last = loop.time()
    finally:
        bridge.unsubscribe(q)
    return lines


async def read_k37(bridge: BridgeClient, motor: int) -> dict[str, Any]:
    lines = await collect(bridge, f"K37.{motor}", quiet=0.2, timeout=2.0)
    for l in lines:
        m = RE_K.match(l)
        if m and int(m.group(1)) == 37:
            v = int(m.group(3))
            try:
                return {"k37": v, "resolution": units.resolution(v), "unite_vitesse": units.speed_unit(v)}
            except KeyError:
                return {"k37": v, "resolution": None, "unite_vitesse": None}
    raise RuntimeError("pas de réponse du moteur à K37")


async def read_position(bridge: BridgeClient, motor: int) -> dict[str, Any]:
    lines = await collect(bridge, f"?96.{motor}", quiet=0.2, timeout=2.0)
    for l in lines:
        m = RE_PX.match(l)
        if m:
            return {"pulses": int(m.group(2)), "ligne": l}
    raise RuntimeError("pas de réponse du moteur à ?96")


@dataclass
class ConfigExport:
    pont: str
    moteur: int
    horodatage: str
    banniere: str | None
    k: dict[int, int]
    registres: dict[str, dict[int, str]]
    banques: list[dict[str, Any]]
    brut: dict[str, list[str]] = field(default_factory=dict)

    def to_cml(self, reference: Reference | None = None) -> str:
        out: list[str] = []
        m = self.moteur
        out.append(f"/ Sauvegarde Cool Muscle Studio - pont {self.pont} - moteur {m} - {self.horodatage}")
        if self.banniere:
            out.append(f"/ {self.banniere}")
        out.append("/ Les K de liaison (K20 K23 K52 K62 K65 K70) sont en commentaire :")
        out.append("/ les retirer du commentaire seulement en connaissance de cause.")
        out.append("")
        out.append("/ --- Parametres K ---")
        for num in sorted(self.k):
            if reference is not None and reference.k(num) is not None:
                out.append(f"/ K{num} : {reference.k(num).nom}")  # en commentaire séparé : « / » et « , » sont des opérateurs CML
            prefix = "/" if num in LINK_K else ""
            out.append(f"{prefix}K{num}.{m}={self.k[num]}")
        out.append("")
        out.append("/ --- Registres (valeurs non nulles) ---")
        for letter in "PSAMTVNRH":
            regs = self.registres.get(letter, {})
            for idx in sorted(regs):
                v = regs[idx]
                if v in ("0", "", '""'):
                    continue
                out.append(f"{letter}{idx}.{m}={v}")
        out.append("")
        out.append("/ --- Banques ---")
        if self.banques:
            out.append(f"B100.{m}")
            out.append(f"L100.{m}")
        for b in self.banques:
            out.append(f"{b['nom']}.{m}")
            for line in b["lignes"]:
                out.append(line)
            out.append(f"END.{m}")
        out.append("")
        out.append(f"$.{m}")
        return "\n".join(out) + "\n"

    def to_dict(self) -> dict[str, Any]:
        return {
            "pont": self.pont, "moteur": self.moteur, "horodatage": self.horodatage, "banniere": self.banniere,
            "k": {str(k): v for k, v in self.k.items()},
            "registres": {l: {str(i): v for i, v in r.items()} for l, r in self.registres.items()},
            "banques": self.banques, "brut": self.brut,
        }


def parse_banks(lines: list[str]) -> list[dict[str, Any]]:
    banks: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for l in lines:
        s = l.strip()
        m = RE_BANK_START.match(s)
        if m and cur is None and int(m.group(2)) != 100:
            cur = {"nom": f"{m.group(1).upper()}{int(m.group(2))}", "lignes": []}
            continue
        if cur is not None:
            if RE_END.match(s):
                banks.append(cur)
                cur = None
            else:
                cur["lignes"].append(s)
    if cur is not None:  # banque non terminée dans la réponse : on la garde telle quelle
        cur["incomplete"] = True
        banks.append(cur)
    return banks


async def export_config(bridge: BridgeClient, motor: int, reference: Reference, dossier: Path, banner_timeout: float = 2.0) -> tuple[ConfigExport, Path, Path]:
    """Lit K, registres et banques, écrit <dossier>/sauvegardes/<pont>_m<n>_<date>.cml et .json."""
    brut: dict[str, list[str]] = {}
    banner = None
    for l in await collect(bridge, f"?85.{motor}", quiet=0.2, timeout=banner_timeout):
        if RE_BANNER.search(l):
            banner = l
    brut["?85"] = [banner] if banner else []
    k_lines = await collect(bridge, f"?90.{motor}")
    brut["?90"] = k_lines
    k: dict[int, int] = {}
    for l in k_lines:
        m = RE_K.match(l)
        if m and int(m.group(2)) == motor:
            k[int(m.group(1))] = int(m.group(3))
    registres: dict[str, dict[int, str]] = {}
    for letter in "PSAMTVNRH":
        lines = await collect(bridge, f"?{letter}.{motor}", quiet=0.3, timeout=4.0)
        brut[f"?{letter}"] = lines
        regs: dict[int, str] = {}
        for l in lines:
            m = RE_REG.match(l)
            if m and m.group(1) == letter and int(m.group(3)) == motor:
                regs[int(m.group(2))] = m.group(4).strip()
        registres[letter] = regs
    bank_lines = await collect(bridge, f"?1000.{motor}", quiet=0.5, timeout=10.0)
    brut["?1000"] = bank_lines
    banques = parse_banks(bank_lines)
    now = datetime.now(timezone.utc).astimezone()
    exp = ConfigExport(pont=bridge.name, moteur=motor, horodatage=now.isoformat(timespec="seconds"), banniere=banner,
                       k=k, registres=registres, banques=banques, brut=brut)
    sdir = Path(dossier) / "sauvegardes"
    sdir.mkdir(parents=True, exist_ok=True)
    slug = "".join(c.lower() if c.isalnum() else "-" for c in bridge.name).strip("-") or "pont"
    base = sdir / f"{slug}_m{motor}_{now:%Y%m%d-%H%M%S}"
    cml_path = base.with_suffix(".cml")
    json_path = base.with_suffix(".json")
    cml_path.write_text(exp.to_cml(reference), encoding="utf-8", newline="\n")
    json_path.write_text(json.dumps(exp.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    return exp, cml_path, json_path


def list_backups(dossier: Path) -> list[dict[str, Any]]:
    sdir = Path(dossier) / "sauvegardes"
    if not sdir.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(sdir.glob("*.cml"), reverse=True):
        st = p.stat()
        out.append({"nom": p.name, "taille": st.st_size, "modifie": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).astimezone().isoformat(timespec="seconds"),
                    "json": p.with_suffix(".json").name if p.with_suffix(".json").is_file() else None})
    return out


_ = time  # conservé pour les horodatages futurs
