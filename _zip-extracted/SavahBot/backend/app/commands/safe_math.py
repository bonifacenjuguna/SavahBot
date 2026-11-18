"""Tiny arithmetic evaluator for $(math ...). Parses with `ast` and allows only numbers and + - * / // % **.
Nothing else is ever executed, so there is no code-injection surface (unlike a raw eval)."""
from __future__ import annotations

import ast
import operator as op

_BIN = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv, ast.FloorDiv: op.floordiv,
        ast.Mod: op.mod, ast.Pow: op.pow}
_UNARY = {ast.UAdd: op.pos, ast.USub: op.neg}
MAX_LEN = 100
MAX_ABS = 1e15


class MathError(ValueError):
    pass


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and (abs(right) > 100 or abs(left) > 1e6):
            raise MathError("exponent too large")
        try:
            result = _BIN[type(node.op)](left, right)
        except ZeroDivisionError as exc:
            raise MathError("division by zero") from exc
        if abs(result) > MAX_ABS:
            raise MathError("number too large")
        return result
    raise MathError("unsupported expression")


def calculate(expr: str) -> str:
    expr = (expr or "").strip()
    if not expr or len(expr) > MAX_LEN:
        raise MathError("empty or too long")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise MathError("syntax error") from exc
    value = _eval(tree.body)
    if isinstance(value, float):
        if value == int(value) and abs(value) < 1e12:
            return str(int(value))
        return f"{value:.6g}"
    return str(value)
