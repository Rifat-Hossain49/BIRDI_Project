#!/usr/bin/env python3
"""Build the isolated, resumable 156-task ACTIVE-TB-S oracle generation run."""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROJECT = ROOT / "extracted_v1" / "active_tb_budgeted_adaptive"
HDLBITS = ROOT / "baselines" / "CorrectBench" / "data" / "HDLBits"
UPLOAD = ROOT / "kaggle_upload_spec_only_full_oracle"
STAGE = UPLOAD / "dataset" / "active_tb_s_oracle_full_v1"
PUBLISH = UPLOAD / "dataset_publish"
KERNEL = UPLOAD / "kernel"
NOTEBOOK = ROOT / "ACTIVE_TB_S_Oracle_Full_Kaggle.ipynb"


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


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
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    for path in (PROJECT / "active_tb").glob("*.py"):
        copy_file(path, STAGE / "project" / path.relative_to(PROJECT))
    for name in ["generate_spec_oracles.py", "spec_only_smoke_test.py"]:
        copy_file(PROJECT / name, STAGE / "project" / name)
    copy_file(PROJECT / "requirements.txt", STAGE / "project" / "requirements.txt")

    rows = [
        json.loads(line)
        for line in (HDLBITS / "HDLBits_data.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(rows) != 156:
        raise RuntimeError(f"Expected 156 HDLBits tasks, found {len(rows)}")
    clean_rows = []
    for row in rows:
        clean = {
            "task_id": str(row["task_id"]),
            "description": row["description"],
            "header": row["header"],
        }
        if set(clean) != {"task_id", "description", "header"}:
            raise AssertionError(clean)
        clean_rows.append(clean)
    spec_path = STAGE / "spec_tasks_full.jsonl"
    spec_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in clean_rows),
        encoding="utf-8",
    )
    (STAGE / "LEAKAGE_BOUNDARY.json").write_text(json.dumps({
        "allowed_fields": ["task_id", "description", "header"],
        "forbidden_fields": [
            "module_code", "canonical_solution", "testbench", "mutants",
            "golden_rtl", "official_test",
        ],
        "task_count": 156,
        "task_ids": [row["task_id"] for row in clean_rows],
        "golden_artifacts_in_dataset": False,
    }, indent=2), encoding="utf-8")

    PUBLISH.mkdir(parents=True, exist_ok=True)
    dataset_zip = PUBLISH / "active_tb_s_oracle_full_v1.zip"
    with zipfile.ZipFile(dataset_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in STAGE.rglob("*"):
            if path.is_file():
                archive.write(path, (Path(STAGE.name) / path.relative_to(STAGE)).as_posix())
    (PUBLISH / "dataset-metadata.json").write_text(json.dumps({
        "title": "ACTIVE-TB-S Spec-Only Oracle Full v1",
        "id": "tishaferdous/active-tb-s-spec-only-oracle-full-v1",
        "licenses": [{"name": "MIT"}],
    }, indent=2), encoding="utf-8")

    notebook = {
        "cells": [
            markdown_cell("""# ACTIVE-TB-S: Full 156-Task Spec-Only Oracle Generation

This phase receives only `task_id`, natural-language `description`, and module `header`. It generates independent Qwen and Llama RTL behavioral-oracle candidates. Golden RTL, official tests, and benchmark mutants are physically absent. A resumable ZIP is atomically refreshed every eight generated candidates.
""", "intro"),
            code_cell("""from pathlib import Path
import json, os, shutil, subprocess, sys, zipfile
os.environ['PYTHONDONTWRITEBYTECODE']='1'
os.environ['TOKENIZERS_PARALLELISM']='false'
os.environ['HF_HOME']='/kaggle/working/hf_cache'
os.environ['TRANSFORMERS_CACHE']='/kaggle/working/hf_cache'
INPUT=Path('/kaggle/input'); WORK=Path('/kaggle/working')
markers=list(INPUT.rglob('active_tb_s_oracle_full_v1/LEAKAGE_BOUNDARY.json'))
if len(markers)==1: SOURCE=markers[0].parent
else:
    archives=list(INPUT.rglob('active_tb_s_oracle_full_v1.zip')); assert len(archives)==1, archives
    attached=WORK/'attached_full_oracle_source'
    with zipfile.ZipFile(archives[0]) as zf: zf.extractall(attached)
    SOURCE=attached/'active_tb_s_oracle_full_v1'
PROJECT=WORK/'active_tb_s_oracle_full_project'
if PROJECT.exists(): shutil.rmtree(PROJECT)
shutil.copytree(SOURCE/'project',PROJECT)
SPEC_TASKS=SOURCE/'spec_tasks_full.jsonl'
OUT=WORK/'active_tb_s_oracle_full_candidates_v1'; OUT.mkdir(exist_ok=True)
SNAPSHOT=WORK/'active_tb_s_oracle_full_checkpoint.zip'

# Optional resume input: attach a prior checkpoint dataset and rerun unchanged.
resume_archives=[p for p in INPUT.rglob('active_tb_s_oracle_full_checkpoint.zip')]
if len(resume_archives)>1: raise RuntimeError(f'Multiple resume checkpoints: {resume_archives}')
if resume_archives:
    resume_dir=WORK/'resume_full_oracle'
    with zipfile.ZipFile(resume_archives[0]) as zf: zf.extractall(resume_dir)
    for name in ['qwen_candidates.jsonl','llama_candidates.jsonl']:
        matches=list(resume_dir.rglob(name))
        if len(matches)==1: shutil.copy2(matches[0],OUT/name)
print('Sanitized source:',SOURCE,'resume:',resume_archives)
""", "setup"),
            code_cell("""boundary=json.loads((SOURCE/'LEAKAGE_BOUNDARY.json').read_text())
spec_rows=[json.loads(line) for line in SPEC_TASKS.read_text().splitlines() if line.strip()]
assert len(spec_rows)==156
assert all(set(row)=={'task_id','description','header'} for row in spec_rows)
assert boundary['golden_artifacts_in_dataset'] is False
assert not list(SOURCE.rglob('*mutant*'))
print('FULL_SPEC_ONLY_LEAKAGE_AUDIT_PASS:',len(spec_rows),'tasks')
""", "audit"),
            code_cell("""subprocess.run(['apt-get','update','-qq'],check=True)
subprocess.run(['apt-get','install','-y','-qq','iverilog'],check=True)
subprocess.run([sys.executable,'-m','pip','install','-q','--no-cache-dir','--force-reinstall',
                'torch==2.5.1','--index-url','https://download.pytorch.org/whl/cu121'],check=True)
subprocess.run([sys.executable,'-m','pip','uninstall','-y','-q','torchvision','torchaudio'],check=False)
subprocess.run([sys.executable,'-m','pip','install','-q','--no-cache-dir',
                'transformers==4.57.6','accelerate>=1.0,<2','bitsandbytes==0.48.2','tqdm>=4.66'],check=True)
probe=subprocess.run([sys.executable,'-c',
 'import torch; print(torch.__version__,torch.cuda.get_device_name(0),torch.cuda.get_device_capability(0)); x=torch.ones(1,device="cuda"); print("CUDA_PROBE_PASS",x.item())'],
 text=True,capture_output=True)
print(probe.stdout)
if probe.returncode: raise RuntimeError(probe.stderr)
subprocess.run([sys.executable,str(PROJECT/'spec_only_smoke_test.py')],check=True,cwd=PROJECT)
""", "deps"),
            code_cell("""QWEN_MODEL='unsloth/Qwen2.5-Coder-7B-Instruct-bnb-4bit'
QWEN_OUT=OUT/'qwen_candidates.jsonl'
cmd=[sys.executable,str(PROJECT/'generate_spec_oracles.py'),
 '--tasks',str(SPEC_TASKS),'--output',str(QWEN_OUT),
 '--model',QWEN_MODEL,'--family','qwen','--candidates-per-task','2',
 '--max-new-tokens','900','--temperature','0.20','--repair-attempts','1','--resume',
 '--snapshot-path',str(SNAPSHOT),'--snapshot-root',str(OUT),'--snapshot-every','8']
subprocess.run(cmd,check=True,cwd=PROJECT)
print('Qwen rows:',len(QWEN_OUT.read_text().splitlines()))
""", "qwen"),
            code_cell("""import gc
gc.collect()
try:
 import torch
 torch.cuda.empty_cache()
except Exception: pass
cache=Path(os.environ['HF_HOME'])
if cache.exists(): shutil.rmtree(cache)
cache.mkdir(parents=True,exist_ok=True)
print('Qwen cache released; checkpoint bytes:',SNAPSHOT.stat().st_size)
""", "release"),
            code_cell("""LLAMA_MODEL='unsloth/Llama-3.1-8B-Instruct-unsloth-bnb-4bit'
LLAMA_OUT=OUT/'llama_candidates.jsonl'
cmd=[sys.executable,str(PROJECT/'generate_spec_oracles.py'),
 '--tasks',str(SPEC_TASKS),'--output',str(LLAMA_OUT),
 '--model',LLAMA_MODEL,'--family','llama','--candidates-per-task','3',
 '--max-new-tokens','900','--temperature','0.20','--repair-attempts','1','--resume',
 '--snapshot-path',str(SNAPSHOT),'--snapshot-root',str(OUT),'--snapshot-every','8']
subprocess.run(cmd,check=True,cwd=PROJECT)
print('Llama rows:',len(LLAMA_OUT.read_text().splitlines()))
""", "llama"),
            code_cell("""expected={QWEN_OUT:312,LLAMA_OUT:468}
for path,count in expected.items():
 rows=[json.loads(line) for line in path.read_text().splitlines() if line.strip()]
 assert len(rows)==count,(path,len(rows),count)
 assert len({(row['task_id'],row['candidate_index']) for row in rows})==count
 print(path.name,'compiled',sum(bool(row['compiled']) for row in rows),'/',count)
manifest={'protocol':'full spec-only oracle generation','task_count':156,
 'input_fields':['task_id','description','header'],'models':[QWEN_MODEL,LLAMA_MODEL],
 'golden_artifacts_seen':False}
(OUT/'oracle_manifest.json').write_text(json.dumps(manifest,indent=2))
if cache.exists(): shutil.rmtree(cache)
archive=WORK/'active_tb_s_oracle_full_candidates_v1.zip'
shutil.make_archive(str(archive.with_suffix('')),'zip',OUT)
print('Final checkpoint:',archive,archive.stat().st_size,'bytes')
""", "package"),
        ],
        "metadata": {
            "accelerator": "GPU",
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.12"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    NOTEBOOK.write_text(json.dumps(notebook, indent=1) + "\n", encoding="utf-8")
    KERNEL.mkdir(parents=True, exist_ok=True)
    copy_file(NOTEBOOK, KERNEL / NOTEBOOK.name)
    (KERNEL / "kernel-metadata.json").write_text(json.dumps({
        "id": "tishaferdous/active-tb-s-oracle-generation-full-v1",
        "title": "ACTIVE-TB-S Oracle Generation Full v1",
        "code_file": NOTEBOOK.name,
        "language": "python", "kernel_type": "notebook", "is_private": True,
        "enable_gpu": True, "enable_internet": True,
        "dataset_sources": ["tishaferdous/active-tb-s-spec-only-oracle-full-v1"],
        "competition_sources": [], "kernel_sources": [],
    }, indent=2), encoding="utf-8")
    with zipfile.ZipFile(dataset_zip) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Corrupt oracle dataset archive")
        if any("\\" in name for name in archive.namelist()):
            raise RuntimeError("Windows path separator in archive")
    print("Built", dataset_zip, dataset_zip.stat().st_size)
    print("Built", NOTEBOOK)


if __name__ == "__main__":
    main()
