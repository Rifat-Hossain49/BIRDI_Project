#!/usr/bin/env python3
"""Stage 2-4: candidate designs -> one reference trace.

  simulate   every candidate design on the task's driver
  group      per scenario, candidates with identical behaviour form one class
  question   for every pair of classes, the first observation where they differ,
             with the agreed history before it -- the localized question
  resolve    a tournament over classes using pairwise answers; with no answers
             (or an abstention) the larger class wins, i.e. plurality voting

Resolution granularity is chosen for soundness, not convenience:
  * combinational tasks and tasks with a reset: per scenario. Every sequential
    scenario starts with a two-cycle reset, so behaviour inside it does not depend
    on what an earlier scenario did, and different scenarios may be won by
    different classes;
  * sequential tasks with no reset port: the whole trace is one unit, because
    state carries across scenario boundaries and splicing classes could produce a
    trace no design can generate.

Answers are applied offline from a file, so questions for every pair can be asked
in one batch and the tournament stays deterministic.
"""
from __future__ import annotations

import json
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from dirtb.hdl import Interface, Trace, simulate

MAX_HISTORY = 24


@dataclass
class Unit:
    """One resolution unit (a scenario, or the whole trace)."""
    key: str
    row_idx: List[int]
    classes: "OrderedDict[Tuple, List[str]]" = field(default_factory=OrderedDict)


def units_for(iface: Interface, trace: Trace) -> List[Unit]:
    per_scenario = iface.clock is None or iface.reset is not None
    if not per_scenario:
        return [Unit("all", list(range(len(trace.rows))))]
    by = OrderedDict()
    for i, (scen, _, _) in enumerate(trace.rows):
        by.setdefault(str(scen), []).append(i)
    return [Unit(k, v) for k, v in by.items()]


def simulate_candidates(driver: str, candidates: Sequence[dict]) -> Dict[str, Trace]:
    out = {}
    for c in candidates:
        t = simulate(c["rtl"], driver)
        if t.status == "RAN" and t.rows:
            out[c["candidate_id"]] = t
    return out


def group(iface: Interface, traces: Dict[str, Trace]) -> Tuple[List[Unit], Optional[int]]:
    """Classes per unit, largest first. Returns the units and the row count."""
    if not traces:
        return [], None
    n_rows = Counter(len(t.rows) for t in traces.values()).most_common(1)[0][0]
    good = {k: t for k, t in traces.items() if len(t.rows) == n_rows}
    ref = next(iter(good.values()))
    units = units_for(iface, ref)
    for u in units:
        cls: Dict[Tuple, List[str]] = {}
        for cid, t in good.items():
            key = tuple(t.rows[i][2] for i in u.row_idx)
            cls.setdefault(key, []).append(cid)
        u.classes = OrderedDict(sorted(cls.items(), key=lambda kv: (-len(kv[1]), kv[1][0])))
    return units, n_rows


def _fmt(names: Sequence[str], values: Sequence[str]) -> str:
    parts = []
    for n, v in zip(names, values):
        parts.append(f"{n}={int(v, 2)}" if v and all(ch in "01" for ch in v) else f"{n}={v}")
    return ", ".join(parts)


def questions(task: dict, iface: Interface, units: List[Unit]) -> List[dict]:
    """Pairwise first-divergence questions for every unit with more than one class."""
    clk = iface.clock
    in_names = [p.name for p in iface.inputs if p.name != clk]
    out_names = [p.name for p in iface.outputs]
    n_in = len(in_names)
    qs = []
    for u in units:
        keys = list(u.classes)
        for a in range(len(keys)):
            for b in range(a + 1, len(keys)):
                ta, tb = keys[a], keys[b]
                k = next((j for j in range(len(ta)) if ta[j] != tb[j]), None)
                if k is None:
                    continue
                oa, ob = ta[k][n_in:], tb[k][n_in:]
                diff = [i for i in range(len(out_names)) if oa[i] != ob[i]]
                if not diff:
                    continue
                hist = [_fmt(in_names + out_names, ta[j]) for j in range(max(0, k - MAX_HISTORY), k)]
                qs.append({
                    "qid": f"{task['task_id']}|{u.key}|{a}|{b}",
                    "task_id": task["task_id"], "unit": u.key, "class_a": a, "class_b": b,
                    "description": task["description"], "header": task["header"],
                    "history": hist, "history_truncated": k > MAX_HISTORY,
                    "cycle_inputs": _fmt(in_names, ta[k][:n_in]),
                    "option_a": {out_names[i]: _fmt([out_names[i]], [oa[i]]).split("=", 1)[1] for i in diff},
                    "option_b": {out_names[i]: _fmt([out_names[i]], [ob[i]]).split("=", 1)[1] for i in diff},
                })
    return qs


def resolve(task: dict, units: List[Unit], answers: Optional[Dict[str, str]] = None
            ) -> Tuple[Optional[Dict[int, Tuple[str, ...]]], Counter]:
    """Winning class per unit. answers maps qid -> 'A' | 'B'; anything else abstains."""
    stats = Counter()
    chosen: Dict[int, Tuple[str, ...]] = {}
    for u in units:
        keys = list(u.classes)
        if not keys:
            return None, stats
        if len(keys) == 1:
            stats["unanimous units"] += 1
            win = 0
        else:
            win = 0
            for challenger in range(1, len(keys)):
                a, b = sorted((win, challenger))
                ans = (answers or {}).get(f"{task['task_id']}|{u.key}|{a}|{b}")
                if ans in ("A", "B"):
                    stats["pairs decided by question"] += 1
                    winner = a if ans == "A" else b
                else:
                    stats["pairs decided by size"] += 1
                    winner = win                    # keys are sorted largest-first
                win = winner
            stats["contested units"] += 1
        for pos, i in enumerate(u.row_idx):
            chosen[i] = keys[win][pos]
    return chosen, stats


def reference_trace(units: List[Unit], chosen: Dict[int, Tuple[str, ...]], template: Trace) -> Trace:
    rows = [(s, st, chosen[i]) for i, (s, st, _) in enumerate(template.rows)]
    return Trace("RAN", rows)
