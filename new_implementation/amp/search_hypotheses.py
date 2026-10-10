#!/usr/bin/env python3
"""Visible fault hypotheses: deterministic mutations of the frozen checker's model.

These are search hypotheses, never oracles. The frozen checker keeps supplying
expected values; a mutation only describes a behaviour a good test ought to
distinguish. Nothing here votes on what is correct.

Mutations are applied to the checker source with a Python AST transform, one
site at a time, so each hypothesis is a single well-defined behavioural change.
Every hypothesis carries a family label so scoring can be family-balanced and a
prolific operator cannot dominate selection.
"""
from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple


@dataclass
class Hypothesis:
    hypothesis_id: str
    family: str
    description: str
    source: str


class _SiteCounter(ast.NodeVisitor):
    """Counts candidate sites so each can be mutated individually."""

    def __init__(self, predicate: Callable[[ast.AST], bool]):
        self.predicate = predicate
        self.count = 0

    def generic_visit(self, node):
        if self.predicate(node):
            self.count += 1
        super().generic_visit(node)


class _SiteMutator(ast.NodeTransformer):
    def __init__(self, predicate, transform, target_index: int):
        self.predicate = predicate
        self.transform = transform
        self.target = target_index
        self.seen = 0

    def visit(self, node):
        node = super().visit(node)
        return node

    def generic_visit(self, node):
        node = super().generic_visit(node)
        if self.predicate(node):
            hit = self.seen
            self.seen += 1
            if hit == self.target:
                return self.transform(node)
        return node


# --- operator definitions -----------------------------------------------------

_CMP_SWAP = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Lt: ast.LtE, ast.LtE: ast.Lt,
             ast.Gt: ast.GtE, ast.GtE: ast.Gt}
_ARITH_SWAP = {ast.Add: ast.Sub, ast.Sub: ast.Add,
               ast.LShift: ast.RShift, ast.RShift: ast.LShift,
               ast.BitAnd: ast.BitOr, ast.BitOr: ast.BitAnd}


def _is_cmp(node) -> bool:
    return isinstance(node, ast.Compare) and type(node.ops[0]) in _CMP_SWAP


def _swap_cmp(node):
    node.ops[0] = _CMP_SWAP[type(node.ops[0])]()
    return node


def _is_arith(node) -> bool:
    return isinstance(node, ast.BinOp) and type(node.op) in _ARITH_SWAP


def _swap_arith(node):
    node.op = _ARITH_SWAP[type(node.op)]()
    return node


def _is_boundary_const(node) -> bool:
    return (isinstance(node, ast.Constant) and isinstance(node.value, int)
            and not isinstance(node.value, bool) and node.value >= 1)


def _off_by_one(node):
    return ast.Constant(value=node.value - 1)


def _is_if(node) -> bool:
    return isinstance(node, ast.If)


def _negate_if(node):
    node.test = ast.UnaryOp(op=ast.Not(), operand=node.test)
    return node


def _is_aug_or_assign_to_state(node) -> bool:
    """An assignment writing a self.<attr>: the checker's state update."""
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        t = node.targets[0]
        return isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self"
    return False


def _hold_state(node):
    """Replace a state update with a no-op: models a register that fails to update."""
    return ast.Expr(value=ast.Constant(value=0))


OPERATORS: List[Tuple[str, str, Callable, Callable]] = [
    ("comparison", "comparison operator swapped", _is_cmp, _swap_cmp),
    ("arithmetic", "arithmetic or shift operator swapped", _is_arith, _swap_arith),
    ("boundary", "integer boundary off by one", _is_boundary_const, _off_by_one),
    ("condition", "branch condition negated", _is_if, _negate_if),
    ("hold", "state update dropped (register holds)", _is_aug_or_assign_to_state, _hold_state),
]


def _model_segment(source: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Split the checker into (head, GoldenDUT class source, tail).

    Only the class is mutated; the driver trailer and helper functions are left
    exactly as found.
    """
    cut = source.find('with open("TBout.txt"')
    body = source if cut == -1 else source[:cut]
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return None, None, None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "GoldenDUT":
            lines = body.splitlines(keepends=True)
            start = node.lineno - 1
            end = node.end_lineno
            return ("".join(lines[:start]), "".join(lines[start:end]),
                    "".join(lines[end:]) + (source[cut:] if cut != -1 else ""))
    return None, None, None


def generate_hypotheses(checker_source: str, max_per_family: int = 6,
                        max_total: int = 40) -> List[Hypothesis]:
    """Produce single-site mutations of the frozen checker's transition model."""
    head, cls_src, tail = _model_segment(checker_source)
    if cls_src is None:
        return []
    out: List[Hypothesis] = []
    seen_hashes = set()
    for family, description, predicate, transform in OPERATORS:
        counter = _SiteCounter(predicate)
        try:
            counter.visit(ast.parse(cls_src))
        except SyntaxError:
            continue
        made = 0
        for index in range(counter.count):
            if made >= max_per_family or len(out) >= max_total:
                break
            try:
                tree = ast.parse(cls_src)
                mutated = _SiteMutator(predicate, transform, index).visit(tree)
                ast.fix_missing_locations(mutated)
                new_cls = ast.unparse(mutated)
            except Exception:
                continue
            candidate = head + new_cls + "\n" + tail
            digest = hashlib.sha256(candidate.encode()).hexdigest()
            if digest in seen_hashes or new_cls.strip() == cls_src.strip():
                continue
            seen_hashes.add(digest)
            out.append(Hypothesis(
                hypothesis_id=f"{family}_{index}",
                family=family,
                description=f"{description} (site {index})",
                source=candidate))
            made += 1
    return out
