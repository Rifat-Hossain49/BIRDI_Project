#!/usr/bin/env python3
"""Score the frozen IVRP arbitration decisions against golden behaviour.

Run only after arbitration_decisions.csv exists and its SHA-256 is recorded.
Golden is used to answer "was the decision right?", never "what decision should
be made?".

Truth available per check point:

  * inside a testbench that PASSED Eval1: golden agreed with every assertion, so
    the recorded expectation is the truth. Any CORRECT there is a false
    correction.
  * at the recorded first failing check of a testbench that FAILED: the
    diagnostic recorded the value golden produced, so truth is known.
  * at any other point inside a failing testbench: truth is unknown. Those
    decisions are counted separately as unscoreable and are excluded from
    precision rather than assumed either way.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULES = ["rule_D", "rule_E", "rule_F", "rule_G"]
PRIMARY = "rule_E"

# Same-population baselines already measured by arbitration_prototype.py.
BASELINE_RECALL = 0.124
BASELINE_FALSE_CORRECTION = 0.0125


def tf(v) -> bool:
    return str(v).strip().lower() == "true"


def widen(a, b):
    n = max(len(a), len(b))
    return a.zfill(n), b.zfill(n)


def same(a, b) -> bool:
    if not a or not b:
        return False
    x, y = widen(a.lower(), b.lower())
    return x == y


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True, type=Path,
                    help="directory holding arbitration_decisions.csv and ivrp_checkpoints.csv")
    ap.add_argument("--diagnostic", type=Path,
                    default=ROOT / "kaggle_runs/eval1_diagnostic_v1/eval1_diagnostic/eval1_diagnostic.csv")
    ap.add_argument("--frozen", type=Path,
                    default=ROOT / "kaggle_runs/spec_only_full_synthesis_v1_complete/active_tb_s_frozen_full_v1.zip")
    ap.add_argument("--task-ids", type=Path,
                    default=ROOT / "kaggle_upload_ivrp/dataset/active_tb_s_ivrp_v1/pilot_task_ids.json")
    args = ap.parse_args()

    dec_path = args.results / "arbitration_decisions.csv"
    digest = hashlib.sha256(dec_path.read_bytes()).hexdigest()
    recorded = (args.results / "arbitration_decisions.sha256").read_text().strip()
    print(f"decision file sha256 : {digest}")
    print(f"recorded on Kaggle   : {recorded}")
    print(f"integrity            : {'MATCH' if digest == recorded else 'MISMATCH'}\n")
    if digest != recorded:
        raise SystemExit("decision file changed after freezing; scoring aborted")

    pilot = set(json.loads(args.task_ids.read_text()))
    decisions = list(csv.DictReader(dec_path.open(encoding="utf-8")))
    checkpoints = {(r["task_id"], r["method"], r["point_hash"]): r
                   for r in csv.DictReader((args.results / "ivrp_checkpoints.csv").open(encoding="utf-8"))}

    import importlib.util
    spec = importlib.util.spec_from_file_location("ap", ROOT / "analysis/arbitration_prototype.py")
    proto = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(proto)
    frozen = {k: v for k, v in proto.load_frozen(args.frozen, "seed_017").items() if k[1] in pilot}

    def key_hash(key):
        return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]

    diag = [d for d in csv.DictReader(args.diagnostic.open(encoding="utf-8")) if d["task_id"] in pilot]
    passing = {(d["method"], d["task_id"]) for d in diag if d["status"] == "PASS"}
    failing = {(d["method"], d["task_id"]): d for d in diag if d["status"] == "FAIL"}

    # Locate the recorded first-failure point for each failing testbench.
    truth = {}
    for (method, task), d in failing.items():
        data = frozen.get((method, task))
        if not data or not d["first_expected"]:
            continue
        for a in data["asserts"]:
            if (a["scenario"] == d["first_fail_scenario"]
                    and a["index"] == int(d["first_fail_index"])
                    and a["expected"] == d["first_expected"].lower()):
                scen = data["suite"].get(a["scenario"])
                k = proto.point_key(scen, a["index"], a["port"])
                if k:
                    truth[(task, method, key_hash(k))] = d["first_got"].lower()
                break

    cb = [json.loads(l) for l in (ROOT / "baselines/ConfiBench/data/CorrectBenchResults/run_info.jsonl")
          .read_text(encoding="utf-8").splitlines() if l.strip()]
    ctype = {r["task_id"]: r.get("circuit_type") for r in cb}

    correlated = set()
    for (task, method, kh), _ in truth.items():
        ck = checkpoints.get((task, method, kh))
        if ck and tf(ck["populationA_supports_tb"]):
            correlated.add((task, method, kh))

    print(f"pilot testbenches: passing {len(passing)}, failing {len(failing)}")
    print(f"known-wrong expectations located: {len(truth)}")
    print(f"correlated subset (population A supports the wrong expectation): {len(correlated)}\n")

    report = {}
    for N in (3, 5):
        for rule in RULES:
            rows = [r for r in decisions if int(r["N"]) == N]
            tp = fp = unscoreable = 0
            broke_tbs, fixed_points = set(), set()
            abstain = keep = correct = 0
            per_class = collections.defaultdict(lambda: collections.Counter())
            for r in rows:
                d = r[rule]
                task, method, kh = r["task_id"], r["method"], r["point_hash"]
                cls = ctype.get(task, "?")
                if d == "ABSTAIN":
                    abstain += 1
                    continue
                if d == "KEEP":
                    keep += 1
                    continue
                correct += 1
                new = r[f"{rule}_value"]
                if (method, task) in passing:
                    fp += 1
                    broke_tbs.add((method, task))
                    per_class[cls]["false_correction"] += 1
                elif (task, method, kh) in truth:
                    if same(new, truth[(task, method, kh)]):
                        tp += 1
                        fixed_points.add((task, method, kh))
                        per_class[cls]["true_correction"] += 1
                    else:
                        fp += 1
                        per_class[cls]["wrong_correction"] += 1
                else:
                    unscoreable += 1
                    per_class[cls]["unscoreable"] += 1
            attempted = tp + fp
            precision = tp / attempted if attempted else float("nan")
            recall = len(fixed_points) / len(truth) if truth else 0.0
            pass_assertions = sum(1 for r in rows if (r["method"], r["task_id"]) in passing)
            fcr = fp / pass_assertions if pass_assertions else 0.0
            corr_hit = sum(1 for k in fixed_points if k in correlated)
            report[(N, rule)] = {
                "attempted": attempted, "tp": tp, "fp": fp, "unscoreable": unscoreable,
                "precision": precision, "precision_ci": wilson(tp, attempted),
                "recall": recall, "recall_ci": wilson(len(fixed_points), len(truth)),
                "false_correction_rate": fcr, "broken_tbs": len(broke_tbs),
                "abstain": abstain, "keep": keep, "correct": correct,
                "abstention_rate": abstain / len(rows) if rows else 0.0,
                "correlated_recovered": corr_hit,
                "per_class": {k: dict(v) for k, v in per_class.items()},
            }

    print("=== Assertion-level results ===")
    hdr = "{:>3s} {:8s} {:>9s} {:>4s} {:>4s} {:>11s} {:>18s} {:>8s} {:>7s} {:>8s} {:>7s}"
    print(hdr.format("N", "rule", "attempted", "TP", "FP", "precision", "95% CI",
                     "recall", "FCR", "brokeTB", "abstain"))
    for N in (3, 5):
        for rule in RULES:
            s = report[(N, rule)]
            lo, hi = s["precision_ci"]
            star = " *" if rule == PRIMARY else ""
            print(hdr.format(
                str(N), rule.replace("rule_", "") + star, str(s["attempted"]),
                str(s["tp"]), str(s["fp"]),
                "nan" if math.isnan(s["precision"]) else f"{s['precision']:.3f}",
                f"[{lo:.3f}, {hi:.3f}]", f"{s['recall']:.3f}",
                f"{s['false_correction_rate']:.4f}", str(s["broken_tbs"]),
                f"{s['abstention_rate']:.3f}"))
    print("  * = PRIMARY rule, the registered basis for the go/no-go decision")
    print(f"  baselines: same-population recall {BASELINE_RECALL:.3f}, "
          f"false-correction {BASELINE_FALSE_CORRECTION:.4f}\n")

    print("=== Correlated subset: does population B break population A's shared errors? ===")
    print(f"  subset size n = {len(correlated)}")
    for N in (3, 5):
        s = report[(N, PRIMARY)]
        k = s["correlated_recovered"]
        lo, hi = wilson(k, len(correlated))
        print(f"  N={N} rule E: recovered {k}/{len(correlated)}"
              f"  95% CI [{lo:.3f}, {hi:.3f}]")
    print()

    print("=== Circuit-class split (PRIMARY rule E) ===")
    for N in (3, 5):
        print(f"  N={N}: {json.dumps(report[(N, PRIMARY)]['per_class'], sort_keys=True)}")
    print()

    print("=== Stage-1 advancement criteria (PRIMARY rule E, N=5) ===")
    s = report[(5, PRIMARY)]
    checks = [
        ("1. precision point estimate >= 0.90",
         (not math.isnan(s["precision"])) and s["precision"] >= 0.90,
         "nan" if math.isnan(s["precision"]) else f"{s['precision']:.3f}"),
        ("2. recall strictly > 0.124 baseline", s["recall"] > BASELINE_RECALL, f"{s['recall']:.3f}"),
        ("3. false-correction rate < 0.0125", s["false_correction_rate"] < BASELINE_FALSE_CORRECTION,
         f"{s['false_correction_rate']:.4f}"),
        ("5. negligible regression on passing TBs", s["broken_tbs"] == 0, f"{s['broken_tbs']} broken"),
        ("6. some recovery in correlated subset", s["correlated_recovered"] > 0,
         f"{s['correlated_recovered']}/{len(correlated)}"),
    ]
    for label, ok, val in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}: {val}")
    print("  (criterion 4, conservative Eval1 delta, is reported in the results document)")

    (args.results / "ivrp_scored.json").write_text(
        json.dumps({f"N{n}_{r}": {k: v for k, v in d.items() if k != "per_class"}
                    for (n, r), d in report.items()}, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {args.results / 'ivrp_scored.json'}")


if __name__ == "__main__":
    main()
