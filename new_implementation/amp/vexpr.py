#!/usr/bin/env python3
"""Small deterministic evaluator for the Verilog RHS subset in frozen drivers.

Recursive descent, no Python eval. Its only job is to reproduce the static
stimulus a generated driver applies, so it covers the operators those drivers
actually use and refuses anything else rather than guessing.

X and Z digits in sized literals evaluate to 0, matching the frozen checkers'
own SignalTxt_to_dictlist policy.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

_TOKEN_RE = re.compile(r"""
    \s*(
        \d*'[sS]?[bBoOdDhH][0-9a-fA-FxXzZ_]+   # sized literal
      | \d+                                     # decimal
      | [A-Za-z_]\w*                            # identifier
      | <<|>>|<=|>=|==|!=|&&|\|\|                # multi-char operators
      | [-+*/%()?:!~^&|<>]                       # single-char
    )
""", re.X)


class ExprError(Exception):
    pass


def _tokenize(text: str) -> List[str]:
    toks, pos = [], 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            if text[pos].isspace():
                pos += 1
                continue
            raise ExprError(f"bad character {text[pos]!r}")
        toks.append(m.group(1))
        pos = m.end()
    return toks


def _literal(tok: str) -> Optional[int]:
    m = re.fullmatch(r"(\d*)'([sS]?)([bBoOdDhH])([0-9a-fA-FxXzZ_]+)", tok)
    if m:
        digits = m.group(4).replace("_", "")
        if re.search(r"[xXzZ]", digits):
            return 0
        base = {"b": 2, "o": 8, "d": 10, "h": 16}[m.group(3).lower()]
        return int(digits, base)
    if re.fullmatch(r"\d+", tok):
        return int(tok)
    return None


class _Parser:
    def __init__(self, toks: List[str], env: Dict[str, int]):
        self.t, self.i, self.env = toks, 0, env

    def peek(self) -> Optional[str]:
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self) -> str:
        tok = self.peek()
        if tok is None:
            raise ExprError("unexpected end of expression")
        self.i += 1
        return tok

    def expect(self, tok: str) -> None:
        got = self.take()
        if got != tok:
            raise ExprError(f"expected {tok!r}, got {got!r}")

    # precedence climbing, lowest first
    def parse(self) -> int:
        v = self.ternary()
        if self.peek() is not None:
            raise ExprError(f"trailing token {self.peek()!r}")
        return v

    def ternary(self) -> int:
        cond = self.logical_or()
        if self.peek() == "?":
            self.take()
            a = self.ternary()
            self.expect(":")
            b = self.ternary()
            return a if cond else b
        return cond

    def _binary(self, ops, nxt):
        v = nxt()
        while self.peek() in ops:
            op = self.take()
            r = nxt()
            v = ops[op](v, r)
        return v

    def logical_or(self):
        return self._binary({"||": lambda a, b: int(bool(a) or bool(b))}, self.logical_and)

    def logical_and(self):
        return self._binary({"&&": lambda a, b: int(bool(a) and bool(b))}, self.bit_or)

    def bit_or(self):
        return self._binary({"|": lambda a, b: a | b}, self.bit_xor)

    def bit_xor(self):
        return self._binary({"^": lambda a, b: a ^ b}, self.bit_and)

    def bit_and(self):
        return self._binary({"&": lambda a, b: a & b}, self.equality)

    def equality(self):
        return self._binary({"==": lambda a, b: int(a == b),
                             "!=": lambda a, b: int(a != b)}, self.relational)

    def relational(self):
        return self._binary({"<": lambda a, b: int(a < b), ">": lambda a, b: int(a > b),
                             "<=": lambda a, b: int(a <= b), ">=": lambda a, b: int(a >= b)},
                            self.shift)

    def shift(self):
        return self._binary({"<<": lambda a, b: a << b, ">>": lambda a, b: a >> b},
                            self.additive)

    def additive(self):
        return self._binary({"+": lambda a, b: a + b, "-": lambda a, b: a - b},
                            self.multiplicative)

    def multiplicative(self):
        def div(a, b):
            if b == 0:
                raise ExprError("division by zero")
            return a // b

        def mod(a, b):
            if b == 0:
                raise ExprError("modulo by zero")
            return a % b

        return self._binary({"*": lambda a, b: a * b, "/": div, "%": mod}, self.unary)

    def unary(self) -> int:
        tok = self.peek()
        if tok == "!":
            self.take()
            return 0 if self.unary() else 1
        if tok == "~":
            self.take()
            return ~self.unary()
        if tok == "-":
            self.take()
            return -self.unary()
        if tok == "+":
            self.take()
            return self.unary()
        return self.primary()

    def primary(self) -> int:
        tok = self.take()
        if tok == "(":
            v = self.ternary()
            self.expect(")")
            return v
        lit = _literal(tok)
        if lit is not None:
            return lit
        if re.fullmatch(r"[A-Za-z_]\w*", tok):
            if tok not in self.env:
                raise ExprError(f"unknown identifier {tok!r}")
            return self.env[tok]
        raise ExprError(f"unexpected token {tok!r}")


def evaluate(expr: str, env: Dict[str, int]) -> int:
    """Evaluate a driver RHS. Raises ExprError on anything unsupported."""
    text = expr.strip().rstrip(";").strip()
    if not text:
        raise ExprError("empty expression")
    return _Parser(_tokenize(text), env).parse()
