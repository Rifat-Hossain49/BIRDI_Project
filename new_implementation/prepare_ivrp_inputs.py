#!/usr/bin/env python3
"""Build the frozen inputs for the IVRP Stage-1 experiment.

Emits, from artefacts already on disk:

  pilot_task_ids.json      the 20 frozen pilot task ids
  spec_tasks_pilot.jsonl   sanitised specification + interface for those 20
  population_a_vote.json   point-hash -> method -> population A cross-method vote

The population A vote is the cross-method majority already measured by
analysis/arbitration_prototype.py, computed with the judged method held out. It
is required by Rule F, which fires only where population A supports the current
expectation. No golden artefact is read here.
"""
from __future__ import annotations

import collections
import csv
import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "kaggle_upload_ivrp" / "dataset" / "active_tb_s_ivrp_v1"
PILOT_EVAL = (ROOT / "kaggle_runs/typed_formal_evaluation_pilot_v6_complete"
              / "active_tb_s_evaluation_pilot_v1/spec_only_eval2_per_task.csv")
FROZEN = ROOT / "kaggle_runs/spec_only_full_synthesis_v1_complete/active_tb_s_frozen_full_v1.zip"
FULL_SPEC = ROOT / "kaggle_upload_spec_only_full_oracle/dataset/active_tb_s_oracle_full_v1/spec_tasks_full.jsonl"


def load_prototype():
    spec = importlib.util.spec_from_file_location("ap", ROOT / "analysis/arbitration_prototype.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def key_hash(key) -> str:
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    pilot = sorted({r["task_id"] for r in csv.DictReader(PILOT_EVAL.open(encoding="utf-8"))})
    if len(pilot) != 20:
        raise RuntimeError(f"expected 20 pilot tasks, got {len(pilot)}")
    (OUT / "pilot_task_ids.json").write_text(json.dumps(pilot, indent=1), encoding="utf-8")
    print("pilot tasks:", len(pilot))

    rows = [json.loads(l) for l in FULL_SPEC.read_text(encoding="utf-8").splitlines() if l.strip()]
    keep = [r for r in rows if r["task_id"] in set(pilot)]
    if len(keep) != 20:
        raise RuntimeError(f"spec rows for pilot: {len(keep)}")
    for r in keep:
        if set(r) != {"task_id", "description", "header"}:
            raise RuntimeError(f"unexpected spec fields: {sorted(r)}")
    (OUT / "spec_tasks_pilot.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in keep), encoding="utf-8")
    print("spec rows written:", len(keep))

    ap = load_prototype()
    frozen = ap.load_frozen(FROZEN, "seed_017")
    frozen = {k: v for k, v in frozen.items() if k[1] in set(pilot)}
    index, located = ap.build_index(frozen)

    votes = collections.defaultdict(dict)
    for (task, key), per_method in index.items():
        kh = key_hash(key)
        for method in per_method:
            others = {m: v for m, v in per_method.items() if m != method}
            if not others:
                continue
            winner, _, _ = ap.vote(others)
            if winner is not None:
                votes[kh][method] = winner
    (OUT / "population_a_vote.json").write_text(json.dumps(votes, indent=0), encoding="utf-8")
    print("population A votes recorded for", len(votes), "check points")

    (OUT / "IVRP_BOUNDARY.json").write_text(json.dumps({
        "stage": "stage_1_screening",
        "task_count": 20,
        "allowed_spec_fields": ["task_id", "description", "header"],
        "forbidden_in_this_dataset": [
            "module_code", "canonical_solution", "testbench", "mutants",
            "golden_rtl", "official_test",
        ],
        "population_b_sees": ["description", "header"],
        "golden_artifacts_in_dataset": False,
    }, indent=2), encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
