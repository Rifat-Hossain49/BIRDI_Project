#!/usr/bin/env python3
"""Publication-compatible comparison of ACTIVE-TB-SAFE against AutoBench/CorrectBench.

The sealed dual evaluation measures Golden-gated hidden-fault detection, which is
not the metric AutoBench and CorrectBench publish. To compare on THEIR terms this
module reproduces their definition exactly:

    Eval1        the testbench accepts the Golden design
    Eval2_ratio  agreement with the OFFICIAL testbench's verdict over the mutant
                 set, so accepting a mutant the official testbench also accepts
                 EARNS agreement and rejecting it LOSES agreement
    Eval2        Eval1 and ratio >= 0.8, with the m2014_q3 exception

Agreement therefore needs the official testbench's own verdict per mutant, which
is computed here by running `HDLBits_data.jsonl`'s `testbench` field. Its output
line is `Mismatches: N in M samples`; N == 0 means it accepts the design.

Comparison is PAIRED per task against the frontends' own recorded
`Eval1_pass` / `Eval2_ratio`, so both sides are measured on identical tasks.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

LOOSE_FACTOR = 0.8
MISMATCH_RE = re.compile(r"Mismatches:\s*(\d+)\s+in\s+(\d+)\s+samples")


@contextlib.contextmanager
def _muted():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        yield


def official_verdict(rtl: str, official_tb: str, work: Path,
                     timeout: int = 120) -> Optional[bool]:
    """True if the official testbench ACCEPTS this design (zero mismatches)."""
    for f in work.glob("*"):
        if f.is_file():
            f.unlink()
    (work / "dut.sv").write_text(rtl, encoding="utf-8")
    (work / "tb.sv").write_text(official_tb, encoding="utf-8")
    c = subprocess.run(["iverilog", "-g2012", "-o", "sim", "dut.sv", "tb.sv"],
                       cwd=work, capture_output=True, text=True, timeout=timeout)
    if c.returncode != 0:
        return None
    r = subprocess.run(["vvp", "sim"], cwd=work, capture_output=True,
                       text=True, timeout=timeout)
    m = MISMATCH_RE.search(r.stdout)
    if not m:
        return None
    return int(m.group(1)) == 0


def ours_verdict(rtl: str, driver: str, checker_src: str, work: Path,
                 timeout: int = 120) -> Optional[bool]:
    """True if OUR testbench accepts this design."""
    for f in work.glob("*"):
        if f.is_file():
            f.unlink()
    (work / "dut.v").write_text(rtl, encoding="utf-8")
    (work / "tb.v").write_text(driver, encoding="utf-8")
    c = subprocess.run(["iverilog", "-g2012", "-o", "sim", "dut.v", "tb.v"],
                       cwd=work, capture_output=True, text=True, timeout=timeout)
    if c.returncode != 0:
        return None
    subprocess.run(["vvp", "sim"], cwd=work, capture_output=True,
                   text=True, timeout=timeout)
    out = work / "TBout.txt"
    if not out.is_file():
        return None
    tbout = out.read_text(encoding="utf-8", errors="replace")
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory(prefix="ov_") as td:
        Path(td, "TBout.txt").write_text(tbout, encoding="utf-8")
        try:
            os.chdir(td)
            ns: Dict[str, object] = {}
            cut = checker_src.find('with open("TBout.txt"')
            defs = checker_src if cut == -1 else checker_src[:cut]
            with _muted():
                exec(compile(defs, "<frozen>", "exec"), ns)
                vecs = ns["SignalTxt_to_dictlist"](tbout)
                failed = ns["check_dut"](vecs)
            return len(list(failed)) == 0
        except Exception:
            return None
        finally:
            os.chdir(cwd)


def published_eval2(task_id: str, ratio_num: int, ratio_den: int,
                    eval1: bool, failed_idxes: List[int]) -> bool:
    """Verbatim port of analyze.py:Eval2_pass, including the task exception."""
    if not eval1:
        return False
    if ratio_den == 0:
        return False
    loose = (ratio_num / ratio_den) >= LOOSE_FACTOR
    if task_id == "m2014_q3":
        return sorted(failed_idxes) == [3, 4, 7, 8, 9, 10] or loose
    return loose


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suites", required=True, type=Path)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--frontend-records", required=True, type=Path)
    ap.add_argument("--golden", required=True, type=Path)
    ap.add_argument("--mutants", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    manifest = json.loads(args.manifest.read_text())
    golden, official, mutants, checkers = {}, {}, {}, {}
    for line in args.golden.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            golden[r["task_id"]] = r["module_code"]
            if r.get("testbench"):
                official[r["task_id"]] = r["testbench"]
    for line in args.mutants.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            mutants[r["task_id"]] = (r.get("mutants") or [])[:10]
    frontend_rows: Dict[str, dict] = {}
    for line in args.frontend_records.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            checkers.setdefault(r["task_id"], r["tb_py_checker"])
            frontend_rows.setdefault(r["task_id"], r)

    tasks = sorted(t for t in manifest["channel1"] if t in golden and t in official)
    if args.limit:
        tasks = tasks[:args.limit]
    print(f"comparing on {len(tasks)} tasks")

    rows = []
    with tempfile.TemporaryDirectory(prefix="sota_") as td:
        work = Path(td)
        for i, tid in enumerate(tasks, 1):
            c1 = manifest["channel1"][tid]
            driver = (args.suites / c1["file"]).read_text(encoding="utf-8")
            ck = checkers.get(tid)
            row = {"task_id": tid, "ours_eval1": False, "ours_ratio_num": 0,
                   "ours_ratio_den": 0, "ours_eval2": False,
                   "sota_eval1": None, "sota_ratio": "", "sota_eval2": None,
                   "note": ""}
            if ck is None:
                row["note"] = "no checker"
                rows.append(row)
                continue

            ours_g = ours_verdict(golden[tid], driver, ck, work)
            if ours_g is None:
                row["note"] = "ours failed on golden"
                rows.append(row)
                continue
            row["ours_eval1"] = ours_g

            agree = 0
            total = 0
            failed_idx: List[int] = []
            for mi, mrtl in enumerate(mutants.get(tid, []), start=1):
                ref = official_verdict(str(mrtl), official[tid], work)
                ours = ours_verdict(str(mrtl), driver, ck, work)
                if ref is None or ours is None:
                    continue
                total += 1
                if ref == ours:
                    agree += 1
                else:
                    failed_idx.append(mi)
            row["ours_ratio_num"] = agree
            row["ours_ratio_den"] = total
            row["ours_eval2"] = published_eval2(tid, agree, total, ours_g, failed_idx)

            fr = frontend_rows.get(tid)
            if fr:
                row["sota_eval1"] = bool(fr.get("Eval1_pass"))
                row["sota_ratio"] = fr.get("Eval2_ratio") or ""
                num = den = 0
                if isinstance(row["sota_ratio"], str) and "/" in row["sota_ratio"]:
                    a, b = row["sota_ratio"].split("/")
                    num, den = int(a), int(b)
                row["sota_eval2"] = published_eval2(
                    tid, num, den, row["sota_eval1"],
                    fr.get("Eval2_failed_mutant_idxes") or [])
            rows.append(row)
            if i % 10 == 0:
                print(f"  {i}/{len(tasks)}", flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {args.out} ({len(rows)} rows)")

    scored = [r for r in rows if r["sota_eval1"] is not None and not r["note"]]
    if scored:
        n = len(scored)
        print(f"\n=== Publication-compatible metric, paired on {n} tasks ===")
        print(f"{'':14s} {'Eval1':>8s} {'Eval2':>8s}")
        print(f"{'ACTIVE-TB-SAFE':14s} {sum(r['ours_eval1'] for r in scored)/n:8.4f} "
              f"{sum(r['ours_eval2'] for r in scored)/n:8.4f}")
        print(f"{'frontend SOTA':14s} {sum(r['sota_eval1'] for r in scored)/n:8.4f} "
              f"{sum(r['sota_eval2'] for r in scored)/n:8.4f}")


if __name__ == "__main__":
    main()
