"""Validation d'un programme CML contre la référence.

Codes :
  E001 instruction inconnue             E002 structure de banque (voir parser)
  E003 constante numérique dans une banque (CML pur)
  E004 ligne de plus de 40 caractères dans une banque
  E005 paramètre K : numéro inconnu / valeur hors plage
  E006 registre : indice ou valeur hors plage
  E007 plus de 200 pas de programme
  E008 pas de banque : indice hors plage
  W004 ligne de plus de 40 caractères hors banque
  W010 K37 modifié : les unités de tous les registres changent
  W011 paramètre qui peut couper la liaison ou changer le comportement du pont (K20, K23, K52, K62, K65, K70)
  W012 numéro de banque > 30
  W013 K non documenté (présent dans le RT3 seulement)
  I020 pas de « $ » : rien ne sera conservé après coupure
"""

from __future__ import annotations

from ..reference import Reference, load_reference
from .model import Diagnostic, Kind, Program, Statement

MAX_LINE = 40
MAX_STEPS = 200
MAX_BANK = 30
LINK_SENSITIVE_K = {20: "vitesse série", 23: "événements/écho", 52: "E/S 1 et 2 série", 62: "mode RS-485/Modbus", 65: "vitesse série aval", 70: "délimiteur"}


def _iter(statements: list[Statement]):
    for st in statements:
        yield st
        yield from _iter(st.then)
        yield from _iter(st.otherwise)
        yield from _iter(st.children)


def validate(program: Program, reference: Reference | None = None) -> list[Diagnostic]:
    """Retourne les diagnostics (ceux du parseur inclus), triés par ligne."""
    ref = reference or load_reference()
    diags: list[Diagnostic] = list(program.diagnostics)
    saw_dollar = False

    for pl in program.lines:
        if pl.code and len(pl.code) > MAX_LINE:
            sev, code = ("erreur", "E004") if pl.in_bank else ("avertissement", "W004")
            diags.append(Diagnostic(sev, code, pl.number, f"ligne de {len(pl.code)} caractères (maximum {MAX_LINE})"))
        for st in _iter(pl.statements):
            if st.kind is Kind.UNKNOWN:
                diags.append(Diagnostic("erreur", "E001", pl.number, f"instruction inconnue : {st.raw!r}"))
            elif st.kind is Kind.COMMAND and st.command == "$":
                saw_dollar = True
            elif st.kind is Kind.REG_WRITE:
                diags.extend(_check_write(st, pl.number, pl.in_bank, ref))
            elif st.kind is Kind.REG_READ:
                fam = ref.registers.get(st.reg or "")
                if fam and st.index is not None:
                    msg = fam.check_index(st.index)
                    if msg:
                        diags.append(Diagnostic("erreur", "E006", pl.number, msg))
            elif st.kind is Kind.STEP:
                diags.extend(_check_step(st, pl.number, ref))
            elif st.kind is Kind.BANK_START and st.index is not None and st.index > MAX_BANK:
                diags.append(Diagnostic("avertissement", "W012", pl.number, f"banque {st.arg} : numéro supérieur à {MAX_BANK}"))
            elif st.kind is Kind.COMMAND and st.command == "[" and st.arg:
                num = int(st.arg.lstrip("L"))
                if num > MAX_BANK:
                    diags.append(Diagnostic("avertissement", "W012", pl.number, f"exécution de la banque {st.arg} : numéro supérieur à {MAX_BANK}"))

    steps = program.step_count()
    if steps > MAX_STEPS:
        diags.append(Diagnostic("erreur", "E007", 0, f"{steps} pas de programme (maximum {MAX_STEPS})"))
    if program.banks and not saw_dollar:
        diags.append(Diagnostic("info", "I020", 0, "aucun « $ » : les banques ne seront pas conservées après une coupure d'alimentation"))

    diags.sort(key=lambda d: (d.line, d.code))
    return diags


def _check_write(st: Statement, line: int, in_bank: bool, ref: Reference) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    if st.reg is None:  # nom CMP non résolu
        out.append(Diagnostic("erreur", "E001", line, f"nom inconnu : {st.name!r} (fichier CMP non compilé ?)"))
        return out
    if in_bank and st.value and st.value.kind == "int":
        out.append(Diagnostic("erreur", "E003", line, f"{st.reg}{st.index} : une constante ne peut pas être affectée dans une banque (copier depuis un autre registre)"))
    if st.reg == "K":
        kp = ref.k(st.index or -1)
        if kp is None:
            out.append(Diagnostic("erreur", "E005", line, f"K{st.index} : paramètre inconnu"))
            return out
        if not kp.documente:
            out.append(Diagnostic("avertissement", "W013", line, f"K{st.index} : paramètre non documenté ({kp.note or 'RT3 seulement'})"))
        if st.value and st.value.kind == "int":
            for pb in kp.check(st.value.int_value or 0):
                out.append(Diagnostic("erreur", "E005", line, pb))
        if st.index == 37:
            out.append(Diagnostic("avertissement", "W010", line, "K37 change la résolution : les unités de tous les registres P, S, A et des banques changent"))
        elif st.index in LINK_SENSITIVE_K:
            out.append(Diagnostic("avertissement", "W011", line, f"K{st.index} ({LINK_SENSITIVE_K[st.index]}) peut couper la liaison avec le pont ESP32"))
        return out
    fam = ref.registers.get(st.reg)
    if fam is None:
        return out
    if st.index is not None:
        msg = fam.check_index(st.index)
        if msg:
            out.append(Diagnostic("erreur", "E006", line, msg))
    if st.value and st.value.kind == "int" and st.reg != "V":
        msg = fam.check_value(st.value.int_value or 0)
        if msg:
            out.append(Diagnostic("erreur", "E006", line, f"{st.reg}{st.index} : {msg}"))
    return out


_STEP_FAMILY = {"P": "P", "Y": "P", "Q": "P", "Z": "P", "@": "P", "S": "S", "A": "A", "M": "M", "T": "T", "W": "T"}


def _check_step(st: Statement, line: int, ref: Reference) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    fam_letter = _STEP_FAMILY.get(st.command or "")
    if fam_letter and st.index is not None:
        fam = ref.registers.get(fam_letter)
        if fam:
            msg = fam.check_index(st.index)
            if msg:
                out.append(Diagnostic("erreur", "E008", line, f"pas {st.command}{st.index} : {msg}"))
    if st.command in ("C", "J", "CL", "JL") and st.index is not None and st.index > MAX_BANK:
        out.append(Diagnostic("avertissement", "W012", line, f"pas {st.command}{st.index} : numéro de banque supérieur à {MAX_BANK}"))
    if st.command == "I" and st.index is not None and not (1 <= st.index <= 4):
        out.append(Diagnostic("erreur", "E008", line, f"entrée I{st.index} : seules I1 à I4 existent"))
    if st.command == "X" and st.index is not None and st.index > 255:
        out.append(Diagnostic("erreur", "E008", line, f"boucle X{st.index} : 255 répétitions au maximum (RT3)"))
    return out
