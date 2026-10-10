#!/usr/bin/env python3
"""Score ACTIVE-TB-S evaluation output against published AutoBench/CorrectBench records.

Reports both metric families side by side:

  * the agreement metric this project uses (generated verdict == official verdict),
  * the AutoBench detection metric (restricted to mutants the official
    testbench actually rejects, with no penalty for over-rejection),

because the two are not interchangeable and only the second is comparable to
the published baselines.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import random
from pathlib import Path

BASELINES = Path(__file__).resolve().parent.parent / "baselines" / "ConfiBench" / "data"


def tf(value) -> bool:
    return str(value).strip().lower() == "true"


def load_jsonl(path: Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def baseline_rows() -> dict:
    return {
        "AutoBench": load_jsonl(BASELINES / "AutoBenchResults" / "run_info_and_codes.jsonl"),
        "AutoBench-direct": load_jsonl(BASELINES / "AutoBenchResults" / "run_info_and_codes_Baseline.jsonl"),
        "CorrectBench": load_jsonl(BASELINES / "CorrectBenchResults" / "run_info.jsonl"),
    }


def frac(text):
    if isinstance(text, str) and "/" in text:
        num, den = text.split("/")
        den = float(den)
        return (float(num), den) if den else None
    return None


def score_baseline(rows: list) -> dict:
    n = len(rows)
    passed = [r for r in rows if r.get("Eval1_pass")]
    exact = sum(1 for r in rows if r.get("Eval2_pass"))
    pairs = [frac(r.get("Eval2_ratio")) for r in rows]
    kn = sum(p[0] for p in pairs if p)
    kd = sum(p[1] for p in pairs if p)
    return {
        "runs": n,
        "eval1": len(passed) / n,
        "eval2_uncond": exact / n,
        "eval2_given_eval1": exact / len(passed) if passed else 0.0,
        "kill_given_eval1": kn / kd if kd else 0.0,
    }


def score_ours(per_task: list, per_mutant: list) -> dict:
    """Score each method under both metric families.

    per_task rows carry the agreement metric; per_mutant rows carry the raw
    verdict pair needed to reconstruct the AutoBench detection metric. Rows are
    keyed by (seed, method, task) because the same task recurs once per seed and
    merging seeds would pool one task's mutants across five independent runs.
    """
    out = {}
    mut_by = collections.defaultdict(list)
    for row in per_mutant:
        mut_by[(row["__seed"], row["method"], row["task_id"])].append(row)

    for method in sorted({row["method"] for row in per_task}):
        rows = [r for r in per_task if r["method"] == method]
        denom = len(rows)
        supported = [r for r in rows if tf(r.get("supported"))]
        passed = [r for r in rows if tf(r.get("eval1_pass"))]

        valid = detected = 0
        exact_tasks = 0
        overkill_n = overkill_d = 0
        for row in passed:
            muts = mut_by[(row["__seed"], method, row["task_id"])]
            golden_catches = [m for m in muts if not tf(m["golden_tb_pass"])]
            golden_accepts = [m for m in muts if tf(m["golden_tb_pass"])]
            hits = [m for m in golden_catches if not tf(m["generated_tb_pass"])]
            valid += len(golden_catches)
            detected += len(hits)
            overkill_d += len(golden_accepts)
            overkill_n += sum(1 for m in golden_accepts if not tf(m["generated_tb_pass"]))
            if golden_catches and len(hits) == len(golden_catches):
                exact_tasks += 1

        out[method] = {
            "tasks": denom,
            "support": len(supported) / denom if denom else 0.0,
            "eval1": len(passed) / denom if denom else 0.0,
            # project metric: verdict agreement with the official testbench
            "agree_eval2_exact": sum(1 for r in passed if tf(r.get("eval2_exact_pass"))) / denom if denom else 0.0,
            "agree_eval2_loose": sum(1 for r in passed if tf(r.get("eval2_loose_pass_0_8"))) / denom if denom else 0.0,
            # AutoBench metric: detection of mutants the official testbench rejects
            "ab_eval2_given_eval1": exact_tasks / len(passed) if passed else 0.0,
            "ab_eval2_uncond": exact_tasks / denom if denom else 0.0,
            "ab_kill_given_eval1": detected / valid if valid else 0.0,
            "overkill": overkill_n / overkill_d if overkill_d else 0.0,
        }
    return out


def bootstrap_delta(per_task, method_a, method_b, field="eval1_pass", iters=10000, seed=17):
    """Paired task-level bootstrap on the difference method_a - method_b.

    The resampling unit is the task, not the (task, seed) pair: seeds are
    repeated measurements of the same task and are averaged first, so the
    interval reflects uncertainty over tasks rather than over reruns.
    """
    acc = collections.defaultdict(lambda: collections.defaultdict(list))
    for row in per_task:
        acc[row["task_id"]][row["method"]].append(tf(row.get(field)))
    by_task = {
        task: {m: sum(v) / len(v) for m, v in methods.items()}
        for task, methods in acc.items()
    }
    tasks = [t for t, m in by_task.items() if method_a in m and method_b in m]
    if not tasks:
        return None
    rng = random.Random(seed)
    point = sum(by_task[t][method_a] - by_task[t][method_b] for t in tasks) / len(tasks)
    deltas = []
    for _ in range(iters):
        sample = [tasks[rng.randrange(len(tasks))] for _ in tasks]
        deltas.append(sum(by_task[t][method_a] - by_task[t][method_b] for t in sample) / len(sample))
    deltas.sort()
    return point, deltas[int(0.025 * iters)], deltas[int(0.975 * iters)], len(tasks)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-output", required=True, type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    # Read only the canonical per-seed directories. The kernel also emits
    # top-level copies and an all-seeds roll-up of the same rows; globbing
    # broadly would count some seeds twice.
    per_task_paths = sorted(args.eval_output.rglob("seed_*/spec_only_eval2_per_task.csv"))
    per_mut_paths = sorted(args.eval_output.rglob("seed_*/spec_only_eval2_per_mutant.csv"))
    if not per_task_paths:
        per_task_paths = sorted(args.eval_output.rglob("spec_only_eval2_per_task.csv"))
        per_mut_paths = sorted(args.eval_output.rglob("spec_only_eval2_per_mutant.csv"))
    if not per_task_paths or not per_mut_paths:
        raise SystemExit("No evaluation CSVs under " + str(args.eval_output))
    if len(per_task_paths) != len(per_mut_paths):
        raise SystemExit("Mismatched per-task/per-mutant file counts: "
                         f"{len(per_task_paths)} vs {len(per_mut_paths)}")

    def tag(path, rows):
        """Stamp each row with the seed its file came from."""
        seed = path.parent.name if path.parent.name.startswith("seed_") else "single"
        for row in rows:
            row["__seed"] = seed
        return rows

    per_task, per_mutant = [], []
    for p in per_task_paths:
        per_task += tag(p, list(csv.DictReader(p.open(encoding="utf-8"))))
    for p in per_mut_paths:
        per_mutant += tag(p, list(csv.DictReader(p.open(encoding="utf-8"))))

    keys = {(r["__seed"], r["method"], r["task_id"]) for r in per_task}
    if len(keys) != len(per_task):
        raise SystemExit("Duplicate (seed, method, task) rows: {} rows, {} unique".format(
            len(per_task), len(keys)))

    print("loaded {} task rows, {} mutant rows from {} file(s) over seeds {}\n".format(
        len(per_task), len(per_mutant), len(per_task_paths),
        sorted({r["__seed"] for r in per_task})))

    print("=== Published baselines (156 tasks) ===")
    header = "{:20s} {:>5s} {:>7s} {:>7s} {:>7s} {:>8s}"
    print(header.format("method", "runs", "Eval1", "Eval2", "E2|E1", "kill|E1"))
    for name, rows in baseline_rows().items():
        s = score_baseline(rows)
        print("{:20s} {:5d} {:7.4f} {:7.4f} {:7.4f} {:8.4f}".format(
            name, s["runs"], s["eval1"], s["eval2_uncond"],
            s["eval2_given_eval1"], s["kill_given_eval1"]))

    ours = score_ours(per_task, per_mutant)
    print("\n=== This work, AutoBench-comparable metric ===")
    print("{:24s} {:>6s} {:>7s} {:>7s} {:>7s} {:>8s} {:>9s}".format(
        "method", "supp", "Eval1", "E2|E1", "Eval2", "kill|E1", "overkill"))
    for method, s in sorted(ours.items(), key=lambda kv: -kv[1]["ab_eval2_uncond"]):
        print("{:24s} {:6.3f} {:7.4f} {:7.4f} {:7.4f} {:8.4f} {:9.4f}".format(
            method, s["support"], s["eval1"], s["ab_eval2_given_eval1"],
            s["ab_eval2_uncond"], s["ab_kill_given_eval1"], s["overkill"]))

    print("\n=== This work, project agreement metric (not baseline-comparable) ===")
    print("{:24s} {:>7s} {:>7s} {:>7s}".format("method", "Eval1", "exact", "loose"))
    for method, s in sorted(ours.items(), key=lambda kv: -kv[1]["agree_eval2_exact"]):
        print("{:24s} {:7.4f} {:7.4f} {:7.4f}".format(
            method, s["eval1"], s["agree_eval2_exact"], s["agree_eval2_loose"]))

    if "typed_formal_active" in ours:
        print("\n=== Paired bootstrap vs controls (Eval1) ===")
        for other in sorted(m for m in ours if m != "typed_formal_active"):
            r = bootstrap_delta(per_task, "typed_formal_active", other)
            if r:
                point, lo, hi, n = r
                flag = "significant" if lo > 0 else ("negative" if hi < 0 else "not significant")
                print("  vs {:24s} delta {:+.4f}  95% CI [{:+.4f}, {:+.4f}]  n={}  {}".format(
                    other, point, lo, hi, n, flag))

    if args.json_out:
        args.json_out.write_text(json.dumps(ours, indent=2), encoding="utf-8")
        print("\nwrote " + str(args.json_out))


if __name__ == "__main__":
    main()
