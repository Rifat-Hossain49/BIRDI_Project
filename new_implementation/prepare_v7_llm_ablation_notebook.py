#!/usr/bin/env python3
"""Derive the focused v7 LLM-attribution notebook from the validated v6 notebook."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROJECT = ROOT / "extracted_v1" / "active_tb_budgeted_adaptive"
SOURCE = PROJECT / "ACTIVE_TB_PLUS_Budgeted_Adaptive_Kaggle.ipynb"
OUTPUT = PROJECT / "ACTIVE_TB_X_LLM_Ablation_Kaggle.ipynb"


def set_source(cell: dict, text: str) -> None:
    cell["source"] = text.splitlines(keepends=True)


notebook = json.loads(SOURCE.read_text(encoding="utf-8"))

set_source(
    notebook["cells"][0],
    """# ACTIVE-TB-X v7 - Exact LLM Contribution Ablation

This focused follow-up compares two otherwise identical methods on the same 24 VerilogEval tasks and the same 32-cycle budget:

1. `active_portfolio_no_llm`: temporal objectives + portfolio scheduler + BMC + heuristics + real coverage,
2. `active_portfolio`: the identical pipeline with evidence-gated Qwen proposals enabled.

The paired design isolates the LLM contribution. Mutation banks, visible/hidden splits, seeds, budgets, task order, formal triage, and scoring remain unchanged. Every `(task, method)` result is checkpointed independently.
""",
)

cell10 = "".join(notebook["cells"][10]["source"])
cell10 = cell10.replace(
    '"active_no_llm", "active_adaptive", "active_portfolio"',
    '"active_no_llm", "active_adaptive", "active_portfolio_no_llm", "active_portfolio"',
)
set_source(notebook["cells"][10], cell10)

set_source(
    notebook["cells"][12],
    """# 12) ACTIVE-TB-X exact LLM attribution run.
RUN_LLM_ABLATION = True
if RUN_LLM_ABLATION:
    import subprocess
    OUT = "/kaggle/working/active_tb_x_llm_ablation_v7"
    cmd = [
        str(VENV_PY), str(WORK_PROJECT / "run_budget_sweep.py"),
        "--output", OUT,
        "--limit", "24",
        "--task-start", "0", "--task-end", "156",
        "--budgets", "32",
        "--methods", "active_portfolio_no_llm", "active_portfolio",
        "--random-seeds", "0",
        "--enable-llm", "--model-path", str(QWEN_MODEL_PATH),
        "--per-gpu-memory-gb", "13.25",
        "--max-input-tokens", "2560",
        "--bmc-timeout", "15",
        "--max-bmc-calls", "8",
        "--max-llm-calls", "4",
        "--adaptive-max-rounds", "20",
        "--exploration-pool", "20",
        "--max-exploration-additions", "6",
        "--llm-stagnation-rounds", "2",
        "--coverage-weight", "0.75",
        "--functional-coverage-weight", "1.0",
        "--novelty-weight", "0.35",
        "--family-weight", "0.50",
        "--llm-batch-candidates", "4",
        "--scheduler-exploration-strength", "0.65",
        "--enable-real-coverage",
        "--real-coverage-interval", "2",
        "--real-coverage-timeout", "90",
        "--mutant-triage-timeout", "4",
        "--max-mutants-per-family", "4",
        "--max-mutants-total", "48",
        "--session-hours", "10.25",
        "--stop-before-minutes", "45",
        "--snapshot-every-jobs", "4",
        "--bootstrap-resamples", "2000",
        "--snapshot-path", "/kaggle/working/active_tb_x_llm_ablation_v7_checkpoint_latest.zip",
    ]
    if LOCAL_DATASET:
        cmd += ["--local-dataset", LOCAL_DATASET]
    if BUDGET_SWEEP_CHECKPOINT:
        cmd += ["--resume-from", BUDGET_SWEEP_CHECKPOINT]
    if OLD_FULL_RUN_CHECKPOINT:
        cmd += ["--reuse-contracts-from", OLD_FULL_RUN_CHECKPOINT]
    print(" ".join(map(str, cmd)))
    subprocess.run(cmd, check=True, cwd=WORK_PROJECT)
""",
)

set_source(
    notebook["cells"][13],
    """# 13) Enforce invariants and report exact LLM attribution.
from collections import Counter
from pathlib import Path
import json
import pandas as pd

def validate_sanity_run(root, expected_rows, allowed_budgets, require_llm=False):
    root = Path(root)
    results_path = root / "per_task_results.csv"
    assert results_path.exists(), f"Missing results: {results_path}"
    df = pd.read_csv(results_path)
    assert len(df) == expected_rows, f"Expected {expected_rows} rows in {root}, found {len(df)}"
    assert not df.duplicated(["task_id", "method"]).any(), f"Duplicate jobs in {root}"
    parsed_budget = pd.to_numeric(df["method"].astype(str).str.extract(r"^b(\\d+)__", expand=False), errors="coerce")
    assert parsed_budget.notna().all(), f"Unparseable exact-budget method labels in {root}"
    assert set(parsed_budget.astype(int)).issubset(set(allowed_budgets))
    supported = df["supported"].astype(str).str.lower().eq("true")
    assert supported.all(), f"Unsupported jobs in {root}:\\n{df.loc[~supported, ['task_id', 'method', 'reason']]}"
    over = df.loc[supported & (pd.to_numeric(df["suite_cycles"]) > parsed_budget)]
    assert over.empty, f"Hard cycle-budget violation in {root}:\\n{over[['task_id', 'method', 'suite_cycles']]}"
    for name in ["budget_curve_summary.csv", "aukc_summary.csv", "paired_bootstrap.csv", "experiment_config.json", "experiment_fingerprint.txt"]:
        assert (root / name).exists(), f"Missing {name} in {root}"
    if require_llm:
        runtime = json.loads((root / "llm_runtime.json").read_text())
        devices = {str(v) for v in runtime.get("device_map", {}).values()}
        assert "cuda:0" in devices and "cuda:1" in devices, f"Model did not use both T4s: {devices}"
        assert not ({"cpu", "disk"} & devices), f"Forbidden model offload: {devices}"
    print(f"SANITY_VALIDATION_PASS: {root} | rows={len(df)}")
    return df

smoke_df = validate_sanity_run(
    "/kaggle/working/active_tb_plus_budget_smoke", expected_rows=54, allowed_budgets={8, 16}
)
if RUN_LLM_SMOKE:
    validate_sanity_run(
        "/kaggle/working/active_tb_plus_llm_smoke", expected_rows=2, allowed_budgets={16}, require_llm=True
    )

ablation_root = Path("/kaggle/working/active_tb_x_llm_ablation_v7")
ablation_df = validate_sanity_run(ablation_root, expected_rows=48, allowed_budgets={32}, require_llm=True)
state = json.loads((ablation_root / "run_state.json").read_text())
assert state.get("status") == "complete", state
assert Path("/kaggle/working/active_tb_x_llm_ablation_v7_checkpoint_latest.zip").exists()

summary = pd.read_csv(ablation_root / "budget_curve_summary.csv")
paired = pd.read_csv(ablation_root / "paired_bootstrap.csv")
direct = paired[
    (paired["method_a"] == "active_portfolio")
    & (paired["method_b"] == "active_portfolio_no_llm")
]
assert len(direct) == 1, f"Missing exact paired comparison:\\n{paired}"
print("\\n=== EXACT LLM ABLATION SUMMARY ===")
print(summary.to_string(index=False))
print("\\n=== PAIRED TASK-LEVEL LLM CONTRIBUTION ===")
print(direct.to_string(index=False))

source_counts = Counter()
for path in ablation_root.rglob("b032__active_portfolio_suite.json"):
    for scenario in json.loads(path.read_text()):
        origin = scenario.get("metadata", {}).get("origin_source")
        source_counts[origin or scenario.get("source", "unknown")] += 1
print("\\n=== FULL PORTFOLIO ACCEPTED SCENARIO ORIGINS ===")
print(dict(source_counts))

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

The runner checkpoints every completed `(task, method)` job and writes `active_tb_x_llm_ablation_v7_checkpoint_latest.zip`. If a session ends early, attach that ZIP to the next T4x2 session, set `BUDGET_SWEEP_CHECKPOINT`, and rerun. The experiment fingerprint prevents incompatible results from being mixed.
""",
)

OUTPUT.write_text(json.dumps(notebook, indent=1, ensure_ascii=True) + "\n", encoding="utf-8")
print(OUTPUT)
