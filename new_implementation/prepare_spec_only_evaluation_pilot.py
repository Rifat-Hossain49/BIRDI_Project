#!/usr/bin/env python3
"""Build the isolated post-freeze ACTIVE-TB-S evaluation phase."""
from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROJECT = ROOT / "extracted_v1" / "active_tb_budgeted_adaptive"
HDLBITS = ROOT / "baselines" / "CorrectBench" / "data" / "HDLBits"
UPLOAD = ROOT / "kaggle_upload_spec_only_evaluation"
STAGE = UPLOAD / "dataset" / "active_tb_s_evaluation_pilot_v1"
PUBLISH = UPLOAD / "dataset_publish"
KERNEL = UPLOAD / "kernel"
NOTEBOOK = ROOT / "ACTIVE_TB_S_Evaluation_Pilot_Kaggle.ipynb"


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def locate(root: Path, name: str) -> Path:
    matches = list(root.rglob(name))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one {name} below {root}, found {matches}")
    return matches[0]


def code_cell(source: str, cell_id: str) -> dict:
    return {"cell_type": "code", "execution_count": None, "id": cell_id, "metadata": {}, "outputs": [], "source": source.splitlines(keepends=True)}


def markdown_cell(source: str, cell_id: str) -> dict:
    return {"cell_type": "markdown", "id": cell_id, "metadata": {}, "source": source.splitlines(keepends=True)}


def subset_jsonl(source: Path, output: Path, task_ids: set[str]) -> None:
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    selected = [row for row in rows if str(row["task_id"]) in task_ids]
    if len(selected) != len(task_ids):
        missing = task_ids - {str(row["task_id"]) for row in selected}
        raise RuntimeError(f"Missing evaluation tasks in {source}: {sorted(missing)}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in selected), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--synthesis-output", required=True, type=Path)
    args = parser.parse_args()
    frozen = locate(args.synthesis_output, "active_tb_s_frozen_pilot_v1.zip")
    specs = locate(ROOT / "kaggle_upload_spec_only_pilot", "spec_tasks_pilot.jsonl")
    task_ids = {
        str(json.loads(line)["task_id"])
        for line in specs.read_text(encoding="utf-8").splitlines() if line.strip()
    }

    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    for path in (PROJECT / "active_tb").glob("*.py"):
        copy_file(path, STAGE / "project" / path.relative_to(PROJECT))
    copy_file(PROJECT / "run_spec_only_evaluation.py", STAGE / "project" / "run_spec_only_evaluation.py")
    copy_file(PROJECT / "sota_eval" / "__init__.py", STAGE / "project" / "sota_eval" / "__init__.py")
    copy_file(PROJECT / "sota_eval" / "eval2_adapter.py", STAGE / "project" / "sota_eval" / "eval2_adapter.py")
    copy_file(frozen, STAGE / "active_tb_s_frozen_pilot_v1.zip")
    subset_jsonl(HDLBITS / "HDLBits_data.jsonl", STAGE / "HDLBits_pilot.jsonl", task_ids)
    subset_jsonl(HDLBITS / "HDLBits_data_mutants.jsonl", STAGE / "HDLBits_mutants_pilot.jsonl", task_ids)
    (STAGE / "EVALUATION_BOUNDARY.json").write_text(json.dumps({
        "phase": "post_freeze_evaluation",
        "frozen_before_golden_access": True,
        "task_count": len(task_ids),
        "task_ids": sorted(task_ids),
        "metrics": ["Eval1", "official_Eval2_exact", "official_Eval2_loose", "raw_mutant_rejection"],
    }, indent=2))

    PUBLISH.mkdir(parents=True, exist_ok=True)
    archive_path = PUBLISH / "active_tb_s_evaluation_pilot_v1.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in STAGE.rglob("*"):
            if path.is_file():
                archive.write(path, (Path(STAGE.name) / path.relative_to(STAGE)).as_posix())
    (PUBLISH / "dataset-metadata.json").write_text(json.dumps({
        "title": "ACTIVE-TB-S Post-Freeze Evaluation Pilot v1",
        "id": "tishaferdous/active-tb-s-post-freeze-evaluation-pilot-v1",
        "licenses": [{"name": "MIT"}],
    }, indent=2))

    notebook = {
        "cells": [
            markdown_cell("""# ACTIVE-TB-S: Post-Freeze Official Evaluation Pilot

This phase receives hash-frozen testbenches plus the VerilogEval golden RTL, official testbenches, and released CorrectBench mutant bank. It cannot modify the generated suites.
""", "intro"),
            code_cell("""from pathlib import Path
import json, shutil, subprocess, sys, zipfile
INPUT=Path('/kaggle/input'); WORK=Path('/kaggle/working')
markers=list(INPUT.rglob('active_tb_s_evaluation_pilot_v1/EVALUATION_BOUNDARY.json'))
if len(markers)==1: SOURCE=markers[0].parent
else:
    archives=list(INPUT.rglob('active_tb_s_evaluation_pilot_v1.zip')); assert len(archives)==1, archives
    dst=WORK/'attached_evaluation_source'
    with zipfile.ZipFile(archives[0]) as zf: zf.extractall(dst)
    SOURCE=dst/'active_tb_s_evaluation_pilot_v1'
PROJECT=WORK/'active_tb_s_evaluation_project'
if PROJECT.exists(): shutil.rmtree(PROJECT)
shutil.copytree(SOURCE/'project',PROJECT)
FROZEN=WORK/'active_tb_s_frozen_pilot_v1'
frozen_archive=SOURCE/'active_tb_s_frozen_pilot_v1.zip'
frozen_directory=SOURCE/'active_tb_s_frozen_pilot_v1'
if frozen_archive.exists():
    with zipfile.ZipFile(frozen_archive) as zf: zf.extractall(FROZEN)
elif frozen_directory.is_dir():
    shutil.copytree(frozen_directory,FROZEN)
else:
    raise FileNotFoundError({'archive':str(frozen_archive),'directory':str(frozen_directory),'source_files':[p.name for p in SOURCE.iterdir()]})
OUT=WORK/'active_tb_s_evaluation_pilot_v1'; OUT.mkdir(exist_ok=True)
print('Evaluation source:',SOURCE)
""", "setup"),
            code_cell("""boundary=json.loads((SOURCE/'EVALUATION_BOUNDARY.json').read_text())
assert boundary['frozen_before_golden_access'] is True
manifest=json.loads((FROZEN/'FROZEN_BEFORE_EVALUATION.json').read_text())
assert manifest['generation_input_fields']==['task_id','description','header']
print('POST_FREEZE_PROVENANCE_AUDIT_PASS:',boundary['task_count'],'tasks')
""", "audit"),
            code_cell("""subprocess.run(['apt-get','update','-qq'],check=True)
subprocess.run(['apt-get','install','-y','-qq','iverilog'],check=True)
cmd=[sys.executable,str(PROJECT/'run_spec_only_evaluation.py'),
 '--frozen-root',str(FROZEN/'frozen'),
 '--tasks',str(SOURCE/'HDLBits_pilot.jsonl'),
 '--mutants',str(SOURCE/'HDLBits_mutants_pilot.jsonl'),
 '--output',str(OUT),'--timeout','30','--resume']
subprocess.run(cmd,check=True,cwd=PROJECT)
""", "evaluate"),
            code_cell("""import pandas as pd
aggregate=pd.read_csv(OUT/'spec_only_eval2_aggregate.csv')
display(aggregate)
per_task=pd.read_csv(OUT/'spec_only_eval2_per_task.csv')
pivot=per_task.pivot(index='task_id',columns='method',values='eval2_ratio')
display(pivot.describe().T)
archive=WORK/'active_tb_s_evaluation_pilot_v1.zip'
shutil.make_archive(str(archive.with_suffix('')),'zip',OUT)
print('Evaluation checkpoint:',archive,archive.stat().st_size,'bytes')
""", "results"),
        ],
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}},
        "nbformat": 4, "nbformat_minor": 5,
    }
    NOTEBOOK.write_text(json.dumps(notebook, indent=1) + "\n")
    KERNEL.mkdir(parents=True, exist_ok=True)
    copy_file(NOTEBOOK, KERNEL / NOTEBOOK.name)
    (KERNEL / "kernel-metadata.json").write_text(json.dumps({
        "id": "tishaferdous/active-tb-s-evaluation-pilot-v1",
        "title": "ACTIVE-TB-S Evaluation Pilot v1",
        "code_file": NOTEBOOK.name,
        "language": "python", "kernel_type": "notebook", "is_private": True,
        "enable_gpu": False, "enable_internet": True,
        "dataset_sources": ["tishaferdous/active-tb-s-post-freeze-evaluation-pilot-v1"],
        "competition_sources": [], "kernel_sources": [],
    }, indent=2))
    print("Built", archive_path)
    print("Built", NOTEBOOK)


if __name__ == "__main__":
    main()
