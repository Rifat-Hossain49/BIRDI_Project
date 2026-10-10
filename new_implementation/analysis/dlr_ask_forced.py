#!/usr/bin/env python3
"""Pilot 1 rerun with budget forcing (DLR_PREREGISTRATION.md Amendment 1).

Same prompt, sampling and 8000-token reasoning cap as the registered thinking pass.
If the reasoning has not closed at the cap, it is closed for the model and the model
writes its answer. Records are written with pass "thinking" so analysis/dlr_score.py
scores them unchanged.

Sharded by task (--shard i --n-shards n) so the 151 questions fit two sessions.
Resumable: every answer is appended as it completes, keyed by qid.
"""
from __future__ import annotations

import argparse
import json
import threading
import time
import urllib.request
import zlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dlr_ask import ANS_RE, PROMPT, fmt, wait_healthy

FORCE_CLOSE = "\n\nI have reasoned enough; I will now give the final answer.\n</think>\n\n"
SAMPLING = {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0.0}
BUDGET, ANSWER_BUDGET = 8000, 1024


def post(base, path, body, timeout):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def complete(base, prompt, n_predict, seed):
    r = post(base, "/completion", {"prompt": prompt, "n_predict": n_predict, "seed": seed,
                                   "cache_prompt": True, **SAMPLING}, 4 * 3600)
    return r.get("content", ""), int(r.get("tokens_predicted", 0)), r.get("stop_type", "")


def shard_tasks(qs, shard, n_shards):
    """Greedy balance of tasks by question count; deterministic."""
    load, owner = [0] * n_shards, {}
    for task, c in sorted(Counter(q["task_id"] for q in qs).items(), key=lambda kv: (-kv[1], kv[0])):
        i = min(range(n_shards), key=lambda j: (load[j], j))
        owner[task] = i
        load[i] += c
    return [q for q in qs if owner[q["task_id"]] == shard]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--n-shards", type=int, default=1)
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--budget-hours", type=float, default=10.5)
    args = ap.parse_args()

    qs = [json.loads(l) for l in args.questions.read_text(encoding="utf-8").splitlines() if l.strip()]
    qs = shard_tasks(qs, args.shard, args.n_shards)
    if args.base == "dry":
        print(f"shard {args.shard}/{args.n_shards}: {len(qs)} questions, tasks",
              sorted({q['task_id'] for q in qs}))
        return
    if not wait_healthy(args.base, 1800):
        raise SystemExit("server never became healthy")
    done = set()
    if args.out.is_file():
        done = {json.loads(l)["qid"] for l in args.out.read_text(encoding="utf-8").splitlines() if l.strip()}
    jobs = [q for q in qs if q["qid"] not in done]
    print(f"{len(qs)} questions in shard, {len(jobs)} to answer", flush=True)

    lock = threading.Lock()
    fh = args.out.open("a", encoding="utf-8", newline="\n")
    t_start, n_done = time.time(), [0]

    def run(q):
        if (time.time() - t_start) / 3600 > args.budget_hours:
            return
        text = PROMPT.format(
            description=q["description"], header=q["header"],
            trunc=" (earlier steps omitted)" if q["history_truncated"] else "",
            history="\n".join(f"  step {i + 1}: {h}" for i, h in enumerate(q["history"]))
                    or "  (none — this is the first step)",
            inputs=q["cycle_inputs"] or "(no inputs)", a=fmt(q["option_a"]), b=fmt(q["option_b"]))
        seed = zlib.crc32(q["qid"].encode()) % 1000000
        t1 = time.time()
        try:
            prompt = post(args.base, "/apply-template", {
                "messages": [{"role": "user", "content": text}],
                "chat_template_kwargs": {"enable_thinking": True}}, 300)["prompt"]
            think, n1, stop1 = complete(args.base, prompt, BUDGET, seed)
            if "</think>" in think and stop1 != "limit":
                full, n, mode = think, n1, "natural"
            elif "</think>" in think:
                more, n2, _ = complete(args.base, prompt + think, ANSWER_BUDGET, seed + 1)
                full, n, mode = think + more, n1 + n2, "continued"
            else:
                forced = think + FORCE_CLOSE
                ans, n2, _ = complete(args.base, prompt + forced, ANSWER_BUDGET, seed + 1)
                full, n, mode = forced + ans, n1 + n2, "forced"
            final = full.split("</think>")[-1]
            m = ANS_RE.findall(final)
            rec = {"qid": q["qid"], "pass": "thinking", "answer": m[-1] if m else None, "mode": mode,
                   "n_tokens": n, "tail": final[-600:], "seconds": round(time.time() - t1, 1)}
        except Exception as exc:
            rec = {"qid": q["qid"], "pass": "thinking", "answer": None, "error": f"{type(exc).__name__}: {exc}"}
        with lock:
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            n_done[0] += 1
            if n_done[0] % 5 == 0:
                print(f"  {n_done[0]}/{len(jobs)} answered, {(time.time()-t_start)/3600:.2f}h", flush=True)

    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        for f in as_completed([ex.submit(run, q) for q in jobs]):
            f.result()
    fh.close()
    print(f"RESULT: {n_done[0]} answers in {(time.time()-t_start)/3600:.2f}h", flush=True)


if __name__ == "__main__":
    main()
