#!/usr/bin/env python3
"""Localized-resolution pilot, question builder (DEVELOPMENT set: ConfiBench-4o).

Hypothesis under test: when a <=30B model's own candidate designs disagree, asking
it ONE pointed question at the first point of divergence resolves the disagreement
more accurately than majority voting over the candidates.

Sequential errors are early and propagating (first divergence ~16% into a trace,
58% corrupt most later rows), so one correctly resolved local decision can repair
a whole scenario. A small model should answer a local question -- "at this cycle,
given this observed history, is the output X or Y?" -- better than it writes a
globally correct design.

For every scenario where the candidates disagree, this builds:
  spec (description + header), the agreed history up to the first divergence, the
  inputs at that cycle, and the two largest candidate classes' outputs there.
Golden's output at that row is stored separately as the answer key and is never
put in the prompt. Identical questions (same task, history and options) are
merged, so repeats across ConfiBench runs are asked once.
"""
from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROWS = ROOT / "kaggle_runs/ref_pilot/ref_rows.jsonl"
TASKS = ROOT / "analysis/j1_tasks.jsonl"
OUT = ROOT / "analysis/dlr_questions.jsonl"
MAX_HISTORY = 24
CAP_PER_TASK = 20
SEED = 20260913


def fmt_row(d: dict, keys) -> str:
    return ", ".join(f"{k}={d.get(k, '?')}" for k in keys)


def build(gold, fam, task, ct, spec, bank, stats):
    if gold is None or len(fam) < 3:
        return
    scen = defaultdict(list)
    for i, g in enumerate(gold):
        try:
            scen[json.loads(g).get("scenario", "?")].append(i)
        except Exception:
            scen["?"].append(i)
    n = len(fam)
    for sc, idx in scen.items():
        traces = [tuple(r[i] if i < len(r) else None for i in idx) for r in fam]
        gt = tuple(gold[i] for i in idx)
        c = Counter(traces)
        if len(c) < 2:
            continue                                   # no disagreement to localize
        (ta, na), (tb, nb) = c.most_common(2)
        top, cnt = c.most_common(1)[0]
        bucket = ("majority-correct" if cnt * 2 > n and top == gt else
                  "select-recoverable" if gt in c else "none-correct")
        k = next((j for j in range(len(idx)) if ta[j] != tb[j]), None)
        if k is None or ta[k] is None or tb[k] is None:
            continue
        ra, rb, rg = json.loads(ta[k]), json.loads(tb[k]), json.loads(gt[k])
        keys = [x for x in rg if x != "scenario"]
        out_keys = sorted(x for x in keys if ra.get(x) != rb.get(x))
        in_keys = [x for x in keys if x not in out_keys]
        if not out_keys:
            continue
        hist = [json.loads(ta[j]) for j in range(max(0, k - MAX_HISTORY), k)]
        opt_a = {x: ra.get(x) for x in out_keys}
        opt_b = {x: rb.get(x) for x in out_keys}
        truth = {x: rg.get(x) for x in out_keys}
        answer = "A" if truth == opt_a else "B" if truth == opt_b else "neither"
        sig = json.dumps([task, [fmt_row(h, keys) for h in hist],
                          fmt_row(rg, in_keys), opt_a, opt_b], sort_keys=True)
        if sig in bank:
            bank[sig]["weight"] += 1
            continue
        stats[(ct, bucket)] += 1
        bank[sig] = {
            "task_id": task, "circuit_type": ct, "bucket": bucket,
            "description": spec["description"], "header": spec["header"],
            "history": [fmt_row(h, keys) for h in hist],
            "history_truncated": k > MAX_HISTORY,
            "cycle_inputs": fmt_row(rg, in_keys),
            "option_a": opt_a, "option_b": opt_b,
            # majority baseline: the larger class's value at the divergence
            "majority_pick": "A",
            "class_sizes": [na, nb, n],
            "answer_key": answer, "weight": 1,
        }


def main() -> None:
    specs = {json.loads(l)["task_id"]: json.loads(l)
             for l in TASKS.read_text(encoding="utf-8").splitlines() if l.strip()}
    bank, stats = {}, Counter()
    cur, gold, fam, task, ct = None, None, [], None, "?"
    with ROWS.open(encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            key = (r["run"], r["task_id"], r["iter_id"])
            if key != cur:
                if cur is not None and task in specs:
                    build(gold, fam, task, ct, specs[task], bank, stats)
                cur, gold, fam, task, ct = key, None, [], r["task_id"], r["circuit_type"]
            if r["status"] != "RAN" or r["rows"] is None:
                continue
            if r["family"] == "golden":
                gold = r["rows"]
            elif r["family"].startswith("A"):
                fam.append(r["rows"])
        if cur is not None and task in specs:
            build(gold, fam, task, ct, specs[task], bank, stats)

    # Keep only questions with a gradable answer, cap per task so no single task
    # dominates, and sample reproducibly.
    rng = random.Random(SEED)
    by_task = defaultdict(list)
    for q in bank.values():
        if q["answer_key"] in ("A", "B"):
            by_task[q["task_id"]].append(q)
    chosen = []
    for t, qs in sorted(by_task.items()):
        rng.shuffle(qs)
        chosen += qs[:CAP_PER_TASK]
    for i, q in enumerate(chosen):
        q["qid"] = f"q{i:04d}"
        if rng.random() < 0.5:                           # randomize option order
            q["option_a"], q["option_b"] = q["option_b"], q["option_a"]
            q["answer_key"] = "B" if q["answer_key"] == "A" else "A"
            q["majority_pick"] = "B"
    OUT.write_text("".join(json.dumps(q) + "\n" for q in chosen), encoding="utf-8")

    print(f"unique divergence questions: {len(bank)}   gradable: {sum(len(v) for v in by_task.values())}"
          f"   chosen (<= {CAP_PER_TASK}/task): {len(chosen)} over {len(by_task)} tasks")
    mix = Counter((q["circuit_type"], q["bucket"]) for q in chosen)
    for k, v in sorted(mix.items()):
        print(f"   {k[0]} {k[1]:20s} {v}")
    maj = sum(1 for q in chosen if q["majority_pick"] == q["answer_key"])
    print(f"majority-vote accuracy on the chosen questions: {maj}/{len(chosen)} = {maj/max(1,len(chosen)):.3f}")


if __name__ == "__main__":
    main()
