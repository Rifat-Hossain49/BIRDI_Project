#!/usr/bin/env python3
"""Sealed evaluator: Golden RTL and Hidden Bank A against frozen suites.

Deliberately imports nothing from the search or generation modules. It reads
only frozen suite files, their hash manifest, the frozen checker sources, Golden
RTL and the hidden mutant bank.

Order enforced here:
  1. verify every suite hash against the manifest,
  2. load Golden RTL,
  3. load Hidden Bank A,
  4. run Golden with each suite, then the frozen checker -> GoldenPass,
  5. run each eligible hidden mutant with the same suite and the same checker,
  6. record verdicts.

A suite whose Golden run fails contributes zero to the primary metric, however
many mutants it rejects.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
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


def simulate(rtl: str, driver: str, workdir: Path, timeout: int = 60
             ) -> Tuple[Optional[str], str]:
    """Compile and run one RTL + driver pair, returning TBout.txt contents."""
    for f in workdir.glob("*"):
        if f.is_file():
            f.unlink()
    (workdir / "dut.v").write_text(rtl, encoding="utf-8")
    (workdir / "tb.v").write_text(driver, encoding="utf-8")
    comp = subprocess.run(["iverilog", "-g2012", "-o", "sim", "dut.v", "tb.v"],
                          cwd=workdir, capture_output=True, text=True, timeout=timeout)
    if comp.returncode != 0:
        return None, f"compile: {comp.stderr[:200]}"
    run = subprocess.run(["vvp", "sim"], cwd=workdir, capture_output=True,
                         text=True, timeout=timeout)
    out = workdir / "TBout.txt"
    if not out.is_file():
        return None, f"no TBout: {run.stderr[:200]}"
    return out.read_text(encoding="utf-8", errors="replace"), ""


def checker_verdict(checker_source: str, tbout: str) -> Tuple[Optional[list], str]:
    """Run the frozen checker verbatim over simulator output."""
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory(prefix="sealed_chk_") as td:
        Path(td, "TBout.txt").write_text(tbout, encoding="utf-8")
        try:
            os.chdir(td)
            ns: Dict[str, object] = {}
            src = checker_source
            cut = src.find('with open("TBout.txt"')
            defs = src if cut == -1 else src[:cut]
            with _muted():
                exec(compile(defs, "<frozen_checker>", "exec"), ns)
                vectors = ns["SignalTxt_to_dictlist"](tbout)
                failed = ns["check_dut"](vectors)
            return list(failed), ""
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"
        finally:
            os.chdir(cwd)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suites", required=True, type=Path)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--checkers", required=True, type=Path,
                    help="JSONL of task_id -> frozen checker source")
    ap.add_argument("--golden", required=True, type=Path)
    ap.add_argument("--mutants", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--max-mutants", type=int, default=10)
    args = ap.parse_args()

    manifest = json.loads(args.manifest.read_text())
    print("verifying frozen suite hashes")
    bad = []
    for key, meta in manifest["suites"].items():
        path = args.suites / meta["file"]
        if not path.is_file():
            bad.append((key, "missing"))
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != meta["sha256"]:
            bad.append((key, "hash mismatch"))
    if bad:
        raise SystemExit(f"suite integrity failure: {bad[:5]} ({len(bad)} total)")
    print(f"  {len(manifest['suites'])} suites verified")

    checkers = {}
    for line in args.checkers.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            checkers[r["task_id"]] = r["tb_py_checker"]

    golden = {}
    for line in args.golden.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            golden[r["task_id"]] = r["module_code"]

    mutants: Dict[str, list] = {}
    for line in args.mutants.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            ms = r.get("mutants") or r.get("mutant_codes") or []
            if isinstance(ms, dict):
                ms = list(ms.values())
            mutants[r["task_id"]] = ms[:args.max_mutants]
    print(f"  golden {len(golden)} tasks, hidden bank {len(mutants)} tasks")

    rows = []
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sealed_sim_") as td:
        work = Path(td)
        for i, (key, meta) in enumerate(sorted(manifest["suites"].items()), 1):
            tid, arm, budget, seed = (meta["task_id"], meta["arm"],
                                      meta["budget"], meta["seed"])
            driver = (args.suites / meta["file"]).read_text(encoding="utf-8")
            checker = checkers.get(tid)
            row = {"task_id": tid, "arm": arm, "budget": budget, "seed": seed,
                   "deployed_cycles": meta["deployed_cycles"],
                   "golden_pass": False, "golden_error": "",
                   "eligible_hidden": 0, "hidden_killed": 0,
                   "hidden_compile_fail": 0, "killed_ids": ""}
            if checker is None or tid not in golden:
                row["golden_error"] = "missing artefact"
                rows.append(row)
                continue

            tbout, err = simulate(golden[tid], driver, work)
            if tbout is None:
                row["golden_error"] = err
                rows.append(row)
                continue
            failed, cerr = checker_verdict(checker, tbout)
            if failed is None:
                row["golden_error"] = f"checker: {cerr}"
                rows.append(row)
                continue
            row["golden_pass"] = (len(failed) == 0)

            killed = []
            for mi, mrtl in enumerate(mutants.get(tid, [])):
                mt, merr = simulate(str(mrtl), driver, work)
                if mt is None:
                    row["hidden_compile_fail"] += 1
                    continue
                row["eligible_hidden"] += 1
                mfailed, _ = checker_verdict(checker, mt)
                if mfailed is None:
                    continue
                if len(mfailed) > 0:
                    killed.append(str(mi))
            row["hidden_killed"] = len(killed)
            row["killed_ids"] = ";".join(killed)
            rows.append(row)
            if i % 25 == 0:
                print(f"  {i}/{len(manifest['suites'])}", flush=True)

    with args.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {args.out} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
