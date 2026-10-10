#!/usr/bin/env python3
"""Derive the full 156-task model-free Track-B notebook."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROJECT = ROOT / "extracted_v1" / "active_tb_budgeted_adaptive"
SOURCE = PROJECT / "ACTIVE_TB_X_LLM_Ablation_Kaggle.ipynb"
OUTPUT = PROJECT / "ACTIVE_TB_X_Full_156_TrackB_Kaggle.ipynb"


def set_source(cell: dict, text: str) -> None:
    cell["source"] = text.splitlines(keepends=True)


notebook = json.loads(SOURCE.read_text(encoding="utf-8"))

set_source(
    notebook["cells"][0],
    """# ACTIVE-TB-X v8 - Full 156-Task Track-B Benchmark

This notebook runs the frozen, model-free scenario-synthesis configuration on all 156 VerilogEval Human tasks:

1. five deterministic Random trials at an exact 32-cycle budget,
2. `active_portfolio_no_llm` at the same 32-cycle budget,
3. family-balanced visible/hidden mutation banks and formal equivalence triage,
4. temporal objectives, heuristic exploration, BMC witnesses, and real Verilator coverage,
5. method-level checkpointing and paired task-level confidence intervals.

This is the **RTL-available Track B** protocol: generation can inspect the golden RTL and visible mutants, while hidden mutants are used only for final scoring. It must not be presented as a specification-only AutoBench/CorrectBench comparison.
""",
)

set_source(
    notebook["cells"][4],
    """# 4) Dependency and dual-T4 runtime preflight. No model is loaded.
import subprocess
subprocess.run([str(VENV_PY), str(WORK_PROJECT / "environment_smoke_test.py")], check=True, cwd=WORK_PROJECT)
subprocess.run([str(VENV_PY), str(WORK_PROJECT / "check_kaggle_runtime.py")], check=True, cwd=WORK_PROJECT)
""",
)

set_source(
    notebook["cells"][5],
    """# 5) Frozen v8 configuration is model-free.
QWEN_MODEL_PATH = None
print("Contract enrichment: mechanical parser")
print("Scenario generation: temporal portfolio + heuristic exploration + BMC")
print("LLM model loaded: no")
""",
)

set_source(
    notebook["cells"][6],
    """# 6) No model-placement preflight is needed.
RUN_FULL_MODEL_LOAD_PREFLIGHT = False
assert QWEN_MODEL_PATH is None
""",
)

set_source(
    notebook["cells"][9],
    """# 9) Resume checkpoint from this exact v8 experiment only.
from pathlib import Path
BUDGET_SWEEP_CHECKPOINT = None
OLD_FULL_RUN_CHECKPOINT = None

def checkpoint_candidates(root="/kaggle/input"):
    root = Path(root)
    if not root.exists():
        return []
    return sorted(str(p) for p in root.rglob("*trackb*v8*checkpoint*.zip"))

print("Checkpoint candidates:")
for i, path in enumerate(checkpoint_candidates()):
    print(f"[{i}] {path}")
print("BUDGET_SWEEP_CHECKPOINT =", BUDGET_SWEEP_CHECKPOINT)
""",
)

set_source(
    notebook["cells"][11],
    """# 11) LLM smoke is disabled for the frozen model-free benchmark.
RUN_LLM_SMOKE = False
""",
)

set_source(
    notebook["cells"][12],
    """# 12) Full 156-task RTL-available Track-B benchmark.
RUN_FULL_TRACK_B = True
if RUN_FULL_TRACK_B:
    import subprocess
    OUT = "/kaggle/working/active_tb_x_full_156_trackb_v8"
    cmd = [
        str(VENV_PY), str(WORK_PROJECT / "run_budget_sweep.py"),
        "--output", OUT,
        "--task-start", "0", "--task-end", "156",
        "--budgets", "32",
        "--methods", "random", "active_portfolio_no_llm",
        "--random-seeds", "0", "1", "2", "3", "4",
        "--bmc-timeout", "15",
        "--max-bmc-calls", "8",
        "--adaptive-max-rounds", "20",
        "--exploration-pool", "20",
        "--max-exploration-additions", "6",
        "--coverage-weight", "0.75",
        "--functional-coverage-weight", "1.0",
        "--novelty-weight", "0.35",
        "--family-weight", "0.50",
        "--scheduler-exploration-strength", "0.65",
        "--enable-real-coverage",
        "--real-coverage-interval", "2",
        "--real-coverage-timeout", "90",
        "--mutant-triage-timeout", "4",
        "--max-mutants-per-family", "4",
        "--max-mutants-total", "48",
        "--session-hours", "10.25",
        "--stop-before-minutes", "45",
        "--snapshot-every-jobs", "10",
        "--bootstrap-resamples", "5000",
        "--snapshot-path", "/kaggle/working/active_tb_x_full_156_trackb_v8_checkpoint_latest.zip",
    ]
    if LOCAL_DATASET:
        cmd += ["--local-dataset", LOCAL_DATASET]
    if BUDGET_SWEEP_CHECKPOINT:
        cmd += ["--resume-from", BUDGET_SWEEP_CHECKPOINT]
    print(" ".join(map(str, cmd)))
    subprocess.run(cmd, check=True, cwd=WORK_PROJECT)
""",
)

set_source(
    notebook["cells"][13],
    """# 13) Enforce full-run invariants and print the paper-facing comparison.
from pathlib import Path
import json
import pandas as pd

def validate_run(root, expected_rows, allowed_budgets, expected_unsupported_tasks=()):
    root = Path(root)
    df = pd.read_csv(root / "per_task_results.csv")
    assert len(df) == expected_rows, f"Expected {expected_rows} rows, found {len(df)}"
    assert not df.duplicated(["task_id", "method"]).any(), "Duplicate jobs"
    parsed_budget = pd.to_numeric(df["method"].astype(str).str.extract(r"^b(\\d+)__", expand=False), errors="coerce")
    assert parsed_budget.notna().all()
    assert set(parsed_budget.astype(int)).issubset(set(allowed_budgets))
    supported = df["supported"].astype(str).str.lower().eq("true")
    unsupported = df.loc[~supported].copy()
    unsupported_tasks = set(unsupported["task_id"].astype(str))
    assert unsupported_tasks == set(expected_unsupported_tasks), (
        f"Unexpected unsupported tasks: {sorted(unsupported_tasks)}"
    )
    if unsupported_tasks:
        method_count = df["method"].nunique()
        counts = unsupported.groupby("task_id")["method"].nunique()
        assert (counts == method_count).all(), (
            "Unsupported task exclusions must apply symmetrically to every method"
        )
        print("DOCUMENTED_UNSUPPORTED_TASKS")
        print(unsupported[["task_id", "reason"]].drop_duplicates().to_string(index=False))
    assert (pd.to_numeric(df["suite_cycles"]) <= parsed_budget).all(), "Cycle-budget violation"
    for name in ["aggregate_results.csv", "budget_curve_summary.csv", "paired_bootstrap.csv", "run_state.json", "llm_usage.json"]:
        assert (root / name).exists(), f"Missing {name}"
    return df

smoke_df = validate_run("/kaggle/working/active_tb_plus_budget_smoke", 54, {8, 16})
root = Path("/kaggle/working/active_tb_x_full_156_trackb_v8")
full_df = validate_run(
    root,
    936,
    {32},
    expected_unsupported_tasks={"review2015_fancytimer", "review2015_fsm", "conwaylife"},
)
state = json.loads((root / "run_state.json").read_text())
assert state.get("status") == "complete", state
usage = json.loads((root / "llm_usage.json").read_text())
assert usage["contract_enrichment"]["calls"] == 0, usage
assert usage["scenario_generation"]["calls"] == 0, usage
assert not usage["contract_enrichment_enabled"], usage
assert Path("/kaggle/working/active_tb_x_full_156_trackb_v8_checkpoint_latest.zip").exists()

print("\\n=== FULL TRACK-B SUMMARY ===")
print(pd.read_csv(root / "budget_curve_summary.csv").to_string(index=False))
print("\\n=== PAIRED TASK-LEVEL COMPARISON ===")
print(pd.read_csv(root / "paired_bootstrap.csv").to_string(index=False))
print("\\n=== LLM USAGE (MUST BE ZERO) ===")
print(json.dumps(usage, indent=2))

PRESERVE_DISPOSABLE_RUNTIME = False
if not PRESERVE_DISPOSABLE_RUNTIME:
    import os, shutil
    os.chdir("/kaggle/working")
    for disposable in [Path(VENV), Path(WORK_PROJECT), Path("/kaggle/working/active_tb_plus_attached_source")]:
        if disposable.exists():
            shutil.rmtree(disposable)
    print("DISPOSABLE_RUNTIME_CLEANUP_PASS")
""",
)

set_source(
    notebook["cells"][14],
    """## Resume policy

The runner checkpoints each completed `(task, method)` job and writes `active_tb_x_full_156_trackb_v8_checkpoint_latest.zip`. If Kaggle stops early, attach that ZIP to a new session, set `BUDGET_SWEEP_CHECKPOINT`, and rerun. The experiment fingerprint rejects incompatible configurations.
""",
)

OUTPUT.write_text(json.dumps(notebook, indent=1, ensure_ascii=True) + "\n", encoding="utf-8")
print(OUTPUT)
