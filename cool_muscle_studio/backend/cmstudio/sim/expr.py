"""Évaluation sûre des expressions CML (banques logiques, branchements)."""

from __future__ import annotations

import ast
import math
import operator
import re
from collections.abc import Callable

_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.Constant,
    ast.Call, ast.Name, ast.Load, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd,
    ast.Not, ast.And, ast.Or, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
)

_RE_STATE = re.compile(r'"([A-Za-z0-9%]+)"')
_RE_REF = re.compile(r"\b([PSAMTVNRHK])(\d+)(?:\.(\d+))?\b", re.I)
_RE_INPUT = re.compile(r"\bI([1-4])(?:\.(\d+))?\b", re.I)
_RE_FUNC = re.compile(r"\bU([1-6])\s*\(", re.I)


def _u1(x: float) -> int:  # sinus, hypothèse : argument en degrés, résultat ×1000
    return round(math.sin(math.radians(x)) * 1000)


def _u2(x: float) -> int:
    return round(math.cos(math.radians(x)) * 1000)


def _u3(x: float) -> int:
    return int(math.sqrt(x)) if x >= 0 else 0


_FUNCS = {"_U1": _u1, "_U2": _u2, "_U3": _u3, "_U4": lambda x: int(x), "_U5": lambda x: int(x), "_U6": lambda x: int(x)}


class ExprError(ValueError):
    pass


def evaluate(text: str, resolve: Callable[[str], int | float]) -> int:
    """Évalue une expression CML. ``resolve`` reçoit 'P1.2', 'I3', '"Px"' et renvoie une valeur."""
    t = text.strip()
    t = t.replace("&&", " and ").replace("||", " or ")
    t = re.sub(r"!!\s*", " not ", t)
    t = _RE_STATE.sub(lambda m: str(resolve(f'"{m.group(1)}"')), t)
    t = _RE_INPUT.sub(lambda m: str(resolve(f"I{m.group(1)}")), t)
    t = _RE_FUNC.sub(lambda m: f"_U{m.group(1)}(", t)
    t = _RE_REF.sub(lambda m: str(resolve(m.group(0).upper())), t)
    try:
        node = ast.parse(t, mode="eval")
    except SyntaxError as exc:
        raise ExprError(f"expression invalide : {text!r}") from exc
    for sub in ast.walk(node):
        if not isinstance(sub, _ALLOWED_NODES):
            raise ExprError(f"élément interdit dans {text!r} : {type(sub).__name__}")
        if isinstance(sub, ast.Name) and sub.id not in _FUNCS:
            raise ExprError(f"nom inconnu dans {text!r} : {sub.id}")
        if isinstance(sub, ast.Call) and not (isinstance(sub.func, ast.Name) and sub.func.id in _FUNCS):
            raise ExprError(f"appel interdit dans {text!r}")
    value = eval(compile(node, "<cml>", "eval"), {"__builtins__": {}}, dict(_FUNCS))  # noqa: S307 - AST filtré
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, float):
        return int(value)  # troncature comme une division entière C
    return int(value)


_OPS = {ast.Add: operator.add}  # conservé pour extension future
