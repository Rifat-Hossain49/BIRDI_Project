#!/usr/bin/env python3
"""Turn J1's raw generations into judge candidates, and grade each one.

Two outputs:
  j1_candidates.jsonl  every sample that produced a module, in the format
                       xjudge_run.py consumes;
  j1_official.jsonl    each candidate's verdict from the OFFICIAL VerilogEval
                       testbench -- used only for the pre-registered §6
                       diagnostic (is a failure one of judge accuracy?), never by
                       the masking rule itself.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

MISMATCH_RE = re.compile(r"Mismatches:\s*(\d+)\s+in\s+(\d+)\s+samples")


def official(rtl: str, tb: str, work: Path, timeout: int = 60):
    for f in work.glob("*"):
        if f.is_file():
            f.unlink()
    (work / "dut.sv").write_text(rtl, encoding="utf-8")
    (work / "tb.sv").write_text(tb, encoding="utf-8")
    try:
        c = subprocess.run(["iverilog", "-g2012", "-o", "sim", "tb.sv", "dut.sv"],
                           cwd=work, capture_output=True, text=True, timeout=timeout)
        if c.returncode != 0:
            return "COMPILE_ERROR"
        r = subprocess.run(["vvp", "sim"], cwd=work, capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    m = MISMATCH_RE.search(r.stdout)
    if not m:
        return "NO_VERDICT"
    return "PASS" if int(m.group(1)) == 0 else "FAIL"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, required=True)
    ap.add_argument("--golden", type=Path, required=True)
    ap.add_argument("--candidates", type=Path, required=True)
    ap.add_argument("--official", type=Path, required=True)
    args = ap.parse_args()

    tbs = {}
    for l in args.golden.read_text(encoding="utf-8").splitlines():
        if l.strip():
            r = json.loads(l)
            tbs[r["task_id"]] = r["testbench"]

    stats = Counter()
    by_type = Counter()
    cands, grades = [], []
    with tempfile.TemporaryDirectory(prefix="j1p_") as td:
        work = Path(td)
        for l in args.raw.read_text(encoding="utf-8").splitlines():
            if not l.strip():
                continue
            r = json.loads(l)
            for s in r["samples"]:
                stats["samples"] += 1
                stats[f"finish={s['finish_reason']}"] += 1
                if not s["rtl"]:
                    stats["no module extracted"] += 1
                    continue
                cands.append({"task_id": r["task_id"], "candidate_id": s["candidate_id"],
                              "family": "qwen35", "model": "Qwen/Qwen3.5-27B-GPTQ-Int4",
                              "rtl": s["rtl"]})
                v = official(s["rtl"], tbs.get(r["task_id"], ""), work)
                stats[f"official {v}"] += 1
                by_type[(r["circuit_type"], v)] += 1
                grades.append({"task_id": r["task_id"], "candidate_id": s["candidate_id"],
                               "circuit_type": r["circuit_type"], "official": v})

    args.candidates.write_text("".join(json.dumps(c) + "\n" for c in cands), encoding="utf-8")
    args.official.write_text("".join(json.dumps(g) + "\n" for g in grades), encoding="utf-8")
    print(json.dumps(dict(stats), indent=1))
    for ct in ("CMB", "SEQ"):
        tot = sum(v for (c, _), v in by_type.items() if c == ct)
        ok = by_type.get((ct, "PASS"), 0)
        if tot:
            print(f"{ct}: {ok}/{tot} candidates pass the official testbench ({ok/tot:.1%})")


if __name__ == "__main__":
    main()
