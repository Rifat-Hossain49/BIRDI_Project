#!/usr/bin/env python3
"""HDL plumbing: ports, stimulus drivers, simulation, traces, comparison.

A testbench in this pipeline is two things kept apart on purpose:
  a DRIVER   deterministic stimulus that instantiates top_module and writes one
             line per observation to TBout.txt; identical for every DUT;
  EXPECTED   the trace a reference design produces under that driver.
A DUT passes when its trace matches EXPECTED at every observation, with X/Z in the
expected value treated as don't-care -- the same convention as the official
VerilogEval testbenches (they compare with ref ^ dut ^ ref under ===).
"""
from __future__ import annotations

import os
import random
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

IVERILOG = shutil.which("iverilog") or ("C:/iverilog/bin/iverilog.exe" if Path("C:/iverilog/bin/iverilog.exe").exists() else "iverilog")
VVP = shutil.which("vvp") or ("C:/iverilog/bin/vvp.exe" if Path("C:/iverilog/bin/vvp.exe").exists() else "vvp")
MISMATCH_RE = re.compile(r"Mismatches:\s*(\d+)\s+in\s+(\d+)\s+samples")
CLOCK_NAMES = {"clk", "clock"}
RESET_HIGH = {"reset", "rst", "areset", "ar", "sreset", "synch_reset"}
RESET_LOW = {"resetn", "rst_n", "reset_n", "aresetn", "areset_n", "arst_n", "rstn"}


# ---------------------------------------------------------------- ports

@dataclass
class Port:
    name: str
    direction: str
    width: int


@dataclass
class Interface:
    inputs: List[Port] = field(default_factory=list)
    outputs: List[Port] = field(default_factory=list)

    @property
    def clock(self) -> Optional[str]:
        return next((p.name for p in self.inputs if p.name.lower() in CLOCK_NAMES and p.width == 1), None)

    @property
    def reset(self) -> Optional[Tuple[str, int]]:
        for p in self.inputs:
            n = p.name.lower()
            if p.width == 1 and n in RESET_LOW:
                return p.name, 0
            if p.width == 1 and n in RESET_HIGH:
                return p.name, 1
        return None

    @property
    def data_inputs(self) -> List[Port]:
        skip = {self.clock} | ({self.reset[0]} if self.reset else set())
        return [p for p in self.inputs if p.name not in skip]


def parse_header(header: str) -> Interface:
    text = re.sub(r"//.*", "", header)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    m = re.search(r"\((.*)\)\s*;", text, re.S)
    body = m.group(1) if m else text
    iface = Interface()
    direction, width = None, 1
    for raw in body.split(","):
        tok = raw.strip()
        if not tok:
            continue
        dm = re.match(r"(input|output|inout)\b\s*(wire|reg|logic|signed|\s)*\s*(\[[^\]]+\])?\s*(\w+)\s*$", tok)
        if dm:
            direction = dm.group(1)
            width = _width(dm.group(3))
            name = dm.group(4)
        else:
            nm = re.match(r"(\[[^\]]+\])?\s*(\w+)\s*$", tok)
            if not nm or direction is None:
                continue
            if nm.group(1):
                width = _width(nm.group(1))
            name = nm.group(2)
        port = Port(name, direction, width)
        (iface.inputs if direction == "input" else iface.outputs).append(port)
    return iface


def _width(rng: Optional[str]) -> int:
    if not rng:
        return 1
    nums = re.findall(r"-?\d+", rng)
    if len(nums) < 2:
        return 1
    return abs(int(nums[0]) - int(nums[1])) + 1


# ---------------------------------------------------------------- stimulus

def _lit(width: int, value: int) -> str:
    return f"{width}'h{value:x}"


def build_driver(iface: Interface, seed: int, seq_scenarios: int = 8, seq_cycles: int = 40,
                 comb_random: int = 400, samples_per_cycle: int = 2,
                 marathons: bool = False) -> str:
    """Deterministic stimulus. Identical text for every DUT of a task."""
    rng = random.Random(seed)
    L = ["`timescale 1ns/1ps", "module tb;"]
    clk = iface.clock
    if clk:
        L.append(f"  reg {clk} = 0;")
    for p in iface.inputs:
        if p.name == clk:
            continue
        L.append(f"  reg [{p.width-1}:0] {p.name};" if p.width > 1 else f"  reg {p.name};")
    for p in iface.outputs:
        L.append(f"  wire [{p.width-1}:0] {p.name};" if p.width > 1 else f"  wire {p.name};")
    L.append("  integer tb_fd_;")
    conns = ", ".join(f".{p.name}({p.name})" for p in iface.inputs + iface.outputs)
    L.append(f"  top_module dut({conns});")
    if clk:
        L.append(f"  always #5 {clk} = ~{clk};")
    sig = [p for p in iface.inputs if p.name != clk] + iface.outputs
    fmt = " ".join(["%0d", "%0d"] + ["%b"] * len(sig))
    args = ", ".join(sig_name for sig_name in [p.name for p in sig])
    display = f'$fdisplay(tb_fd_, "{fmt}", tb_scen_, tb_step_{", " + args if args else ""});'
    L += ["  integer tb_scen_, tb_step_;", "  initial begin", '    tb_fd_ = $fopen("TBout.txt", "w");']
    for p in iface.inputs:
        if p.name != clk:
            L.append(f"    {p.name} = 0;")
    step = 0
    if clk:
        rst = iface.reset
        data = iface.data_inputs
        for s in range(seq_scenarios):
            hold = s % 2 == 1                      # odd scenarios hold values 1-4 cycles
            held, hold_left = {}, 0
            L.append(f"    tb_scen_ = {s};")
            for c in range(seq_cycles):
                L.append("    #1;")
                if rst:
                    name, active = rst
                    # reset for the first two cycles of every scenario, then at random
                    on = c < 2 or rng.random() < 0.05
                    L.append(f"    {name} = {active if on else 1 - active};")
                if hold and hold_left > 0:
                    hold_left -= 1
                else:
                    held = {p.name: rng.getrandbits(p.width) for p in data}
                    hold_left = rng.randint(0, 3) if hold else 0
                for p in data:
                    L.append(f"    {p.name} = {_lit(p.width, held[p.name])};")
                L.append(f"    #3; tb_step_ = {step}; {display}")
                step += 1
                if samples_per_cycle >= 2:
                    L.append(f"    #5; tb_step_ = {step}; {display}")
                    step += 1
                    L.append("    #1;")
                else:
                    L.append("    #6;")
        if marathons:
            # Long constant-input runs after a reset. Deep counters, long timers and
            # "held for N cycles" behaviour (clock rollover, BCD wrap, count-down,
            # falling long enough to splat) are unreachable when inputs change every
            # cycle. Emitted as repeat loops so the driver stays small; one
            # observation per cycle keeps the traces tractable.
            obs = display.replace("tb_step_,", "tb_step_,")
            plans = [("ones", 44000), ("zeros", 2048), ("randhold", 8192)]
            # Cost budget, not a per-task rule: total observed bits across the long
            # runs is capped, so narrow designs (clocks, counters, timers) keep full
            # length while wide ones (e.g. a 256-cell grid) get proportionally shorter
            # runs they do not need and could not simulate in time.
            width_sum = sum(p.width for p in data) + sum(p.width for p in iface.outputs)
            total = sum(c for _, c in plans)
            scale = min(1.0, 4_000_000 / max(1, width_sum * total))
            plans = [(k, max(256, int(c * scale))) for k, c in plans]
            for m_i, (kind, cycles) in enumerate(plans):
                L.append(f"    tb_scen_ = {seq_scenarios + m_i};")
                segments = []
                if kind == "randhold":
                    left = cycles
                    while left > 0:
                        n = min(left, rng.randint(64, 1024))
                        segments.append(({p.name: rng.getrandbits(p.width) for p in data}, n))
                        left -= n
                else:
                    fill = (lambda w: (1 << w) - 1) if kind == "ones" else (lambda w: 0)
                    segments = [({p.name: fill(p.width) for p in data}, cycles)]
                first = True
                for vals, n in segments:
                    for p in data:
                        L.append(f"    {p.name} = {_lit(p.width, vals[p.name])};")
                    if first and rst:
                        name, active = rst
                        # two reset cycles at the start of each long run
                        L.append(f"    {name} = {active};")
                        L.append(f"    repeat (2) begin #4; tb_step_ = {step}; {obs} #6; end")
                        step += 2
                        L.append(f"    {name} = {1 - active};")
                        n = max(0, n - 2)
                    first = False
                    L.append(f"    tb_step_ = {step};")
                    L.append(f"    repeat ({n}) begin #4; {obs} tb_step_ = tb_step_ + 1; #6; end")
                    step += n
    else:
        data = iface.inputs
        bits = sum(p.width for p in data)
        vectors = []
        if bits <= 10:
            for v in range(1 << bits):
                vectors.append(v)
        else:
            vectors = [0, (1 << bits) - 1] + [1 << i for i in range(min(bits, 64))]
            vectors += [rng.getrandbits(bits) for _ in range(comb_random)]
        L.append("    tb_scen_ = 0;")
        for i, v in enumerate(vectors):
            if i and i % 32 == 0:
                L.append(f"    tb_scen_ = {i // 32};")
            off = 0
            for p in reversed(data):
                L.append(f"    {p.name} = {_lit(p.width, (v >> off) & ((1 << p.width) - 1))};")
                off += p.width
            L.append(f"    #5; tb_step_ = {step}; {display}")
            step += 1
            L.append("    #5;")
    L += ["    $fclose(tb_fd_);", "    $finish;", "  end", "endmodule", ""]
    return "\n".join(L)


# ---------------------------------------------------------------- simulation

def _run(cmd, cwd, timeout, tries=5):
    """subprocess.run with retries for transient Windows launch denials.

    On Windows a freshly written file in the working directory is sometimes still
    held by antivirus scanning, and CreateProcess then fails with WinError 5. It
    clears within moments, so the launch is retried rather than crashing a long
    evaluation. Timeouts are NOT retried: they are real outcomes.
    """
    import time as _t
    for k in range(tries):
        try:
            return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        except PermissionError:
            if k == tries - 1:
                raise
            _t.sleep(0.5 * (k + 1))


@dataclass
class Trace:
    status: str
    rows: Optional[List[Tuple[int, int, Tuple[str, ...]]]] = None
    detail: str = ""


def simulate(rtl: str, driver: str, timeout: int = 60, workdir: Optional[Path] = None) -> Trace:
    own = workdir is None
    work = Path(tempfile.mkdtemp(prefix="dirtb_")) if own else workdir
    try:
        for f in work.glob("*"):
            if f.is_file():
                f.unlink()
        (work / "dut.v").write_text(rtl, encoding="utf-8")
        (work / "tb.v").write_text(driver, encoding="utf-8")
        try:
            c = _run([IVERILOG, "-g2012", "-o", "sim", "tb.v", "dut.v"], work, timeout)
        except subprocess.TimeoutExpired:
            return Trace("COMPILE_TIMEOUT")
        if c.returncode != 0:
            return Trace("COMPILE_ERROR", detail=(c.stderr or "")[:300])
        try:
            _run([VVP, "-n", "sim"], work, timeout)
        except subprocess.TimeoutExpired:
            return Trace("SIM_TIMEOUT")
        out = work / "TBout.txt"
        if not out.is_file():
            return Trace("NO_OUTPUT")
        rows = []
        for line in out.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                rows.append((int(parts[0]), int(parts[1]), tuple(parts[2:])))
            except ValueError:
                continue
        return Trace("RAN", rows)
    finally:
        if own:
            shutil.rmtree(work, ignore_errors=True)


def matches(expected: Trace, dut: Trace) -> bool:
    """DUT agrees with the expected trace at every observation; expected X/Z = don't-care."""
    if expected.status != "RAN" or dut.status != "RAN":
        return False
    if len(expected.rows) != len(dut.rows):
        return False
    for (_, _, ev), (_, _, dv) in zip(expected.rows, dut.rows):
        if len(ev) != len(dv):
            return False
        for e, d in zip(ev, dv):
            if len(e) != len(d):
                return False
            for eb, db in zip(e, d):
                if eb in "xXzZ":
                    continue
                if eb != db:
                    return False
    return True


def official_accepts(rtl: str, official_tb: str, timeout: int = 60) -> Optional[bool]:
    work = Path(tempfile.mkdtemp(prefix="dirtb_off_"))
    try:
        (work / "dut.sv").write_text(rtl, encoding="utf-8")
        (work / "tb.sv").write_text(official_tb, encoding="utf-8")
        try:
            c = _run([IVERILOG, "-g2012", "-o", "sim", "tb.sv", "dut.sv"], work, timeout)
            if c.returncode != 0:
                return False
            r = _run([VVP, "-n", "sim"], work, timeout)
        except subprocess.TimeoutExpired:
            return False
        m = MISMATCH_RE.search(r.stdout)
        if not m:
            return None
        return int(m.group(1)) == 0
    finally:
        shutil.rmtree(work, ignore_errors=True)
