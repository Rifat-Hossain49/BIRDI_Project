#!/usr/bin/env python3
"""Score DLR pilot 1 exactly as DLR_PREREGISTRATION.md §5-6 specifies."""
from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
Q = ROOT / "analysis/dlr_questions.jsonl"


def cluster_boot(pairs_by_task, n=10000, seed=0):
    rng = random.Random(seed)
    tasks = sorted(pairs_by_task)
    diffs = []
    for _ in range(n):
        s = [pairs_by_task[rng.choice(tasks)] for _ in tasks]
        tot = sum(len(x) for x in s)
        diffs.append(sum(d for x in s for d in x) / tot)
    diffs.sort()
    return diffs[int(0.025 * n)], diffs[int(0.975 * n) - 1]


def main() -> None:
    answers = Path(sys.argv[1])
    qs = {json.loads(l)["qid"]: json.loads(l) for l in Q.read_text(encoding="utf-8").splitlines() if l.strip()}
    got = defaultdict(dict)
    for l in answers.read_text(encoding="utf-8").splitlines():
        if l.strip():
            r = json.loads(l)
            got[r["pass"]][r["qid"]] = r
    maj = {k: q["majority_pick"] == q["answer_key"] for k, q in qs.items()}
    print(f"questions: {len(qs)}   majority-vote accuracy: {sum(maj.values())/len(qs):.4f}\n")
    for p in ("direct", "thinking"):
        res = got.get(p, {})
        if not res:
            print(f"[{p}] no answers")
            continue
        answered = [k for k in qs if k in res]
        abst = sum(1 for k in answered if res[k].get("answer") not in ("A", "B"))
        pipe, strict, by_task = {}, {}, defaultdict(list)
        bucket = defaultdict(lambda: [0, 0, 0])
        for k in answered:
            q, a = qs[k], res[k].get("answer")
            pick = a if a in ("A", "B") else q["majority_pick"]
            pipe[k] = pick == q["answer_key"]
            strict[k] = a == q["answer_key"]
            by_task[q["task_id"]].append(int(pipe[k]) - int(maj[k]))
            b = bucket[(q["circuit_type"], q["bucket"])]
            b[0] += 1; b[1] += pipe[k]; b[2] += maj[k]
        n = len(answered)
        acc = sum(pipe.values()) / n
        macc = sum(maj[k] for k in answered) / n
        lo, hi = cluster_boot(by_task)
        print(f"[{p}] answered {n}/{len(qs)}   abstentions {abst}")
        print(f"   pipeline accuracy {acc:.4f}   strict {sum(strict.values())/n:.4f}   "
              f"majority on same {macc:.4f}")
        print(f"   delta vs majority {acc - macc:+.4f}   task-clustered 95% CI [{lo:+.4f}, {hi:+.4f}]")
        for (ct, bk), (m, ok, mj) in sorted(bucket.items()):
            print(f"      {ct} {bk:20s} n={m:3d}  DLR {ok/m:.3f}  majority {mj/m:.3f}")
        if p == "thinking":
            go = lo > 0 and acc >= 0.85 and n == len(qs)
            print(f"\n   DECISION (CI lower > 0 and accuracy >= 0.85, all questions answered): "
                  f"{'GO' if go else 'NO-GO'}" + ("" if n == len(qs) else "  [INCOMPLETE -- not a valid decision]"))


if __name__ == "__main__":
    main()
