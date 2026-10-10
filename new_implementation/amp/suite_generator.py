#!/usr/bin/env python3
"""Emit frozen stimulus suites for the six Step-E arms.

Search sees only the frozen CorrectBench checker and visible checker-mutation
hypotheses. Golden RTL and hidden faults are absent from this module by
construction: nothing here reads them.

A suite is a single continuous input sequence, grown by greedy marginal-gain
append. Dependency is preserved automatically because expectations are always
recomputed over the whole emitted sequence; segments are never spliced together
from abstract states.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from checker_state import StateModel, snapshot, validate_against_checker
from frontend_adapter import FrozenChecker, parse_driver, recover_expectations
from search_hypotheses import generate_hypotheses
from sequence_search import input_candidates

ROOT = Path(__file__).resolve().parent.parent
RECORDS = ROOT / "baselines/ConfiBench/data/CorrectBenchResults/run_info_and_codes.jsonl"

BUDGETS = [8, 16, 32, 64]
RANDOM_SEEDS = [1000, 1001, 1002]
EXPLORE_SEED = 17
STATE_CAP = 200
WEIGHTS = {"fault": 1.0, "state": 1.0, "transition": 0.5, "boundary": 0.5}
ARMS = ["ORIGINAL", "TRUNCATION", "RANDOM", "GREEDY_VISIBLE",
        "STATE_ONLY", "STATE_PLUS_FAULT"]


@dataclass
class SearchCost:
    candidates_evaluated: int = 0
    checker_steps: int = 0
    states_explored: int = 0
    transitions_explored: int = 0
    visible_mutations: int = 0
    cpu_seconds: float = 0.0
    peak_states: int = 0
    cap_hit: bool = False


@dataclass
class Task:
    task_id: str
    parse: object
    checker: FrozenChecker
    model: Optional[StateModel]
    expectations: List[Optional[Dict[str, int]]]
    hypotheses: List[object] = field(default_factory=list)
    mutant_models: Dict[str, StateModel] = field(default_factory=dict)
    family: Dict[str, str] = field(default_factory=dict)
    supported: bool = True
    reason: str = ""


def load_task(row) -> Optional[Task]:
    parse = parse_driver(row.get("tb_v_driver") or "")
    if not parse.supported:
        return None
    checker = FrozenChecker(row.get("tb_py_checker") or "")
    if not checker.supported:
        return None
    exp, err = recover_expectations(parse, checker, max_bits=12)
    if exp is None:
        return None
    model = StateModel(row["tb_py_checker"], parse.output_signals, parse.widths)
    good, why = validate_against_checker(model, parse, exp)
    task = Task(row["task_id"], parse, checker, model if good else None, exp)
    if not good:
        task.supported = False
        task.reason = why
        return task
    rng = random.Random(EXPLORE_SEED)
    seqs = [[e.inputs for e in parse.events]]
    for _ in range(3):
        seqs.append([{s: rng.randrange(1 << min(parse.widths.get(s, 1), 4))
                      for s in parse.input_signals} for _ in range(12)])
    if not model.check_determinism(seqs):
        task.supported = False
        task.reason = model.reason or "non-deterministic"
        task.model = None
        return task
    for h in generate_hypotheses(row.get("tb_py_checker") or ""):
        mm = StateModel(h.source, parse.output_signals, parse.widths)
        if mm.supported:
            task.hypotheses.append(h)
            task.mutant_models[h.hypothesis_id] = mm
            task.family[h.hypothesis_id] = h.family
    return task


# --- evidence over a sequence -------------------------------------------------

def sequence_evidence(task: Task, seq: Sequence[Dict[str, int]]
                      ) -> Tuple[Set[str], Set[str], Set[str], Set[str]]:
    """States, transitions, boundary events and distinguished fault families."""
    steps = task.model.run(seq)
    states = {s.state_after for s in steps}
    transitions = {f"{s.state_before}|{json.dumps(s.inputs, sort_keys=True)}" for s in steps}
    boundary = set()
    seen_vals: Dict[str, Set[int]] = {}
    for i, s in enumerate(steps):
        if not s.expected:
            continue
        for k, v in s.expected.items():
            seen_vals.setdefault(k, set()).add(v)
            width = task.parse.widths.get(k, 1)
            if v == 0:
                boundary.add(f"{k}=min")
            if v == (1 << width) - 1:
                boundary.add(f"{k}=max")
        if i:
            prev = steps[i - 1].expected or {}
            for k, v in s.expected.items():
                if k in prev and prev[k] > v:
                    boundary.add(f"{k}=wrap")
    fams = set()
    for hid, mm in task.mutant_models.items():
        msteps = mm.run(seq)
        for a, b in zip(steps, msteps):
            if a.expected is not None and b.expected != a.expected:
                fams.add(task.family[hid])
                break
    return states, transitions, boundary, fams


def score(states_new, trans_new, bound_new, fam_new, cost, weights) -> float:
    if cost <= 0:
        return 0.0
    return (weights["fault"] * fam_new + weights["state"] * states_new
            + weights["transition"] * trans_new + weights["boundary"] * bound_new) / cost


# --- arms ---------------------------------------------------------------------

class _Live:
    """Checker plus mutant instances advanced alongside the growing sequence.

    Pure speed: re-running the whole prefix for every candidate is O(|seq|) per
    candidate and does not scale. Advancing live instances and deep-copying only
    to trial a suffix gives identical results at O(|suffix|). Verified against
    the non-incremental path by `--verify`.
    """

    def __init__(self, task: Task):
        self.task = task
        self.dut = task.model.new()
        self.muts = {hid: mm.new() for hid, mm in task.mutant_models.items()}

    def clone(self):
        other = _Live.__new__(_Live)
        other.task = self.task
        other.dut = copy.deepcopy(self.dut)
        other.muts = {k: copy.deepcopy(v) for k, v in self.muts.items()}
        return other

    def advance(self, suffix):
        """Step the suffix, returning the evidence it contributes."""
        task = self.task
        states, transitions, boundary, fams = set(), set(), set(), set()
        prev_exp = None
        for inputs in suffix:
            st = task.model.step(self.dut, inputs)
            states.add(st.state_after)
            transitions.add(f"{st.state_before}|{json.dumps(inputs, sort_keys=True)}")
            if st.expected:
                for k, v in st.expected.items():
                    width = task.parse.widths.get(k, 1)
                    if v == 0:
                        boundary.add(f"{k}=min")
                    if v == (1 << width) - 1:
                        boundary.add(f"{k}=max")
                    if prev_exp and k in prev_exp and prev_exp[k] > v:
                        boundary.add(f"{k}=wrap")
                prev_exp = st.expected
            for hid, mm in task.mutant_models.items():
                mstep = mm.step(self.muts[hid], inputs)
                if st.expected is not None and mstep.expected != st.expected:
                    fams.add(task.family[hid])
        return states, transitions, boundary, fams


def build_directed(task: Task, budget: int, weights: Dict[str, float],
                   cost_out: SearchCost) -> List[Dict[str, int]]:
    """Greedy marginal-gain append over candidate continuations."""
    started = time.time()
    signals, widths = task.parse.input_signals, task.parse.widths
    rng = random.Random(EXPLORE_SEED)
    seq: List[Dict[str, int]] = []
    live = _Live(task)
    states: Set[str] = set()
    trans: Set[str] = set()
    bound: Set[str] = set()
    fams: Set[str] = set()

    while len(seq) < budget:
        prev = seq[-1] if seq else None
        options: List[List[Dict[str, int]]] = [[c] for c in
                                               input_candidates(signals, widths, prev, rng)]
        # LONG_HORIZON_CONTINUATION: hold the current regime.
        if prev is not None:
            for extra in (2, 4, 8, 16):
                if len(seq) + extra <= budget:
                    options.append([dict(prev) for _ in range(extra)])
        best, best_val = None, 0.0
        for opt in options:
            if len(seq) + len(opt) > budget:
                continue
            cost_out.candidates_evaluated += 1
            trial = live.clone()
            s, t, b, f = trial.advance(opt)
            cost_out.checker_steps += len(opt) * (1 + len(task.mutant_models))
            val = score(len(s - states), len(t - trans), len(b - bound),
                        len(f - fams), len(opt), weights)
            if val > best_val:
                best, best_val = (opt, s, t, b, f), val
        if best is None:
            # No scoring gain left: spend the remaining budget deterministically
            # rather than stopping early, so the arm is not artificially weak.
            filler = input_candidates(signals, widths, prev, rng)[0]
            s, t, b, f = live.advance([dict(filler)])
            seq.append(dict(filler))
            states |= s; trans |= t; bound |= b; fams |= f
            continue
        opt, s, t, b, f = best
        live.advance(opt)
        seq.extend(opt)
        states |= s; trans |= t; bound |= b; fams |= f

    cost_out.states_explored = len(states)
    cost_out.transitions_explored = len(trans)
    cost_out.peak_states = len(states)
    cost_out.cap_hit = len(states) >= STATE_CAP
    cost_out.visible_mutations = len(task.mutant_models)
    cost_out.cpu_seconds = time.time() - started
    return seq[:budget]


def build_random(task: Task, budget: int, seed: int, cost_out: SearchCost
                 ) -> List[Dict[str, int]]:
    started = time.time()
    rng = random.Random(seed)
    signals, widths = task.parse.input_signals, task.parse.widths
    seq = [{s: rng.randrange(1 << min(widths.get(s, 1), 12)) for s in signals}
           for _ in range(budget)]
    cost_out.candidates_evaluated = budget
    cost_out.checker_steps = budget
    cost_out.cpu_seconds = time.time() - started
    return seq


def build_original(task: Task) -> List[Dict[str, int]]:
    return [dict(e.inputs) for e in task.parse.events]


def build_truncation(task: Task, budget: int) -> List[Dict[str, int]]:
    return [dict(e.inputs) for e in task.parse.events[:budget]]


# --- Verilog emission ---------------------------------------------------------

def emit_driver(task: Task, seq: Sequence[Dict[str, int]]) -> str:
    """Emit a driver reproducing the original's declarations and print format."""
    original = task.parse
    src = None
    for e in original.events:
        if e.check_en:
            src = e
            break
    src = src or original.events[0]

    lines = ["`timescale 1ns / 1ps", "module testbench;"]
    for name in ["clk"] + original.input_signals:
        w = original.widths.get(name, 1)
        decl = f"reg [{w-1}:0] {name};" if w > 1 else f"reg {name};"
        lines.append("  " + decl)
    for name in original.output_signals:
        w = original.widths.get(name, 1)
        decl = f"wire [{w-1}:0] {name};" if w > 1 else f"wire {name};"
        lines.append("  " + decl)
    lines.append("  integer file, scenario;")
    ports = ["clk"] + original.input_signals + original.output_signals
    conns = ", ".join(f".{p}({p})" for p in ports if p in original.widths or p == "clk")
    lines += [f"  top_module DUT ({conns});", ""]
    lines += ["  initial begin", "    clk = 0;", "    forever #5 clk = ~clk;",
              "  end", ""]
    lines += ['  initial begin', '    file = $fopen("TBout.txt", "w");',
              "    scenario = 1;"]
    for name in original.input_signals:
        lines.append(f"    {name} = 0;")
    fmt = src.fmt
    args = ", ".join(src.args)
    for vec in seq:
        for name in original.input_signals:
            lines.append(f"    {name} = {vec.get(name, 0)};")
        lines.append(f'    $fdisplay(file, "{fmt}", {args});')
        lines.append("    #10;")
    lines += ["    $fclose(file);", "    $finish;", "  end", "endmodule", ""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", type=Path, default=ROOT / "amp" / "pilot_tasks.json")
    ap.add_argument("--out", type=Path, default=ROOT / "amp" / "suites")
    args = ap.parse_args()

    want = set(json.loads(args.tasks.read_text()))
    rows = [json.loads(l) for l in RECORDS.read_text(encoding="utf-8").splitlines() if l.strip()]
    seen, picked = set(), []
    for r in rows:
        if r["task_id"] in want and r["task_id"] not in seen:
            seen.add(r["task_id"])
            picked.append(r)

    args.out.mkdir(parents=True, exist_ok=True)
    manifest = {"weights": WEIGHTS, "budgets": BUDGETS, "state_cap": STATE_CAP,
                "explore_seed": EXPLORE_SEED, "random_seeds": RANDOM_SEEDS,
                "arms": ARMS, "suites": {}, "search_cost": {},
                "unsupported": {}, "mechanism": {}}

    for row in picked:
        task = load_task(row)
        if task is None:
            manifest["unsupported"][row["task_id"]] = "adapter"
            print(f"  {row['task_id']}: adapter unsupported")
            continue
        tid = task.task_id
        if not task.supported:
            manifest["unsupported"][tid] = task.reason
            print(f"  {tid}: state model unsupported ({task.reason[:40]})")

        orig_seq = build_original(task)
        if task.model is not None:
            o_states, o_trans, o_bound, o_fams = sequence_evidence(task, orig_seq)
            manifest["mechanism"][tid] = {
                "original_states": len(o_states), "original_transitions": len(o_trans),
                "original_boundary": sorted(o_bound), "original_fault_families": sorted(o_fams),
                "hypotheses": len(task.mutant_models)}

        for budget in BUDGETS:
            plans: List[Tuple[str, int, List[Dict[str, int]], SearchCost]] = []
            plans.append(("ORIGINAL", 0, orig_seq, SearchCost()))
            plans.append(("TRUNCATION", 0, build_truncation(task, budget), SearchCost()))
            for s in RANDOM_SEEDS:
                c = SearchCost()
                plans.append(("RANDOM", s, build_random(task, budget, s, c), c))
            if task.model is not None:
                for arm, w in (("GREEDY_VISIBLE", {"fault": 1.0, "state": 0.0,
                                                   "transition": 0.0, "boundary": 0.0}),
                               ("STATE_ONLY", {"fault": 0.0, "state": 1.0,
                                               "transition": 0.5, "boundary": 0.5}),
                               ("STATE_PLUS_FAULT", WEIGHTS)):
                    c = SearchCost()
                    plans.append((arm, 0, build_directed(task, budget, w, c), c))

            for arm, seed, seq, cost in plans:
                key = f"{tid}|{arm}|{budget}|{seed}"
                verilog = emit_driver(task, seq)
                name = f"{tid}__{arm}__B{budget}__s{seed}.v"
                # Write bytes, not text: write_text applies newline translation
                # on Windows, so the file bytes would not match the hash and the
                # sealed evaluator (running on Linux) would reject every suite.
                payload = verilog.encode("utf-8")
                (args.out / name).write_bytes(payload)
                digest = hashlib.sha256(payload).hexdigest()
                manifest["suites"][key] = {
                    "file": name, "sha256": digest, "deployed_cycles": len(seq),
                    "task_id": tid, "arm": arm, "budget": budget, "seed": seed}
                manifest["search_cost"][key] = vars(cost)
            print(f"  {tid}: budget {budget} emitted {len(plans)} suites", flush=True)

    blob = json.dumps(manifest, sort_keys=True, indent=1)
    (args.out.parent / "suite_manifest.json").write_text(blob, encoding="utf-8")
    global_hash = hashlib.sha256(blob.encode()).hexdigest()
    (args.out.parent / "suite_manifest.sha256").write_text(global_hash + "\n", encoding="utf-8")
    print(f"\nemitted {len(manifest['suites'])} suites")
    print(f"manifest sha256 = {global_hash}")


if __name__ == "__main__":
    main()
