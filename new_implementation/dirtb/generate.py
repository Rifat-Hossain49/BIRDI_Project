#!/usr/bin/env python3
"""Stage 3 candidate generation with budget forcing, against a running llama-server.

Measured on 168 dev samples: 26% of thinking-mode samples ran out of tokens before
closing their reasoning and produced nothing, and those consumed 46% of all tokens.
A plain lower cap does not help (an 8k cap would also cut 30% of samples that do
finish). Budget forcing does: reasoning gets at most B tokens; if it has not closed
by then it is closed for the model and the model writes its answer from what it has.
Every sample yields a design at bounded cost.

Reading paths (the generation prompt) are a parameter, so the same script serves the
direct path and, if pilot 2 passes, the checklist path. Only pipeline inputs are used
(task id, specification, header): golden, the official testbench and the mutants are
never read.

Resumable: every sample is appended as soon as it completes, keyed by
(task, path, sample index).
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from j1_generate import PROMPT as DIRECT_PROMPT, extract_rtl  # noqa: E402

FORCE_CLOSE = "\n\nI have reasoned enough; I will now write the final module.\n</think>\n\n"
SAMPLING = {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0.0}


def post(base, path, body, timeout):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def render(base, user_text):
    r = post(base, "/apply-template", {"messages": [{"role": "user", "content": user_text}],
                                       "chat_template_kwargs": {"enable_thinking": True}}, 300)
    return r["prompt"]


def complete(base, prompt, n_predict, seed, timeout=4 * 3600):
    body = {"prompt": prompt, "n_predict": n_predict, "seed": seed, "cache_prompt": True, **SAMPLING}
    r = post(base, "/completion", body, timeout)
    return r.get("content", ""), int(r.get("tokens_predicted", 0)), r.get("stop_type", "")


def generate_one(base, prompt_text, seed, budget, answer_budget):
    prompt = render(base, prompt_text)
    think, n1, stop1 = complete(base, prompt, budget, seed)
    if "</think>" in think:
        if stop1 == "limit":                               # answer itself got cut: let it finish
            more, n2, stop2 = complete(base, prompt + think, answer_budget, seed + 1)
            return think + more, n1 + n2, "continued", stop2
        return think, n1, "natural", stop1
    text = think + FORCE_CLOSE                            # budget forcing
    ans, n2, stop2 = complete(base, prompt + text, answer_budget, seed + 1)
    return text + ans, n1 + n2, "forced", stop2


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", type=Path, required=True, help="jsonl with task_id, description, header, circuit_type")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--path", action="append", required=True,
                    help="NAME=PROMPTFILE, or 'direct' for the J1 prompt; repeatable")
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--budget", type=int, default=8000, help="max reasoning tokens before forcing")
    ap.add_argument("--answer-budget", type=int, default=3000)
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--budget-hours", type=float, default=11.0)
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    args = ap.parse_args()

    paths = {}
    for spec in args.path:
        if spec == "direct":
            paths["direct"] = DIRECT_PROMPT
        else:
            name, f = spec.split("=", 1)
            paths[name] = Path(f).read_text(encoding="utf-8")
    tasks = [json.loads(l) for l in args.tasks.read_text(encoding="utf-8").splitlines() if l.strip()]
    done = set()
    if args.out.is_file():
        for l in args.out.read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l)
                done.add((r["task_id"], r["path"], r["sample_idx"]))
    jobs = [(t, p, j) for t in tasks for p in paths for j in range(args.samples)
            if (t["task_id"], p, j) not in done]
    print(f"{len(tasks)} tasks x {len(paths)} paths x {args.samples} = "
          f"{len(tasks) * len(paths) * args.samples} samples; {len(done)} done; {len(jobs)} to run", flush=True)

    t_start = time.time()
    lock = threading.Lock()
    fh = args.out.open("a", encoding="utf-8", newline="\n")
    stats = {"done": 0, "tokens": 0, "natural": 0, "forced": 0, "continued": 0, "module": 0, "errors": 0}

    def run(t, p, j):
        if (time.time() - t_start) / 3600 > args.budget_hours:
            return
        seed = (zlib.crc32(f"{t['task_id']}|{p}".encode()) % 100000) * 10 + j
        t1 = time.time()
        try:
            text, ntok, mode, stop = generate_one(args.base, paths[p].format(description=t["description"],
                                                                             header=t["header"]),
                                                  seed, args.budget, args.answer_budget)
            rtl = extract_rtl(text)
            rec = {"task_id": t["task_id"], "circuit_type": t.get("circuit_type", "?"), "path": p,
                   "sample_idx": j, "candidate_id": f"{p}_{t['task_id']}_{j}", "mode": mode,
                   "final_stop": stop, "n_tokens": ntok, "rtl": rtl,
                   "tail": text.split("</think>")[-1][-1200:], "seconds": round(time.time() - t1, 1)}
        except Exception as exc:
            with lock:
                stats["errors"] += 1
            print(f"  {t['task_id']}/{p}#{j} failed: {type(exc).__name__}: {exc}", flush=True)
            return
        with lock:
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            stats["done"] += 1
            stats["tokens"] += ntok
            stats[mode] += 1
            stats["module"] += bool(rtl)
            if stats["done"] % 10 == 0:
                el = time.time() - t_start
                print(f"  {stats['done']}/{len(jobs)} {stats} {stats['tokens']/max(1e-9,el):.0f} tok/s", flush=True)

    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        for f in as_completed([ex.submit(run, t, p, j) for t, p, j in jobs]):
            f.result()
    fh.close()
    print(f"RESULT: {stats} in {(time.time() - t_start) / 3600:.2f}h", flush=True)


if __name__ == "__main__":
    main()
