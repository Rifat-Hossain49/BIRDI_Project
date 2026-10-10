#!/usr/bin/env python3
"""Phase-1 gate: does the formal witness pipeline actually work?

Runs every synthetic case, extracts a witness, replays it on Golden and mutant
under Icarus, and requires the replay to reproduce the divergence. Emits a funnel
that must account for 100% of calls.

Gate: >= 90% SAT-to-replay on supported cases. Nothing downstream is built until
this passes, because a formal channel that loses 71 of 84 witnesses produces
uninterpretable results.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from formal_witness import (Design, OUTCOMES, WitnessResult, parse_vlogtb,
                            run_bmc, tools_available, uses_internal_state_forcing)
from synthetic_cases import CASES, Case


def design_of(case: Case) -> Design:
    ins = {k: v for k, v in case.inputs.items() if k != case.reset}
    return Design(clock=case.clock, reset=case.reset,
                  reset_active=case.reset_active, reset_sync=case.reset_sync,
                  inputs=ins, outputs=case.outputs)


def emit_replay_tb(design: Design, seq: List[Dict[str, int]], dut: str) -> str:
    """A deployable testbench: drives only top-level pins, never internal state."""
    L = ["`timescale 1ns/1ps", "module tb;"]
    if design.sequential:
        L.append("  reg clk_i = 0;")
    if design.reset:
        L.append(f"  reg {design.reset};")
    for n, w in design.inputs.items():
        L.append(f"  reg [{w-1}:0] {n};" if w > 1 else f"  reg {n};")
    for n, w in design.outputs.items():
        L.append(f"  wire [{w-1}:0] {n};" if w > 1 else f"  wire {n};")
    pairs = []
    if design.sequential:
        pairs.append(f".{design.clock}(clk_i)")
    if design.reset:
        pairs.append(f".{design.reset}({design.reset})")
    pairs += [f".{n}({n})" for n in design.inputs]
    pairs += [f".{n}({n})" for n in design.outputs]
    L.append(f"  {dut} DUT ({', '.join(pairs)});")
    if design.sequential:
        L += ["  always #5 clk_i = ~clk_i;"]
    L += ['  integer f;', "  initial begin",
          '    f = $fopen("OUT.txt", "w");']
    for n in design.inputs:
        L.append(f"    {n} = 0;")
    if design.reset:
        # Mirror the miter's reset schedule exactly. The miter updates reset on
        # `f_half`, a HALF-cycle grid, so releasing reset only on whole-period
        # boundaries makes the harness strictly less expressive than the model
        # it is replaying: asynchronous and synchronous reset differ precisely
        # when reset moves between clock edges, and a whole-period harness can
        # never exhibit that. Reset is therefore released mid-cycle, two periods
        # in, matching `f_half >= 4`.
        L.append(f"    {design.reset} = 1'b{design.reset_active};")
        L.append("    #25;")
        L.append(f"    {design.reset} = 1'b{1 - design.reset_active};")
        L.append("    #5;")
    fmt = ", ".join(f"{n}=%0d" for n in design.outputs)
    args = ", ".join(design.outputs)
    for vec in seq:
        for n in design.inputs:
            L.append(f"    {n} = {vec.get(n, 0)};")
        L.append("    #10;" if design.sequential else "    #1;")
        L.append(f'    $fdisplay(f, "{fmt}", {args});')
    L += ["    $fclose(f);", "    $finish;", "  end", "endmodule", ""]
    return "\n".join(L)


def simulate(rtl: str, tb: str, workdir: Path, top: str) -> Optional[str]:
    for f in workdir.glob("*"):
        if f.is_file():
            f.unlink()
    (workdir / "dut.v").write_text(rtl.replace("top_module", top), encoding="utf-8")
    (workdir / "tb.v").write_text(tb, encoding="utf-8")
    c = subprocess.run(["iverilog", "-g2012", "-o", "sim", "dut.v", "tb.v"],
                       cwd=workdir, capture_output=True, text=True, timeout=60)
    if c.returncode != 0:
        return None
    subprocess.run(["vvp", "sim"], cwd=workdir, capture_output=True,
                   text=True, timeout=60)
    out = workdir / "OUT.txt"
    return out.read_text(encoding="utf-8", errors="replace") if out.is_file() else None


def evaluate(case: Case, bounds, timeout_s: float, workdir: Path) -> WitnessResult:
    design = design_of(case)
    last = WitnessResult("UNSAT_AT_BOUND", message="no bound produced SAT")
    for depth in bounds:
        status, vlogtb, secs, msg = run_bmc(case.golden, case.mutant, design,
                                            depth, timeout_s, workdir)
        if status in ("TIMEOUT", "UNSUPPORTED_CONSTRUCT"):
            return WitnessResult(status, depth, secs, message=msg)
        if status == "UNSAT":
            last = WitnessResult("UNSAT_AT_BOUND", depth, secs, message=msg)
            continue
        if status == "EXTRACTION_FAILED":
            return WitnessResult("EXTRACTION_FAILED", depth, secs, message=msg)

        dump = workdir.parent / "vlogtb_samples"
        dump.mkdir(exist_ok=True)
        (dump / f"{case.name}_b{depth}.v").write_text(vlogtb, encoding="utf-8")

        if uses_internal_state_forcing(vlogtb):
            return WitnessResult("INITIAL_STATE_ILLEGAL", depth, secs,
                                 message="witness forces internal state")
        seq = parse_vlogtb(vlogtb, design, depth)
        if not seq:
            # A design with no free inputs still has a witness: time itself.
            if not design.inputs:
                seq = [{} for _ in range(depth)]
            else:
                return WitnessResult("EXTRACTION_FAILED", depth, secs,
                                     message="no input steps parsed")

        tb = emit_replay_tb(design, seq, "golden_dut")
        g = simulate(case.golden, tb, workdir, "golden_dut")
        m = simulate(case.mutant, emit_replay_tb(design, seq, "mutant_dut"),
                     workdir, "mutant_dut")
        if g is None or m is None:
            return WitnessResult("REPLAY_ERROR", depth, secs,
                                 message="witness testbench failed to simulate")
        if g == m:
            return WitnessResult("REPLAY_NO_DIVERGENCE", depth, secs,
                                 sequence=seq, message="outputs agreed on replay")

        # Minimise: drop leading cycles while divergence survives.
        best = seq
        for start in range(1, len(seq)):
            trial = seq[start:]
            gg = simulate(case.golden, emit_replay_tb(design, trial, "golden_dut"),
                          workdir, "golden_dut")
            mm = simulate(case.mutant, emit_replay_tb(design, trial, "mutant_dut"),
                          workdir, "mutant_dut")
            if gg is not None and mm is not None and gg != mm:
                best = trial
            else:
                break
        return WitnessResult("ACCEPTED", depth, secs, sequence=best,
                             minimised_from=len(seq))
    return last


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bounds", default="4,8,16,32")
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--out", type=Path, default=Path("witness_funnel.csv"))
    args = ap.parse_args()

    ok, msg = tools_available()
    if not ok:
        print(f"TOOLING_MISSING: {msg}")
        rows = [{"case": c.name, "family": c.family, "expect": c.expect,
                 "outcome": "TOOLING_MISSING", "bound": 0, "seconds": 0.0,
                 "witness_len": 0, "message": msg} for c in CASES]
    else:
        bounds = [int(x) for x in args.bounds.split(",")]
        rows = []
        outdir = args.out.parent
        (outdir / "vlogtb_samples").mkdir(parents=True, exist_ok=True)
        work = outdir / "wit_work"
        work.mkdir(parents=True, exist_ok=True)
        if True:
            for case in CASES:
                r = evaluate(case, bounds, args.timeout, work)
                rows.append({"case": case.name, "family": case.family,
                             "expect": case.expect, "outcome": r.outcome,
                             "bound": r.bound, "seconds": round(r.solver_seconds, 2),
                             "witness_len": len(r.sequence), "message": r.message[:160]})
                print(f"  {case.name:20s} {r.outcome:24s} bound={r.bound:3d} "
                      f"len={len(r.sequence):3d} {r.message[:60]}", flush=True)

    with args.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    counts = collections.Counter(r["outcome"] for r in rows)
    total = len(rows)
    print("\n=== Funnel (must account for 100% of calls) ===")
    for k in OUTCOMES:
        if counts[k]:
            print(f"  {k:26s} {counts[k]:3d}  ({counts[k]/total:5.1%})")
    accounted = sum(counts[k] for k in OUTCOMES)
    print(f"  accounted: {accounted}/{total}")

    supported = total - counts["UNSUPPORTED_CONSTRUCT"] - counts["TOOLING_MISSING"]
    rate = counts["ACCEPTED"] / supported if supported else 0.0
    print(f"\nSAT-to-replay on supported cases: {counts['ACCEPTED']}/{supported} = {rate:.1%}")
    print(f"GATE (>=90%): {'PASS' if rate >= 0.9 else 'FAIL'}")


if __name__ == "__main__":
    main()
