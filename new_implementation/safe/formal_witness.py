#!/usr/bin/env python3
"""Differential BMC witness synthesis with a complete, mutually exclusive funnel.

The predecessor produced 84 SAT and only 13 accepted witnesses, and its report
explained just 24 of the 71 losses. Nothing here is trusted until the funnel
accounts for every call, so each outcome below is exclusive and every path
assigns exactly one.

Two deliberate departures from the predecessor:

  * Witnesses are extracted from Yosys's **native** witness export
    (`--dump-yw` / `--dump-vlogtb`) rather than by parsing a VCD and matching
    signal names by suffix. Suffix matching guessed at identity; the native
    export names signals the way the miter declared them.
  * A witness that depends on forcing internal registers is **rejected**, not
    repaired. Only input-driven witnesses from a legal initial condition are
    deployable, so anything else is `INITIAL_STATE_ILLEGAL`.

Cycle accounting: the miter drives the clock, so `f_step` counts half-cycles.
The reset window and the assertion guard are both expressed in half-steps here
to remove the off-by-one the predecessor's mixed units invited.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Mutually exclusive outcomes. Every call assigns exactly one.
OUTCOMES = [
    "ACCEPTED",                 # witness replayed and reproduced divergence
    "UNSAT_AT_BOUND",           # no counterexample within the bound; NOT equivalence
    "TIMEOUT",
    "UNSUPPORTED_CONSTRUCT",    # miter or synthesis rejected the design
    "EXTRACTION_FAILED",        # SAT but no witness could be read out
    "INITIAL_STATE_ILLEGAL",    # witness needs forced internal state
    "REPLAY_NO_DIVERGENCE",     # witness replayed but outputs agreed
    "REPLAY_ERROR",             # simulation of the witness failed
    "TOOLING_MISSING",
]


@dataclass
class WitnessResult:
    outcome: str
    bound: int = 0
    solver_seconds: float = 0.0
    sequence: List[Dict[str, int]] = field(default_factory=list)
    message: str = ""
    minimised_from: int = 0

    @property
    def accepted(self) -> bool:
        return self.outcome == "ACCEPTED"


@dataclass
class Design:
    """Everything the miter needs, kept explicit so nothing is inferred."""
    clock: Optional[str]
    reset: Optional[str]
    reset_active: int
    reset_sync: bool
    inputs: Dict[str, int]      # excluding clock and reset
    outputs: Dict[str, int]

    @property
    def sequential(self) -> bool:
        return self.clock is not None


def tools_available() -> Tuple[bool, str]:
    missing = [t for t in ("yosys", "yosys-smtbmc", "iverilog", "vvp")
               if shutil.which(t) is None]
    return (not missing), ("missing: " + ", ".join(missing) if missing else "")


def build_miter(design: Design, depth: int) -> str:
    """Golden-vs-mutant miter.

    Reset is driven by the harness rather than left symbolic: a solver free to
    choose reset can manufacture counterexamples a deployable testbench could
    never reproduce, which is one way the predecessor produced unreplayable
    witnesses.
    """
    L: List[str] = ["module miter;"]
    if design.sequential:
        L += [f"  reg {design.clock} = 1'b0;",
              "  integer f_half = 0;",
              "  always @($global_clock) begin",
              f"    {design.clock} <= ~{design.clock};",
              "    f_half <= f_half + 1;",
              "  end"]
    for name, w in design.inputs.items():
        width = "" if w == 1 else f"[{w-1}:0] "
        L.append(f"  (* anyseq *) reg {width}{name};")

    reset_half = 4                                  # two full cycles of reset
    if design.reset:
        inactive = 1 - design.reset_active
        L += [f"  reg {design.reset} = 1'b{design.reset_active};",
              "  always @($global_clock) begin",
              f"    if (f_half >= {reset_half}) {design.reset} <= 1'b{inactive};",
              "  end"]

    for name, w in design.outputs.items():
        width = "" if w == 1 else f"[{w-1}:0] "
        L += [f"  wire {width}g_{name};", f"  wire {width}m_{name};"]

    def conns(prefix: str) -> str:
        pairs = []
        if design.sequential:
            pairs.append(f".{design.clock}({design.clock})")
        if design.reset:
            pairs.append(f".{design.reset}({design.reset})")
        for name in design.inputs:
            pairs.append(f".{name}({name})")
        for name in design.outputs:
            pairs.append(f".{name}({prefix}_{name})")
        return ", ".join(pairs)

    L += [f"  golden_dut golden ({conns('g')});",
          f"  mutant_dut mutant ({conns('m')});", ""]

    eq = " && ".join(f"(g_{n} == m_{n})" for n in design.outputs) or "1'b1"
    if design.sequential:
        # Assert only after reset has been released, in the same half-step unit.
        guard = reset_half + 1 if design.reset else 1
        L += [f"  always @(posedge {design.clock}) begin",
              f"    if (f_half >= {guard}) assert({eq});",
              "  end"]
    else:
        L.append(f"  always @* assert({eq});")
    L += ["endmodule", ""]
    return "\n".join(L)


_YW_LINE = re.compile(r"^\s*(\w+)\s*=\s*([01xz]+)\s*$", re.I)


def parse_vlogtb(text: str, design: Design, depth: int) -> List[Dict[str, int]]:
    """Recover the input sequence from Yosys's generated testbench.

    The real `--dump-vlogtb` layout, confirmed against captured output:

        UUT.en = 1'b0;              // initial value, before any cycle block
        if (cycle == 0) begin
          UUT.en <= 1'b0;           // per-step value, non-blocking
        end

    Signals carry the `UUT.` hierarchical prefix and per-step assignments use
    `<=`. Values persist until reassigned, so each step inherits the previous
    one. Lines Yosys commented out are internal state it could not drive and are
    correctly ignored.
    """
    wanted = set(design.inputs)
    assign = re.compile(
        r"^UUT\.(\w+)\s*(<=|=)\s*(\d+)'([bdhBDH])([0-9a-fA-FxXzZ_]+)\s*;")
    cycle_open = re.compile(r"^if\s*\(\s*cycle\s*==\s*(\d+)\s*\)")

    initial: Dict[str, int] = {}
    per_cycle: Dict[int, Dict[str, int]] = {}
    current: Optional[int] = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        m = cycle_open.match(line)
        if m:
            current = int(m.group(1))
            continue
        if line.startswith("end"):
            current = None
            continue
        m = assign.match(line)
        if not m:
            continue
        name, op, _w, base, digits = m.groups()
        if name not in wanted:
            continue
        digits = digits.replace("_", "")
        if re.search(r"[xz]", digits, re.I):
            value = 0                       # undriven bits deploy as zero
        else:
            value = int(digits, {"b": 2, "d": 10, "h": 16}[base.lower()])
        if current is None and op == "=":
            initial[name] = value
        elif current is not None:
            per_cycle.setdefault(current, {})[name] = value

    if not per_cycle and not initial:
        return []

    # The initial assignment is in force at the FIRST sampled edge; the cycle-N
    # block is a non-blocking update that only takes effect afterwards. Letting
    # cycle 0 overwrite the initial value drops the first stimulus entirely,
    # which is how a genuinely diverging witness replayed as all-zeros.
    seq: List[Dict[str, int]] = []
    live = dict(initial)
    seq.append(dict(live))
    for i in range(max(per_cycle) + 1 if per_cycle else 0):
        live.update(per_cycle.get(i, {}))
        seq.append(dict(live))
    return seq


def uses_internal_state_forcing(vlogtb: str) -> bool:
    """Detect a witness that only works by forcing registers inside the DUT.

    Yosys may initialise submodule state hierarchically in its generated
    testbench. A deployable test cannot do that, so such a witness is refused.
    """
    for line in vlogtb.splitlines():
        s = line.strip()
        if s.startswith("//"):
            continue
        # hierarchical assignment into the instantiated designs
        if re.search(r"\b(golden|mutant)\s*\.", s) and "=" in s:
            return True
        if re.search(r"\bforce\b", s):
            return True
    return False


def run_bmc(golden: str, mutant: str, design: Design, depth: int,
            timeout_s: float, workdir: Path) -> Tuple[str, str, float, str]:
    """Returns (status, vlogtb_text, seconds, message). status in SAT/UNSAT/..."""
    import time
    for f in workdir.glob("*"):
        if f.is_file():
            f.unlink()
    (workdir / "golden_dut.v").write_text(
        golden.replace("top_module", "golden_dut"), encoding="utf-8")
    (workdir / "mutant_dut.v").write_text(
        mutant.replace("top_module", "mutant_dut"), encoding="utf-8")
    (workdir / "miter.sv").write_text(build_miter(design, depth), encoding="utf-8")

    script = "\n".join([
        "read_verilog -sv golden_dut.v mutant_dut.v",
        "read_verilog -sv -formal miter.sv",
        "prep -top miter",
        "flatten",
        "memory_map",
        "clk2fflogic" if design.sequential else "opt",
        "write_smt2 -wires miter.smt2",
    ])
    (workdir / "run.ys").write_text(script, encoding="utf-8")

    started = time.time()
    try:
        syn = subprocess.run(["yosys", "-q", "run.ys"], cwd=workdir,
                             capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return "TIMEOUT", "", time.time() - started, "yosys timeout"
    if syn.returncode != 0:
        return "UNSUPPORTED_CONSTRUCT", "", time.time() - started, syn.stderr[-300:]

    cmd = ["yosys-smtbmc", "-s", "z3", "-t", str(depth), "--dump-vlogtb",
           "witness_tb.v", "miter.smt2"]
    try:
        bmc = subprocess.run(cmd, cwd=workdir, capture_output=True,
                             text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return "TIMEOUT", "", time.time() - started, "smtbmc timeout"
    elapsed = time.time() - started
    out = bmc.stdout + bmc.stderr
    if "Status: PASSED" in out or "PASSED" in out and "FAILED" not in out:
        return "UNSAT", "", elapsed, "no counterexample within bound"
    if "FAILED" not in out and "Assert failed" not in out:
        return "UNSUPPORTED_CONSTRUCT", "", elapsed, out[-300:]
    tb = workdir / "witness_tb.v"
    if not tb.is_file():
        return "EXTRACTION_FAILED", "", elapsed, "no vlogtb emitted"
    return "SAT", tb.read_text(encoding="utf-8", errors="replace"), elapsed, ""
