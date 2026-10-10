#!/usr/bin/env python3
"""ACTIVE-TB-SAFE Channel 2: formal shadow verification.

Channel 1 is the frozen generator's verdict, passed through untouched. This
module never reads, modifies or re-derives it, which is what makes
non-regression a property of the architecture rather than a measurement.

Channel 2 works like this:

    spec-only candidate RTL (>=2 independent families)
      -> differential BMC between candidate pairs
      -> witness: an input sequence on which they provably disagree
      -> the FROZEN CHECKER adjudicates what the output should be there
      -> shadow test = witness + checker expectation
      -> DUT failing a shadow test raises a WARNING, never a verdict

The critical discipline, and the difference from the abandoned IVRP branch:
**candidates never vote on truth.** They are used only to locate behavioural
disagreement, which is a search signal. The expected value at that point comes
from the frozen checker alone. Where the checker has no definite opinion, the
point is abstained from and no shadow test is emitted.

Golden RTL is not read here. Candidates were generated from specification and
interface only, so the information setting matches the frozen frontend's.
"""
from __future__ import annotations

import contextlib
import io
import json
import random
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "amp"))

from formal_witness import Design, run_bmc, tools_available, uses_internal_state_forcing
from formal_witness import parse_vlogtb


@dataclass
class ShadowTest:
    """A witness plus the frozen checker's expectation at each step.

    `prefix` is the frozen driver's own initialisation sequence, replayed before
    the witness. Without it the checker starts in its `__init__` state while the
    DUT starts at power-up, and the two diverge from step 0 -- which made the
    first Channel 2 build reject correct designs on 6 of 9 tasks.
    """
    task_id: str
    prefix: List[Dict[str, int]]
    witness: List[Dict[str, int]]
    expected: List[Optional[Dict[str, int]]]
    source_pair: Tuple[str, str]
    bound: int
    solver_seconds: float
    # One flag per step of prefix+witness. False means DRIVE the stimulus but do
    # not print that step, so the frozen checker never sees it and cannot judge
    # it. None means every step is asserted. Only ever set for stateless
    # checkers: skipping a printed row costs a stateful checker one clock of its
    # own state evolution, which would desynchronise everything after it.
    mask: Optional[List[bool]] = None

    @property
    def steps(self) -> List[Dict[str, int]]:
        return list(self.prefix) + list(self.witness)

    @property
    def cycles(self) -> int:
        """Full deployed cost: the initialisation prefix is not free."""
        return len(self.prefix) + len(self.witness)

    def asserts(self, i: int) -> bool:
        return self.mask is None or (i < len(self.mask) and self.mask[i])

    @property
    def asserted_points(self) -> int:
        return sum(1 for i, e in enumerate(self.expected)
                   if e is not None and self.asserts(i))


@dataclass
class ShadowReport:
    task_id: str
    pairs_attempted: int = 0
    witnesses_found: int = 0
    witnesses_rejected_illegal: int = 0
    witnesses_unparsed: int = 0
    adjudicated: int = 0
    abstained_no_opinion: int = 0
    tests: List[ShadowTest] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"task_id": self.task_id, "pairs_attempted": self.pairs_attempted,
                "witnesses_found": self.witnesses_found,
                "witnesses_rejected_illegal": self.witnesses_rejected_illegal,
                "witnesses_unparsed": self.witnesses_unparsed,
                "adjudicated": self.adjudicated,
                "abstained_no_opinion": self.abstained_no_opinion,
                "shadow_tests": len(self.tests),
                "shadow_cycles": sum(t.cycles for t in self.tests),
                "asserted_points": sum(t.asserted_points for t in self.tests),
                # Per-test witness lengths, so a matched-resource ablation can
                # reproduce this task's exact test budget without re-solving.
                "witness_lengths": [len(t.witness) for t in self.tests],
                "notes": self.notes}


def design_from_parse(parse, reset_name: Optional[str],
                      reset_active: int = 1) -> Design:
    """Build the BMC design description from the frozen driver's interface."""
    ins = {n: parse.widths.get(n, 1) for n in parse.input_signals if n != reset_name}
    outs = {n: parse.widths.get(n, 1) for n in parse.output_signals}
    clk = "clk" if "clk" in parse.widths else None
    return Design(clock=clk, reset=reset_name, reset_active=reset_active,
                  reset_sync=True, inputs=ins, outputs=outs)


def guess_reset(parse) -> Tuple[Optional[str], int]:
    """Identify a reset port conservatively, from its name only.

    A wrong guess would change the miter's assumptions, so anything ambiguous is
    treated as having no reset, which is the safe direction: the harness then
    drives it as an ordinary input.
    """
    for name in parse.input_signals:
        low = name.lower()
        if low in ("reset", "rst", "areset"):
            return name, 1
        if low in ("resetn", "rst_n", "reset_n", "areset_n", "arst_n", "aresetn"):
            return name, 0
    return None, 1


def init_prefix(parse) -> List[Dict[str, int]]:
    """The frozen driver's own setup, up to its first observation point.

    Reusing the generator's initialisation rather than inventing one keeps the
    checker's state evolution identical to the context it was written for.

    Only SOME templates mark observation points with a "[check]" prefix. Where no
    event is marked, the checker observes every row, so the first observation
    point is row 0 and there is no setup to replay -- the prefix is empty. An
    earlier version scanned for the first marked event and, finding none, fell
    off the end and returned the ENTIRE driver trace as prefix. That affected 76
    of 150 CorrectBench and 66 of 135 AutoBench drivers: every shadow suite on
    them re-ran the whole original stimulus before its witness, inflating the
    reported shadow cost and making a warning impossible to attribute to the
    witness rather than to the replayed original trace.
    """
    if not any(ev.check_en for ev in parse.events):
        return []
    out: List[Dict[str, int]] = []
    for ev in parse.events:
        if ev.check_en:
            break
        out.append(dict(ev.inputs))
    return out


def adjudicate(state_model, witness: Sequence[Dict[str, int]]
               ) -> List[Optional[Dict[str, int]]]:
    """Ask the FROZEN checker what it expects along the witness.

    Returns one entry per step: the value the checker accepts, or None where it
    has no single definite opinion. None means abstain, never guess.
    """
    steps = state_model.run(witness)
    return [s.expected for s in steps]


def translation_audit(parse, tests: Sequence[ShadowTest], state_model,
                      checker_source: str) -> dict:
    """Locate every point at which the emitted suite and the frozen checker
    would disagree about their own expectations, rather than only reporting that
    one exists.

    This replaces the earlier "checker-blessed candidate" rule, which defeated
    the channel's own purpose. That rule called a candidate *blessed* if it
    passed the ORIGINAL Channel 1 testbench, then discarded any shadow suite
    that rejected such a candidate. But surviving the original suite does not
    make a design correct -- finding a design that escapes the original tests
    and then fails a new, checker-adjudicated test is precisely the intended
    benefit. The old rule threw exactly those away (6 tasks on CorrectBench, 2
    on AutoBench), and bought its zero false alarms with them.

    What genuinely needs checking is TRANSLATION FIDELITY, and it needs no
    candidates at all. Expectations are computed through `load()`/`check()`, but
    a deployed suite is scored through `check_dut()` over a rendered TBout --
    two different paths through the same frozen checker. So: replay the suite's
    own trace, fill every observation point with a value the checker itself
    accepts, and run the NATIVE `check_dut` over the result. Anything it rejects
    is a defect in our translation, not a property of any design under test.

    Two distinct defects, neither of which is a detection:
      * unsatisfiable point -- the checker accepts NO output value there, so the
        suite would reject every design, Golden included;
      * path disagreement -- `check_dut` rejects what `load()`/`check()` predicted.

    A candidate merely FAILING a shadow test is a detection and is not a defect.

    Returns {ok, why, bad: {test_index: [step_index, ...]}, points}.
    """
    from frontend_adapter import Event as FEvent, render_tbout

    src = next((e for e in parse.events if e.check_en), parse.events[0])
    bad: Dict[int, List[int]] = {}
    events: List[FEvent] = []
    observed: List[Dict[str, int]] = []
    origin: List[Tuple[int, int]] = []

    for ti, test in enumerate(tests):
        dut = state_model.new()
        for si, vec in enumerate(test.steps):
            if not test.asserts(si):
                continue
            acc = state_model.accepted_values(dut, vec, limit=2)
            if acc is None:
                return {"ok": False, "why": f"checker sweep unusable at test {ti} step {si}",
                        "bad": {}, "points": 0}
            if not acc:
                bad.setdefault(ti, []).append(si)
                continue
            exp = test.expected[si] if si < len(test.expected) else None
            use = exp if exp is not None else acc[0]
            try:
                with _model_quiet():
                    dut.load(state_model._vector(vec, observed=use))
            except Exception as exc:
                return {"ok": False, "why": f"checker load raised: {type(exc).__name__}",
                        "bad": {}, "points": 0}
            events.append(FEvent(scenario=ti + 1, check_en=True, inputs=dict(vec),
                                 fmt=src.fmt, args=src.args))
            observed.append(dict(use))
            origin.append((ti, si))

    unsat = sum(len(v) for v in bad.values())
    if not events:
        return {"ok": False, "why": "no satisfiable assertion point in the suite",
                "bad": bad, "points": 0}

    # Bisect the whole-suite verdict down to the offending points. The label the
    # checker reports is unreliable here for the same reason it is unreliable in
    # expectation recovery -- many drivers hard-code it -- so positions are found
    # by growing a prefix and watching the failure count, which needs no labels.
    n, err = _native_failcount(checker_source, render_tbout(parse, events, observed))
    if n is None:
        return {"ok": False, "why": f"native checker raised on shadow trace: {err}",
                "bad": bad, "points": len(events)}
    if n:
        prev = 0
        for k in range(1, len(events) + 1):
            cur, e2 = _native_failcount(
                checker_source, render_tbout(parse, events[:k], observed[:k]))
            if cur is None:
                return {"ok": False, "why": f"native checker raised: {e2}",
                        "bad": bad, "points": len(events)}
            if cur > prev:
                ti, si = origin[k - 1]
                bad.setdefault(ti, []).append(si)
            prev = cur

    total_bad = sum(len(v) for v in bad.values())
    if total_bad:
        why = (f"{unsat} unsatisfiable and {total_bad - unsat} path-disagreeing "
               f"point(s) of {len(events) + unsat}")
    else:
        why = f"translation consistent over {len(events)} assertion point(s)"
    return {"ok": not total_bad, "why": why, "bad": bad,
            "points": len(events) + unsat}


def translation_consistent(parse, tests: Sequence[ShadowTest], state_model,
                           checker_source: str) -> Tuple[bool, str]:
    """Boolean form of `translation_audit`, for the suite-level gate."""
    a = translation_audit(parse, tests, state_model, checker_source)
    return a["ok"], a["why"]


def repair_tests(tests: Sequence[ShadowTest], bad: Dict[int, List[int]],
                 stateless: bool) -> Tuple[List[ShadowTest], str]:
    """Keep the sound part of a suite instead of discarding all of it.

    Rejecting a whole suite because one point is untranslatable throws away every
    other assertion that was fine, and with it the stimulus that reached them.
    Two repairs, chosen by the checker's shape because soundness differs:

      stateless -- MASK the offending steps. The stimulus is still driven, so the
        DUT advances identically; the step is simply not printed, so the checker
        never judges it. Sound only because a stateless checker carries nothing
        between rows.

      stateful -- TRUNCATE each test just before its first bad step. A stateful
        checker advances once per printed row, so masking a row would cost it a
        clock and desynchronise every later expectation. Truncation preserves the
        stimulus prefix and the checker's history exactly, and simply stops early.

    Tests left with no asserted point are dropped.
    """
    out: List[ShadowTest] = []
    masked = truncated = dropped = 0
    for ti, t in enumerate(tests):
        steps = t.steps
        bs = sorted(set(bad.get(ti, [])))
        if not bs:
            out.append(t)
            continue
        if stateless:
            mask = [t.asserts(i) and i not in set(bs) for i in range(len(steps))]
            nt = ShadowTest(task_id=t.task_id, prefix=t.prefix, witness=t.witness,
                            expected=t.expected, source_pair=t.source_pair,
                            bound=t.bound, solver_seconds=t.solver_seconds,
                            mask=mask)
            if nt.asserted_points:
                out.append(nt)
                masked += 1
            else:
                dropped += 1
            continue
        cut = bs[0]
        if cut <= len(t.prefix):
            dropped += 1
            continue
        keep = cut - len(t.prefix)
        nt = ShadowTest(task_id=t.task_id, prefix=t.prefix,
                        witness=t.witness[:keep],
                        expected=t.expected[:cut], source_pair=t.source_pair,
                        bound=t.bound, solver_seconds=t.solver_seconds,
                        mask=None if t.mask is None else t.mask[:cut])
        if nt.asserted_points:
            out.append(nt)
            truncated += 1
        else:
            dropped += 1
    how = "masked" if stateless else "truncated"
    return out, (f"{how} {masked or truncated} test(s), dropped {dropped}, "
                 f"kept {len(out)}/{len(tests)}")


@contextlib.contextmanager
def _model_quiet():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        yield


def _native_failcount(checker_source: str, tbout: str
                      ) -> Tuple[Optional[int], str]:
    """Failures reported by the checker's OWN check_dut over a rendered trace."""
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory(prefix="nfc_") as td:
        Path(td, "TBout.txt").write_text(tbout, encoding="utf-8")
        try:
            os.chdir(td)
            ns: Dict[str, object] = {}
            cut = checker_source.find('with open("TBout.txt"')
            defs = checker_source if cut == -1 else checker_source[:cut]
            with _model_quiet():
                exec(compile(defs, "<frozen>", "exec"), ns)
                vecs = ns["SignalTxt_to_dictlist"](tbout)
                failed = ns["check_dut"](vecs)
            return len(list(failed)), ""
        except Exception as exc:
            return None, f"{type(exc).__name__}"
        finally:
            os.chdir(cwd)


def suite_simulates(shadow_driver: str, channel1_driver: str,
                    candidates: Dict[str, str], workdir: Path
                    ) -> Tuple[bool, str]:
    """The suite we ship must run on real RTL that the frozen driver also runs.

    Compiling only against the frozen driver's declarations is not enough: a
    port-list or width slip shows up at elaboration. Requiring a candidate on
    which BOTH drivers elaborate separates our defect from a broken candidate --
    if Channel 1 compiles there and Channel 2 does not, the fault is ours.
    """
    import subprocess

    def elaborate(rtl: str, driver: str) -> bool:
        for f in workdir.glob("*"):
            if f.is_file():
                f.unlink()
        (workdir / "dut.v").write_text(rtl, encoding="utf-8")
        (workdir / "tb.v").write_text(driver, encoding="utf-8")
        try:
            c = subprocess.run(["iverilog", "-g2012", "-o", "sim", "dut.v", "tb.v"],
                               cwd=workdir, capture_output=True, text=True, timeout=90)
        except subprocess.TimeoutExpired:
            return False
        if c.returncode != 0:
            return False
        try:
            subprocess.run(["vvp", "sim"], cwd=workdir, capture_output=True,
                           text=True, timeout=90)
        except subprocess.TimeoutExpired:
            return False
        return (workdir / "TBout.txt").is_file()

    c1_ok = 0
    for name, rtl in candidates.items():
        if not elaborate(rtl, channel1_driver):
            continue
        c1_ok += 1
        if elaborate(rtl, shadow_driver):
            return True, f"elaborates and runs on {name}"
    if c1_ok == 0:
        return False, "no candidate runs the frozen driver either; cannot check"
    return False, f"shadow driver fails to run on {c1_ok} candidate(s) that Channel 1 runs"


def self_consistent(shadow_driver: str, channel1_driver: str,
                    checker_source: str, candidates: Dict[str, str],
                    workdir: Path) -> Tuple[bool, str]:
    """A shadow test must never reject a design the frozen checker accepts.

    This is the deployment-realistic safety gate: Golden is unavailable at
    generation time, but the candidate RTLs are. Any candidate that passes the
    frozen generator's own Channel 1 suite has been blessed by the checker, so a
    shadow test that rejects it is self-inconsistent and would raise a false
    warning. Such tests are dropped rather than shipped.
    """
    import subprocess

    def run(rtl: str, driver: str) -> Optional[str]:
        for f in workdir.glob("*"):
            if f.is_file():
                f.unlink()
        (workdir / "dut.v").write_text(rtl, encoding="utf-8")
        (workdir / "tb.v").write_text(driver, encoding="utf-8")
        c = subprocess.run(["iverilog", "-g2012", "-o", "sim", "dut.v", "tb.v"],
                           cwd=workdir, capture_output=True, text=True, timeout=90)
        if c.returncode != 0:
            return None
        subprocess.run(["vvp", "sim"], cwd=workdir, capture_output=True,
                       text=True, timeout=90)
        out = workdir / "TBout.txt"
        return out.read_text(encoding="utf-8", errors="replace") if out.is_file() else None

    def verdict(tbout: str) -> Optional[int]:
        import os, tempfile, contextlib, io
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory(prefix="sc_") as td:
            Path(td, "TBout.txt").write_text(tbout, encoding="utf-8")
            try:
                os.chdir(td)
                ns: Dict[str, object] = {}
                cut = checker_source.find('with open("TBout.txt"')
                defs = checker_source if cut == -1 else checker_source[:cut]
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                    exec(compile(defs, "<frozen>", "exec"), ns)
                    vecs = ns["SignalTxt_to_dictlist"](tbout)
                    failed = ns["check_dut"](vecs)
                return len(list(failed))
            except Exception:
                return None
            finally:
                os.chdir(cwd)

    blessed = 0
    for name, rtl in candidates.items():
        t1 = run(rtl, channel1_driver)
        if t1 is None:
            continue
        v1 = verdict(t1)
        if v1 is None or v1 != 0:
            continue                       # checker does not bless this candidate
        blessed += 1
        t2 = run(rtl, shadow_driver)
        if t2 is None:
            return False, f"shadow suite failed to simulate on blessed {name}"
        v2 = verdict(t2)
        if v2 is None or v2 != 0:
            return False, f"shadow suite rejects checker-blessed candidate {name}"
    if blessed == 0:
        return False, "no candidate is blessed by the checker; cannot self-validate"
    return True, f"consistent on {blessed} blessed candidate(s)"


def channel1_accepts(candidates: Dict[str, str], channel1_driver: str,
                     checker_source: str, workdir: Path
                     ) -> Dict[str, Optional[bool]]:
    """Which candidates does the FROZEN Channel 1 suite accept?

    True  accepted -- Channel 1 cannot tell this design from a correct one
    False rejected -- Channel 1 already separates it
    None  did not run (compile error, no TBout, checker raised)

    Golden is not consulted: this is the frozen generator's own verdict on
    candidate RTL, available at generation time exactly as it is at deployment.
    """
    import subprocess
    out: Dict[str, Optional[bool]] = {}
    for name, rtl in candidates.items():
        for f in workdir.glob("*"):
            if f.is_file():
                f.unlink()
        (workdir / "dut.v").write_text(rtl, encoding="utf-8")
        (workdir / "tb.v").write_text(channel1_driver, encoding="utf-8")
        try:
            c = subprocess.run(["iverilog", "-g2012", "-o", "sim", "dut.v", "tb.v"],
                               cwd=workdir, capture_output=True, text=True, timeout=90)
            if c.returncode != 0:
                out[name] = None
                continue
            subprocess.run(["vvp", "sim"], cwd=workdir, capture_output=True,
                           text=True, timeout=90)
        except subprocess.TimeoutExpired:
            out[name] = None
            continue
        tb = workdir / "TBout.txt"
        if not tb.is_file():
            out[name] = None
            continue
        n, _ = _native_failcount(checker_source,
                                tb.read_text(encoding="utf-8", errors="replace"))
        out[name] = None if n is None else (n == 0)
    return out


def rank_pairs(candidates: Dict[str, str],
               accepts: Optional[Dict[str, Optional[bool]]] = None
               ) -> List[Tuple[str, str]]:
    """Order candidate pairs by how much a disagreement between them would be
    worth, before spending any solver time.

    Cross-family only, as before: two samples from one model share their
    mistakes, so a within-family disagreement is weak evidence.

    The ordering is the new part. A witness is only useful if it separates
    designs that Channel 1 does NOT already separate -- if Channel 1 already
    rejects a candidate, a shadow test that also rejects it adds nothing, and
    the pair still costs a full BMC budget. So pairs are ranked:

      0  both accepted by Channel 1  -- two designs the frozen suite cannot tell
                                        apart, yet which provably differ. This is
                                        precisely the blind spot the channel
                                        exists to cover.
      1  one accepted, one rejected  -- partially informative.
      2  neither accepted            -- both already caught; lowest value.
      3  unknown (did not run)       -- no basis to prefer it.

    With `accepts=None` this degenerates to the original fixed order, which is
    what the ablation arm uses.
    """
    names = sorted(candidates)
    pairs: List[Tuple[str, str]] = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if a.rsplit("_", 1)[0] != b.rsplit("_", 1)[0]:
                pairs.append((a, b))
    if accepts is None:
        return pairs

    def rank(pair: Tuple[str, str]) -> Tuple[int, str, str]:
        va, vb = accepts.get(pair[0]), accepts.get(pair[1])
        if va is None or vb is None:
            tier = 3
        elif va and vb:
            tier = 0
        elif va or vb:
            tier = 1
        else:
            tier = 2
        return (tier, pair[0], pair[1])

    return sorted(pairs, key=rank)


def random_witnesses(task_id: str, design: Design, state_model,
                     lengths: Sequence[int], seed: int,
                     prefix: Optional[List[Dict[str, int]]] = None) -> ShadowReport:
    """The stimulus ablation: same test budget, chosen at random.

    Everything downstream is identical to the formal arm -- the same frozen
    checker adjudicates, the same gate applies, the same driver is emitted. Only
    the way the input sequence is CHOSEN differs. That isolates the one question
    the formal machinery has to answer: does solving for a provable disagreement
    between two candidates find anything that uniformly random stimulus of the
    same length and count would not?

    `lengths` comes from the formal arm's own manifest, so the budget matches
    test for test and cycle for cycle rather than by a nominal parameter.
    """
    rng = random.Random(f"{task_id}:{seed}")
    report = ShadowReport(task_id=task_id)
    report.notes.append(f"random stimulus, seed {seed}, "
                        f"{len(lengths)} test(s) matched to the formal arm")
    pre = list(prefix or [])
    for n in lengths:
        report.pairs_attempted += 1
        seq = [{name: rng.getrandbits(w) for name, w in design.inputs.items()}
               for _ in range(max(1, n))]
        report.witnesses_found += 1
        expected = adjudicate(state_model, pre + seq)
        if not any(e is not None for e in expected):
            report.abstained_no_opinion += 1
            continue
        report.adjudicated += 1
        report.tests.append(ShadowTest(
            task_id=task_id, prefix=pre, witness=seq, expected=expected,
            source_pair=("random", "random"), bound=len(seq),
            solver_seconds=0.0))
    return report


def differential_witnesses(task_id: str, candidates: Dict[str, str],
                           design: Design, state_model, bounds: Sequence[int],
                           timeout_s: float, workdir: Path,
                           max_pairs: int = 6,
                           prefix: Optional[List[Dict[str, int]]] = None,
                           accepts: Optional[Dict[str, Optional[bool]]] = None
                           ) -> ShadowReport:
    """Find witnesses where two independent candidates provably disagree.

    Pairs are drawn across DIFFERENT families only. Two samples from the same
    model tend to share their mistakes, so a within-family disagreement is weak
    evidence that anything interesting is happening.

    `accepts` carries the frozen Channel 1 verdict per candidate. When supplied,
    the budget is spent first on pairs Channel 1 cannot separate, which is where
    a new test can add something. Passing None restores the original fixed order
    and is the ablation arm.
    """
    report = ShadowReport(task_id=task_id)
    ranked = rank_pairs(candidates, accepts)
    pairs = ranked[:max_pairs]
    if accepts is not None:
        tiers = [sum(1 for p in pairs
                     if (accepts.get(p[0]) is True and accepts.get(p[1]) is True))]
        report.notes.append(f"pair budget {len(pairs)}/{len(ranked)}, "
                            f"{tiers[0]} in the Channel-1-blind tier")

    seen_witnesses: set = set()
    for a, b in pairs:
        report.pairs_attempted += 1
        found = False
        for depth in bounds:
            status, vlogtb, secs, msg = run_bmc(candidates[a], candidates[b],
                                                design, depth, timeout_s, workdir)
            if status in ("TIMEOUT", "UNSUPPORTED_CONSTRUCT"):
                report.notes.append(f"{a}|{b}: {status} {msg[:60]}")
                break
            if status == "UNSAT":
                continue                      # agree at this bound; try deeper
            if status == "EXTRACTION_FAILED":
                report.witnesses_unparsed += 1
                break
            if uses_internal_state_forcing(vlogtb):
                report.witnesses_rejected_illegal += 1
                break

            seq = parse_vlogtb(vlogtb, design, depth)
            if not seq:
                if design.inputs:
                    report.witnesses_unparsed += 1
                    break
                seq = [{} for _ in range(depth)]

            key = json.dumps(seq, sort_keys=True)
            if key in seen_witnesses:
                break                          # duplicate stimulus, no new information
            seen_witnesses.add(key)
            report.witnesses_found += 1
            found = True

            pre = list(prefix or [])
            # Expectations must cover exactly what the driver will emit:
            # the initialisation prefix and then the witness.
            expected = adjudicate(state_model, pre + seq)
            if not any(e is not None for e in expected):
                report.abstained_no_opinion += 1
                break
            report.adjudicated += 1
            report.tests.append(ShadowTest(
                task_id=task_id, prefix=pre, witness=seq, expected=expected,
                source_pair=(a, b), bound=depth, solver_seconds=secs))
            break
        if not found:
            report.notes.append(f"{a}|{b}: no witness within bounds")
    return report


def emit_shadow_driver(parse, tests: Sequence[ShadowTest],
                       reset_name: Optional[str], reset_active: int) -> str:
    """Emit the shadow tests as one deployable driver.

    Uses the frozen driver's own declarations and print format, so the frozen
    checker can score the output without modification.
    """
    src = next((e for e in parse.events if e.check_en), parse.events[0])
    L = ["`timescale 1ns / 1ps", "module testbench;"]
    for name in ["clk"] + parse.input_signals:
        w = parse.widths.get(name, 1)
        L.append(f"  reg [{w-1}:0] {name};" if w > 1 else f"  reg {name};")
    for name in parse.output_signals:
        w = parse.widths.get(name, 1)
        L.append(f"  wire [{w-1}:0] {name};" if w > 1 else f"  wire {name};")
    L.append("  integer file, scenario;")
    ports = ["clk"] + parse.input_signals + parse.output_signals
    L.append("  top_module DUT (" + ", ".join(f".{p}({p})" for p in ports) + ");")
    L += ["", "  initial begin", "    clk = 0;", "    forever #5 clk = ~clk;",
          "  end", "", "  initial begin",
          '    file = $fopen("TBout.txt", "w");']
    for name in parse.input_signals:
        L.append(f"    {name} = 0;")
    fmt, args = src.fmt, ", ".join(src.args)
    for idx, test in enumerate(tests, start=1):
        L.append(f"    scenario = {idx};")
        for step, vec in enumerate(test.steps):
            for name in parse.input_signals:
                if name in vec:
                    L.append(f"    {name} = {vec[name]};")
            # A masked step still drives its stimulus and still costs a period,
            # so the DUT advances exactly as it would have; it is only withheld
            # from the checker, which therefore cannot judge it.
            if test.asserts(step):
                L.append(f'    $fdisplay(file, "{fmt}", {args});')
            L.append("    #10;")
    L += ["    $fclose(file);", "    $finish;", "  end", "endmodule", ""]
    return chr(10).join(L)
