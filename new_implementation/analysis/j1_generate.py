#!/usr/bin/env python3
"""J1 judge: Qwen3.5-27B (GPTQ-Int4), zero-shot, thinking on, on Kaggle 2x T4.

Fixed by XJUDGE_PREREGISTRATION.md before any output was seen:
  * model      Qwen/Qwen3.5-27B-GPTQ-Int4, no fine-tuning of any kind
  * input      specification + module header only (what ConfiBench's generator saw)
  * samples    5 per task
  * sampling   Qwen's thinking-mode defaults: T=0.6, top_p=0.95, top_k=20, min_p=0

Operational safeguards, none of which change what is measured:
  * a smoke test before the full run, so an unsupported kernel fails in minutes;
  * a short ladder of load configurations, each failure logged in full -- the
    model is never silently swapped for a different one;
  * results written after every chunk, so a session timeout loses nothing;
  * a wall-clock guard that stops launching work before Kaggle's session limit.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import traceback
from pathlib import Path

MODEL = "Qwen/Qwen3.5-27B-GPTQ-Int4"
PROMPT = (
    "You are an expert digital designer. Implement the following specification "
    "as a synthesizable Verilog module.\n\n"
    "Specification:\n{description}\n\n"
    "Use exactly this module interface:\n{header}\n\n"
    "Return the complete module, from `module top_module` to `endmodule`, in a "
    "single ```verilog code block."
)

LOAD_LADDER = [
    dict(dtype="float16"),
    dict(dtype="float16", enforce_eager=True),
    dict(dtype="float16", enforce_eager=True, quantization="gptq"),
    dict(dtype="float16", enforce_eager=True, quantization="gptq", max_model_len=12288),
]


def extract_rtl(text: str):
    """The final answer's Verilog module, or None.

    Only text after a CLOSED `</think>` counts. A generation that ran out of
    tokens mid-reasoning has no final answer, and a module drafted inside the
    reasoning is a draft, not the model's answer -- counting it would quietly
    lower the judge's quality while inflating its sample count.
    """
    if "</think>" not in text:
        return None
    tail = text.split("</think>")[-1]
    for block in re.findall(r"```(?:verilog|systemverilog|sv|v)?\s*\n(.*?)```", tail, re.S):
        if "module" in block and "endmodule" in block:
            return block.strip() + "\n"
    m = re.search(r"(module\s+top_module\b.*?endmodule)", tail, re.S)
    return m.group(1).strip() + "\n" if m else None


def load_model(max_len: int, log):
    from vllm import LLM
    for i, cfg in enumerate(LOAD_LADDER):
        kw = dict(model=MODEL, tensor_parallel_size=2, max_model_len=max_len,
                  gpu_memory_utilization=0.92, trust_remote_code=True,
                  limit_mm_per_prompt={"image": 0, "video": 0})
        kw.update(cfg)
        log(f"load attempt {i + 1}/{len(LOAD_LADDER)}: {cfg}")
        try:
            t0 = time.time()
            llm = LLM(**kw)
            log(f"  loaded in {time.time() - t0:.0f}s")
            return llm, cfg
        except Exception:
            log("  FAILED:\n" + traceback.format_exc()[-3000:])
    return None, None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--log", type=Path, required=True)
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--max-model-len", type=int, default=16384)
    ap.add_argument("--max-new", type=int, default=15000)
    ap.add_argument("--chunk", type=int, default=6)
    ap.add_argument("--budget-hours", type=float, default=8.5)
    args = ap.parse_args()

    logf = args.log.open("a", encoding="utf-8")

    def log(msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        logf.write(line + "\n")
        logf.flush()

    t_start = time.time()
    tasks = [json.loads(l) for l in args.tasks.read_text(encoding="utf-8").splitlines() if l.strip()]
    done = set()
    if args.out.is_file():
        for l in args.out.read_text(encoding="utf-8").splitlines():
            if l.strip():
                done.add(json.loads(l)["task_id"])
    todo = [t for t in tasks if t["task_id"] not in done]
    log(f"{len(tasks)} tasks, {len(done)} already done, {len(todo)} to generate")

    llm, cfg = load_model(args.max_model_len, log)
    if llm is None:
        log("RESULT: model could not be loaded on this hardware under any configuration")
        sys.exit(2)

    from vllm import SamplingParams
    max_len = cfg.get("max_model_len", args.max_model_len)
    max_new = min(args.max_new, max_len - 1200)

    # Smoke test: one short completion, measured.
    t0 = time.time()
    smoke = llm.chat([[{"role": "user", "content": "Write a Verilog 2-input AND gate module named top_module."}]],
                     SamplingParams(temperature=0.6, top_p=0.95, top_k=20, max_tokens=256),
                     chat_template_kwargs={"enable_thinking": False}, use_tqdm=False)
    toks = len(smoke[0].outputs[0].token_ids)
    log(f"smoke test: {toks} tokens in {time.time() - t0:.1f}s "
        f"({toks / max(1e-9, time.time() - t0):.1f} tok/s single stream)")

    sp = SamplingParams(n=args.samples, temperature=0.6, top_p=0.95, top_k=20, min_p=0.0,
                        max_tokens=max_new, seed=20260911)
    total_tokens = 0
    with args.out.open("a", encoding="utf-8", newline="\n") as fh:
        for i in range(0, len(todo), args.chunk):
            elapsed_h = (time.time() - t_start) / 3600
            if elapsed_h > args.budget_hours:
                log(f"budget guard: {elapsed_h:.2f}h elapsed, stopping before chunk {i // args.chunk + 1}")
                break
            chunk = todo[i:i + args.chunk]
            msgs = [[{"role": "user", "content": PROMPT.format(**t)}] for t in chunk]
            t0 = time.time()
            outs = llm.chat(msgs, sp, chat_template_kwargs={"enable_thinking": True}, use_tqdm=False)
            dt = time.time() - t0
            ctoks = 0
            for t, o in zip(chunk, outs):
                samples = []
                for j, c in enumerate(o.outputs):
                    ctoks += len(c.token_ids)
                    samples.append({
                        "candidate_id": f"qwen35_{t['task_id']}_{j}",
                        "finish_reason": c.finish_reason,
                        "n_tokens": len(c.token_ids),
                        "thought_closed": "</think>" in c.text,
                        "rtl": extract_rtl(c.text),
                        "tail": c.text.split("</think>")[-1][-1500:],
                    })
                fh.write(json.dumps({"task_id": t["task_id"], "circuit_type": t["circuit_type"],
                                     "load_config": cfg, "samples": samples}) + "\n")
            fh.flush()
            total_tokens += ctoks
            got = sum(1 for o in outs for c in o.outputs if extract_rtl(c.text))
            log(f"chunk {i // args.chunk + 1}: {len(chunk)} tasks, {ctoks} tokens in {dt:.0f}s "
                f"({ctoks / max(1e-9, dt):.0f} tok/s), {got}/{len(chunk) * args.samples} with a module")
    log(f"RESULT: generated {total_tokens} tokens in {(time.time() - t_start) / 3600:.2f}h")


if __name__ == "__main__":
    main()
