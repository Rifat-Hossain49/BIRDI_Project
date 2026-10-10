#!/usr/bin/env python3
"""ACTIVE-TB-D: dependency-preserving distillation of CorrectBench suites.

Keeps the frozen CorrectBench checker byte for byte and selects which of its own
stimulus to run, under an exact deployed-cycle budget.

The point of difference from classical test-suite reduction: these testbenches
are sequential and carry checker state across scenarios, so dropping a scenario
from the middle silently changes what later scenarios test. Every scenario is
therefore tested for independent startability by replaying it from a fresh
checker and requiring identical expectations. A scenario that fails that test
may only be selected together with its full prefix, and the prefix cycles are
charged to the budget.

Selection is family-balanced over a visible checker-mutation bank. Golden RTL and
hidden faults are absent from this module.

Emits: the selected ORIGINAL events, in chronological order, as an executable
driver reproducing the original's declarations and print format.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from compaction import (BUDGETS, TaskModel, build_task, cost_of, detected,
                        families_of, select_greedy)
from suite_generator import emit_driver

ROOT = Path(__file__).resolve().parent.parent
RECORDS = ROOT / "baselines/ConfiBench/data/CorrectBenchResults/run_info_and_codes.jsonl"


class _EmitShim:
    """Adapts a compaction TaskModel to the driver emitter."""

    def __init__(self, model: TaskModel):
        self.parse = model.parse


def select(model: TaskModel, budget: int, by_family: bool) -> Tuple[int, Set[int]]:
    bank = sorted(model.detection)
    _chosen, cost, cov = select_greedy(model, budget, bank, by_family=by_family)
    return cost, cov


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", type=Path, default=ROOT / "amp" / "pilot_tasks.json")
    ap.add_argument("--out", type=Path, default=ROOT / "amp" / "distill_suites")
    ap.add_argument("--max-bits", type=int, default=12)
    args = ap.parse_args()

    want = set(json.loads(args.tasks.read_text()))
    rows = [json.loads(l) for l in RECORDS.read_text(encoding="utf-8").splitlines() if l.strip()]
    seen, picked = set(), []
    for r in rows:
        if r["task_id"] in want and r["task_id"] not in seen:
            seen.add(r["task_id"])
            picked.append(r)

    args.out.mkdir(parents=True, exist_ok=True)
    manifest = {"method": "ACTIVE-TB-D dependency-preserving distillation",
                "budgets": BUDGETS, "suites": {}, "independence": {}, "skipped": {}}

    for row in picked:
        model = build_task(row, args.max_bits)
        if model is None:
            manifest["skipped"][row["task_id"]] = "adapter unsupported"
            print(f"  {row['task_id']}: skipped")
            continue
        tid = model.task_id
        n_ind = sum(1 for v in model.independent.values() if v)
        manifest["independence"][tid] = {
            "scenarios": len(model.scenario_span),
            "independently_startable": n_ind,
            "visible_hypotheses": len(model.detection),
            "original_cycles": len(model.parse.events)}
        if not model.detection:
            print(f"  {tid}: no discriminating hypotheses, distillation degenerate")

        shim = _EmitShim(model)
        for budget in BUDGETS:
            for arm, by_family in (("DISTILL_GREEDY", False), ("DISTILL_FAMILY", True)):
                cost, cov = select(model, budget, by_family)
                # Emit the ORIGINAL events at the covered indices, in order.
                seq = [dict(model.parse.events[i].inputs) for i in sorted(cov)]
                if not seq:
                    seq = [dict(model.parse.events[0].inputs)]
                verilog = emit_driver(shim, seq)
                name = f"{tid}__{arm}__B{budget}__s0.v"
                payload = verilog.encode("utf-8")
                (args.out / name).write_bytes(payload)
                manifest["suites"][f"{tid}|{arm}|{budget}|0"] = {
                    "file": name, "sha256": hashlib.sha256(payload).hexdigest(),
                    "deployed_cycles": len(seq), "task_id": tid, "arm": arm,
                    "budget": budget, "seed": 0,
                    "scenarios_selected": len({model.parse.events[i].scenario for i in cov})}
            print(f"  {tid}: B{budget} distilled", flush=True)

    blob = json.dumps(manifest, sort_keys=True, indent=1)
    (ROOT / "amp" / "distill_manifest.json").write_text(blob, encoding="utf-8")
    digest = hashlib.sha256(blob.encode()).hexdigest()
    (ROOT / "amp" / "distill_manifest.sha256").write_text(digest + "\n", encoding="utf-8")
    print(f"\nemitted {len(manifest['suites'])} suites")
    print(f"manifest sha256 = {digest}")


if __name__ == "__main__":
    main()
