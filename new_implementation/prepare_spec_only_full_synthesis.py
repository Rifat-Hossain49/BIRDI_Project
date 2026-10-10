#!/usr/bin/env python3
"""Build the resumable gold-free 156-task ACTIVE-TB-S synthesis phase."""
from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROJECT = ROOT / "extracted_v1" / "active_tb_budgeted_adaptive"
UPLOAD = ROOT / "kaggle_upload_spec_only_full_synthesis"
STAGE = UPLOAD / "dataset" / "active_tb_s_synthesis_full_v1"
PUBLISH = UPLOAD / "dataset_publish"
KERNEL = UPLOAD / "kernel"
NOTEBOOK = ROOT / "ACTIVE_TB_S_Synthesis_Full_Kaggle.ipynb"


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def locate(root: Path, name: str) -> Path:
    matches = list(root.rglob(name))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one {name} below {root}, found {matches}")
    return matches[0]


def read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def code_cell(source: str, cell_id: str) -> dict:
    return {
        "cell_type": "code", "execution_count": None, "id": cell_id,
        "metadata": {}, "outputs": [], "source": source.splitlines(keepends=True),
    }


def markdown_cell(source: str, cell_id: str) -> dict:
    return {
        "cell_type": "markdown", "id": cell_id, "metadata": {},
        "source": source.splitlines(keepends=True),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--oracle-output", required=True, type=Path)
    args = parser.parse_args()
    qwen = locate(args.oracle_output, "qwen_candidates.jsonl")
    llama = locate(args.oracle_output, "llama_candidates.jsonl")
    codegemma = locate(args.oracle_output, "codegemma_candidates.jsonl")
    spec = locate(ROOT / "kaggle_upload_spec_only_full_oracle", "spec_tasks_full.jsonl")
    for path, expected in ((qwen, 312), (llama, 468)):
        if len(read_rows(path)) != expected:
            raise RuntimeError(f"Incomplete full candidate file: {path}")
    repairs = read_rows(codegemma)
    if len(repairs) > 312 or len({(r["task_id"], r["candidate_index"]) for r in repairs}) != len(repairs):
        raise RuntimeError(f"Invalid full CodeGemma repair file: {codegemma}")

    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    for path in (PROJECT / "active_tb").glob("*.py"):
        copy_file(path, STAGE / "project" / path.relative_to(PROJECT))
    for name in ["run_spec_only_synthesis.py", "typed_temporal_smoke_test.py"]:
        copy_file(PROJECT / name, STAGE / "project" / name)
    copy_file(spec, STAGE / "spec_tasks_full.jsonl")
    for path in [qwen, llama, codegemma]:
        copy_file(path, STAGE / path.name)
    methods = [
        "single_oracle", "homogeneous_ensemble", "diverse_ensemble",
        "diverse_active", "typed_formal_active",
    ]
    (STAGE / "SYNTHESIS_BOUNDARY.json").write_text(json.dumps({
        "allowed_spec_fields": ["task_id", "description", "header"],
        "candidate_sources": [qwen.name, llama.name, codegemma.name],
        "task_count": 156,
        "golden_artifacts_in_dataset": False,
        "methods": methods,
    }, indent=2), encoding="utf-8")

    PUBLISH.mkdir(parents=True, exist_ok=True)
    dataset_zip = PUBLISH / "active_tb_s_synthesis_full_v1.zip"
    with zipfile.ZipFile(dataset_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in STAGE.rglob("*"):
            if path.is_file():
                archive.write(path, (Path(STAGE.name) / path.relative_to(STAGE)).as_posix())
    (PUBLISH / "dataset-metadata.json").write_text(json.dumps({
        "title": "ACTIVE-TB-S Gold-Free Synthesis Full v1",
        "id": "tishaferdous/active-tb-s-gold-free-synthesis-full-v1",
        "licenses": [{"name": "MIT"}],
    }, indent=2), encoding="utf-8")

    notebook = {
        "cells": [
            markdown_cell("""# ACTIVE-TB-S: Full 156-Task Gold-Free Testbench Synthesis

This phase consumes only sanitized specifications and generated oracle candidates. Five ablation variants, including typed temporal execution plus replay-checked formal disagreement, are hash-frozen before golden evaluation assets become available.
""", "intro"),
            code_cell("""from pathlib import Path
import json, shutil, subprocess, sys, zipfile
INPUT=Path('/kaggle/input'); WORK=Path('/kaggle/working')
markers=list(INPUT.rglob('active_tb_s_synthesis_full_v1/SYNTHESIS_BOUNDARY.json'))
if len(markers)==1: SOURCE=markers[0].parent
else:
 archives=list(INPUT.rglob('active_tb_s_synthesis_full_v1.zip')); assert len(archives)==1,archives
 attached=WORK/'attached_full_synthesis_source'
 with zipfile.ZipFile(archives[0]) as zf: zf.extractall(attached)
 SOURCE=attached/'active_tb_s_synthesis_full_v1'
PROJECT=WORK/'active_tb_s_synthesis_full_project'
if PROJECT.exists(): shutil.rmtree(PROJECT)
shutil.copytree(SOURCE/'project',PROJECT)
OUT=WORK/'active_tb_s_frozen_full_v1'
MASTER_SNAPSHOT=WORK/'active_tb_s_frozen_full_checkpoint.zip'
resume_archives=list(INPUT.rglob('active_tb_s_frozen_full_checkpoint.zip'))
if len(resume_archives)>1: raise RuntimeError(resume_archives)
if OUT.exists(): shutil.rmtree(OUT)
if resume_archives:
 with zipfile.ZipFile(resume_archives[0]) as zf: zf.extractall(OUT)
else: OUT.mkdir()
print('Gold-free full synthesis source:',SOURCE,'resume:',resume_archives)
""", "setup"),
            code_cell("""boundary=json.loads((SOURCE/'SYNTHESIS_BOUNDARY.json').read_text())
assert boundary['golden_artifacts_in_dataset'] is False
assert not list(SOURCE.rglob('*mutant*'))
spec_rows=[json.loads(x) for x in (SOURCE/'spec_tasks_full.jsonl').read_text().splitlines() if x.strip()]
assert len(spec_rows)==156 and all(set(r)=={'task_id','description','header'} for r in spec_rows)
print('FULL_GOLD_FREE_SYNTHESIS_AUDIT_PASS:',len(spec_rows),'tasks')
""", "audit"),
            code_cell("""subprocess.run(['apt-get','update','-qq'],check=True)
subprocess.run(['apt-get','install','-y','-qq','iverilog','yosys','z3'],check=True)
subprocess.run([sys.executable,'-m','pip','install','-q','vcdvcd'],check=True)
subprocess.run([sys.executable,str(PROJECT/'typed_temporal_smoke_test.py')],check=True,cwd=PROJECT)
SEEDS=[17,29,43,59,73]
for seed in SEEDS:
 seed_out=OUT/f'seed_{seed:03d}'; seed_out.mkdir(parents=True,exist_ok=True)
 seed_snapshot=WORK/f'active_tb_s_frozen_seed_{seed:03d}_checkpoint.zip'
 partial=list(INPUT.rglob(seed_snapshot.name))
 if len(partial)>1: raise RuntimeError(partial)
 if partial and not (seed_out/'synthesis_summary.csv').exists():
  with zipfile.ZipFile(partial[0]) as zf: zf.extractall(seed_out)
 cmd=[sys.executable,str(PROJECT/'run_spec_only_synthesis.py'),
  '--tasks',str(SOURCE/'spec_tasks_full.jsonl'),
  '--candidates',*[str(SOURCE/name) for name in boundary['candidate_sources']],
  '--output',str(seed_out),'--cycle-budget','32','--scenario-pool-size','96',
  '--min-oracles','3','--min-consensus','0.75','--pseudo-mutants','24',
  '--max-formal-witness-calls','3','--formal-timeout','10','--random-seed',str(seed),
  '--resume','--snapshot-path',str(seed_snapshot),'--snapshot-every','20']
 subprocess.run(cmd,check=True,cwd=PROJECT)
 shutil.make_archive(str(MASTER_SNAPSHOT.with_suffix('')),'zip',OUT)
 print('Completed seed',seed,'master checkpoint bytes',MASTER_SNAPSHOT.stat().st_size)
""", "synthesize"),
            code_cell("""import pandas as pd
parts=[]
for seed in SEEDS:
 part=pd.read_csv(OUT/f'seed_{seed:03d}'/'synthesis_summary.csv'); part['seed']=seed
 assert len(part)==156*len(boundary['methods']),(seed,len(part))
 manifest=json.loads((OUT/f'seed_{seed:03d}'/'FROZEN_BEFORE_EVALUATION.json').read_text())
 assert manifest['generation_input_fields']==['task_id','description','header']
 assert manifest['random_seed']==seed
 parts.append(part)
summary=pd.concat(parts,ignore_index=True)
assert len(summary)==156*len(boundary['methods'])*len(SEEDS)
summary.to_csv(OUT/'synthesis_summary_all_seeds.csv',index=False)
report=summary.groupby(['seed','method'],as_index=False).agg(tasks=('task_id','count'),supported=('supported','sum'),mean_scenarios=('suite_scenarios','mean'))
print(report.to_string(index=False))
archive=WORK/'active_tb_s_frozen_full_v1.zip'
shutil.make_archive(str(archive.with_suffix('')),'zip',OUT)
print('Frozen full checkpoint:',archive,archive.stat().st_size,'bytes')
""", "package"),
        ],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    NOTEBOOK.write_text(json.dumps(notebook, indent=1) + "\n", encoding="utf-8")
    KERNEL.mkdir(parents=True, exist_ok=True)
    copy_file(NOTEBOOK, KERNEL / NOTEBOOK.name)
    (KERNEL / "kernel-metadata.json").write_text(json.dumps({
        "id": "tishaferdous/active-tb-s-synthesis-full-v1",
        "title": "ACTIVE-TB-S Synthesis Full v1",
        "code_file": NOTEBOOK.name,
        "language": "python", "kernel_type": "notebook", "is_private": True,
        "enable_gpu": False, "enable_internet": True,
        "dataset_sources": ["tishaferdous/active-tb-s-gold-free-synthesis-full-v1"],
        "competition_sources": [], "kernel_sources": [],
    }, indent=2), encoding="utf-8")
    with zipfile.ZipFile(dataset_zip) as archive:
        if archive.testzip() is not None or any("\\" in name for name in archive.namelist()):
            raise RuntimeError("Invalid synthesis dataset archive")
    print("Built", dataset_zip, dataset_zip.stat().st_size)
    print("Built", NOTEBOOK)


if __name__ == "__main__":
    main()
