"""Analyseur syntaxique CML : instruction, ligne, programme.

Toute la syntaxe reconnue ici vient de la documentation (voir
reference/cml_reference.yaml, sections commandes_directes, requetes, banques).
Ce qui n'est pas reconnu devient Kind.UNKNOWN : le validateur le signale, il
n'est jamais « deviné ».
"""

from __future__ import annotations

import re

from .lexer import contains_outside_quotes, is_comment, normalize, split_outside_quotes, split_statements
from .model import Bank, Diagnostic, Kind, ParsedLine, Program, Statement, Value

REGISTER_LETTERS = "PSAMTVNRHK"

_RE_BANK_START = re.compile(r"^([BL])(\d+)(?:\.(\d+))?$", re.I)
_RE_END = re.compile(r"^END(?:\.(\d+))?$", re.I)
_RE_ASSIGN = re.compile(r"^([A-Za-z_][\w%]*)(?:\.(\d+))?\s*=(?!=)\s*(.*)$")
# « S.1=50 » ou « P=1000 » (mode direct, UG §9) : lettre seule = indice 0
_RE_REG = re.compile(rf"^([{REGISTER_LETTERS}{REGISTER_LETTERS.lower()}])(\d*)$")
_RE_QUERY = re.compile(r"^\?([A-Za-z0-9]*)(?:\.(\d+))?$")
_RE_MOTOR_SUFFIX = re.compile(r"^(.*?)\.(\d+)([+-]?)$")  # P4.1+ / @2.1- : le signe suit l'id
_RE_STEP = re.compile(r"^(CL|JL|[PSAMXYQZCJWTI@])(\d+|-)?([+-])?$", re.I)
_RE_INT = re.compile(r"^-?\d+$")
_RE_STR = re.compile(r'^"(.*)"$')
_RE_REF = re.compile(rf"\b([{REGISTER_LETTERS}])(\d+)(?:\.(\d+))?\b")
_RE_NAME = re.compile(r"[A-Za-z_][\w%]*")
_RE_COMPARE = re.compile(r"==|!=|>=|<=|&&|\|\||!!")

# commandes directes dont le corps (sans .id) est fixe
_FIXED_COMMANDS: dict[str, tuple[str, str | None]] = {
    "~": ("~", None),
    "(": ("(", None),
    ")": (")", None),
    "$": ("$", None),
    "]": ("]", None),
    "]L": ("]L", None),
    "]1": ("]1", None),
    "}": ("}", None),
    ">": (">", None),
    "<": ("<", None),
    "*": ("*", None),
    "*1": ("*1", None),
    "_SKH": ("_SKH", None),
    "FFFFFFFFF": ("FFFFFFFFF", None),
}
_RE_CARET = re.compile(r"^\^(\d*)$")
_RE_BAR = re.compile(r"^\|(\d*)$")
_RE_OUTPUT = re.compile(r"^([OF])(\d)$", re.I)
_RE_EXEC_BANK = re.compile(r"^\[(L?)(\d+)$", re.I)
_RE_NODE = re.compile(r"^\{(\d+)$")


def _parse_value(text: str) -> Value:
    text = text.strip()
    if _RE_INT.match(text):
        return Value("int", text, int(text))
    if _RE_STR.match(text):
        return Value("str", text)
    refs = tuple(f"{m.group(1).upper()}{m.group(2)}" for m in _RE_REF.finditer(text))
    return Value("expr", text, refs=refs)


def _split_motor(text: str) -> tuple[str, int | None]:
    m = _RE_MOTOR_SUFFIX.match(text)
    if m and m.group(1):
        return m.group(1) + (m.group(3) or ""), int(m.group(2))
    return text, None


def is_condition(text: str) -> bool:
    """Vrai si l'instruction ressemble à la requête d'un branchement."""
    t = text.strip()
    if _RE_COMPARE.search(t):
        return True
    if re.match(r"^I\d(?:\.\d+)?$", t, re.I):
        return True
    # comparaison simple > ou < entre deux opérandes (pas la commande seule)
    if len(t) > 1 and re.search(r"[A-Za-z0-9_\")]\s*[<>]\s*[A-Za-z0-9_\"-]", t):
        return True
    return False


def parse_statement(text: str, in_bank: bool = False) -> Statement:
    """Analyse une instruction (sans virgule de haut niveau)."""
    raw = text.strip()
    s = raw
    merge = False
    if s.endswith(";"):
        merge = True
        s = s[:-1].rstrip()
    if not s:
        return Statement(Kind.UNKNOWN, raw, merge=merge)

    # jonction a:b (hors guillemets)
    if contains_outside_quotes(s, ":") and not _RE_STR.match(s):
        parts = [p.strip() for p in split_outside_quotes(s, ":") if p.strip()]
        if len(parts) >= 2:
            st = Statement(Kind.JUNCTION, raw, merge=merge)
            st.children = [parse_statement(p, in_bank) for p in parts]
            return st

    # début / fin de banque
    m = _RE_BANK_START.match(s)
    if m:
        kind, num, motor = m.group(1).upper(), int(m.group(2)), m.group(3)
        if num == 100:
            return Statement(Kind.COMMAND, raw, motor=int(motor) if motor else None, command=f"{kind}100", merge=merge)
        return Statement(Kind.BANK_START, raw, motor=int(motor) if motor else None, command=kind, arg=f"{kind}{num}", index=num, merge=merge)
    m = _RE_END.match(s)
    if m:
        return Statement(Kind.BANK_END, raw, motor=int(m.group(1)) if m.group(1) else None, merge=merge)

    # affectation
    m = _RE_ASSIGN.match(s)
    if m:
        lhs, motor, rhs = m.group(1), m.group(2), m.group(3)
        value = _parse_value(rhs)
        mreg = _RE_REG.match(lhs)
        motor_id = int(motor) if motor else None
        if mreg:
            return Statement(Kind.REG_WRITE, raw, motor=motor_id, reg=mreg.group(1).upper(), index=int(mreg.group(2) or 0), value=value, merge=merge)
        up = lhs.upper()
        if up in ("_SKH", "_MOP") or re.match(r"^D\d+$", up):
            return Statement(Kind.COMMAND, raw, motor=motor_id, command=up if not up.startswith("D") else "D", arg=up[1:] if up.startswith("D") else None, value=value, merge=merge)
        return Statement(Kind.REG_WRITE, raw, motor=motor_id, name=lhs, value=value, merge=merge)

    # requête
    m = _RE_QUERY.match(s)
    if m:
        return Statement(Kind.QUERY, raw, motor=int(m.group(2)) if m.group(2) else None, arg=m.group(1), merge=merge)

    body, motor_id = _split_motor(s)
    body_up = body.upper()

    # commandes directes
    if body_up in _FIXED_COMMANDS:
        cmd, arg = _FIXED_COMMANDS[body_up]
        return Statement(Kind.COMMAND, raw, motor=motor_id, command=cmd, arg=arg, merge=merge)
    m = _RE_CARET.match(body)
    if m:
        return Statement(Kind.COMMAND, raw, motor=motor_id, command="^", arg=m.group(1) or None, merge=merge)
    m = _RE_BAR.match(body)
    if m:
        return Statement(Kind.COMMAND, raw, motor=motor_id, command="|", arg=m.group(1) or None, merge=merge)
    m = _RE_OUTPUT.match(body)
    if m:
        return Statement(Kind.COMMAND, raw, motor=motor_id, command=m.group(1).upper(), arg=m.group(2), merge=merge)
    m = _RE_EXEC_BANK.match(body)
    if m:
        return Statement(Kind.COMMAND, raw, motor=motor_id, command="[", arg=f"{m.group(1).upper()}{m.group(2)}", merge=merge)
    m = _RE_NODE.match(body)
    if m:
        return Statement(Kind.COMMAND, raw, motor=motor_id, command="{", arg=m.group(1), merge=merge)

    # lecture de registre (hors banque) ou pas de banque
    mreg = _RE_REG.match(body)
    mstep = _RE_STEP.match(body)
    if mreg and (not in_bank or mreg.group(1).upper() in "VNRHK"):
        return Statement(Kind.REG_READ, raw, motor=motor_id, reg=mreg.group(1).upper(), index=int(mreg.group(2) or 0), merge=merge)
    if mstep:
        op = mstep.group(1).upper()
        num = mstep.group(2)
        sign = mstep.group(3)
        if num is None and op not in ("X",):
            return Statement(Kind.UNKNOWN, raw, motor=motor_id, merge=merge)
        return Statement(
            Kind.STEP,
            raw,
            motor=motor_id,
            command=op,
            arg=num,
            index=int(num) if num and num.isdigit() else None,
            plus=sign == "+",
            minus=sign == "-",
            merge=merge,
        )
    return Statement(Kind.UNKNOWN, raw, motor=motor_id, merge=merge)


def parse_line(text: str, number: int = 1, in_bank: bool = False) -> ParsedLine:
    """Analyse une ligne complète (plusieurs instructions, branchement éventuel)."""
    raw = text.rstrip("\r\n")
    code = normalize(raw)
    if not code:
        return ParsedLine(number, raw, "", [], in_bank=in_bank)
    if is_comment(code):
        return ParsedLine(number, raw, "", [], is_comment=True, in_bank=in_bank)
    parts = split_statements(code)
    statements: list[Statement]
    if len(parts) == 3 and is_condition(parts[0]):
        st = Statement(Kind.BRANCH, code, condition=parts[0])
        st.then = [parse_statement(parts[1], in_bank)]
        st.otherwise = [parse_statement(parts[2], in_bank)]
        statements = [st]
    else:
        statements = [parse_statement(p, in_bank) for p in parts]
    return ParsedLine(number, raw, code, statements, in_bank=in_bank)


def parse_program(text: str) -> Program:
    """Analyse un fichier CML complet : lignes, banques, diagnostics de structure."""
    lines: list[ParsedLine] = []
    banks: list[Bank] = []
    diags: list[Diagnostic] = []
    current: Bank | None = None
    for number, raw in enumerate(text.splitlines(), start=1):
        pl = parse_line(raw, number, in_bank=current is not None)
        starts = [s for s in pl.statements if s.kind is Kind.BANK_START]
        ends = [s for s in pl.statements if s.kind is Kind.BANK_END]
        if starts:
            st = starts[0]
            if current is not None:
                diags.append(Diagnostic("erreur", "E002", number, f"banque {st.arg} ouverte alors que {current.name} n'est pas terminée par END"))
                banks.append(current)
            current = Bank(kind=st.command or "B", number=st.index or 0, motor=st.motor, start_line=number)
            pl.in_bank = False
            lines.append(pl)
            # instructions après le B# sur la même ligne (rare) : ignorées ici
            if len(pl.statements) > 1:
                diags.append(Diagnostic("avertissement", "W003", number, "instructions après le début de banque sur la même ligne"))
            continue
        if ends:
            if current is None:
                diags.append(Diagnostic("erreur", "E002", number, "END sans banque ouverte"))
                pl.in_bank = False
            else:
                current.end_line = number
                banks.append(current)
                current = None
                pl.in_bank = True
            lines.append(pl)
            continue
        if current is not None:
            pl.in_bank = True
            current.lines.append(pl)
        lines.append(pl)
    if current is not None:
        diags.append(Diagnostic("erreur", "E002", current.start_line, f"banque {current.name} non terminée par END"))
        banks.append(current)
    return Program(lines=lines, banks=banks, diagnostics=diags)
