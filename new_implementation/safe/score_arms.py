#!/usr/bin/env python3
"""Paired comparison of the ACTIVE-TB-SAFE arms against the frozen frontend.

`reconcile_eval.py` produces per-task Eval1/Eval2 for every arm on a shared
execution path. This turns those into the comparison that actually answers the
question, with three disciplines the earlier scoring lacked.

**Pairing.** Every arm is scored on the SAME task, so the comparison is a paired
one and the bootstrap resamples tasks, not measurements. An unpaired difference
of means would mostly measure which tasks each arm happened to cover.

**The right baseline.** The headline contrast is each arm against `primary` --
ACTIVE-TB-SAFE Channel 1, which is the frontend's own driver byte for byte. That
is the only contrast that isolates what Channel 2 ADDED, because Channel 1 is
inherited rather than earned. Inheriting a baseline's score is not evidence of
beating it, so `d vs primary` is reported as the result and the absolute number
is reported only as context.

**Cost shown next to benefit.** A combined arm can only differ from `primary` by
raising an alarm, so every d decomposes into alarms that were right and alarms
that were wrong. Both are printed.

The bootstrap is percentile, on the paired per-task difference, so a CI that
straddles zero means the arms are not separated at that sample size -- which is a
finding, not a failure, and is reported as such.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

REFERENCE = "primary"


def truthy(v: str) -> Optional[bool]:
    if v == "True":
        return True
    if v == "False":
        return False
    return None


def load(path: Path) -> Tuple[List[dict], List[str]]:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    arms = sorted({k[len("eval1_"):] for k in rows[0] if k.startswith("eval1_")}
                  - {"published", "literal", REFERENCE})
    return rows, ["published", "literal", REFERENCE] + arms


def scope_rows(rows: Sequence[dict], scope: str) -> List[dict]:
    if scope == "requested":
        return list(rows)
    if scope == "available":
        return [r for r in rows if r.get("available") == "True"]
    return [r for r in rows if r.get("complete") == "True"]


def mean(vals: Sequence[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def paired_bootstrap(a: Sequence[float], b: Sequence[float], n: int = 10000,
                     seed: int = 0) -> Tuple[float, float, float]:
    """Percentile CI for mean(a) - mean(b), resampling TASKS together."""
    assert len(a) == len(b)
    rng = random.Random(seed)
    k = len(a)
    if k == 0:
        return 0.0, 0.0, 0.0
    diffs = [x - y for x, y in zip(a, b)]
    obs = mean(diffs)
    boot = []
    for _ in range(n):
        idx = [rng.randrange(k) for _ in range(k)]
        boot.append(mean([diffs[i] for i in idx]))
    boot.sort()
    return obs, boot[int(0.025 * n)], boot[int(0.975 * n) - 1]


def column(rows: Sequence[dict], arm: str, metric: str) -> List[float]:
    """1.0 where the arm passes, 0.0 otherwise.

    A row the arm could not score counts as 0, never as absent: dropping it would
    shrink the denominator for whichever arm failed, which flatters that arm.
    """
    return [1.0 if truthy(r.get(f"{metric}_{arm}", "")) else 0.0 for r in rows]


def report(name: str, rows: Sequence[dict], arms: Sequence[str],
           scope: str, boot: int) -> dict:
    rs = scope_rows(rows, scope)
    out: Dict[str, dict] = {}
    print(f"\n### {name} -- scope `{scope}`, N = {len(rs)}")
    if not rs:
        print("  (no rows)")
        return out
    print(f"{'arm':13s} {'Eval1':>8s} {'Eval2':>8s}   "
          f"{'dEval2 vs primary':>19s}  {'95% CI':>18s}")
    ref2 = column(rs, REFERENCE, "eval2")
    for arm in arms:
        e1, e2 = column(rs, arm, "eval1"), column(rs, arm, "eval2")
        if arm == REFERENCE:
            line = f"{'--':>19s}  {'(reference)':>18s}"
            d = lo = hi = 0.0
        else:
            d, lo, hi = paired_bootstrap(e2, ref2, boot)
            line = f"{d:+19.4f}  [{lo:+.4f}, {hi:+.4f}]"
        print(f"{arm:13s} {mean(e1):8.4f} {mean(e2):8.4f}   {line}")
        out[arm] = {"eval1": round(mean(e1), 4), "eval2": round(mean(e2), 4),
                    "delta_eval2_vs_primary": round(d, 4),
                    "ci95": [round(lo, 4), round(hi, 4)],
                    "separated": bool(lo > 0 or hi < 0)}
    return out


def alarm_ledger(name: str, rows: Sequence[dict], arms: Sequence[str]) -> dict:
    """Where each combined arm differs from `primary`, and whether it was right."""
    print(f"\n### {name} -- what each shadow channel actually did")
    print(f"{'arm':13s} {'tasks w/ C2':>12s} {'Golden false alarm':>19s} "
          f"{'alarms on accepted':>19s} {'Eval2 gained':>13s} {'lost':>6s}")
    led: Dict[str, dict] = {}
    for arm in arms:
        if arm in ("published", "literal", REFERENCE):
            continue
        have = sum(1 for r in rows if r.get(f"has_c2_{arm}") == "True")
        ga = sum(1 for r in rows if r.get(f"golden_shadow_{arm}") == "FAIL")
        ma = sum(int(r.get(f"alarms_accepted_{arm}") or 0) for r in rows)
        gained = sum(1 for r in rows
                     if truthy(r.get(f"eval2_{arm}")) is True
                     and truthy(r.get(f"eval2_{REFERENCE}")) is not True)
        lost = sum(1 for r in rows
                   if truthy(r.get(f"eval2_{REFERENCE}")) is True
                   and truthy(r.get(f"eval2_{arm}")) is not True)
        print(f"{arm:13s} {have:12d} {ga:19d} {ma:19d} {gained:13d} {lost:6d}")
        led[arm] = {"tasks_with_channel2": have, "golden_false_alarms": ga,
                    "alarms_on_accepted_mutants": ma,
                    "tasks_eval2_gained": gained, "tasks_eval2_lost": lost}
    return led


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", action="append", required=True,
                    help="NAME=PATH of a reconcile_eval output, repeatable")
    ap.add_argument("--scope", default="available",
                    choices=("requested", "available", "complete"))
    ap.add_argument("--bootstrap", type=int, default=10000)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    summary: Dict[str, dict] = {}
    for spec in args.csv:
        name, path = spec.split("=", 1)
        rows, arms = load(Path(path))
        summary[name] = {"n_rows": len(rows), "arms": arms, "by_scope": {}}
        for scope in ("requested", "available", "complete"):
            summary[name]["by_scope"][scope] = report(name, rows, arms, scope,
                                                      args.bootstrap)
        summary[name]["alarms"] = alarm_ledger(name, rows, arms)

    print("\n" + "=" * 74)
    print("Reading this table: `primary` IS the frontend's own testbench, byte for")
    print("byte, so matching it is inheritance rather than a win. The result is the")
    print("d column. A CI straddling zero means the arms are not separated at this")
    print("sample size -- report that, do not round it to a win.")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, indent=1, sort_keys=True),
                            encoding="utf-8")
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
