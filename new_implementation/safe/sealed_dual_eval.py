#!/usr/bin/env python3
"""Sealed dual-channel evaluation for ACTIVE-TB-SAFE.

Runs both channels against Golden RTL and Hidden Bank A through the frozen
checker, and reports them separately. Imports no search or synthesis code.

Three questions, in order of importance:

  1. Does Channel 1 still behave exactly as the frozen generator's own stimulus?
     If not, non-regression is broken and nothing else matters.
  2. Does Channel 2 false-alarm on Golden? A shadow test that rejects a correct
     design is noise, and a warning channel that cries wolf is worse than none.
  3. Does Channel 2 catch hidden faults Channel 1 misses? That is the entire
     value proposition.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@contextlib.contextmanager
def _muted():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        yield


def simulate(rtl: str, driver: str, work: Path, timeout: int = 90) -> Tuple[Optional[str], str]:
    for f in work.glob("*"):
        if f.is_file():
            f.unlink()
    (work / "dut.v").write_text(rtl, encoding="utf-8")
    (work / "tb.v").write_text(driver, encoding="utf-8")
    c = subprocess.run(["iverilog", "-g2012", "-o", "sim", "dut.v", "tb.v"],
                       cwd=work, capture_output=True, text=True, timeout=timeout)
    if c.returncode != 0:
        return None, f"compile: {c.stderr[:160]}"
    subprocess.run(["vvp", "sim"], cwd=work, capture_output=True,
                   text=True, timeout=timeout)
    out = work / "TBout.txt"
    return (out.read_text(encoding="utf-8", errors="replace"), "") if out.is_file() \
        else (None, "no TBout")


def verdict(checker_src: str, tbout: str) -> Tuple[Optional[list], str]:
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory(prefix="dual_") as td:
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
            return list(failed), ""
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"
        finally:
            os.chdir(cwd)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suites", required=True, type=Path)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--checkers", required=True, type=Path)
    ap.add_argument("--golden", required=True, type=Path)
    ap.add_argument("--mutants", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    manifest = json.loads(args.manifest.read_text())
    checkers, golden, mutants = {}, {}, {}
    for line in args.checkers.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            checkers[r["task_id"]] = r["tb_py_checker"]
    for line in args.golden.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            golden[r["task_id"]] = r["module_code"]
    for line in args.mutants.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            mutants[r["task_id"]] = (r.get("mutants") or [])[:10]

    rows = []
    with tempfile.TemporaryDirectory(prefix="dualsim_") as td:
        work = Path(td)
        tasks = sorted(set(manifest["channel1"]) | set(manifest["channel2"]))
        for i, tid in enumerate(tasks, 1):
            ck = checkers.get(tid)
            if ck is None or tid not in golden:
                continue
            for channel in ("channel1", "channel2"):
                meta = manifest[channel].get(tid)
                row = {"task_id": tid, "channel": channel,
                       "cycles": 0, "golden_pass": False, "golden_error": "",
                       "eligible_hidden": 0, "hidden_killed": 0, "killed_ids": ""}
                if not meta:
                    rows.append(row)
                    continue
                row["cycles"] = meta["cycles"]
                drv = (args.suites / meta["file"]).read_text(encoding="utf-8")

                tb, err = simulate(golden[tid], drv, work)
                if tb is None:
                    row["golden_error"] = err
                    rows.append(row)
                    continue
                failed, cerr = verdict(ck, tb)
                if failed is None:
                    row["golden_error"] = f"checker: {cerr}"
                    rows.append(row)
                    continue
                row["golden_pass"] = (len(failed) == 0)

                killed = []
                for mi, mrtl in enumerate(mutants.get(tid, [])):
                    mt, _ = simulate(str(mrtl), drv, work)
                    if mt is None:
                        continue
                    row["eligible_hidden"] += 1
                    mf, _ = verdict(ck, mt)
                    if mf is not None and len(mf) > 0:
                        killed.append(str(mi))
                row["hidden_killed"] = len(killed)
                row["killed_ids"] = ";".join(killed)
                rows.append(row)
            print(f"  {i}/{len(tasks)} {tid}", flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {args.out} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
