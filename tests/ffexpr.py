"""A tiny, whitelist-only evaluator for the subset of ffmpeg expression syntax VisualKit emits.

Used to prove that the expression string sent to ffmpeg agrees with the pure-Python
`PropertyCurve.value_at`, without needing ffmpeg. Deliberately not `eval()`: it walks
the parsed tree and only accepts numbers, variables, + - * /, and known functions.
"""

from __future__ import annotations

import ast
import math
import re
from typing import Any, Callable

_PY_KEYWORD_FIX = re.compile(r"\bif\(")


def _round_half_away(x: float) -> float:
    return math.floor(x + 0.5) if x >= 0 else -math.floor(-x + 0.5)


_FUNCS: dict[str, Callable[..., float]] = {
    "clip": lambda x, lo, hi: min(max(x, lo), hi),
    "lt": lambda a, b: 1.0 if a < b else 0.0,
    "lte": lambda a, b: 1.0 if a <= b else 0.0,
    "gt": lambda a, b: 1.0 if a > b else 0.0,
    "gte": lambda a, b: 1.0 if a >= b else 0.0,
    "eq": lambda a, b: 1.0 if a == b else 0.0,
    "if_": lambda c, a, b=0.0: a if c != 0 else b,
    "pow": lambda a, b: a**b,
    "max": max,
    "min": min,
    "abs": abs,
    "round": _round_half_away,
    "trunc": math.trunc,
    "sin": math.sin,
    "cos": math.cos,
    "hypot": math.hypot,
}
_CONSTS = {"PI": math.pi}


def evaluate(expr: str, **variables: float) -> float:
    """Evaluate an ffmpeg expression such as ``"0+(100)*clip((t-1)/2,0,1)"`` at the given variables."""
    tree = ast.parse(_PY_KEYWORD_FIX.sub("if_(", expr.strip()), mode="eval")
    return float(_eval(tree.body, {**_CONSTS, **variables}))


def _eval(node: ast.AST, env: dict[str, float]) -> Any:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise ValueError(f"unknown variable {node.id!r} in ffmpeg expression")
        return env[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _eval(node.operand, env)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
        # A curve with N keyframes is an N-term left-leaning sum: walk the spine iteratively
        # so a 1000-keyframe expression does not hit Python's recursion limit.
        spine: list[ast.BinOp] = []
        cur: ast.AST = node
        while isinstance(cur, ast.BinOp) and isinstance(cur.op, (ast.Add, ast.Sub)):
            spine.append(cur)
            cur = cur.left
        total = _eval(cur, env)
        for bin_op in reversed(spine):
            rhs = _eval(bin_op.right, env)
            total = total + rhs if isinstance(bin_op.op, ast.Add) else total - rhs
        return total
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Div)):
        a, b = _eval(node.left, env), _eval(node.right, env)
        return a * b if isinstance(node.op, ast.Mult) else a / b
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
        return _FUNCS[node.func.id](*[_eval(a, env) for a in node.args])
    raise ValueError(f"unsupported construct in ffmpeg expression: {ast.dump(node)[:80]}")
