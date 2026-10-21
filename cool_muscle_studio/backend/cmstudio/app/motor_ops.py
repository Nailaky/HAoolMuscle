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
RE_REG = re.compile(r"^([PSAMTVNRH])(\d+)\.(\d+)=([^,]*)$")
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


def statements(lines: list[str]) -> list[str]:
    """Découpe les lignes reçues en instructions : le moteur renvoie ?90 et les
    registres par groupes séparés par des virgules (observé : K20.1=0,K21.1=0,…)."""
    out: list[str] = []
    for l in lines:
        for part in l.split(","):
            p = part.strip()
            if p:
                out.append(p)
    return out


async def read_k37(bridge: BridgeClient, motor: int) -> dict[str, Any]:
    lines = await collect(bridge, f"K37.{motor}", quiet=0.25, timeout=3.0)
    for st in statements(lines):
        m = RE_K.match(st)
        if m and int(m.group(1)) == 37:
            v = int(m.group(3))
            try:
                return {"k37": v, "resolution": units.resolution(v), "unite_vitesse": units.speed_unit(v), "moteur": int(m.group(2))}
            except KeyError:
                return {"k37": v, "resolution": None, "unite_vitesse": None, "moteur": int(m.group(2))}
    raise RuntimeError(f"pas de réponse du moteur {motor} à K37 (lignes reçues : {lines or 'aucune'})")


async def read_position(bridge: BridgeClient, motor: int) -> dict[str, Any]:
    lines = await collect(bridge, f"?96.{motor}", quiet=0.25, timeout=3.0)
    for st in statements(lines):
        m = RE_PX.match(st)
        if m:
            return {"pulses": int(m.group(2)), "ligne": st}
    raise RuntimeError(f"pas de réponse du moteur {motor} à ?96 (lignes reçues : {lines or 'aucune'})")


@dataclass
class ConfigExport:
    pont: str
    moteur: int
    horodatage: str
    banniere: str | None
    k: dict[int, str]
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


RE_TOTAL = re.compile(r"^-\s*Total\s+(\d+)\s+steps?\s*-$", re.I)


def normalize_bank_line(line: str) -> str:
    """« A2.1, S2.1, P3.1+ » (format de ?1000) -> « A2.1,S2.1,P3.1+ »."""
    return ",".join(p.strip() for p in line.split(","))


def parse_banks(lines: list[str]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Analyse la réponse à ?1000 (format observé sur le moteur réel, RT3.14) :

        B1.1
        A2.1, S2.1, P3.1+
        B2.1
        A1.1, S1.1, P2.1
        - Total 12 steps -
        L1.1
        I4.1, [2.1, [3.1
        - Total 4 steps -

    Un nouvel en-tête B#/L# ferme la banque en cours ; il n'y a pas de END.
    Un éventuel END est accepté aussi. Retourne (banques, totaux par type).
    """
    banks: list[dict[str, Any]] = []
    totals: dict[str, int] = {}
    cur: dict[str, Any] | None = None
    for l in lines:
        s = l.strip()
        m = RE_BANK_START.match(s)
        if m and int(m.group(2)) != 100:
            if cur is not None:
                banks.append(cur)
            cur = {"nom": f"{m.group(1).upper()}{int(m.group(2))}", "lignes": []}
            continue
        mt = RE_TOTAL.match(s)
        if mt:
            if cur is not None:
                banks.append(cur)
                totals[cur["nom"][0]] = int(mt.group(1))
                cur = None
            continue
        if RE_END.match(s):
            if cur is not None:
                banks.append(cur)
                cur = None
            continue
        if cur is not None and s:
            cur["lignes"].append(normalize_bank_line(s))
    if cur is not None:
        banks.append(cur)
    return banks, totals


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
    k: dict[int, str] = {}
    for st in statements(k_lines):
        m = RE_K.match(st)
        if m and int(m.group(2)) == motor:
            k[int(m.group(1))] = m.group(3)  # texte conservé tel quel (K26.1=0000, K28.1=0800)
    registres: dict[str, dict[int, str]] = {}
    for letter in "PSAMTVNRH":
        lines = await collect(bridge, f"?{letter}.{motor}", quiet=0.3, timeout=4.0)
        brut[f"?{letter}"] = lines
        regs: dict[int, str] = {}
        for st in statements(lines):
            m = RE_REG.match(st)
            if m and m.group(1) == letter and int(m.group(3)) == motor:
                regs[int(m.group(2))] = m.group(4).strip()
        registres[letter] = regs
    bank_lines = await collect(bridge, f"?1000.{motor}", quiet=0.5, timeout=10.0)
    brut["?1000"] = bank_lines
    banques, totaux = parse_banks(bank_lines)
    brut["totaux"] = [f"{k}:{v}" for k, v in totaux.items()]
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
