#!/usr/bin/env python3
"""Build the gold-free ACTIVE-TB-S synthesis phase from oracle checkpoints."""
from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROJECT = ROOT / "extracted_v1" / "active_tb_budgeted_adaptive"
UPLOAD = ROOT / "kaggle_upload_spec_only_synthesis"
STAGE = UPLOAD / "dataset" / "active_tb_s_synthesis_pilot_v1"
PUBLISH = UPLOAD / "dataset_publish"
KERNEL = UPLOAD / "kernel"
NOTEBOOK = ROOT / "ACTIVE_TB_S_Synthesis_Pilot_Kaggle.ipynb"


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def code_cell(source: str, cell_id: str) -> dict:
    return {
        "cell_type": "code", "execution_count": None, "id": cell_id,
        "metadata": {}, "outputs": [], "source": source.splitlines(keepends=True),
    }


def markdown_cell(source: str, cell_id: str) -> dict:
    return {"cell_type": "markdown", "id": cell_id, "metadata": {}, "source": source.splitlines(keepends=True)}


def locate(root: Path, name: str) -> Path:
    matches = list(root.rglob(name))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one {name} below {root}, found {matches}")
    return matches[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--oracle-output", required=True, type=Path)
    args = parser.parse_args()

    qwen = locate(args.oracle_output, "qwen_candidates.jsonl")
    llama = locate(args.oracle_output, "llama_candidates.jsonl")
    codegemma_matches = list(args.oracle_output.rglob("codegemma_candidates.jsonl"))
    if len(codegemma_matches) > 1:
        raise RuntimeError(f"Expected at most one CodeGemma checkpoint, found {codegemma_matches}")
    codegemma = codegemma_matches[0] if codegemma_matches else None
    spec = locate(ROOT / "kaggle_upload_spec_only_pilot", "spec_tasks_pilot.jsonl")
    expected_rows = {qwen: 40, llama: 60}
    for path in (qwen, llama):
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(rows) != expected_rows[path]:
            raise RuntimeError(f"Incomplete oracle checkpoint {path}: {len(rows)}/{expected_rows[path]} rows")
    candidate_paths = [qwen, llama]
    if codegemma is not None:
        rows = [json.loads(line) for line in codegemma.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not rows or len(rows) > 40:
            raise RuntimeError(f"Invalid CodeGemma repair checkpoint {codegemma}: {len(rows)} rows")
        keys = {(str(row["task_id"]), int(row["candidate_index"])) for row in rows}
        if len(keys) != len(rows):
            raise RuntimeError("CodeGemma repair checkpoint contains duplicate task/sample keys")
        candidate_paths.append(codegemma)

    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    for path in (PROJECT / "active_tb").glob("*.py"):
        copy_file(path, STAGE / "project" / path.relative_to(PROJECT))
    copy_file(PROJECT / "run_spec_only_synthesis.py", STAGE / "project" / "run_spec_only_synthesis.py")
    copy_file(PROJECT / "typed_temporal_smoke_test.py", STAGE / "project" / "typed_temporal_smoke_test.py")
    copy_file(spec, STAGE / "spec_tasks_pilot.jsonl")
    for path in candidate_paths:
        copy_file(path, STAGE / path.name)
    (STAGE / "SYNTHESIS_BOUNDARY.json").write_text(json.dumps({
        "allowed_spec_fields": ["task_id", "description", "header"],
        "candidate_sources": [path.name for path in candidate_paths],
        "golden_artifacts_in_dataset": False,
        "methods": [
            "single_oracle", "homogeneous_ensemble", "diverse_ensemble",
            "diverse_active", "typed_formal_active",
        ],
    }, indent=2))

    PUBLISH.mkdir(parents=True, exist_ok=True)
    archive_path = PUBLISH / "active_tb_s_synthesis_pilot_v1.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in STAGE.rglob("*"):
            if path.is_file():
                archive.write(path, (Path(STAGE.name) / path.relative_to(STAGE)).as_posix())
    (PUBLISH / "dataset-metadata.json").write_text(json.dumps({
        "title": "ACTIVE-TB-S Gold-Free Synthesis Pilot v1",
        "id": "tishaferdous/active-tb-s-gold-free-synthesis-pilot-v1",
        "licenses": [{"name": "MIT"}],
    }, indent=2))

    notebook = {
        "cells": [
            markdown_cell("""# ACTIVE-TB-S: Gold-Free Testbench Synthesis Pilot

This phase consumes only sanitized specifications and model-generated oracle candidates. It freezes four ablation variants before any golden RTL, official testbench, or benchmark mutant is available.
""", "intro"),
            code_cell("""from pathlib import Path
import json, shutil, subprocess, sys, zipfile
INPUT=Path('/kaggle/input'); WORK=Path('/kaggle/working')
markers=list(INPUT.rglob('active_tb_s_synthesis_pilot_v1/SYNTHESIS_BOUNDARY.json'))
if len(markers)==1: SOURCE=markers[0].parent
else:
    archives=list(INPUT.rglob('active_tb_s_synthesis_pilot_v1.zip')); assert len(archives)==1, archives
    dst=WORK/'attached_synthesis_source'
    with zipfile.ZipFile(archives[0]) as zf: zf.extractall(dst)
    SOURCE=dst/'active_tb_s_synthesis_pilot_v1'
PROJECT=WORK/'active_tb_s_synthesis_project'
if PROJECT.exists(): shutil.rmtree(PROJECT)
shutil.copytree(SOURCE/'project', PROJECT)
OUT=WORK/'active_tb_s_frozen_pilot_v1'; OUT.mkdir(exist_ok=True)
print('Gold-free synthesis source:', SOURCE)
""", "setup"),
            code_cell("""boundary=json.loads((SOURCE/'SYNTHESIS_BOUNDARY.json').read_text())
assert boundary['golden_artifacts_in_dataset'] is False
assert not list(SOURCE.rglob('*mutant*'))
spec_rows=[json.loads(x) for x in (SOURCE/'spec_tasks_pilot.jsonl').read_text().splitlines() if x.strip()]
assert len(spec_rows)==20 and all(set(r)=={'task_id','description','header'} for r in spec_rows)
print('GOLD_FREE_SYNTHESIS_AUDIT_PASS:', len(spec_rows), 'tasks')
""", "audit"),
            code_cell("""subprocess.run(['apt-get','update','-qq'],check=True)
subprocess.run(['apt-get','install','-y','-qq','iverilog','yosys','z3'],check=True)
subprocess.run([sys.executable,'-m','pip','install','-q','vcdvcd'],check=True)
subprocess.run([sys.executable,str(PROJECT/'typed_temporal_smoke_test.py')],check=True,cwd=PROJECT)
cmd=[sys.executable,str(PROJECT/'run_spec_only_synthesis.py'),
 '--tasks',str(SOURCE/'spec_tasks_pilot.jsonl'),
 '--candidates',*[str(SOURCE/name) for name in boundary['candidate_sources']],
 '--output',str(OUT),'--cycle-budget','32','--scenario-pool-size','96',
 '--min-oracles','3','--min-consensus','0.75','--pseudo-mutants','24',
 '--max-formal-witness-calls','3','--formal-timeout','10','--resume']
subprocess.run(cmd,check=True,cwd=PROJECT)
""", "synthesize"),
            code_cell("""import pandas as pd
summary=pd.read_csv(OUT/'synthesis_summary.csv')
assert len(summary)==20*len(boundary['methods'])
report=summary.groupby('method',as_index=False).agg(tasks=('task_id','count'),supported=('supported','sum'),mean_scenarios=('suite_scenarios','mean'))
print(report.to_string(index=False))
manifest=json.loads((OUT/'FROZEN_BEFORE_EVALUATION.json').read_text())
assert manifest['generation_input_fields']==['task_id','description','header']
archive=WORK/'active_tb_s_frozen_pilot_v1.zip'
shutil.make_archive(str(archive.with_suffix('')),'zip',OUT)
print('Frozen checkpoint:',archive,archive.stat().st_size,'bytes')
""", "package"),
        ],
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}},
        "nbformat": 4, "nbformat_minor": 5,
    }
    NOTEBOOK.write_text(json.dumps(notebook, indent=1) + "\n")
    KERNEL.mkdir(parents=True, exist_ok=True)
    copy_file(NOTEBOOK, KERNEL / NOTEBOOK.name)
    (KERNEL / "kernel-metadata.json").write_text(json.dumps({
        "id": "tishaferdous/active-tb-s-synthesis-pilot-v1",
        "title": "ACTIVE-TB-S Synthesis Pilot v1",
        "code_file": NOTEBOOK.name,
        "language": "python", "kernel_type": "notebook", "is_private": True,
        "enable_gpu": False, "enable_internet": True,
        "dataset_sources": ["tishaferdous/active-tb-s-gold-free-synthesis-pilot-v1"],
        "competition_sources": [], "kernel_sources": [],
    }, indent=2))
    print("Built", archive_path)
    print("Built", NOTEBOOK)


if __name__ == "__main__":
    main()
