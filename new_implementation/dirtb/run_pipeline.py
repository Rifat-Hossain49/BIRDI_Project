#!/usr/bin/env python3
"""End-to-end pipeline run: candidates -> frozen stimulus -> resolution -> Eval1/Eval2.

For each task:
  driver    frozen stimulus (random scenarios + cost-budgeted long runs)
  simulate  every candidate design on the driver
  group     classes of identical behaviour per resolution unit
  resolve   localized-question answers if an answers file is given, else plurality
  expected  the reference trace assembled from the winning classes
  evaluate  Eval1 / Eval2 exactly as ConfiBench computes them

A task with no candidate that simulates has no reference; it is scored as a
failure (Eval1 and Eval2 false), never dropped from the denominator.

Also reports ConfiBench-4o's own per-task Eval1/Eval2 on the same task subset
(averaged over its 3 runs), so the comparison is on identical tasks.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import zipfile
import zlib
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dirtb.bench import ZIP, load                                    # noqa: E402
from dirtb.evaluate import evaluate, save_cache                      # noqa: E402
from dirtb.hdl import build_driver, parse_header                     # noqa: E402
from dirtb.resolve import group, reference_trace, resolve, simulate_candidates  # noqa: E402

LOOSE = 0.8


def confibench_per_task(variant="ConfiBench_4o"):
    z = zipfile.ZipFile(ZIP)
    base = f"saves_inEDA/TODAES/{variant}/"
    acc = defaultdict(lambda: [[], []])
    for n in z.namelist():
        if n.startswith(base) and n.endswith("/data.json") and n[len(base):].count("/") == 2:
            d = json.loads(z.read(n).decode("utf-8", "replace"))
            e1 = bool(d.get("Eval1_pass"))
            e2 = False
            if e1:
                if d.get("Eval2_pass"):
                    e2 = True
                else:
                    r = d.get("Eval2_ratio") or ""
                    if "/" in r:
                        a, b = r.split("/")
                        e2 = float(b) > 0 and float(a) / float(b) >= LOOSE
                    if d["task_id"] == "m2014_q3":
                        e2 = e2 or d.get("Eval2_failed_mutant_idxes", []) == [3, 4, 7, 8, 9, 10]
            acc[d["task_id"]][0].append(e1)
            acc[d["task_id"]][1].append(e2)
    return {t: (sum(v[0]) / len(v[0]), sum(v[1]) / len(v[1])) for t, v in acc.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", type=Path, required=True, help="jsonl: task_id, candidate_id, rtl")
    ap.add_argument("--answers", type=Path, help="jsonl: qid, answer (A/B) from localized questions")
    ap.add_argument("--split", default="dev")
    ap.add_argument("--only-candidate-tasks", action="store_true",
                    help="restrict to tasks that have at least one candidate")
    ap.add_argument("--policy", choices=("plurality", "unanimity"), default="plurality",
                    help="unanimity: check an output bit only where every simulated candidate agrees")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if args.policy == "unanimity":
        from dirtb.abstain_policies import abstain_trace

    cands = defaultdict(list)
    for l in args.candidates.read_text(encoding="utf-8").splitlines():
        if l.strip():
            r = json.loads(l)
            if r.get("rtl"):
                cands[r["task_id"]].append(r)
    answers = None
    if args.answers:
        answers = {}
        for l in args.answers.read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l)
                answers[r["qid"]] = r.get("answer")
    tasks = load(args.split)
    if args.only_candidate_tasks:
        tasks = [t for t in tasks if t["task_id"] in cands]
    cb = confibench_per_task()

    results = []
    t_all = time.time()
    for i, t in enumerate(tasks, 1):
        t0 = time.time()
        iface = parse_header(t["header"])
        driver = build_driver(iface, seed=zlib.crc32(t["task_id"].encode()), marathons=True)
        traces = simulate_candidates(driver, cands.get(t["task_id"], []))
        units, n_rows = group(iface, traces)
        rec = {"task_id": t["task_id"], "circuit_type": t["circuit_type"],
               "n_candidates": len(cands.get(t["task_id"], [])), "n_ran": len(traces),
               "confibench_eval1": cb.get(t["task_id"], (0, 0))[0],
               "confibench_eval2": cb.get(t["task_id"], (0, 0))[1]}
        chosen, stats = (resolve(t, units, answers) if units else (None, Counter()))
        if not chosen:
            rec.update({"eval1": False, "eval2": False, "note": "no candidate simulated"})
        else:
            # the template must have the grouped row count; the first simulated candidate may not
            good = {k: tr for k, tr in traces.items() if len(tr.rows) == n_rows}
            template = next(iter(good.values()))
            expected = reference_trace(units, chosen, template)
            x_frac = 0.0
            if args.policy == "unanimity":
                n_in = len([p for p in iface.inputs if p.name != iface.clock])
                expected, x_frac = abstain_trace(units, good, n_in, template,
                                                 [r[2] for r in expected.rows], "vote", 1.0)
            rec.update(evaluate(t, driver, expected))
            rec["resolution"] = dict(stats)
            rec["policy"], rec["x_frac"] = args.policy, round(x_frac, 4)
        results.append(rec)
        print(f"  [{i:3d}/{len(tasks)}] {t['task_id']:22s} ran {rec['n_ran']}/{rec['n_candidates']}  "
              f"Eval1 {rec['eval1']!s:5s} Eval2 {rec['eval2']!s:5s}  "
              f"(ConfiBench {rec['confibench_eval1']:.2f}/{rec['confibench_eval2']:.2f})  {time.time()-t0:.0f}s",
              flush=True)
    save_cache()
    args.out.write_text(json.dumps(results, indent=1), encoding="utf-8")

    print(f"\n{len(results)} tasks in {time.time()-t_all:.0f}s")
    for ct in ("CMB", "SEQ", None):
        rs = [r for r in results if ct is None or r["circuit_type"] == ct]
        if not rs:
            continue
        n = len(rs)
        print(f"  {ct or 'ALL':4s} n={n:3d}   pipeline Eval1 {sum(r['eval1'] for r in rs)/n:.3f} "
              f"Eval2 {sum(r['eval2'] for r in rs)/n:.3f}   |   ConfiBench-4o Eval1 "
              f"{sum(r['confibench_eval1'] for r in rs)/n:.3f} Eval2 {sum(r['confibench_eval2'] for r in rs)/n:.3f}")


if __name__ == "__main__":
    main()
