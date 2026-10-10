#!/usr/bin/env python3
"""Run a judge's RTLs on ConfiBench's masked sub-testbenches.

For every (sub-testbench, judge RTL) pair: compile the judge RTL against
ConfiBench's own driver, simulate, and run ConfiBench's own Python checker. The
output is the checker's failure list, read exactly as ConfiBench reads it
(`TB4_eval.py:TC_pass_from_TC_out`), so a judge RTL is judged by the same
machinery that judged GPT-4o's RTLs.

A judge RTL that fails to compile, times out or crashes the checker is recorded
as NOT RUN and later excluded from p(s) -- it is neither a vote for nor against
the checker.

Output: one json line per pair,
  {variant, run, task_id, iter_id, candidate_id, family, status, failed}
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional


@contextlib.contextmanager
def _muted():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        yield


def scenario_ids(failed) -> List[int]:
    """ConfiBench's own normalisation: keep the digits of each reported id."""
    out = []
    for s in failed:
        d = "".join(ch for ch in str(s) if ch.isdigit())
        if d:
            out.append(int(d))
    return sorted(set(out))


def run_one(rtl: str, tb_v: str, tb_py: str, work: Path, timeout: int
            ) -> (str, Optional[List[int]]):
    for f in work.glob("*"):
        if f.is_file():
            f.unlink()
    (work / "dut.v").write_text(rtl, encoding="utf-8")
    (work / "tb.v").write_text(tb_v, encoding="utf-8")
    try:
        c = subprocess.run(["iverilog", "-g2012", "-o", "sim", "tb.v", "dut.v"],
                           cwd=work, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "COMPILE_TIMEOUT", None
    if c.returncode != 0:
        return "COMPILE_ERROR", None
    try:
        subprocess.run(["vvp", "sim"], cwd=work, capture_output=True,
                       text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "SIM_TIMEOUT", None
    out = work / "TBout.txt"
    if not out.is_file():
        return "NO_TBOUT", None
    txt = out.read_text(encoding="utf-8", errors="replace")
    cut = tb_py.find('with open("TBout.txt"')
    defs = tb_py if cut == -1 else tb_py[:cut]
    cwd = os.getcwd()
    try:
        os.chdir(work)
        ns: Dict[str, object] = {}
        with _muted():
            exec(compile(defs, "<confibench_checker>", "exec"), ns)
            vecs = ns["SignalTxt_to_dictlist"](txt)
            failed = ns["check_dut"](vecs)
        return "RAN", scenario_ids(failed)
    except Exception as exc:
        return f"CHECKER_ERROR:{type(exc).__name__}", None
    finally:
        os.chdir(cwd)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subtbs", type=Path, required=True)
    ap.add_argument("--candidates", type=Path, required=True,
                    help="jsonl of {task_id, candidate_id, family, rtl}")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--timeout", type=int, default=60)
    args = ap.parse_args()

    subtbs = [json.loads(l) for l in args.subtbs.read_text(encoding="utf-8").splitlines() if l.strip()]
    cands: Dict[str, List[dict]] = {}
    for l in args.candidates.read_text(encoding="utf-8").splitlines():
        if l.strip():
            r = json.loads(l)
            cands.setdefault(r["task_id"], []).append(r)
    todo = sum(len(cands.get(s["task_id"], [])) for s in subtbs)
    print(f"{len(subtbs)} sub-testbenches, {todo} simulations", flush=True)

    done = 0
    t0 = time.time()
    status_count: Dict[str, int] = {}
    with tempfile.TemporaryDirectory(prefix="xj_") as td, \
            args.out.open("w", encoding="utf-8", newline="\n") as fh:
        work = Path(td)
        for s in subtbs:
            for c in cands.get(s["task_id"], []):
                st, failed = run_one(c["rtl"], s["tb_v"], s["tb_py"], work, args.timeout)
                status_count[st.split(":")[0]] = status_count.get(st.split(":")[0], 0) + 1
                fh.write(json.dumps({
                    "variant": s["variant"], "run": s["run"], "task_id": s["task_id"],
                    "iter_id": s["iter_id"], "candidate_id": c["candidate_id"],
                    "family": c.get("family", ""), "status": st, "failed": failed}) + "\n")
                done += 1
                if done % 200 == 0:
                    rate = done / max(1e-9, time.time() - t0)
                    print(f"  {done}/{todo}  {rate:.1f}/s  {status_count}", flush=True)
    print(f"done: {done} simulations in {time.time()-t0:.0f}s  {status_count}")


if __name__ == "__main__":
    main()
