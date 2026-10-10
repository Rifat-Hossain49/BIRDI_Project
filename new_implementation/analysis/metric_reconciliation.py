#!/usr/bin/env python3
"""Reproduce the published CorrectBench/ConfiBench Eval2 exactly, and reconcile.

The published Eval2 is NOT raw mutant detection and is NOT the stored
`Eval2_pass` boolean. Per `ConfiBench/analyze.py` and `CorrectBench/analyze.py`:

    LOOSE_FACTOR = 0.8

    loose_Eval2_pass(d) = d["Eval2_pass"] or (Eval2_ratio >= 0.8)

    Eval2_pass(d) = loose_Eval2_pass(d),
                    except task m2014_q3, which also passes when
                    Eval2_failed_mutant_idxes == [3,4,7,8,9,10]

Eval2_ratio counts *agreement with the golden testbench's verdicts* over the
mutant set, so a mutant the official testbench accepts must also be accepted.
Agreement with a weak official testbench is not the same measurement as genuine
bug detection, and the two are reported separately below.
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "baselines" / "ConfiBench" / "data"
LOOSE_FACTOR = 0.8


def load(path: Path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def ratio_pair(d):
    s = d.get("Eval2_ratio")
    if not isinstance(s, str) or "/" not in s:
        return None
    a, b = s.split("/")
    try:
        a, b = float(a), float(b)
    except ValueError:
        return None
    return (a, b) if b else None


def loose_eval2_pass(d) -> bool:
    """Verbatim port of analyze.py:loose_Eval2_pass."""
    if d.get("Eval2_pass", False):
        return True
    p = ratio_pair(d)
    if p is None:
        return False
    return (p[0] / p[1]) >= LOOSE_FACTOR


def published_eval2(d) -> bool:
    """Verbatim port of analyze.py:Eval2_pass, including the task exception."""
    if d.get("task_id") == "m2014_q3":
        return (d.get("Eval2_failed_mutant_idxes", []) == [3, 4, 7, 8, 9, 10]
                or loose_eval2_pass(d))
    return loose_eval2_pass(d)


def eval0_pass(d) -> bool:
    return bool(d.get("Eval0_iv_pass", False) and d.get("Eval0_py_pass", False))


def strict_all_verdicts_agree(d) -> bool:
    return bool(d.get("Eval2_pass", False))


def raw_mutant_detection(d):
    """Fraction of mutants this testbench REJECTED, regardless of golden agreement.

    Not recoverable from these records: they store agreement, plus the indices
    where agreement failed. Returned as None where it cannot be derived.
    """
    return None


def summarise(name, rows):
    n = len(rows)
    e1 = sum(1 for r in rows if r.get("Eval1_pass"))
    pub = sum(1 for r in rows if published_eval2(r))
    strict = sum(1 for r in rows if strict_all_verdicts_agree(r))
    # Published tables gate Eval2 on Eval0 and Eval1 in the counting helpers.
    gated = sum(1 for r in rows if eval0_pass(r) and r.get("Eval1_pass") and published_eval2(r))
    return {"runs": n, "eval1": e1 / n,
            "published_eval2": pub / n,
            "published_eval2_gated_on_eval0_eval1": gated / n,
            "strict_all_verdicts_agree": strict / n}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-out", type=Path)
    args = ap.parse_args()

    sources = {
        "AutoBench": DATA / "AutoBenchResults" / "run_info_and_codes.jsonl",
        "AutoBench-direct": DATA / "AutoBenchResults" / "run_info_and_codes_Baseline.jsonl",
        "CorrectBench(run_info)": DATA / "CorrectBenchResults" / "run_info.jsonl",
        "CorrectBench(codes)": DATA / "CorrectBenchResults" / "run_info_and_codes.jsonl",
        "CorrectBench(new)": DATA / "CorrectBenchResults" / "run_info_and_codes_new.jsonl",
    }

    ctype = {}
    for p in sources.values():
        if p.exists():
            for r in load(p):
                ctype.setdefault(r["task_id"], r.get("circuit_type"))

    out = {}
    print("=== Published metric, reproduced from analyze.py ===")
    print(f"{'source':28s} {'runs':>5s} {'tasks':>6s} {'Eval1':>7s} "
          f"{'pubEval2':>9s} {'gated':>7s} {'strict':>7s}")
    for name, path in sources.items():
        if not path.exists():
            print(f"{name:28s} MISSING")
            continue
        rows = load(path)
        s = summarise(name, rows)
        tasks = len({r["task_id"] for r in rows})
        out[name] = dict(s, tasks=tasks, path=str(path))
        print(f"{name:28s} {s['runs']:5d} {tasks:6d} {s['eval1']:7.4f} "
              f"{s['published_eval2']:9.4f} {s['published_eval2_gated_on_eval0_eval1']:7.4f} "
              f"{s['strict_all_verdicts_agree']:7.4f}")

    print("\n=== Sequential-only, published metric ===")
    print(f"{'source':28s} {'runs':>5s} {'Eval1':>7s} {'pubEval2':>9s} {'strict':>7s}")
    for name, path in sources.items():
        if not path.exists():
            continue
        rows = [r for r in load(path) if ctype.get(r["task_id"]) == "SEQ"]
        if not rows:
            continue
        s = summarise(name, rows)
        out.setdefault(name, {})["sequential"] = s
        print(f"{name:28s} {s['runs']:5d} {s['eval1']:7.4f} "
              f"{s['published_eval2']:9.4f} {s['strict_all_verdicts_agree']:7.4f}")

    print("\n=== Reconciliation against the CorrectBench paper ===")
    print("  paper overall Eval2    : 0.7013")
    print("  paper sequential Eval2 : 0.5493")
    for key in ("CorrectBench(run_info)", "CorrectBench(codes)", "CorrectBench(new)"):
        if key in out and "sequential" in out[key]:
            print(f"  {key:24s} overall {out[key]['published_eval2']:.4f}  "
                  f"sequential {out[key]['sequential']['published_eval2']:.4f}")

    print("\n=== pass@1 vs best-of-k, per task ===")
    for key, path in (("CorrectBench(run_info)", sources["CorrectBench(run_info)"]),):
        rows = load(path)
        by = collections.defaultdict(list)
        for r in rows:
            by[r["task_id"]].append(r)
        any_pass = sum(1 for t, rs in by.items() if any(published_eval2(x) for x in rs))
        mean_rate = sum(sum(1 for x in rs if published_eval2(x)) / len(rs)
                        for rs in by.values()) / len(by)
        print(f"  {key}: tasks {len(by)}, per-run mean {mean_rate:.4f}, "
              f"any-run (best-of-k) {any_pass/len(by):.4f}")

    if args.json_out:
        args.json_out.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json_out}")


if __name__ == "__main__":
    main()
