#!/usr/bin/env python3
"""Reference-accuracy pilot: is a two-family consensus a trustworthy reference?

For every ConfiBench-4o sub-testbench on the 33 tasks where both judge families
have designs: simulate golden and every judge design on ConfiBench's own driver,
parse each TBout row with ConfiBench's own `SignalTxt_to_dictlist`, and record the
rows. Inputs are driven identically for every DUT, so two rows are equal exactly
when the DUT outputs are equal.

Per row this later yields:
  golden row, family-A majority row, family-B majority row.
Consensus exists when both families have a majority and the two agree.

The numbers that decide the repair pipeline:
  precision  P(consensus == golden)   -- a wrong consensus would break Eval1
  coverage   share of rows with a consensus
both split by combinational / sequential.

Output: one json line per (sub-testbench, DUT) with its parsed rows or a status.
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


@contextlib.contextmanager
def _muted():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        yield


def simulate(rtl: str, tb_v: str, work: Path, timeout: int):
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
        subprocess.run(["vvp", "sim"], cwd=work, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "SIM_TIMEOUT", None
    out = work / "TBout.txt"
    if not out.is_file():
        return "NO_TBOUT", None
    return "RAN", out.read_text(encoding="utf-8", errors="replace")


def parse_rows(tbout: str, tb_py: str):
    cut = tb_py.find('with open("TBout.txt"')
    defs = tb_py if cut == -1 else tb_py[:cut]
    ns = {}
    with _muted():
        exec(compile(defs, "<confibench_checker>", "exec"), ns)
        rows = ns["SignalTxt_to_dictlist"](tbout)
    return [json.dumps({k: str(v).strip() for k, v in r.items()}, sort_keys=True) for r in rows]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subtbs", type=Path, required=True)
    ap.add_argument("--duts", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--timeout", type=int, default=60)
    args = ap.parse_args()

    subtbs = [json.loads(l) for l in args.subtbs.read_text(encoding="utf-8").splitlines() if l.strip()]
    duts = {}
    for l in args.duts.read_text(encoding="utf-8").splitlines():
        if l.strip():
            r = json.loads(l)
            duts.setdefault(r["task_id"], []).append(r)
    todo = sum(len(duts.get(s["task_id"], [])) for s in subtbs)
    print(f"{len(subtbs)} sub-testbenches, {todo} simulations", flush=True)

    t0 = time.time()
    done = 0
    status = {}
    with tempfile.TemporaryDirectory(prefix="ref_") as td, \
            args.out.open("w", encoding="utf-8", newline="\n") as fh:
        work = Path(td)
        for s in subtbs:
            for d in duts.get(s["task_id"], []):
                st, tbout = simulate(d["rtl"], s["tb_v"], work, args.timeout)
                rows = None
                if st == "RAN":
                    cwd = os.getcwd()
                    try:
                        os.chdir(work)
                        rows = parse_rows(tbout, s["tb_py"])
                    except Exception as exc:
                        st, rows = f"PARSE_ERROR:{type(exc).__name__}", None
                    finally:
                        os.chdir(cwd)
                key = st.split(":")[0]
                status[key] = status.get(key, 0) + 1
                fh.write(json.dumps({
                    "run": s["run"], "task_id": s["task_id"], "iter_id": s["iter_id"],
                    "circuit_type": s["circuit_type"], "eval1_pass": s["eval1_pass"],
                    "family": d["family"], "candidate_id": d["candidate_id"],
                    "status": st, "rows": rows}) + "\n")
                done += 1
                if done % 300 == 0:
                    print(f"  {done}/{todo}  {done / max(1e-9, time.time() - t0):.1f}/s  {status}",
                          flush=True)
    print(f"done: {done} simulations in {time.time() - t0:.0f}s  {status}")


if __name__ == "__main__":
    main()
