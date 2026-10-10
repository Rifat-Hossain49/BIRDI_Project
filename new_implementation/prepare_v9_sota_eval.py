#!/usr/bin/env python3
"""Build the compact ACTIVE-TB-X official Eval2 Kaggle dataset and notebook."""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROJECT = ROOT / "extracted_v1" / "active_tb_budgeted_adaptive"
V8 = ROOT / "kaggle_runs" / "full_trackb_v8_version1" / "active_tb_x_full_156_trackb_v8"
BASE = ROOT / "baselines" / "CorrectBench" / "data" / "HDLBits"
UPLOAD = ROOT / "kaggle_upload_v9_sota_eval"
STAGE = UPLOAD / "stage" / "active_tb_x_sota_eval_v9"
DATASET_DIR = UPLOAD / "dataset"
KERNEL_DIR = UPLOAD / "kernel"
ZIP_PATH = DATASET_DIR / "active_tb_x_sota_eval_v9.zip"
NOTEBOOK = ROOT / "ACTIVE_TB_X_Official_Eval2_Kaggle.ipynb"


def code_cell(source: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": source.splitlines(keepends=True),
    }


def markdown_cell(source: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(keepends=True)}


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


if STAGE.exists():
    shutil.rmtree(STAGE)
STAGE.mkdir(parents=True)

# Runtime source, including the protocol adapter.
for path in PROJECT.rglob("*"):
    if not path.is_file() or "__pycache__" in path.parts:
        continue
    relative = path.relative_to(PROJECT)
    if relative.suffix in {".py", ".txt", ".md"}:
        copy_file(path, STAGE / "project" / relative)

# Official Eval2 task and mutant banks.
copy_file(BASE / "HDLBits_data.jsonl", STAGE / "official" / "HDLBits_data.jsonl")
copy_file(BASE / "HDLBits_data_mutants.jsonl", STAGE / "official" / "HDLBits_data_mutants.jsonl")

# Released aggregate baseline evidence, already derived from all released runs.
copy_file(PROJECT / "sota_eval" / "released_baseline_runs.csv", STAGE / "baselines" / "released_baseline_runs.csv")
copy_file(PROJECT / "sota_eval" / "released_baseline_runs_aggregate.json", STAGE / "baselines" / "released_baseline_runs_aggregate.json")

# V8 task artifacts needed to reconstruct self-checking testbenches.
for task_dir in V8.iterdir():
    if not task_dir.is_dir() or task_dir.name == "shared_task_cache":
        continue
    contract = task_dir / "contract.json"
    suite = task_dir / "b032__active_portfolio_no_llm_suite.json"
    if contract.exists() and suite.exists():
        copy_file(contract, STAGE / "suites" / task_dir.name / contract.name)
        copy_file(suite, STAGE / "suites" / task_dir.name / suite.name)

# A two-row local dataset regenerates only suites absent from Kaggle's paginated download.
task_rows = [json.loads(line) for line in (BASE / "HDLBits_data.jsonl").read_text().splitlines() if line.strip()]
missing_ids = {"zero", "xnorgate"}
with (STAGE / "official" / "missing_tasks.jsonl").open("w", encoding="utf-8") as handle:
    for row in task_rows:
        if row["task_id"] not in missing_ids:
            continue
        transformed = {
            "task_id": row["task_id"],
            "prompt": row["header"],
            "canonical_solution": row["module_code"],
            "detail_description": row["description"],
            "test": row.get("testbench", ""),
        }
        handle.write(json.dumps(transformed) + "\n")

DATASET_DIR.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for path in STAGE.rglob("*"):
        if path.is_file():
            archive.write(path, (Path(STAGE.name) / path.relative_to(STAGE)).as_posix())

notebook = {
    "cells": [
        markdown_cell("""# ACTIVE-TB-X: Official Eval2 Comparison

This compact continuation job reconstructs the two V8 suites missing from the downloaded artifact, then evaluates ACTIVE-TB-X against the exact AutoBench/CorrectBench Eval2 mutant bank.

**Protocol warning:** ACTIVE-TB-X is reference-assisted Track B. AutoBench, CorrectBench, and Direct are spec-only. Their scores are displayed together for test-quality context, but they are not claimed as equal-input generation results.
"""),
        code_cell("""# 1) Locate and unpack the attached v9 dataset.
from pathlib import Path
import json, os, shutil, subprocess, sys, zipfile

os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
sys.dont_write_bytecode = True

INPUT = Path('/kaggle/input')
WORK = Path('/kaggle/working')
matches = list(INPUT.rglob('active_tb_x_sota_eval_v9.zip'))
if len(matches) == 1:
    with zipfile.ZipFile(matches[0]) as zf:
        zf.extractall(WORK)
    ROOT = WORK / 'active_tb_x_sota_eval_v9'
else:
    # Kaggle commonly expands ZIP dataset contents before mounting them.
    markers = list(INPUT.rglob('active_tb_x_sota_eval_v9/official/HDLBits_data.jsonl'))
    assert len(markers) == 1, {'zip_matches': matches, 'markers': markers}
    ROOT = markers[0].parents[1]
PROJECT = ROOT / 'project'
SUITES = ROOT / 'suites'
OFFICIAL = ROOT / 'official'
print('Attached artifact root:', ROOT)
print('Existing V8 suites:', len(list(SUITES.glob('*/b032__active_portfolio_no_llm_suite.json'))))
"""),
        code_cell("""# 2) Install only native verification tools and lightweight Python dependencies.
subprocess.run(['apt-get', 'update', '-qq'], check=True)
subprocess.run(['apt-get', 'install', '-y', '-qq', 'iverilog', 'verilator', 'yosys'], check=True)
subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '--no-cache-dir', 'vcdvcd'], check=True)
sys.path.insert(0, str(PROJECT))
import ast
ast.parse((PROJECT/'sota_eval'/'eval2_adapter.py').read_text())
print('Toolchain ready')
"""),
        code_cell("""# 3) Verify that all V8-supported task suites survived artifact pagination.
supported_suite_ids = {
    path.parent.name for path in SUITES.glob('*/b032__active_portfolio_no_llm_suite.json')
}
documented_unsupported = {'review2015_fancytimer', 'review2015_fsm', 'conwaylife'}
official_ids = {
    json.loads(line)['task_id']
    for line in (OFFICIAL/'HDLBits_data.jsonl').read_text().splitlines() if line.strip()
}
assert official_ids - supported_suite_ids == documented_unsupported, sorted(official_ids - supported_suite_ids)
assert len(supported_suite_ids) == 153, len(supported_suite_ids)
print('V8 supported suites ready:', len(supported_suite_ids))
"""),
        code_cell("""# 4) Run official Eval2 with per-task checkpointing.
EVAL_OUT = WORK / 'active_tb_x_official_eval2_v9'
cmd = [
    sys.executable, str(PROJECT/'sota_eval'/'eval2_adapter.py'),
    '--tasks', str(OFFICIAL/'HDLBits_data.jsonl'),
    '--mutants', str(OFFICIAL/'HDLBits_data_mutants.jsonl'),
    '--suites-root', str(SUITES),
    '--output', str(EVAL_OUT),
    '--timeout', '30', '--resume',
]
subprocess.run(cmd, check=True, cwd=PROJECT)
"""),
        code_cell("""# 5) Show only the paper-facing comparison and protocol labels.
import json, pandas as pd
active = json.loads((EVAL_OUT/'active_tb_eval2_aggregate.json').read_text())
released = json.loads((ROOT/'baselines'/'released_baseline_runs_aggregate.json').read_text())
rows = []
for method, values in released.items():
    rows.append({
        'method': method,
        'input_access': values['input_access'],
        'tasks': values['tasks_per_run'],
        'runs': values['independent_runs'],
        'Eval2 exact pass@1': values['mean_eval2_exact_pass_at_1'],
        'Eval2 loose pass@1 (>=0.8)': values['mean_eval2_loose_pass_at_1_0_8'],
    })
rows.append({
    'method': active['method'], 'input_access': active['input_access'],
    'tasks': active['tasks_supported'], 'runs': 1,
    'Eval2 exact pass@1': active['eval2_exact_pass_at_1'],
    'Eval2 loose pass@1 (>=0.8)': active['eval2_loose_pass_at_1_0_8'],
})
comparison = pd.DataFrame(rows).sort_values('Eval2 loose pass@1 (>=0.8)', ascending=False)
display(comparison.style.format({'Eval2 exact pass@1':'{:.3f}', 'Eval2 loose pass@1 (>=0.8)':'{:.3f}'}))
comparison.to_csv(EVAL_OUT/'official_eval2_comparison.csv', index=False)
print(json.dumps(active, indent=2))
assert active['tasks_supported'] >= 153, active
"""),
        code_cell("""# 6) Save a compact resumable output, excluding disposable tool caches.
archive = WORK / 'active_tb_x_official_eval2_v9_results.zip'
shutil.make_archive(str(archive.with_suffix('')), 'zip', EVAL_OUT)
print('Result archive:', archive, archive.stat().st_size, 'bytes')
"""),
    ],
    "metadata": {
        "accelerator": "GPU",
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.11"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}
NOTEBOOK.write_text(json.dumps(notebook, indent=1) + "\n")

KERNEL_DIR.mkdir(parents=True, exist_ok=True)
copy_file(NOTEBOOK, KERNEL_DIR / NOTEBOOK.name)
(DATASET_DIR / "dataset-metadata.json").write_text(json.dumps({
    "title": "ACTIVE-TB-X Official Eval2 v9",
    "id": "tishaferdous/active-tb-x-official-eval2-v9",
    "licenses": [{"name": "MIT"}],
}, indent=2))
(KERNEL_DIR / "kernel-metadata.json").write_text(json.dumps({
    "id": "tishaferdous/active-tb-x-official-eval2-benchmark-v9",
    "title": "ACTIVE-TB-X Official Eval2 Benchmark v9",
    "code_file": NOTEBOOK.name,
    "language": "python",
    "kernel_type": "notebook",
    "is_private": True,
    "enable_gpu": True,
    "enable_internet": True,
    "dataset_sources": ["tishaferdous/active-tb-x-official-eval2-v9"],
    "competition_sources": [],
    "kernel_sources": [],
}, indent=2))

with zipfile.ZipFile(ZIP_PATH) as archive:
    bad = archive.testzip()
    assert bad is None, bad
    assert all("\\" not in name for name in archive.namelist())
print(f"Built {ZIP_PATH} ({ZIP_PATH.stat().st_size} bytes)")
print(f"Built {NOTEBOOK}")
