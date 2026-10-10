#!/usr/bin/env python3
"""Lossless adapter over frozen CorrectBench checker and driver artefacts.

Design rule, learned the hard way: the adapter NEVER reimplements checker
semantics. The 780 CorrectBench artefacts span several generated templates that
differ in ways that matter --- some gate observation on a "[check]" prefix and
call check() before load(), others check every vector and call load() from
inside check(); some keep the scenario id as an int, others as a string. Any
reimplementation silently changes benchmark semantics on some template.

So the only verdict path is the frozen checker's own SignalTxt_to_dictlist and
check_dut, executed verbatim on text rendered in the driver's own format. The
adapter's job is confined to:

  parse_driver     recover the event sequence and the exact $fdisplay format,
  render_tbout     re-emit that sequence as TBout.txt text,
  FrozenChecker    execute the original checker file and expose its verdict,
  expected_at      recover the checker's point expectation by replaying a
                   prefix and sweeping the observed value.

Expectation recovery is simulator-free because the checker's state evolution
depends only on driver-supplied inputs, which are static in the driver text.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import os
import re
import shutil
import tempfile
import itertools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from vexpr import ExprError, evaluate as _eval_expr


@contextlib.contextmanager
def _muted():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        yield


@dataclass
class Event:
    """One line the driver writes to TBout.txt."""
    scenario: object
    check_en: bool
    inputs: Dict[str, int]
    fmt: str = ""
    args: Tuple[str, ...] = ()


@dataclass
class DriverParse:
    events: List[Event] = field(default_factory=list)
    input_signals: List[str] = field(default_factory=list)
    output_signals: List[str] = field(default_factory=list)
    widths: Dict[str, int] = field(default_factory=dict)
    supported: bool = True
    reason: str = ""

    @property
    def scenarios(self) -> List[object]:
        seen, order = set(), []
        for e in self.events:
            if e.scenario not in seen:
                seen.add(e.scenario)
                order.append(e.scenario)
        return order

    def indices_for(self, sid) -> List[int]:
        return [i for i, e in enumerate(self.events) if e.scenario == sid]


_PORT_RE = re.compile(
    r"^\s*(reg|wire)\s+(?:\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*)?"
    r"([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*;", re.M)
_FDISPLAY_RE = re.compile(r'\$fdisplay\s*\(\s*\w+\s*,\s*"(.*?)"\s*(?:,\s*([^;]*?))?\)\s*;')
_ASSIGN_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*(.+)$")
_REPEAT_RE = re.compile(r"^\s*repeat\s*\(\s*(\d+)\s*\)\s*begin\s*$")


def _declared_ports(verilog: str):
    """Ports declared by the frozen driver, including comma-separated lists.

    `wire o2, o1, o0;` is legal and common, and an earlier single-name pattern
    matched none of it -- the whole statement was skipped, so three outputs
    simply did not exist as far as the adapter was concerned. Every downstream
    stage then compared against zeros for them, which is why `vector0` recovered
    1 expectation out of 7. One shared width applies to every name in the list.
    """
    regs, wires, widths = [], [], {}
    for kind, hi, lo, names in _PORT_RE.findall(verilog):
        width = abs(int(hi) - int(lo)) + 1 if hi else 1
        for name in (n.strip() for n in names.split(",")):
            if not name:
                continue
            (regs if kind == "reg" else wires).append(name)
            widths[name] = width
    return regs, wires, widths


def _eval_rhs(expr: str, env: Dict[str, int]) -> Optional[int]:
    """Evaluate a driver RHS, or None if the expression is unsupported."""
    try:
        return _eval_expr(expr, env)
    except ExprError:
        return None


def parse_driver(verilog: str) -> DriverParse:
    out = DriverParse()
    regs, wires, widths = _declared_ports(verilog)
    out.input_signals = [r for r in regs if r != "clk"]
    out.output_signals = wires
    out.widths = widths

    blocks = []
    for m in re.finditer(r"initial\s+begin", verilog):
        start, depth = m.end(), 1
        end = len(verilog)
        for t in re.finditer(r"\bbegin\b|\bend\b", verilog[start:]):
            depth += 1 if t.group(0) == "begin" else -1
            if depth == 0:
                end = start + t.start()
                break
        blocks.append(verilog[start:end])
    body = next((b for b in blocks if "$fdisplay" in b), None)
    if body is None:
        out.supported = False
        out.reason = "no initial block emitting $fdisplay"
        return out

    env: Dict[str, int] = {r: 0 for r in regs}
    env["clk"] = 0
    env["scenario"] = 0
    scenario: object = 0
    failures: List[str] = []

    def apply_assignments(segment: str) -> None:
        nonlocal scenario
        # A single source line may carry several assignments: "y = 3'b000; w = 1'b0;"
        for part in segment.split(";"):
            part = part.strip()
            if not part or "$" in part or part.startswith("#"):
                continue
            part = re.sub(r"^#\d+\s*", "", part)
            m = _ASSIGN_RE.match(part)
            if not m:
                continue
            name, rhs = m.group(1), m.group(2)
            if name == "scenario":
                v = _eval_rhs(rhs, env)
                if v is not None:
                    scenario = v
                    # Keep it visible to the evaluator: drivers legitimately
                    # reference the scenario counter (e.g. "d = scenario % 2").
                    env["scenario"] = v
                continue
            if name in env:
                v = _eval_rhs(rhs, env)
                if v is None:
                    failures.append(f"unsupported RHS {rhs!r}")
                else:
                    env[name] = v

    def run(lines: Sequence[str]) -> None:
        idx = 0
        while idx < len(lines):
            line = lines[idx]
            m = _REPEAT_RE.match(line)
            if m:
                count, depth, j = int(m.group(1)), 1, idx + 1
                while j < len(lines):
                    if re.search(r"\bbegin\b", lines[j]):
                        depth += 1
                    if re.search(r"\bend\b", lines[j]):
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                inner = lines[idx + 1:j]
                for _ in range(count):
                    run(inner)
                idx = j + 1
                continue

            disp = list(_FDISPLAY_RE.finditer(line))
            if disp:
                # Statements before the first $fdisplay take effect first.
                apply_assignments(line[:disp[0].start()])
                for fm in disp:
                    fmt = fm.group(1)
                    args = tuple(a.strip() for a in (fm.group(2) or "").split(",") if a.strip())
                    out.events.append(Event(
                        scenario=scenario,
                        check_en=fmt.startswith("[check]"),
                        inputs={s: env.get(s, 0) for s in out.input_signals},
                        fmt=fmt, args=args))
                apply_assignments(line[disp[-1].end():])
            else:
                apply_assignments(line)
            idx += 1

    run(body.splitlines())
    if failures:
        out.supported = False
        out.reason = failures[0]
    elif not out.events:
        out.supported = False
        out.reason = "no events recovered"
    return out


_SPEC_RE = re.compile(r"%(?:0?\d+)?[dbhosxDBHOSX]")


def render_tbout(parse: DriverParse, events: Sequence[Event],
                 observed: Sequence[Dict[str, int]]) -> str:
    """Re-emit events using each event's own captured $fdisplay format."""
    lines = []
    for ev, obs in zip(events, observed):
        values = []
        for name in ev.args:
            if name == "scenario":
                values.append(ev.scenario)
            elif name in obs:
                values.append(obs[name])
            elif name in ev.inputs:
                values.append(ev.inputs[name])
            elif name == "clk":
                values.append(0)
            else:
                values.append(0)
        text, i = ev.fmt, 0

        def sub(_m):
            nonlocal i
            v = values[i] if i < len(values) else 0
            i += 1
            return str(v)

        lines.append(_SPEC_RE.sub(sub, text))
    return "\n".join(lines) + "\n"


class FrozenChecker:
    """Executes the frozen checker file verbatim; never reimplements it."""

    def __init__(self, source: str):
        self.source = source
        self.sha256 = hashlib.sha256(source.encode()).hexdigest()
        self.supported = True
        self.reason = ""
        self._ns: Dict[str, object] = {}
        self._dir = None
        self._out = None
        head = source.find('with open("TBout.txt"')
        self._defs = source if head == -1 else source[:head]
        try:
            with _muted():
                exec(compile(self._defs, "<frozen_checker>", "exec"), self._ns)
        except Exception as exc:
            self.supported = False
            self.reason = f"checker failed to load: {type(exc).__name__}: {exc}"
            return
        for fn in ("SignalTxt_to_dictlist", "check_dut"):
            if fn not in self._ns:
                self.supported = False
                self.reason = f"checker lacks {fn}"
                return

    def _scratch(self) -> str:
        """One scratch directory per checker, reused across calls.

        `verdict` is called once per candidate output value per position, which
        reaches hundreds of thousands of calls on a wide multi-output task.
        Creating and destroying a temporary directory each time made filesystem
        churn, not the checker, the dominant cost -- the checker functions
        themselves run in microseconds. The directory is still a real cwd holding
        a real TBout.txt, so anything a checker does with the filesystem behaves
        exactly as before; only the create/destroy is hoisted out of the loop.
        """
        if self._dir is None:
            self._dir = tempfile.mkdtemp(prefix="amp_")
            self._out = Path(self._dir, "TBout.txt")
        return self._dir

    def verdict(self, tbout: str) -> Tuple[Optional[list], str]:
        """Run the original parser and check_dut. Returns its failure list."""
        cwd = os.getcwd()
        td = self._scratch()
        self._out.write_text(tbout, encoding="utf-8")
        try:
            os.chdir(td)
            with _muted():
                vectors = self._ns["SignalTxt_to_dictlist"](tbout)
                failed = self._ns["check_dut"](vectors)
            return list(failed), ""
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"
        finally:
            os.chdir(cwd)

    def close(self) -> None:
        if self._dir:
            shutil.rmtree(self._dir, ignore_errors=True)
            self._dir = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


def expected_at(parse: DriverParse, checker: FrozenChecker, index: int,
                known: Dict[int, Dict[str, int]], max_bits: int = 10,
                max_combos: int = 512) -> Optional[Dict[str, int]]:
    """Recover the checker's point expectation at `index`.

    Replays the real prefix [0..index] through the frozen checker and sweeps the
    observed value, keeping the assignment the checker accepts. Earlier
    positions use expectations already recovered, so the checker state at
    `index` is genuine.

    Two generalisations the hardening pass required, both discovered from real
    tasks and both general rather than task-specific:

    * multi-output checkers are swept over the Cartesian product of their
      outputs (circuit8, circuit10, ece241_2013_q4, lemmings3);
    * a checker's expectation domain can exceed the driver's declared port
      width, so when nothing is accepted within the declared width the sweep
      widens (mt2015_muxdff declares `wire Q` as 1 bit while the checker holds a
      3-bit value).
    """
    outs = parse.output_signals
    if not outs:
        return None
    prefix = list(parse.events[:index + 1])

    def obs_for(assignment: Dict[str, int]):
        seq = []
        for i in range(index + 1):
            if i == index:
                seq.append(dict(assignment))
            else:
                seq.append(dict(known.get(i, {o: 0 for o in outs})))
        return seq

    def sweep(bits_for: Dict[str, int]) -> Optional[Dict[str, int]]:
        ranges = [range(1 << bits_for[o]) for o in outs]
        total = 1
        for r in ranges:
            total *= len(r)
            if total > max_combos:
                return None
        best, fewest = [], None
        for combo in itertools.product(*ranges):
            assignment = dict(zip(outs, combo))
            failed, _ = checker.verdict(render_tbout(parse, prefix, obs_for(assignment)))
            if failed is None:
                return None
            n = len(failed)
            if fewest is None or n < fewest:
                fewest, best = n, [assignment]
            elif n == fewest:
                best.append(assignment)
        if len(best) == 1:
            return best[0]
        return None

    declared = {o: min(parse.widths.get(o, 1), max_bits) for o in outs}
    got = sweep(declared)
    if got is not None:
        return got
    # Widen only when the declared width admitted no unique answer.
    if len(outs) == 1:
        widened = {outs[0]: max_bits}
        if widened[outs[0]] > declared[outs[0]]:
            return sweep(widened)
    return None


def replay_cost(events: Sequence[Event]) -> int:
    """Deployment cost: every emitted event is one driver period, setup included."""
    return len(events)


def scenario_controllable(parse: DriverParse) -> bool:
    """Can we tell the checker WHICH position a reported failure came from?

    The fast single-pass recovery labels each event with its index and reads the
    reported labels back. That only works if `scenario` is an argument of the
    driver's `$fdisplay`. Many drivers instead bake the label into the format
    string -- `$fdisplay(file, "scenario: 1, a = %d, out = %d", a, out)` -- so
    every row renders as `scenario: 1`, relabelling does nothing, and the
    single-pass sweep collapses every position onto one.

    That case is not rare: 66 of 156 AutoBench drivers and 4 of 156 CorrectBench
    drivers are like this. It is also silent -- the existing guard compares the
    failure COUNT before and after relabelling, which is trivially unchanged
    when relabelling has no effect, so the guard passed and wrong expectations
    were returned rather than none.
    """
    return bool(parse.events) and all("scenario" in e.args for e in parse.events)


def _recover_positionwise(parse: DriverParse, checker: FrozenChecker,
                          max_bits: int, max_combos: int, max_work: int,
                          max_invocations: int = 60_000
                          ) -> Tuple[Optional[List[Optional[Dict[str, int]]]], str]:
    """Recover one position at a time by replaying the real prefix.

    Used when the scenario label is not controllable, so failures cannot be
    attributed to a position. Costs O(n^2) checker runs instead of O(combos),
    which is why it is the fallback and not the default.
    """
    outs = parse.output_signals
    if not outs:
        return None, "no output signals"
    n = len(parse.events)
    bits = {o: min(parse.widths.get(o, 1), max_bits) for o in outs}
    combos = 1
    for o in outs:
        combos *= 1 << bits[o]
        if combos > max_combos:
            return None, f"output space {combos} exceeds probe budget"
    # Two budgets, because the two costs scale differently. Row rendering is
    # O(combos * n^2/2), but the dominant real cost is the number of CHECKER
    # INVOCATIONS -- each parses a trace and runs check_dut -- which is
    # O(combos * n). Budgeting only on rendered rows let fsm_onehot through at
    # 4096 combos x 20 events: 860k rendered rows looked affordable while the
    # 82k checker invocations behind them took a quarter of an hour.
    work = combos * n * (n + 1) // 2
    if work > max_work:
        return None, (f"position-wise probe work {work} exceeds budget "
                      f"{max_work} (scenario label not controllable)")
    invocations = combos * n
    if invocations > max_invocations:
        return None, (f"position-wise probe needs {invocations} checker "
                      f"invocations, over the {max_invocations} budget "
                      f"(scenario label not controllable)")

    known: Dict[int, Dict[str, int]] = {}
    out: List[Optional[Dict[str, int]]] = []
    for i in range(n):
        got = expected_at(parse, checker, i, known, max_bits=max_bits,
                          max_combos=max_combos)
        if got is not None:
            known[i] = got
        out.append(got)
    if not any(e is not None for e in out):
        return None, "no position yielded a unique expectation"
    return out, ""


def recover_expectations(parse: DriverParse, checker: FrozenChecker,
                         max_bits: int = 12, max_combos: int = 4096,
                         max_work: int = 12_000_000
                         ) -> Tuple[Optional[List[Optional[Dict[str, int]]]], str]:
    """Recover every check point's expectation in O(candidates) checker runs.

    Replaying a prefix per event is O(n^2) and does not scale to the largest
    driver (review2015_count1k emits 3068 events). Instead each candidate output
    assignment is applied to the WHOLE sequence in one check_dut run, and the
    positions the checker does not flag are the positions that candidate
    satisfies.

    This relies on one property, which is verified rather than assumed: the
    checker's state evolution must not depend on the observed DUT output, so
    that one sweep is valid at every position simultaneously. Positions are
    identified by rendering the scenario field as the event index, which the
    frozen checkers use only as a reporting label; the verification step below
    confirms that relabelling does not change the verdict.

    Returns (expectations, "") or (None, reason).
    """
    outs = parse.output_signals
    if not outs:
        return None, "no output signals"

    # Position attribution below depends on the scenario label being an argument
    # of the driver's $fdisplay. Where it is baked into the format string the
    # relabelling is a no-op, the count-based guard passes vacuously, and every
    # position collapses onto one -- returning WRONG expectations rather than
    # none. Detect that up front and take the slower, sound path.
    if not scenario_controllable(parse):
        return _recover_positionwise(parse, checker, max_bits, max_combos, max_work)

    indexed = [Event(scenario=i, check_en=e.check_en, inputs=e.inputs,
                     fmt=e.fmt, args=e.args) for i, e in enumerate(parse.events)]

    # Honour the declared port width: capping below it silently loses every
    # expectation above the cap (review2015_count1k declares q as 10 bits and
    # counts mod 1000). The budget is expressed as total work rather than an
    # arbitrary bit limit, so wide outputs are attempted when affordable.
    bits = {o: min(parse.widths.get(o, 1), max_bits) for o in outs}
    combos = 1
    for o in outs:
        combos *= 1 << bits[o]
        if combos > max_combos:
            return None, f"output space {combos} exceeds probe budget"
    work = combos * max(1, len(parse.events))
    if work > max_work:
        return None, f"probe work {work} exceeds budget {max_work}"

    # Verification: relabelling scenarios must not change how many checks fail.
    probe = [{o: 0 for o in outs} for _ in parse.events]
    orig_failed, err = checker.verdict(render_tbout(parse, parse.events, probe))
    if orig_failed is None:
        return None, f"checker raised: {err}"
    idx_failed, err = checker.verdict(render_tbout(parse, indexed, probe))
    if idx_failed is None:
        return None, f"checker raised on indexed render: {err}"
    if len(orig_failed) != len(idx_failed):
        return None, "scenario relabelling changed the verdict"

    def sweep(bit_map: Dict[str, int]):
        sets: Dict[Tuple[int, ...], set] = {}
        for combo in itertools.product(*[range(1 << bit_map[o]) for o in outs]):
            assign = dict(zip(outs, combo))
            obs = [dict(assign) for _ in parse.events]
            failed, err = checker.verdict(render_tbout(parse, indexed, obs))
            if failed is None:
                return None, f"checker raised: {err}"
            failed_idx = set()
            for f in failed:
                try:
                    failed_idx.add(int(f))
                except (TypeError, ValueError):
                    return None, "failure labels are not event indices"
            sets[combo] = failed_idx
        return sets, ""

    passing_sets, err = sweep(bits)
    if passing_sets is None:
        return None, err

    def unresolved(sets) -> List[int]:
        """Positions every candidate fails: the true expectation is out of range."""
        out_idx = []
        for i in range(len(parse.events)):
            if all(i in failed for failed in sets.values()):
                out_idx.append(i)
        return out_idx

    # A checker's expectation domain can exceed the driver's declared port width
    # (mt2015_muxdff declares `wire Q` as 1 bit while the checker holds 3 bits).
    # Widen only when some position rejects every candidate in the declared range.
    if unresolved(passing_sets) and len(outs) == 1:
        wide = {outs[0]: max_bits}
        if wide[outs[0]] > bits[outs[0]] and (1 << wide[outs[0]]) <= max_combos:
            wider, werr = sweep(wide)
            if wider is not None and len(unresolved(wider)) < len(unresolved(passing_sets)):
                passing_sets = wider

    expectations: List[Optional[Dict[str, int]]] = []
    for i in range(len(parse.events)):
        accepted = [c for c, failed in passing_sets.items() if i not in failed]
        # A position the checker never flags for any candidate has no opinion.
        if len(accepted) == 1:
            expectations.append(dict(zip(outs, accepted[0])))
        else:
            expectations.append(None)
    return expectations, ""
