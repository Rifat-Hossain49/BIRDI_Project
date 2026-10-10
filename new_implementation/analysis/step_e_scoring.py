#!/usr/bin/env python3
"""Score the Step-E sealed evaluation under the frozen analysis definitions.

Frozen in STEP_E_ANALYSIS_FREEZE.md:
  * RANDOM's three seeds are averaged per task x budget BEFORE pairing; the
    statistical unit is the task, never task x seed.
  * ORIGINAL is an unbudgeted reference, excluded from equal-budget comparisons.
  * Group A / Group B assignment is fixed from pre-hidden exploration only.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import random
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EQUAL_BUDGET = ["TRUNCATION", "RANDOM", "GREEDY_VISIBLE", "STATE_ONLY", "STATE_PLUS_FAULT"]
BUDGETS = [8, 16, 32, 64]
HEADLINE = 32

GROUP_B = {"dff8ar", "ece241_2013_q4"}
UNCLASSIFIED = {"mt2015_muxdff"}


def h_value(row) -> float:
    """Golden-gated hidden detection for one suite."""
    elig = int(row["eligible_hidden"])
    if elig == 0:
        return 0.0
    if str(row["golden_pass"]).lower() != "true":
        return 0.0
    return int(row["hidden_killed"]) / elig


def task_values(rows, arm, budget):
    """Task -> value, averaging RANDOM seeds first (frozen rule)."""
    by = collections.defaultdict(list)
    for r in rows:
        if r["arm"] == arm and int(r["budget"]) == budget:
            by[r["task_id"]].append(h_value(r))
    return {t: sum(v) / len(v) for t, v in by.items()}


def boot(pairs, iters=20000, seed=17):
    if not pairs:
        return 0.0, 0.0, 0.0
    rng = random.Random(seed)
    n = len(pairs)
    point = sum(pairs) / n
    ds = sorted(sum(pairs[rng.randrange(n)] for _ in range(n)) / n for _ in range(iters))
    return point, ds[int(0.025 * iters)], ds[int(0.975 * iters)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", type=Path,
                    default=ROOT / "kaggle_runs/step_e_sealed_v1/step_e_results/sealed_records.csv")
    ap.add_argument("--out", type=Path, default=ROOT / "amp" / "step_e_metrics.csv")
    args = ap.parse_args()

    rows = list(csv.DictReader(args.records.open(encoding="utf-8")))
    tasks = sorted({r["task_id"] for r in rows})
    print(f"records {len(rows)}, tasks {len(tasks)}\n")

    print("=== Golden acceptance by arm and budget ===")
    print(f"{'arm':18s} " + " ".join(f"{'B'+str(b):>8s}" for b in BUDGETS))
    for arm in ["ORIGINAL"] + EQUAL_BUDGET:
        cells = []
        for b in BUDGETS:
            sub = [r for r in rows if r["arm"] == arm and int(r["budget"]) == b]
            if not sub:
                cells.append("     -")
                continue
            by = collections.defaultdict(list)
            for r in sub:
                by[r["task_id"]].append(str(r["golden_pass"]).lower() == "true")
            per = [sum(v) / len(v) for v in by.values()]
            cells.append(f"{sum(per)/len(per):8.3f}")
        print(f"{arm:18s} " + " ".join(cells))

    print("\n=== H_A(B): Golden-gated hidden RTL fault detection ===")
    print(f"{'arm':18s} " + " ".join(f"{'B'+str(b):>8s}" for b in BUDGETS))
    table = {}
    for arm in ["ORIGINAL"] + EQUAL_BUDGET:
        cells = []
        for b in BUDGETS:
            tv = task_values(rows, arm, b)
            table[(arm, b)] = tv
            cells.append(f"{sum(tv.values())/len(tv):8.4f}" if tv else "     -")
        print(f"{arm:18s} " + " ".join(cells))
    print("  ORIGINAL is the unbudgeted full-suite reference, not an equal-budget arm.")

    print("\n=== RANDOM across-seed variability ===")
    for b in BUDGETS:
        by = collections.defaultdict(list)
        for r in rows:
            if r["arm"] == "RANDOM" and int(r["budget"]) == b:
                by[r["task_id"]].append(h_value(r))
        sds = [statistics.pstdev(v) for v in by.values() if len(v) > 1]
        print(f"  B={b:3d}: mean per-task SD over 3 seeds = {sum(sds)/len(sds):.4f}"
              f"   max = {max(sds):.4f}")

    print(f"\n=== Primary paired comparisons at B={HEADLINE} (task-level) ===")
    comparisons = [("STATE_PLUS_FAULT", "RANDOM"), ("STATE_PLUS_FAULT", "GREEDY_VISIBLE"),
                   ("STATE_ONLY", "RANDOM"), ("STATE_PLUS_FAULT", "STATE_ONLY"),
                   ("STATE_PLUS_FAULT", "TRUNCATION")]
    print(f"{'comparison':40s} {'mean':>8s} {'median':>8s} {'95% CI':>20s} {'W/T/L':>10s}")
    for a, b_arm in comparisons:
        va, vb = table[(a, HEADLINE)], table[(b_arm, HEADLINE)]
        common = sorted(set(va) & set(vb) - UNCLASSIFIED)
        pairs = [va[t] - vb[t] for t in common]
        pt, lo, hi = boot(pairs)
        w = sum(1 for d in pairs if d > 1e-9)
        l = sum(1 for d in pairs if d < -1e-9)
        print(f"{a+' vs '+b_arm:40s} {pt:+8.4f} {statistics.median(pairs):+8.4f} "
              f"[{lo:+.4f}, {hi:+.4f}] {w:3d}/{len(pairs)-w-l:3d}/{l:3d}")

    print(f"\n=== Per-task H_A({HEADLINE}) ===")
    hdr = ["TRUNCATION", "RANDOM", "GREEDY_VISIBLE", "STATE_ONLY", "STATE_PLUS_FAULT", "ORIGINAL"]
    print(f"{'task':22s} {'grp':4s} " + " ".join(f"{h[:8]:>9s}" for h in hdr))
    for t in tasks:
        grp = "UNCL" if t in UNCLASSIFIED else ("B" if t in GROUP_B else "A")
        cells = [f"{table[(h, HEADLINE)].get(t, float('nan')):9.3f}" for h in hdr]
        print(f"{t:22s} {grp:4s} " + " ".join(cells))

    print("\n=== Group analysis at B=32 (descriptive; Group B has n=2) ===")
    for label, sel in (("A saturated", lambda t: t not in GROUP_B and t not in UNCLASSIFIED),
                       ("B state-rich", lambda t: t in GROUP_B)):
        ts = [t for t in tasks if sel(t)]
        if not ts:
            continue
        va, vb = table[("STATE_PLUS_FAULT", HEADLINE)], table[("RANDOM", HEADLINE)]
        pairs = [va[t] - vb[t] for t in ts if t in va and t in vb]
        print(f"  {label:14s} n={len(pairs):2d}  STATE_PLUS_FAULT - RANDOM = "
              f"{sum(pairs)/len(pairs):+.4f}" if pairs else f"  {label}: none")

    print("\n=== Efficiency vs ORIGINAL (explicitly not equal-budget) ===")
    orig = table[("ORIGINAL", HEADLINE)]
    for arm in ["TRUNCATION", "STATE_PLUS_FAULT"]:
        tv = table[(arm, HEADLINE)]
        ts = [t for t in tv if orig.get(t, 0) > 0]
        if not ts:
            continue
        ratio = sum(tv[t] / orig[t] for t in ts) / len(ts)
        print(f"  {arm:18s} retains {ratio:6.1%} of ORIGINAL detection at 32 cycles "
              f"(ORIGINAL mean cost 259.3)")

    out_rows = []
    for arm in ["ORIGINAL"] + EQUAL_BUDGET:
        for b in BUDGETS:
            for t, v in table[(arm, b)].items():
                out_rows.append({"task_id": t, "arm": arm, "budget": b,
                                 "h_value": round(v, 6),
                                 "group": "UNCL" if t in UNCLASSIFIED else
                                          ("B" if t in GROUP_B else "A")})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
