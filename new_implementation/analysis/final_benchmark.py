#!/usr/bin/env python3
"""Final ACTIVE-TB-D benchmark: distillation against CorrectBench and baselines.

Merges the Step-E sealed records (ORIGINAL, TRUNCATION, RANDOM, already scored on
Golden-gated hidden RTL faults) with the distillation sealed records, and scores
them under one metric.

The claim under test is efficiency, not raw detection: does dependency-preserving
distillation retain CorrectBench's hidden-fault detection at a fraction of its
deployed cycles, and does it beat truncation and random at equal budget?
"""
from __future__ import annotations

import argparse
import collections
import csv
import random
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUDGETS = [8, 16, 32, 64]
HEADLINE = 32


def h_value(row) -> float:
    elig = int(row["eligible_hidden"])
    if elig == 0:
        return 0.0
    if str(row["golden_pass"]).lower() != "true":
        return 0.0
    return int(row["hidden_killed"]) / elig


def task_values(rows, arm, budget):
    by = collections.defaultdict(list)
    for r in rows:
        if r["arm"] == arm and int(r["budget"]) == budget:
            by[r["task_id"]].append(h_value(r))
    return {t: sum(v) / len(v) for t, v in by.items()}


def task_cycles(rows, arm, budget):
    by = collections.defaultdict(list)
    for r in rows:
        if r["arm"] == arm and int(r["budget"]) == budget:
            by[r["task_id"]].append(int(r["deployed_cycles"]))
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
    ap.add_argument("--step-e", type=Path,
                    default=ROOT / "kaggle_runs/step_e_sealed_v1/step_e_results/sealed_records.csv")
    ap.add_argument("--distill", type=Path,
                    default=ROOT / "kaggle_runs/distill_sealed_v1/distill_results/sealed_records.csv")
    ap.add_argument("--out", type=Path, default=ROOT / "amp" / "final_benchmark.csv")
    args = ap.parse_args()

    rows = list(csv.DictReader(args.step_e.open(encoding="utf-8")))
    keep = {"ORIGINAL", "TRUNCATION", "RANDOM"}
    rows = [r for r in rows if r["arm"] in keep]
    if args.distill.is_file():
        rows += list(csv.DictReader(args.distill.open(encoding="utf-8")))
    else:
        print(f"WARNING: {args.distill} not present; distillation arms missing")

    arms = sorted({r["arm"] for r in rows})
    tasks = sorted({r["task_id"] for r in rows})
    print(f"arms: {arms}\ntasks: {len(tasks)}\n")

    # Tasks where CorrectBench's own suite already rejects Golden contribute zero
    # to every arm; a checker-preserving backend cannot lift them.
    orig = task_values(rows, "ORIGINAL", HEADLINE)
    usable = sorted(t for t, v in orig.items() if v > 0)
    print(f"tasks where CorrectBench passes Golden and kills >0 hidden faults: "
          f"{len(usable)} of {len(tasks)}")
    print(f"  {usable}\n")

    print("=== H(B): Golden-gated hidden RTL fault detection, all tasks ===")
    print(f"{'arm':18s} " + " ".join(f"{'B'+str(b):>9s}" for b in BUDGETS))
    table = {}
    for arm in ["ORIGINAL", "TRUNCATION", "RANDOM", "DISTILL_GREEDY", "DISTILL_FAMILY"]:
        cells = []
        for b in BUDGETS:
            tv = task_values(rows, arm, b)
            table[(arm, b)] = tv
            cells.append(f"{sum(tv.values())/len(tv):9.4f}" if tv else "        -")
        if any(c.strip() != "-" for c in cells):
            print(f"{arm:18s} " + " ".join(cells))

    print("\n=== Mean deployed cycles ===")
    print(f"{'arm':18s} " + " ".join(f"{'B'+str(b):>9s}" for b in BUDGETS))
    for arm in ["ORIGINAL", "TRUNCATION", "RANDOM", "DISTILL_GREEDY", "DISTILL_FAMILY"]:
        cells = []
        for b in BUDGETS:
            tc = task_cycles(rows, arm, b)
            cells.append(f"{sum(tc.values())/len(tc):9.1f}" if tc else "        -")
        if any(c.strip() != "-" for c in cells):
            print(f"{arm:18s} " + " ".join(cells))

    print(f"\n=== Efficiency vs CorrectBench full suite (headline B={HEADLINE}) ===")
    oc = task_cycles(rows, "ORIGINAL", HEADLINE)
    for arm in ["TRUNCATION", "RANDOM", "DISTILL_GREEDY", "DISTILL_FAMILY"]:
        tv, tc = table.get((arm, HEADLINE)), task_cycles(rows, arm, HEADLINE)
        if not tv:
            continue
        ts = [t for t in tv if orig.get(t, 0) > 0]
        if not ts:
            continue
        ret = sum(tv[t] / orig[t] for t in ts) / len(ts)
        cost = sum(tc[t] / oc[t] for t in ts) / len(ts)
        print(f"  {arm:18s} retains {ret:6.1%} of CorrectBench detection "
              f"at {cost:5.1%} of its cycles")

    print(f"\n=== Paired comparisons at B={HEADLINE} (equal budget) ===")
    print(f"{'comparison':44s} {'mean':>8s} {'median':>8s} {'95% CI':>20s} {'W/T/L':>10s}")
    pairs_to_test = [("DISTILL_FAMILY", "TRUNCATION"), ("DISTILL_FAMILY", "RANDOM"),
                     ("DISTILL_GREEDY", "TRUNCATION"), ("DISTILL_GREEDY", "RANDOM"),
                     ("DISTILL_FAMILY", "DISTILL_GREEDY")]
    for a, b_arm in pairs_to_test:
        va, vb = table.get((a, HEADLINE)), table.get((b_arm, HEADLINE))
        if not va or not vb:
            continue
        common = sorted(set(va) & set(vb))
        d = [va[t] - vb[t] for t in common]
        pt, lo, hi = boot(d)
        w = sum(1 for x in d if x > 1e-9)
        l = sum(1 for x in d if x < -1e-9)
        print(f"{a+' vs '+b_arm:44s} {pt:+8.4f} {statistics.median(d):+8.4f} "
              f"[{lo:+.4f}, {hi:+.4f}] {w:3d}/{len(d)-w-l:3d}/{l:3d}")

    print(f"\n=== Per-task H({HEADLINE}) ===")
    hdr = ["ORIGINAL", "TRUNCATION", "RANDOM", "DISTILL_GREEDY", "DISTILL_FAMILY"]
    print(f"{'task':22s} " + " ".join(f"{h[:9]:>10s}" for h in hdr))
    for t in tasks:
        cells = []
        for h in hdr:
            v = table.get((h, HEADLINE), {}).get(t)
            cells.append("         -" if v is None else f"{v:10.3f}")
        print(f"{t:22s} " + " ".join(cells))

    out = []
    for arm in hdr:
        for b in BUDGETS:
            for t, v in table.get((arm, b), {}).items():
                out.append({"task_id": t, "arm": arm, "budget": b, "h_value": round(v, 6)})
    if out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
            w.writeheader()
            w.writerows(out)
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
