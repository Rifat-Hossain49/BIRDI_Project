#!/usr/bin/env python3
"""Ask the localized-resolution questions against a running llama-server.

Implements DLR_PREREGISTRATION.md §4. Resumable: every answer is appended as it
completes, keyed by (qid, pass), so a timed-out session loses nothing.
"""
from __future__ import annotations

import argparse
import json
import re
import threading
import time
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

PROMPT = """You are verifying a digital hardware design against its specification.

Specification:
{description}

Module interface:
{header}

A testbench drives this module and samples its signals once per step. These are the \
steps observed so far; every candidate implementation agreed on all of them{trunc}:
{history}

At the next step the inputs are: {inputs}

Two candidate implementations disagree about the outputs at this step:
Option A: {a}
Option B: {b}

According to the specification, which option is correct? Reason carefully about the \
circuit's behaviour and state, then end your reply with exactly one final line: \
ANSWER: A  or  ANSWER: B"""

ANS_RE = re.compile(r"ANSWER:\s*([AB])\b")


def post(url, body, timeout):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def wait_healthy(base, limit):
    t0 = time.time()
    while time.time() - t0 < limit:
        try:
            with urllib.request.urlopen(base + "/health", timeout=10) as r:
                if b"ok" in r.read():
                    return True
        except Exception:
            pass
        time.sleep(5)
    return False


def fmt(opt: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in opt.items())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--budget-hours", type=float, default=10.0)
    args = ap.parse_args()

    if not wait_healthy(args.base, 1800):
        raise SystemExit("server never became healthy")
    qs = [json.loads(l) for l in args.questions.read_text(encoding="utf-8").splitlines() if l.strip()]
    done = set()
    if args.out.is_file():
        for l in args.out.read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l)
                done.add((r["qid"], r["pass"]))
    # direct pass first: it is cheap and guarantees a complete secondary result
    jobs = [(q, p) for p in ("direct", "thinking") for q in qs if (q["qid"], p) not in done]
    print(f"{len(qs)} questions, {len(jobs)} answers to generate", flush=True)

    lock = threading.Lock()
    fh = args.out.open("a", encoding="utf-8", newline="\n")
    t_start = time.time()
    n_done = [0]

    def run(q, p):
        if (time.time() - t_start) / 3600 > args.budget_hours:
            return
        text = PROMPT.format(
            description=q["description"], header=q["header"],
            trunc=" (earlier steps omitted)" if q["history_truncated"] else "",
            history="\n".join(f"  step {i + 1}: {h}" for i, h in enumerate(q["history"]))
                    or "  (none — this is the first step)",
            inputs=q["cycle_inputs"] or "(no inputs)", a=fmt(q["option_a"]), b=fmt(q["option_b"]))
        body = {"messages": [{"role": "user", "content": text}],
                "temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0.0,
                "max_tokens": 8000 if p == "thinking" else 256,
                "seed": zlib.crc32(q["qid"].encode()) % 1000000,
                "chat_template_kwargs": {"enable_thinking": p == "thinking"}}
        t1 = time.time()
        try:
            r = post(args.base + "/v1/chat/completions", body, 3 * 3600)
            ch = r["choices"][0]
            content = ch["message"].get("content") or ""
            final = content.split("</think>")[-1]
            m = ANS_RE.findall(final)
            ans = m[-1] if m else None
            rec = {"qid": q["qid"], "pass": p, "answer": ans,
                   "finish_reason": ch.get("finish_reason"),
                   "n_tokens": r.get("usage", {}).get("completion_tokens", 0),
                   "tail": final[-600:], "seconds": round(time.time() - t1, 1)}
        except Exception as exc:
            rec = {"qid": q["qid"], "pass": p, "answer": None, "error": f"{type(exc).__name__}: {exc}"}
        with lock:
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            n_done[0] += 1
            if n_done[0] % 10 == 0:
                print(f"  {n_done[0]}/{len(jobs)} answered, {(time.time()-t_start)/3600:.2f}h", flush=True)

    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        for f in as_completed([ex.submit(run, q, p) for q, p in jobs]):
            f.result()
    fh.close()
    print(f"RESULT: {n_done[0]} answers in {(time.time()-t_start)/3600:.2f}h", flush=True)


if __name__ == "__main__":
    main()
