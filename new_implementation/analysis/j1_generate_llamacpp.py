#!/usr/bin/env python3
"""J1 judge via llama.cpp (XJUDGE_PREREGISTRATION.md, Amendment 1).

Same model, prompt, sampling and extraction as j1_generate.py; only the engine
differs. Talks to a running `llama-server` over its OpenAI-compatible endpoint.

The server is started with `--reasoning-format none`, so the model's reasoning
stays inline as <think>...</think> and the SAME strict extractor applies: only a
module after a closed </think> counts.

Every sample is appended to the samples file the moment it completes, keyed by
(task, sample index), so a session that hits its time limit loses nothing and a
second session resumes where the first stopped.
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
from j1_generate import PROMPT, extract_rtl  # noqa: E402  (identical prompt + extractor)


def post(url: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def wait_healthy(base: str, limit_s: float) -> bool:
    t0 = time.time()
    while time.time() - t0 < limit_s:
        try:
            with urllib.request.urlopen(base + "/health", timeout=10) as r:
                if b"ok" in r.read():
                    return True
        except Exception:
            pass
        time.sleep(5)
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", type=Path, required=True)
    ap.add_argument("--samples-out", type=Path, required=True)
    ap.add_argument("--raw-out", type=Path, required=True)
    ap.add_argument("--log", type=Path, required=True)
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--max-new", type=int, default=15000)
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--budget-hours", type=float, default=8.5)
    ap.add_argument("--prompt-file", type=Path, default=None,
                    help="alternative prompt template with {description} and {header}; "
                         "defaults to j1_generate.PROMPT")
    ap.add_argument("--id-prefix", default="qwen35")
    args = ap.parse_args()
    prompt_tpl = args.prompt_file.read_text(encoding="utf-8") if args.prompt_file else PROMPT

    lock = threading.Lock()
    logf = args.log.open("a", encoding="utf-8")

    def log(msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        with lock:
            print(line, flush=True)
            logf.write(line + "\n")
            logf.flush()

    t_start = time.time()
    if not wait_healthy(args.base, 1800):
        log("RESULT: llama-server never became healthy")
        sys.exit(2)

    tasks = [json.loads(l) for l in args.tasks.read_text(encoding="utf-8").splitlines() if l.strip()]
    done = set()
    if args.samples_out.is_file():
        for l in args.samples_out.read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l)
                done.add((r["task_id"], r["sample_idx"]))
    jobs = [(t, j) for t in tasks for j in range(args.samples) if (t["task_id"], j) not in done]
    log(f"{len(tasks)} tasks x {args.samples} = {len(tasks) * args.samples} samples; "
        f"{len(done)} already done, {len(jobs)} to run, concurrency {args.concurrency}")

    t0 = time.time()
    smoke = post(args.base + "/v1/chat/completions", {
        "messages": [{"role": "user", "content": "Write a Verilog 2-input AND gate named top_module."}],
        "max_tokens": 200, "temperature": 0.6,
        "chat_template_kwargs": {"enable_thinking": False}}, 600)
    st = smoke.get("usage", {}).get("completion_tokens", 0)
    log(f"smoke test: {st} tokens in {time.time() - t0:.1f}s")

    out_f = args.samples_out.open("a", encoding="utf-8", newline="\n")
    stats = {"tokens": 0, "done": 0, "with_module": 0, "errors": 0}

    def run(t, j):
        if (time.time() - t_start) / 3600 > args.budget_hours:
            return None
        body = {"messages": [{"role": "user", "content": prompt_tpl.format(**t)}],
                "temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0.0,
                "max_tokens": args.max_new,
                # zlib.crc32, not hash(): str hashing is randomised per process, which
                # would give different seeds in a resumed second session.
                "seed": (zlib.crc32(t["task_id"].encode()) % 100000) * 10 + j,
                "chat_template_kwargs": {"enable_thinking": True}}
        t1 = time.time()
        try:
            r = post(args.base + "/v1/chat/completions", body, 4 * 3600)
        except Exception as exc:
            with lock:
                stats["errors"] += 1
            log(f"  {t['task_id']}#{j} request failed: {type(exc).__name__}: {exc}")
            return None
        ch = r["choices"][0]
        text = ch["message"].get("content") or ""
        rc = ch["message"].get("reasoning_content")
        if rc and "</think>" not in text:          # defensive: server split it anyway
            text = "<think>" + rc + "</think>" + text
        ntok = r.get("usage", {}).get("completion_tokens", 0)
        rtl = extract_rtl(text)
        rec = {"task_id": t["task_id"], "circuit_type": t["circuit_type"], "sample_idx": j,
               "candidate_id": f"{args.id_prefix}_{t['task_id']}_{j}",
               "finish_reason": ch.get("finish_reason"), "n_tokens": ntok,
               "thought_closed": "</think>" in text, "rtl": rtl,
               "tail": text.split("</think>")[-1][-1500:],
               "seconds": round(time.time() - t1, 1)}
        with lock:
            out_f.write(json.dumps(rec) + "\n")
            out_f.flush()
            stats["tokens"] += ntok
            stats["done"] += 1
            stats["with_module"] += bool(rtl)
            n = stats["done"]
        if n % 10 == 0:
            el = time.time() - t_start
            log(f"  {n}/{len(jobs)} samples, {stats['with_module']} with a module, "
                f"{stats['tokens']} tokens, {stats['tokens'] / max(1e-9, el):.0f} tok/s overall")
        return rec

    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = [ex.submit(run, t, j) for t, j in jobs]
        for _ in as_completed(futs):
            pass
    out_f.close()

    # Group every sample done so far (this session and earlier ones) by task.
    by_task = {}
    for l in args.samples_out.read_text(encoding="utf-8").splitlines():
        if l.strip():
            r = json.loads(l)
            by_task.setdefault(r["task_id"], {"task_id": r["task_id"],
                                              "circuit_type": r["circuit_type"],
                                              "load_config": {"engine": "llama.cpp",
                                                              "gguf": "Qwen3.5-27B-Q4_K_M"},
                                              "samples": []})["samples"].append(r)
    args.raw_out.write_text("".join(json.dumps(v) + "\n" for v in by_task.values()),
                            encoding="utf-8")
    complete = sum(1 for v in by_task.values() if len(v["samples"]) >= args.samples)
    log(f"RESULT: {stats['done']} samples this session, {stats['errors']} request errors; "
        f"{complete}/{len(tasks)} tasks complete; {stats['tokens']} tokens in "
        f"{(time.time() - t_start) / 3600:.2f}h")


if __name__ == "__main__":
    main()
