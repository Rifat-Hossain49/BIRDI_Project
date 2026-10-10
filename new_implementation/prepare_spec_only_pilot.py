#!/usr/bin/env python3
"""Prepare physically separated ACTIVE-TB-S pilot artifacts."""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROJECT = ROOT / "extracted_v1" / "active_tb_budgeted_adaptive"
HDLBITS = ROOT / "baselines" / "CorrectBench" / "data" / "HDLBits"
UPLOAD = ROOT / "kaggle_upload_spec_only_pilot"
ORACLE_STAGE = UPLOAD / "oracle_dataset" / "active_tb_s_oracle_pilot_v1"
ORACLE_DATASET = UPLOAD / "oracle_dataset_publish"
ORACLE_KERNEL = UPLOAD / "oracle_kernel"
ORACLE_NOTEBOOK = ROOT / "ACTIVE_TB_S_Oracle_Pilot_Kaggle.ipynb"

PILOT_IDS = [
    "mux2to1v", "ringer", "kmap3", "popcount3", "fadd",
    "mux256to1", "vector4", "7458", "m2014_q6b", "gates100",
    "dff8ar", "count10", "lfsr5", "fsm1", "fsm_serial",
    "edgecapture", "rule90", "review2015_fsmseq", "gshare", "countbcd",
]


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


if ORACLE_STAGE.exists():
    shutil.rmtree(ORACLE_STAGE)
ORACLE_STAGE.mkdir(parents=True)

# Only oracle-generation source and sanitized specs enter this phase. Evaluation
# scripts are deliberately excluded so the isolation boundary is visible in the
# artifact itself, not merely enforced by convention.
for path in (PROJECT / "active_tb").glob("*.py"):
    copy_file(path, ORACLE_STAGE / "project" / path.relative_to(PROJECT))
for name in ["generate_spec_oracles.py", "spec_only_smoke_test.py"]:
    copy_file(PROJECT / name, ORACLE_STAGE / "project" / name)
copy_file(PROJECT / "requirements.txt", ORACLE_STAGE / "project" / "requirements.txt")

rows = [json.loads(line) for line in (HDLBITS / "HDLBits_data.jsonl").read_text().splitlines() if line.strip()]
by_id = {str(row["task_id"]): row for row in rows}
with (ORACLE_STAGE / "spec_tasks_pilot.jsonl").open("w", encoding="utf-8") as handle:
    for task_id in PILOT_IDS:
        row = by_id[task_id]
        clean = {"task_id": task_id, "description": row["description"], "header": row["header"]}
        assert not ({"module_code", "testbench", "mutants"} & set(clean))
        handle.write(json.dumps(clean, sort_keys=True) + "\n")
(ORACLE_STAGE / "LEAKAGE_BOUNDARY.json").write_text(json.dumps({
    "allowed_fields": ["task_id", "description", "header"],
    "forbidden_fields": ["module_code", "canonical_solution", "testbench", "mutants", "golden_rtl"],
    "task_ids": PILOT_IDS,
    "golden_artifacts_in_dataset": False,
}, indent=2))

ORACLE_DATASET.mkdir(parents=True, exist_ok=True)
oracle_zip = ORACLE_DATASET / "active_tb_s_oracle_pilot_v1.zip"
with zipfile.ZipFile(oracle_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for path in ORACLE_STAGE.rglob("*"):
        if path.is_file():
            archive.write(path, (Path(ORACLE_STAGE.name) / path.relative_to(ORACLE_STAGE)).as_posix())
(ORACLE_DATASET / "dataset-metadata.json").write_text(json.dumps({
    "title": "ACTIVE-TB-S Spec-Only Oracle Pilot v1",
    "id": "tishaferdous/active-tb-s-spec-only-oracle-pilot-v1",
    "licenses": [{"name": "MIT"}],
}, indent=2))

notebook = {
    "cells": [
        markdown_cell("""# ACTIVE-TB-S: Physically Isolated Spec-Only Oracle Pilot

This phase sees only `task_id`, natural-language `description`, and the required module `header`. It generates two executable oracle candidates with Qwen and three with Llama 3.1. Golden RTL, official testbenches, and mutants are not present in the attached dataset.
""", "intro"),
        code_cell("""# 1) Locate the sanitized artifact and copy executable code to writable storage.
from pathlib import Path
import json, os, shutil, subprocess, sys, zipfile
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
os.environ['TOKENIZERS_PARALLELISM'] = 'false'
os.environ['HF_HOME'] = '/kaggle/working/hf_cache'
os.environ['TRANSFORMERS_CACHE'] = '/kaggle/working/hf_cache'

INPUT = Path('/kaggle/input')
WORK = Path('/kaggle/working')
markers = list(INPUT.rglob('active_tb_s_oracle_pilot_v1/LEAKAGE_BOUNDARY.json'))
if len(markers) == 1:
    SOURCE = markers[0].parent
else:
    archives = list(INPUT.rglob('active_tb_s_oracle_pilot_v1.zip'))
    assert len(archives) == 1, {'markers': markers, 'archives': archives}
    extracted = WORK / 'attached_oracle_source'
    with zipfile.ZipFile(archives[0]) as zf: zf.extractall(extracted)
    SOURCE = extracted / 'active_tb_s_oracle_pilot_v1'
PROJECT = WORK / 'active_tb_s_project'
if PROJECT.exists(): shutil.rmtree(PROJECT)
shutil.copytree(SOURCE/'project', PROJECT)
SPEC_TASKS = SOURCE / 'spec_tasks_pilot.jsonl'
OUT = WORK / 'active_tb_s_oracle_candidates_v1'
OUT.mkdir(exist_ok=True)
print('Sanitized source:', SOURCE)
""", "setup"),
        code_cell("""# 2) Enforce the leakage boundary before any model is loaded.
boundary = json.loads((SOURCE/'LEAKAGE_BOUNDARY.json').read_text())
spec_rows = [json.loads(line) for line in SPEC_TASKS.read_text().splitlines() if line.strip()]
assert len(spec_rows) == 20
assert all(set(row) == {'task_id','description','header'} for row in spec_rows)
for forbidden in boundary['forbidden_fields']:
    assert all(forbidden not in row for row in spec_rows)
assert not list(SOURCE.rglob('*mutant*'))
print('SPEC_ONLY_LEAKAGE_AUDIT_PASS:', len(spec_rows), 'tasks')
""", "leakage"),
        code_cell("""# 3) Install a GPU-compatible generation/runtime stack.
subprocess.run(['apt-get','update','-qq'], check=True)
subprocess.run(['apt-get','install','-y','-qq','iverilog'], check=True)
# Kaggle may allocate a Pascal P100 even when a generic GPU is requested. Its
# newest base-image PyTorch can omit sm_60 kernels, so use a wheel that supports
# both P100 and T4 instead of relying on the mutable image default.
subprocess.run([sys.executable,'-m','pip','install','-q','--no-cache-dir','--force-reinstall',
                'torch==2.5.1','--index-url','https://download.pytorch.org/whl/cu121'], check=True)
subprocess.run([sys.executable,'-m','pip','uninstall','-y','-q','torchvision','torchaudio'], check=False)
subprocess.run([sys.executable,'-m','pip','install','-q','--no-cache-dir',
                'transformers==4.57.6','accelerate>=1.0,<2','bitsandbytes==0.48.2','tqdm>=4.66'], check=True)
gpu_probe = subprocess.run([sys.executable,'-c',
    'import torch; print(torch.__version__, torch.cuda.get_device_name(0), torch.cuda.get_device_capability(0)); '
    'x=torch.ones(1,device="cuda"); print("CUDA_PROBE_PASS",x.item())'],
    text=True, capture_output=True)
print(gpu_probe.stdout)
if gpu_probe.returncode != 0: raise RuntimeError(gpu_probe.stderr)
subprocess.run([sys.executable, str(PROJECT/'spec_only_smoke_test.py')], check=True, cwd=PROJECT)
""", "deps"),
        code_cell("""# 4) Qwen-family independent candidates. Prequantized checkpoint keeps disk use bounded.
QWEN_MODEL = 'unsloth/Qwen2.5-Coder-7B-Instruct-bnb-4bit'
QWEN_OUT = OUT / 'qwen_candidates.jsonl'
cmd = [sys.executable, str(PROJECT/'generate_spec_oracles.py'),
       '--tasks', str(SPEC_TASKS), '--output', str(QWEN_OUT),
       '--model', QWEN_MODEL, '--family', 'qwen', '--candidates-per-task', '2',
       '--max-new-tokens', '900', '--temperature', '0.20', '--repair-attempts', '1', '--resume']
subprocess.run(cmd, check=True, cwd=PROJECT)
print('Qwen rows:', len(QWEN_OUT.read_text().splitlines()))
""", "qwen"),
        code_cell("""# 5) Release Qwen weights/cache before loading the independent Llama family.
import gc
gc.collect()
try:
    import torch
    torch.cuda.empty_cache()
except Exception: pass
cache = Path(os.environ['HF_HOME'])
if cache.exists(): shutil.rmtree(cache)
cache.mkdir(parents=True, exist_ok=True)
print('Qwen cache released')
""", "release"),
        code_cell("""# 6) Meta Llama-family independent candidates.
LLAMA_MODEL = 'unsloth/Llama-3.1-8B-Instruct-unsloth-bnb-4bit'
LLAMA_OUT = OUT / 'llama_candidates.jsonl'
cmd = [sys.executable, str(PROJECT/'generate_spec_oracles.py'),
       '--tasks', str(SPEC_TASKS), '--output', str(LLAMA_OUT),
       '--model', LLAMA_MODEL, '--family', 'llama', '--candidates-per-task', '3',
       '--max-new-tokens', '900', '--temperature', '0.20', '--repair-attempts', '1', '--resume']
subprocess.run(cmd, check=True, cwd=PROJECT)
print('Llama rows:', len(LLAMA_OUT.read_text().splitlines()))
""", "llama"),
        code_cell("""# 7) Validate and package the checkpoint for the gold-free synthesis phase.
expected_rows = {QWEN_OUT: 40, LLAMA_OUT: 60}
for path in [QWEN_OUT, LLAMA_OUT]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert len(rows) == expected_rows[path], (path, len(rows))
    print(path.name, 'compiled', sum(bool(row['compiled']) for row in rows), '/', len(rows))
manifest = {
    'protocol': 'spec-only oracle generation',
    'task_count': 20,
    'input_fields': ['task_id','description','header'],
    'models': [QWEN_MODEL, LLAMA_MODEL],
}
(OUT/'oracle_manifest.json').write_text(json.dumps(manifest, indent=2))
archive = WORK / 'active_tb_s_oracle_candidates_v1.zip'
shutil.make_archive(str(archive.with_suffix('')), 'zip', OUT)
if cache.exists(): shutil.rmtree(cache)
print('Checkpoint:', archive, archive.stat().st_size, 'bytes')
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
ORACLE_NOTEBOOK.write_text(json.dumps(notebook, indent=1) + "\n")
ORACLE_KERNEL.mkdir(parents=True, exist_ok=True)
copy_file(ORACLE_NOTEBOOK, ORACLE_KERNEL / ORACLE_NOTEBOOK.name)
(ORACLE_KERNEL / "kernel-metadata.json").write_text(json.dumps({
    "id": "tishaferdous/active-tb-s-oracle-generation-pilot-v1",
    "title": "ACTIVE-TB-S Oracle Generation Pilot v1",
    "code_file": ORACLE_NOTEBOOK.name,
    "language": "python", "kernel_type": "notebook", "is_private": True,
    "enable_gpu": True, "enable_internet": True,
    "dataset_sources": ["tishaferdous/active-tb-s-spec-only-oracle-pilot-v1"],
    "competition_sources": [], "kernel_sources": [],
}, indent=2))

with zipfile.ZipFile(oracle_zip) as archive:
    assert archive.testzip() is None
    assert all("\\" not in name for name in archive.namelist())
print('Built', oracle_zip, oracle_zip.stat().st_size)
print('Built', ORACLE_NOTEBOOK)
