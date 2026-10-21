"""Prétraitement CMP (dialecte de Control Room) vers CML pur.

Source : page « CML vs CMP » et User Guide §20.2.
- commentaires « // » (fin de ligne) et « /* ... */ » (multi-lignes), non envoyés ;
- « #define NOM VALEUR » : constante remplacée partout ;
- « var NOM REG » : nom remplacé par le registre (ex : var Home P1) ;
- constantes numériques dans une banque : Control Room « assigne la constante
  à un registre non utilisé » ; ici un registre N libre est alloué et sa
  définition insérée avant la banque.
Le résultat garde le même nombre de lignes que l'entrée (les lignes
supprimées deviennent vides) pour conserver les numéros de ligne ;
les définitions insérées sont ajoutées juste avant la banque et décalent
les lignes suivantes : ``line_map[i]`` donne la ligne d'origine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import Diagnostic, Kind
from .parser import parse_line, parse_program

_RE_DEFINE = re.compile(r"^\s*#define\s+([A-Za-z_]\w*)\s+(\S+)\s*$")
_RE_VAR = re.compile(r"^\s*var\s+([A-Za-z_]\w*)\s+([A-Za-z]\d+(?:\.\d+)?)\s*$", re.I)


@dataclass
class CmpResult:
    cml: str
    defines: dict[str, str] = field(default_factory=dict)
    variables: dict[str, str] = field(default_factory=dict)
    constants: dict[str, int] = field(default_factory=dict)  # registre alloué -> constante
    diagnostics: list[Diagnostic] = field(default_factory=list)
    line_map: list[int] = field(default_factory=list)       # index 0 = ligne 1 du CML -> ligne d'origine


def _strip_block_comments(text: str) -> str:
    out: list[str] = []
    i = 0
    in_str = False
    while i < len(text):
        ch = text[i]
        if ch == '"':
            in_str = not in_str
            out.append(ch)
            i += 1
        elif not in_str and text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                end = len(text) - 2
            # conserve les retours à la ligne pour garder la numérotation
            out.append("".join("\n" for c in text[i:end + 2] if c == "\n"))
            i = end + 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _strip_line_comment(line: str) -> str:
    in_str = False
    for i, ch in enumerate(line):
        if ch == '"':
            in_str = not in_str
        elif not in_str and line.startswith("//", i):
            return line[:i].rstrip()
    return line


def _substitute(line: str, mapping: dict[str, str]) -> str:
    if not mapping:
        return line
    names = sorted(mapping, key=len, reverse=True)
    pattern = re.compile(r"(?<![\w])(" + "|".join(re.escape(n) for n in names) + r")(?![\w])")
    parts = line.split('"')
    # les segments impairs sont à l'intérieur des guillemets
    out: list[str] = []
    for i, seg in enumerate(parts):
        out.append(seg if i % 2 else pattern.sub(lambda m: mapping[m.group(1)], seg))
    return '"'.join(out)


def preprocess(text: str) -> CmpResult:
    """Transforme un texte CMP en CML pur (sans allocation de constantes)."""
    res = CmpResult(cml="")
    text = _strip_block_comments(text)
    lines = [_strip_line_comment(ln.rstrip("\r")).rstrip() for ln in text.split("\n")]
    kept: list[str] = []
    for number, line in enumerate(lines, start=1):
        m = _RE_DEFINE.match(line)
        if m:
            res.defines[m.group(1)] = m.group(2)
            kept.append("")
            continue
        m = _RE_VAR.match(line)
        if m:
            res.variables[m.group(1)] = m.group(2).upper()
            kept.append("")
            continue
        kept.append(line)
    mapping = {**res.defines, **res.variables}
    res.cml = "\n".join(_substitute(ln, mapping) for ln in kept)
    res.line_map = list(range(1, len(kept) + 1))
    return res


def compile_cmp(text: str) -> CmpResult:
    """Prétraite puis alloue des registres N pour les constantes dans les banques."""
    res = preprocess(text)
    prog = parse_program(res.cml)
    # registres N déjà utilisés dans le fichier
    used: set[int] = set()
    for ln in prog.lines:
        for st in _iter_statements(ln.statements):
            if st.kind in (Kind.REG_WRITE, Kind.REG_READ) and st.reg == "N" and st.index is not None:
                used.add(st.index)
            if st.value and st.value.kind == "expr":
                for ref in st.value.refs:
                    if ref.startswith("N"):
                        used.add(int(ref[1:]))
    free = [i for i in range(1, 26) if i not in used]
    cml_lines = res.cml.split("\n")
    insertions: dict[int, list[str]] = {}  # avant la ligne (1-based) -> définitions
    for bank in prog.banks:
        for pl in bank.lines:
            for st in pl.statements:
                if st.kind is Kind.REG_WRITE and st.reg and st.value and st.value.kind == "int":
                    if not free:
                        res.diagnostics.append(Diagnostic("erreur", "E010", pl.number, "plus de registre N libre pour remplacer une constante dans la banque"))
                        continue
                    n = free.pop(0)
                    suffix = f".{st.motor}" if st.motor is not None else ""
                    reg_name = f"N{n}{suffix}"
                    res.constants[reg_name] = st.value.int_value or 0
                    insertions.setdefault(bank.start_line, []).append(f"{reg_name}={st.value.int_value}")
                    old = pl.code
                    new = re.sub(r"=\s*-?\d+\s*$", f"={reg_name}", st.raw.rstrip(";")) + (";" if st.raw.endswith(";") else "")
                    cml_lines[pl.number - 1] = cml_lines[pl.number - 1].replace(st.raw, new, 1)
                    _ = old
    out: list[str] = []
    line_map: list[int] = []
    for number, line in enumerate(cml_lines, start=1):
        for ins in insertions.get(number, []):
            out.append(ins)
            line_map.append(number)
        out.append(line)
        line_map.append(number)
    res.cml = "\n".join(out)
    res.line_map = line_map
    return res


def _iter_statements(statements):
    for st in statements:
        yield st
        yield from _iter_statements(st.then)
        yield from _iter_statements(st.otherwise)
        yield from _iter_statements(st.children)


__all__ = ["CmpResult", "compile_cmp", "preprocess", "parse_line"]
