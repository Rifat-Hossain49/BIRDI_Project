#!/usr/bin/env python3
"""Scenario-level reference accuracy for a single strong family (EXPLORATORY, dev set).

The pre-registered decision in ref_analyze.py concerned the TWO-family reference
and came out NO-GO. The same data showed the single strong family (Qwen3.5-27B)
at 99.57% row precision on sequential rows. Row precision flatters long sequential
traces, so this re-measures at the unit a checker repair actually needs: a whole
scenario, every row correct.

Tiers by golden-free agreement among the family's designs that ran:
  unanimous  every design produces identical rows for the whole scenario
  majority   a strict majority agrees on every row
This is exploratory analysis on the development set; any rule built on it must be
frozen and confirmed on ConfiBench-4o-mini before it counts.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def analyze_group(gold, fam_rows, stats, ct):
    if gold is None or len(fam_rows) < 3:
        stats[ct]["sub-testbenches skipped (<3 designs ran)"] += 1
        return
    scen_rows = defaultdict(list)
    for i, g in enumerate(gold):
        try:
            sc = json.loads(g).get("scenario", "?")
        except Exception:
            sc = "?"
        scen_rows[sc].append(i)
    n = len(fam_rows)
    for sc, idx in scen_rows.items():
        s = stats[ct]
        s["scenarios"] += 1
        per_design = [tuple(r[i] if i < len(r) else None for i in idx) for r in fam_rows]
        gold_t = tuple(gold[i] for i in idx)
        c = Counter(per_design)
        top, cnt = c.most_common(1)[0]
        if cnt == n:
            s["unanimous"] += 1
            s["unanimous correct"] += (top == gold_t)
        if cnt * 2 > n:
            s["majority"] += 1
            s["majority correct"] += (top == gold_t)


def main() -> None:
    path = Path(sys.argv[1])
    stats = defaultdict(Counter)
    cur_key, gold, fam, ct = None, None, [], "?"
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            key = (r["run"], r["task_id"], r["iter_id"])
            if key != cur_key:
                if cur_key is not None:
                    analyze_group(gold, fam, stats, ct)
                cur_key, gold, fam, ct = key, None, [], r["circuit_type"]
            if r["status"] != "RAN" or r["rows"] is None:
                continue
            if r["family"] == "golden":
                gold = r["rows"]
            elif r["family"].startswith("A"):
                fam.append(r["rows"])
        if cur_key is not None:
            analyze_group(gold, fam, stats, ct)

    for ctp in ("CMB", "SEQ"):
        s = stats[ctp]
        if not s["scenarios"]:
            continue
        print(f"== {ctp} ==  scenarios {s['scenarios']}"
              f"   (sub-testbenches skipped: {s['sub-testbenches skipped (<3 designs ran)']})")
        for tier in ("unanimous", "majority"):
            k, ok = s[tier], s[f"{tier} correct"]
            print(f"   {tier:9s}: coverage {k/s['scenarios']:.3f}   "
                  f"scenario precision {ok/max(1,k):.4f}   (wrong scenarios: {k-ok})")


if __name__ == "__main__":
    main()
