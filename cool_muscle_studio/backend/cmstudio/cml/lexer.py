"""Découpage d'une ligne CML en instructions.

Règles (User Guide §10.1.1, §10.5.2, §10.6, §20.2.1) :
- une ligne contient une ou plusieurs instructions séparées par des virgules ;
- une ligne qui commence par « / » (ou « // ») est un commentaire, non envoyé au moteur ;
- les chaînes sont entre guillemets doubles et peuvent contenir virgules et deux-points ;
- « : » joint deux instructions exécutées en même temps (jonction).
"""

from __future__ import annotations


def normalize(line: str) -> str:
    """Retire CR/LF et les espaces de bout."""
    return line.rstrip("\r\n").strip()


def is_comment(line: str) -> bool:
    s = line.lstrip()
    return s.startswith("/")


def split_outside_quotes(text: str, sep: str) -> list[str]:
    """Découpe ``text`` sur ``sep`` en ignorant les séparateurs entre guillemets."""
    parts: list[str] = []
    cur: list[str] = []
    in_str = False
    for ch in text:
        if ch == '"':
            in_str = not in_str
            cur.append(ch)
        elif ch == sep and not in_str:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts


def split_statements(line: str) -> list[str]:
    """Instructions d'une ligne (sans commentaire), espaces retirés, vides supprimées."""
    code = normalize(line)
    if not code or is_comment(code):
        return []
    return [p.strip() for p in split_outside_quotes(code, ",") if p.strip()]


def contains_outside_quotes(text: str, needle: str) -> bool:
    in_str = False
    i = 0
    n = len(needle)
    while i < len(text):
        ch = text[i]
        if ch == '"':
            in_str = not in_str
        elif not in_str and text.startswith(needle, i):
            return True
        i += 1
    return False
