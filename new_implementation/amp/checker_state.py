#!/usr/bin/env python3
"""The frozen checker as an executable transition system.

Compaction showed that selecting subsets of the original stimulus is exhausted
above ~16 cycles, so amplification must generate new trajectories. To do that we
need to know what state the checker is in, not merely what it recently observed.

The frozen `GoldenDUT` already carries that state. This module drives the
checker's own `load()` and snapshots its instance dictionary. That is
introspection, not reimplementation: no expected-value logic is rewritten.

Because the artefacts span several templates (some call `check()` before
`load()`, others call `load()` from inside `check()`), driving `load()` directly
is NOT automatically equivalent to the `check_dut` path. Every task must pass
`validate_against_checker` before its state model is used; a task that fails is
downgraded rather than assumed.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple


# The frontends' checker files end with a driver block that reads TBout.txt at
# import time. Everything up to it is definitions, which is all we execute.
_TBOUT_OPEN = 'with open("TBout.txt"'


@contextlib.contextmanager
def _muted():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        yield


def _canonical(value, depth: int = 0):
    """Deterministic serialisation of checker state.

    Excludes anything that is not behavioural: object identity, file handles,
    callables, modules. Unknown objects fall back to their own __dict__ so a
    checker holding a small helper object still yields a stable key.
    """
    if depth > 6:
        return "..."
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_canonical(v, depth + 1) for v in value]
    if isinstance(value, set):
        return sorted(_canonical(v, depth + 1) for v in value)
    if isinstance(value, dict):
        return {str(k): _canonical(v, depth + 1) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if hasattr(value, "__dict__"):
        return {str(k): _canonical(v, depth + 1)
                for k, v in sorted(vars(value).items())
                if not k.startswith("_") and not callable(v)}
    return None                                  # unserialisable: not behavioural


def snapshot(dut) -> str:
    state = {k: _canonical(v) for k, v in sorted(vars(dut).items())
             if not k.startswith("_") and not callable(v)}
    return json.dumps(state, sort_keys=True, default=str)


@dataclass
class Step:
    inputs: Dict[str, int]
    state_before: str
    state_after: str
    expected: Optional[Dict[str, int]]


@dataclass
class StateModel:
    """Drives a frozen checker as a transition system."""
    checker_source: str
    outputs: List[str]
    widths: Dict[str, int]
    supported: bool = True
    reason: str = ""
    deterministic: bool = False
    _ns: Dict[str, object] = field(default_factory=dict)
    # (canonical state, inputs) -> expectation. The determinism gate guarantees
    # this mapping is a function, so memoising it cannot change any result; it
    # only avoids re-sweeping the output space for states already seen. This is
    # the dominant cost on wide outputs (review2015_count1k probes 1024
    # candidates per step).
    _exp_cache: Dict[Tuple[str, str], Optional[Dict[str, int]]] = field(default_factory=dict)

    def __post_init__(self):
        src = self.checker_source
        cut = src.find('with open("TBout.txt"')
        defs = src if cut == -1 else src[:cut]
        try:
            with _muted():
                exec(compile(defs, "<checker_model>", "exec"), self._ns)
        except Exception as exc:
            self.supported = False
            self.reason = f"load failed: {type(exc).__name__}: {exc}"
            return
        if "GoldenDUT" not in self._ns:
            self.supported = False
            self.reason = "no GoldenDUT"

    def new(self):
        return self._ns["GoldenDUT"]()

    def _vector(self, inputs: Dict[str, int], scenario=0, check_en=True,
                observed: Optional[Dict[str, int]] = None) -> Dict[str, object]:
        vec: Dict[str, object] = dict(inputs)
        vec["scenario"] = scenario
        vec["check_en"] = check_en
        for o in self.outputs:
            vec[o] = (observed or {}).get(o, 0)
        return vec

    def accepted_values(self, dut, inputs: Dict[str, int], limit: int = 2
                        ) -> Optional[List[Dict[str, int]]]:
        """Every output value this checker instance would accept right now, up
        to `limit`. None means the sweep is not usable (too wide, or the checker
        raised).

        An EMPTY list is meaningful and distinct from None: the checker accepts
        nothing here, so any suite asserting this point rejects every design,
        Golden included. `expected_from` collapses that case into None, which is
        why the translation gate calls this directly.
        """
        bits = {o: min(self.widths.get(o, 1), 12) for o in self.outputs}
        total = 1
        for o in self.outputs:
            total *= 1 << bits[o]
            if total > 4096:
                return None
        import itertools
        accepted: List[Dict[str, int]] = []
        for combo in itertools.product(*[range(1 << bits[o]) for o in self.outputs]):
            probe = copy.deepcopy(dut)
            assign = dict(zip(self.outputs, combo))
            try:
                with _muted():
                    ok = probe.check(self._vector(inputs, observed=assign))
            except Exception:
                return None
            if ok:
                accepted.append(assign)
                if len(accepted) >= limit:
                    break
        return accepted

    def expected_from(self, dut, inputs: Dict[str, int]) -> Optional[Dict[str, int]]:
        """The UNIQUE output value this checker instance will accept right now.

        Sweeps candidate observations through the checker's own `check()`, so
        the accepted value comes from the frozen logic, not from a model of it.
        None where the accepted value is not unique -- that is an abstention,
        never a guess.
        """
        acc = self.accepted_values(dut, inputs, limit=2)
        if acc is None or len(acc) != 1:
            return None
        return acc[0]

    def step(self, dut, inputs: Dict[str, int]) -> Step:
        before = snapshot(dut)
        key = (before, json.dumps(inputs, sort_keys=True))
        if key in self._exp_cache:
            exp = self._exp_cache[key]
        else:
            exp = self.expected_from(dut, inputs)
            self._exp_cache[key] = exp
        try:
            with _muted():
                dut.load(self._vector(inputs, observed=exp))
        except Exception as exc:
            self.supported = False
            self.reason = f"load raised: {type(exc).__name__}: {exc}"
            return Step(inputs, before, before, exp)
        return Step(inputs, before, snapshot(dut), exp)

    def run(self, sequence: Sequence[Dict[str, int]]) -> List[Step]:
        dut = self.new()
        return [self.step(dut, inputs) for inputs in sequence]

    def check_determinism(self, sequences: Sequence[Sequence[Dict[str, int]]]) -> bool:
        """Same canonical state plus same input must give the same successor.

        A checker that fails this is not a usable transition system, however
        well it behaves on its original trace.
        """
        seen: Dict[Tuple[str, str], Tuple[str, str]] = {}
        for seq in sequences:
            for st in self.run(seq):
                key = (st.state_before, json.dumps(st.inputs, sort_keys=True))
                val = (st.state_after, json.dumps(st.expected, sort_keys=True))
                if key in seen and seen[key] != val:
                    self.deterministic = False
                    self.reason = "non-deterministic transition"
                    return False
                seen[key] = val
        self.deterministic = True
        return True


def validate_against_checker(model: StateModel, parse, recovered_expectations
                             ) -> Tuple[bool, str]:
    """Direct-drive must agree with the check_dut path on the ORIGINAL stimulus.

    This is the gate that decides whether a task's state model may be used. It
    compares the expectations produced by stepping `load()` directly against the
    expectations recovered through the frozen `check_dut`, position by position,
    on the driver's own event sequence.
    """
    if not model.supported:
        return False, model.reason
    steps = model.run([e.inputs for e in parse.events])
    if not model.supported:
        return False, model.reason
    agree = mismatch = 0
    for i, st in enumerate(steps):
        ref = recovered_expectations[i]
        if ref is None:
            continue
        if st.expected == ref:
            agree += 1
        else:
            mismatch += 1
    if agree == 0:
        return False, "no comparable expectations"
    if mismatch:
        return False, f"direct-drive disagrees at {mismatch}/{agree + mismatch} positions"
    return True, ""


class _Stateless:
    """A state object that carries nothing, so every step is independent."""

    def load(self, _vector) -> None:
        return None


@dataclass
class StatelessModel:
    """Adjudication for frozen checkers that expose no `GoldenDUT`.

    45 of 156 AutoBench checkers are written as a pure function of one test
    vector -- `check_dut` loops over rows and compares each against a helper
    like `compute_expected_output(...)` with nothing carried between rows. The
    original `StateModel` rejected all 45 for having no `GoldenDUT`, which made
    it the single largest addressable loss on that frontend. Structurally these
    are the EASIEST checkers, not the hardest: with no state, the expected value
    at a step depends only on that step's inputs.

    Statelessness is verified, never assumed. `validate_stateless` requires that
    `check_dut` over the whole trace flags exactly the rows it flags when each
    row is presented alone. A checker that quietly accumulates state across the
    loop fails that test and is rejected, as before.

    The checker is still executed verbatim: the accepted value comes from
    running the frontend's own `check_dut` over a rendered one-row TBout, not
    from any model of what it ought to compute.
    """
    checker_source: str
    parse: object                      # DriverParse, for the driver's own fmt
    outputs: List[str]
    widths: Dict[str, int]
    supported: bool = True
    reason: str = ""
    deterministic: bool = True         # trivially: there is no state to diverge
    _ns: Dict[str, object] = field(default_factory=dict)
    _exp_cache: Dict[str, Optional[Dict[str, int]]] = field(default_factory=dict)

    def __post_init__(self):
        src = self.checker_source
        cut = src.find(_TBOUT_OPEN)
        defs = src if cut == -1 else src[:cut]
        try:
            with _muted():
                exec(compile(defs, "<checker_stateless>", "exec"), self._ns)
        except Exception as exc:
            self.supported = False
            self.reason = f"load failed: {type(exc).__name__}: {exc}"
            return
        if "check_dut" not in self._ns or "SignalTxt_to_dictlist" not in self._ns:
            self.supported = False
            self.reason = "no check_dut/SignalTxt_to_dictlist"

    def new(self):
        return _Stateless()

    def _vector(self, inputs: Dict[str, int], scenario=0, check_en=True,
                observed: Optional[Dict[str, int]] = None) -> Dict[str, object]:
        vec: Dict[str, object] = dict(inputs)
        vec["scenario"] = scenario
        vec["check_en"] = check_en
        for o in self.outputs:
            vec[o] = (observed or {}).get(o, 0)
        return vec

    def _failing_rows(self, rows: Sequence[Dict[str, object]]) -> Optional[list]:
        """`check_dut` over rendered rows, using the driver's own print format."""
        from frontend_adapter import Event, render_tbout
        src = next((e for e in self.parse.events if e.check_en), self.parse.events[0])
        events, observed = [], []
        for i, row in enumerate(rows, start=1):
            ins = {k: v for k, v in row.items()
                   if k not in ("scenario", "check_en") and k not in self.outputs}
            events.append(Event(scenario=row.get("scenario", i), check_en=True,
                                inputs=ins, fmt=src.fmt, args=src.args))
            observed.append({o: row.get(o, 0) for o in self.outputs})
        try:
            with _muted():
                txt = render_tbout(self.parse, events, observed)
                vecs = self._ns["SignalTxt_to_dictlist"](txt)
                return list(self._ns["check_dut"](vecs))
        except Exception:
            return None

    def accepted_values(self, dut, inputs: Dict[str, int], limit: int = 2
                        ) -> Optional[List[Dict[str, int]]]:
        bits = {o: min(self.widths.get(o, 1), 12) for o in self.outputs}
        total = 1
        for o in self.outputs:
            total *= 1 << bits[o]
            if total > 4096:
                return None
        import itertools
        accepted: List[Dict[str, int]] = []
        for combo in itertools.product(*[range(1 << bits[o]) for o in self.outputs]):
            assign = dict(zip(self.outputs, combo))
            failed = self._failing_rows([self._vector(inputs, scenario=1,
                                                      observed=assign)])
            if failed is None:
                return None
            if not failed:
                accepted.append(assign)
                if len(accepted) >= limit:
                    break
        return accepted

    def expected_from(self, dut, inputs: Dict[str, int]) -> Optional[Dict[str, int]]:
        acc = self.accepted_values(dut, inputs, limit=2)
        if acc is None or len(acc) != 1:
            return None
        return acc[0]

    def step(self, dut, inputs: Dict[str, int]) -> Step:
        key = json.dumps(inputs, sort_keys=True)
        if key in self._exp_cache:
            exp = self._exp_cache[key]
        else:
            exp = self.expected_from(dut, inputs)
            self._exp_cache[key] = exp
        return Step(inputs, "", "", exp)

    def run(self, sequence: Sequence[Dict[str, int]]) -> List[Step]:
        dut = self.new()
        return [self.step(dut, inputs) for inputs in sequence]

    def check_determinism(self, sequences) -> bool:
        return True


def validate_stateless(model: "StatelessModel", parse, recovered_expectations,
                       max_positional: int = 64) -> Tuple[bool, str]:
    """Two independent conditions, both required.

    1. STATELESSNESS. `check_dut` over the driver's whole trace must flag exactly
       the rows it flags when each row is presented alone. A checker that carries
       state across the loop violates this and is rejected -- the pure-function
       adjudication would be unsound for it.
    2. AGREEMENT. As on the stateful path: the expectations produced by the
       one-row sweep must match those recovered through the full `check_dut`
       replay on the driver's own stimulus.
    """
    if not model.supported:
        return False, model.reason
    if not parse.events:
        return False, "no events"

    probe = [model._vector(e.inputs, scenario=i + 1,
                           observed=(recovered_expectations[i] or {}))
             for i, e in enumerate(parse.events)]

    # Compare per-row VERDICTS, never the returned labels. Most of these drivers
    # hard-code the scenario in the $fdisplay format string ("scenario: 1, x =
    # %d, ..."), so every row is labelled 1 and some checkers report a row index
    # instead; matching label sets against row positions compares two different
    # things and rejects perfectly stateless checkers.
    alone: List[bool] = []
    for i, row in enumerate(probe):
        one = model._failing_rows([row])
        if one is None:
            return False, f"check_dut raised on row {i} alone"
        alone.append(bool(one))

    whole = model._failing_rows(probe)
    if whole is None:
        return False, "check_dut raised on the driver trace"
    if len(whole) != sum(alone):
        return False, (f"not stateless: {len(whole)} failure(s) in context vs "
                       f"{sum(alone)} judged one row at a time")

    # Positional check, where affordable. Growing the prefix one row at a time
    # asks the only question that matters -- did adding THIS row add a failure --
    # without relying on labels, but it costs O(n^2) rendering, and the largest
    # drivers emit over 3000 events. Above the budget the aggregate count above
    # plus the expectation agreement below is what the model is accepted on, and
    # the weaker check is named in the reason so it is never mistaken for the
    # stronger one.
    level = "aggregate"
    if len(probe) <= max_positional:
        prev = 0
        for k in range(1, len(probe) + 1):
            cur = model._failing_rows(probe[:k])
            if cur is None:
                return False, f"check_dut raised on the first {k} row(s)"
            n = len(cur)
            if n < prev:
                return False, ("not stateless: failure count fell from "
                               f"{prev} to {n} when row {k - 1} was added")
            if n - prev > 1:
                return False, (f"not stateless: row {k - 1} added {n - prev} "
                               "failures at once")
            if (n > prev) != alone[k - 1]:
                return False, (f"not stateless: row {k - 1} is judged "
                               "differently alone than in context")
            prev = n
        level = "positional"

    steps = model.run([e.inputs for e in parse.events])
    agree = mismatch = 0
    for i, st in enumerate(steps):
        ref = recovered_expectations[i]
        if ref is None:
            continue
        if st.expected == ref:
            agree += 1
        else:
            mismatch += 1
    if agree == 0:
        return False, "no comparable expectations"
    if mismatch:
        return False, f"one-row sweep disagrees at {mismatch}/{agree + mismatch} positions"
    return True, f"stateless verified ({level}, {agree} expectations matched)"


def build_model(checker_source: str, parse, outputs, widths):
    """Pick the adjudication model that matches the checker's shape.

    Shape is read from the artefact, never assumed from the frontend name: a
    ConfiBench transfer gets whichever model its own checkers call for with no
    code change, which is what keeps the method frozen across frontends.
    """
    if "GoldenDUT" in checker_source:
        return StateModel(checker_source, outputs, widths), "stateful"
    return StatelessModel(checker_source, parse, outputs, widths), "stateless"


def validate_model(model, parse, recovered_expectations) -> Tuple[bool, str]:
    """Dispatch to the validation gate that belongs to this model's shape."""
    if isinstance(model, StatelessModel):
        return validate_stateless(model, parse, recovered_expectations)
    return validate_against_checker(model, parse, recovered_expectations)
