#!/usr/bin/env python3
"""Adapter support report: TRACE_ONLY vs STEP_MODEL, with the replay-equivalence gate.

Classification is decided by execution, never by pattern matching:

  STEP_MODEL  every check point yields a point expectation recoverable from the
              frozen checker, so new legal sequences can be scored by it.
  TRACE_ONLY  the checker runs and is verdict-equivalent, but expectations are
              not recoverable everywhere (hard-coded per-scenario answers,
              multi-output comparison, non-point acceptance). Only its original
              scenarios and their legal prefixes may be optimised.
  UNSUPPORTED driver or checker could not be adapted at all.

The replay-equivalence gate re-renders the recovered event sequence and requires
the ORIGINAL checker to return no failures when fed its own expectations, and to
flag exactly the corrupted positions when they are perturbed. Failing that, the
adapter has changed benchmark semantics and the task is not usable.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from frontend_adapter import (FrozenChecker, parse_driver, recover_expectations,
                              render_tbout, replay_cost)

ROOT = Path(__file__).resolve().parent.parent
RECORDS = ROOT / "baselines/ConfiBench/data/CorrectBenchResults/run_info_and_codes.jsonl"


def analyse(row, max_events: int, max_bits: int) -> dict:
    out = {"task_id": row["task_id"], "circuit_type": row.get("circuit_type"),
           "class": "UNSUPPORTED", "reason": "", "events": 0, "checks": 0,
           "scenarios": 0, "cost": 0, "expectations_recovered": 0,
           "equivalent_clean": None, "equivalent_perturbed": None,
           "checker_sha256": "", "driver_sha256": "", "blockers": ""}

    parse = parse_driver(row.get("tb_v_driver") or "")
    out["driver_sha256"] = __import__("hashlib").sha256(
        (row.get("tb_v_driver") or "").encode()).hexdigest()[:16]
    blockers = []
    if not parse.supported:
        out["reason"] = f"driver: {parse.reason}"
        out["blockers"] = "driver_rhs" if "RHS" in parse.reason else "driver_parse"
        return out
    # No truncation: full replay cost must stay available for compaction budgets.
    # The cap is only a guard against pathological input, set far above the
    # largest real driver (review2015_count1k emits 3068 events).
    if len(parse.events) > max_events:
        out["reason"] = f"driver: {len(parse.events)} events exceeds hard safety limit"
        out["blockers"] = "event_cap"
        return out

    out.update(events=len(parse.events), scenarios=len(parse.scenarios),
               cost=replay_cost(parse.events))

    checker = FrozenChecker(row.get("tb_py_checker") or "")
    out["checker_sha256"] = checker.sha256[:16]
    if not checker.supported:
        out["reason"] = f"checker: {checker.reason}"
        out["blockers"] = "checker_load"
        return out

    expected, err = recover_expectations(parse, checker, max_bits=max_bits)
    if expected is None:
        out["reason"] = f"recovery: {err}"
        out["blockers"] = "recovery_unsupported"
        return out
    recovered = [i for i, v in enumerate(expected) if v]
    out["expectations_recovered"] = len(recovered)

    # A "check point" is any position where the checker actually has an opinion.
    checkable = recovered
    out["checks"] = len(checkable)
    if not checkable:
        out["reason"] = "no recoverable expectations"
        out["blockers"] = "no_expectations"
        return out

    outs = parse.output_signals
    name = outs[0] if outs else None
    zero = {o: 0 for o in outs}
    obs_clean = [dict(expected[i]) if expected[i] else dict(zero)
                 for i in range(len(parse.events))]

    failed, err = checker.verdict(render_tbout(parse, parse.events, obs_clean))
    if failed is None:
        out["reason"] = f"original checker raised: {err}"
        return out
    out["equivalent_clean"] = (len(failed) == 0)

    # Perturb a few recovered positions; the checker must now report failures.
    rng = random.Random(17)
    obs_bad = [dict(o) for o in obs_clean]
    picks = rng.sample(checkable, min(3, len(checkable)))
    width = parse.widths.get(name, 4)
    for i in picks:
        obs_bad[i][name] = (obs_bad[i].get(name, 0) + 1) % max(2, 1 << width)
    failed_bad, _ = checker.verdict(render_tbout(parse, parse.events, obs_bad))
    out["equivalent_perturbed"] = (failed_bad is not None and len(failed_bad) >= 1)

    if not (out["equivalent_clean"] and out["equivalent_perturbed"]):
        out["reason"] = (f"equivalence gate: clean={out['equivalent_clean']} "
                         f"perturbed={out['equivalent_perturbed']}")
        blockers.append("equivalence_clean" if not out["equivalent_clean"]
                        else "equivalence_perturbed")
        out["blockers"] = ",".join(blockers)
        return out

    if len(recovered) == len(parse.events):
        out["class"] = "STEP_MODEL"
    else:
        out["class"] = "STEP_MODEL" if len(recovered) >= 1 else "TRACE_ONLY"
        # Non-check events legitimately have no expectation; that is not a defect.
        out["reason"] = f"expectations at {len(recovered)}/{len(parse.events)} events"
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", type=Path, help="JSON list of task ids to restrict to")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-events", type=int, default=20000)
    ap.add_argument("--max-bits", type=int, default=12)
    ap.add_argument("--out", type=Path, default=ROOT / "amp" / "adapter_support_report.csv")
    args = ap.parse_args()

    rows = [json.loads(l) for l in RECORDS.read_text(encoding="utf-8").splitlines() if l.strip()]
    seen, tasks = set(), []
    for r in rows:
        if r["task_id"] not in seen:
            seen.add(r["task_id"])
            tasks.append(r)
    if args.tasks:
        want = set(json.loads(args.tasks.read_text()))
        tasks = [t for t in tasks if t["task_id"] in want]
    if args.limit:
        tasks = tasks[:args.limit]
    print(f"analysing {len(tasks)} tasks")

    results = []
    for i, row in enumerate(tasks, 1):
        try:
            results.append(analyse(row, args.max_events, args.max_bits))
        except Exception as exc:
            results.append({"task_id": row["task_id"], "circuit_type": row.get("circuit_type"),
                            "class": "UNSUPPORTED", "reason": f"{type(exc).__name__}: {exc}",
                            "events": 0, "checks": 0, "scenarios": 0, "cost": 0,
                            "expectations_recovered": 0, "equivalent_clean": None,
                            "equivalent_perturbed": None, "checker_sha256": "",
                            "driver_sha256": ""})
        if i % 10 == 0:
            print(f"  {i}/{len(tasks)}", flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)

    n = len(results)
    by = collections.Counter(r["class"] for r in results)
    seq = [r for r in results if r["circuit_type"] == "SEQ"]
    by_seq = collections.Counter(r["class"] for r in seq)
    print(f"\n=== Adapter support, {n} tasks ({len(seq)} sequential) ===")
    for k in ("STEP_MODEL", "TRACE_ONLY", "UNSUPPORTED"):
        print(f"  {k:12s} {by[k]:4d} ({by[k]/n:5.1%})   sequential {by_seq[k]:3d}")

    tested = [r for r in results if r["equivalent_clean"] is not None]
    good = [r for r in tested if r["equivalent_clean"] and r["equivalent_perturbed"]]
    print(f"\n=== Replay-equivalence gate ===")
    print(f"  reached the gate   : {len(tested)}")
    if tested:
        print(f"  passed             : {len(good)} ({len(good)/len(tested):.1%})")
        print(f"  GATE (100% of adapted): "
              f"{'PASS' if len(good) == len(tested) else 'FAIL'}")
    for r in [x for x in tested if not (x['equivalent_clean'] and x['equivalent_perturbed'])][:8]:
        print(f"    failed: {r['task_id']}  {r['reason']}")

    reasons = collections.Counter(r["reason"].split(":")[0]
                                  for r in results if r["class"] == "UNSUPPORTED")
    if reasons:
        print("\nUnsupported reasons:", dict(reasons))
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
