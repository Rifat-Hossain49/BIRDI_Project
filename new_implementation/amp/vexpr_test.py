#!/usr/bin/env python3
"""Unit tests for the driver RHS evaluator.

Covers every construct the hardening pass added, including the three that
blocked pilot tasks: `!d` (dualedge), `scenario % 2` (m2014_q4k), and
`(data == 1) ? 0 : 1` (review2015_shiftcount).
"""
from __future__ import annotations

import sys

from vexpr import ExprError, evaluate

ok = True
ENV = {"d": 1, "scenario": 7, "data": 1, "a": 6, "b": 3, "zero": 0, "q": 0b1010}


def eq(expr, want, env=None):
    global ok
    try:
        got = evaluate(expr, env if env is not None else ENV)
    except ExprError as exc:
        got = f"ExprError({exc})"
    good = got == want
    ok = ok and good
    print(f"  [{'ok' if good else 'FAIL'}] {expr!r} -> {got!r}, want {want!r}")


def rejects(expr):
    global ok
    try:
        evaluate(expr, ENV)
        print(f"  [FAIL] {expr!r} should have been rejected")
        ok = False
    except ExprError:
        print(f"  [ok] {expr!r} rejected as unsupported")


def main() -> int:
    print("Blocking cases from the pilot")
    eq("!d", 0)
    eq("!zero", 1)
    eq("scenario % 2", 1)
    eq("(data == 1) ? 0 : 1", 0)
    eq("(data == 0) ? 0 : 1", 1)

    print("Literals")
    eq("3'b000", 0)
    eq("3'b101", 5)
    eq("4'hF", 15)
    eq("8'd200", 200)
    eq("1'bx", 0)
    eq("2'bz1", 0)
    eq("42", 42)

    print("Unary")
    eq("~zero", -1)
    eq("-b", -3)
    eq("!(a > b)", 0)

    print("Arithmetic and precedence")
    eq("a + b * 2", 12)
    eq("(a + b) * 2", 18)
    eq("a / b", 2)
    eq("a % b", 0)
    eq("a - b - 1", 2)

    print("Comparison and logical")
    eq("a > b", 1)
    eq("a < b", 0)
    eq("a >= 6", 1)
    eq("a <= 5", 0)
    eq("a == 6", 1)
    eq("a != 6", 0)
    eq("(a > b) && (b > 0)", 1)
    eq("(a < b) || (b > 0)", 1)

    print("Bitwise and shift")
    eq("q & 3", 2)
    eq("q | 1", 11)
    eq("q ^ 15", 5)
    eq("1 << 3", 8)
    eq("q >> 1", 5)

    print("Nested ternary and parentheses")
    eq("(a > b) ? ((b > 0) ? 1 : 2) : 3", 1)
    eq("(a < b) ? 1 : ((b == 3) ? 7 : 9)", 7)

    print("Division and modulo by zero are errors, not silent zeros")
    eq("a / zero", "ExprError(division by zero)")
    eq("a % zero", "ExprError(modulo by zero)")

    print("Unsupported input is refused rather than guessed")
    rejects("unknown_signal + 1")
    rejects("$random")
    rejects("a +")
    rejects("{a, b}")

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
