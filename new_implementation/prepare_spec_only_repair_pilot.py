#!/usr/bin/env python3
"""Build the isolated disagreement-directed third-family repair pilot."""
from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROJECT = ROOT / "extracted_v1" / "active_tb_budgeted_adaptive"
UPLOAD = ROOT / "kaggle_upload_spec_only_repair"
STAGE = UPLOAD / "dataset" / "active_tb_s_disagreement_repair_pilot_v1"
PUBLISH = UPLOAD / "dataset_publish"
KERNEL = UPLOAD / "kernel"
NOTEBOOK = ROOT / "ACTIVE_TB_S_Disagreement_Repair_Kaggle.ipynb"


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def locate(root: Path, name: str) -> Path:
    matches = list(root.rglob(name))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one {name} below {root}, found {matches}")
    return matches[0]


def code_cell(source: str, cell_id: str) -> dict:
    return {
        "cell_type": "code", "execution_count": None, "id": cell_id,
        "metadata": {}, "outputs": [], "source": source.splitlines(keepends=True),
    }


def markdown_cell(source: str, cell_id: str) -> dict:
    return {"cell_type": "markdown", "id": cell_id, "metadata": {}, "source": source.splitlines(keepends=True)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--oracle-output", required=True, type=Path)
    args = parser.parse_args()

    qwen = locate(args.oracle_output, "qwen_candidates.jsonl")
    llama = locate(args.oracle_output, "llama_candidates.jsonl")
    spec = locate(ROOT / "kaggle_upload_spec_only_pilot", "spec_tasks_pilot.jsonl")
    for path, expected in ((qwen, 40), (llama, 60)):
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(rows) != expected:
            raise RuntimeError(f"Incomplete oracle checkpoint {path}: {len(rows)}/{expected}")
        if any(row.get("metadata", {}).get("golden_artifacts_seen") for row in rows):
            raise RuntimeError(f"Candidate checkpoint claims golden access: {path}")

    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    for path in (PROJECT / "active_tb").glob("*.py"):
        copy_file(path, STAGE / "project" / path.relative_to(PROJECT))
    for name in ["generate_spec_oracles.py", "repair_spec_oracles.py", "spec_only_smoke_test.py"]:
        copy_file(PROJECT / name, STAGE / "project" / name)
    copy_file(spec, STAGE / "spec_tasks_pilot.jsonl")
    copy_file(qwen, STAGE / "qwen_candidates.jsonl")
    copy_file(llama, STAGE / "llama_candidates.jsonl")
    boundary = {
        "allowed_spec_fields": ["task_id", "description", "header"],
        "allowed_repair_evidence": [
            "typed_spec_contract", "generated_candidate_rtl", "generated_candidate_traces"
        ],
        "forbidden_fields": [
            "module_code", "canonical_solution", "testbench", "mutants",
            "golden_rtl", "official_test",
        ],
        "candidate_sources": ["qwen_candidates.jsonl", "llama_candidates.jsonl"],
        "golden_artifacts_in_dataset": False,
    }
    (STAGE / "REPAIR_BOUNDARY.json").write_text(json.dumps(boundary, indent=2))

    PUBLISH.mkdir(parents=True, exist_ok=True)
    archive_path = PUBLISH / "active_tb_s_disagreement_repair_pilot_v1.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in STAGE.rglob("*"):
            if path.is_file():
                archive.write(path, (Path(STAGE.name) / path.relative_to(STAGE)).as_posix())
    (PUBLISH / "dataset-metadata.json").write_text(json.dumps({
        "title": "ACTIVE TB S Repair Generation Pilot v1",
        "id": "tishaferdous/active-tb-s-disagreement-repair-pilot-v1",
        "licenses": [{"name": "MIT"}],
    }, indent=2))

    notebook = {
        "cells": [
            markdown_cell("""# ACTIVE-TB-S: Disagreement-Directed Third-Family Repair

This physically isolated phase invokes CodeGemma only for tasks where the Qwen and Llama executable oracles have inadequate trace coverage or unresolved family-level disagreements. It sees sanitized specifications, a typed temporal contract derived from those specifications, and generated candidate behavior. Golden RTL, benchmark tests, and benchmark mutants are absent.
""", "intro"),
            code_cell("""from pathlib import Path
import json, os, shutil, subprocess, sys, zipfile
os.environ['PYTHONDONTWRITEBYTECODE']='1'
os.environ['TOKENIZERS_PARALLELISM']='false'
os.environ['HF_HOME']='/kaggle/working/hf_cache'
os.environ['TRANSFORMERS_CACHE']='/kaggle/working/hf_cache'
INPUT=Path('/kaggle/input'); WORK=Path('/kaggle/working')
markers=list(INPUT.rglob('active_tb_s_disagreement_repair_pilot_v1/REPAIR_BOUNDARY.json'))
if len(markers)==1: SOURCE=markers[0].parent
else:
    archives=list(INPUT.rglob('active_tb_s_disagreement_repair_pilot_v1.zip')); assert len(archives)==1, archives
    dst=WORK/'attached_repair_source'
    with zipfile.ZipFile(archives[0]) as zf: zf.extractall(dst)
    SOURCE=dst/'active_tb_s_disagreement_repair_pilot_v1'
PROJECT=WORK/'active_tb_s_repair_project'
if PROJECT.exists(): shutil.rmtree(PROJECT)
shutil.copytree(SOURCE/'project',PROJECT)
OUT=WORK/'active_tb_s_repaired_oracles_v1'; OUT.mkdir(exist_ok=True)
print('Isolated repair source:',SOURCE)
""", "setup"),
            code_cell("""boundary=json.loads((SOURCE/'REPAIR_BOUNDARY.json').read_text())
assert boundary['golden_artifacts_in_dataset'] is False
assert not list(SOURCE.rglob('*mutant*'))
spec_rows=[json.loads(line) for line in (SOURCE/'spec_tasks_pilot.jsonl').read_text().splitlines() if line.strip()]
assert len(spec_rows)==20 and all(set(row)=={'task_id','description','header'} for row in spec_rows)
for name, expected in [('qwen_candidates.jsonl',40),('llama_candidates.jsonl',60)]:
    rows=[json.loads(line) for line in (SOURCE/name).read_text().splitlines() if line.strip()]
    assert len(rows)==expected
    assert all(not row.get('metadata',{}).get('golden_artifacts_seen',False) for row in rows)
print('REPAIR_LEAKAGE_AUDIT_PASS:',len(spec_rows),'tasks')
""", "audit"),
            code_cell("""subprocess.run(['apt-get','update','-qq'],check=True)
subprocess.run(['apt-get','install','-y','-qq','iverilog'],check=True)
subprocess.run([sys.executable,'-m','pip','install','-q','--no-cache-dir','--force-reinstall',
                'torch==2.5.1','--index-url','https://download.pytorch.org/whl/cu121'],check=True)
subprocess.run([sys.executable,'-m','pip','uninstall','-y','-q','torchvision','torchaudio'],check=False)
subprocess.run([sys.executable,'-m','pip','install','-q','--no-cache-dir',
                'transformers==4.57.6','accelerate>=1.0,<2','bitsandbytes==0.48.2',
                'sentencepiece','tqdm>=4.66'],check=True)
probe=subprocess.run([sys.executable,'-c',
 'import torch; print(torch.__version__,torch.cuda.get_device_name(0),torch.cuda.get_device_capability(0)); x=torch.ones(1,device="cuda"); print("CUDA_PROBE_PASS",x.item())'],
 text=True,capture_output=True)
print(probe.stdout)
if probe.returncode: raise RuntimeError(probe.stderr)
subprocess.run([sys.executable,str(PROJECT/'spec_only_smoke_test.py')],check=True,cwd=PROJECT)
""", "deps"),
            code_cell("""MODEL='unsloth/codegemma-7b-it-bnb-4bit'
CODEGEMMA_OUT=OUT/'codegemma_candidates.jsonl'
ANALYSIS_OUT=OUT/'repair_selection.json'
cmd=[sys.executable,str(PROJECT/'repair_spec_oracles.py'),
 '--tasks',str(SOURCE/'spec_tasks_pilot.jsonl'),
 '--candidates',str(SOURCE/'qwen_candidates.jsonl'),str(SOURCE/'llama_candidates.jsonl'),
 '--output',str(CODEGEMMA_OUT),'--analysis-output',str(ANALYSIS_OUT),
 '--model',MODEL,'--family','codegemma','--candidates-per-task','2',
 '--resolution-threshold','0.85','--scenario-pool-size','96',
 '--max-new-tokens','900','--max-input-tokens','7168',
 '--temperature','0.20','--repair-attempts','1','--resume']
subprocess.run(cmd,check=True,cwd=PROJECT)
""", "repair"),
            code_cell("""for name in ['qwen_candidates.jsonl','llama_candidates.jsonl']:
    shutil.copy2(SOURCE/name,OUT/name)
selection=json.loads((OUT/'repair_selection.json').read_text())
selected={row['task_id'] for row in selection if row['selected']}
rows=[json.loads(line) for line in CODEGEMMA_OUT.read_text().splitlines() if line.strip()]
assert len(rows)==2*len(selected),(len(rows),len(selected))
assert {(row['task_id'],row['candidate_index']) for row in rows}=={(task_id,index) for task_id in selected for index in range(2)}
print('Selected tasks:',len(selected),'/ 20')
print('CodeGemma compiled:',sum(bool(row['compiled']) for row in rows),'/',len(rows))
manifest={'protocol':'disagreement-directed third-family repair','task_count':20,
 'selected_task_count':len(selected),'model':MODEL,'golden_artifacts_seen':False,
 'candidate_files':['qwen_candidates.jsonl','llama_candidates.jsonl','codegemma_candidates.jsonl']}
(OUT/'repair_manifest.json').write_text(json.dumps(manifest,indent=2))
cache=Path(os.environ['HF_HOME'])
if cache.exists(): shutil.rmtree(cache)
archive=WORK/'active_tb_s_repaired_oracles_v1.zip'
shutil.make_archive(str(archive.with_suffix('')),'zip',OUT)
print('Augmented oracle checkpoint:',archive,archive.stat().st_size,'bytes')
""", "package"),
        ],
        "metadata": {
            "accelerator": "GPU",
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.12"},
        },
        "nbformat": 4, "nbformat_minor": 5,
    }
    NOTEBOOK.write_text(json.dumps(notebook, indent=1) + "\n")
    KERNEL.mkdir(parents=True, exist_ok=True)
    copy_file(NOTEBOOK, KERNEL / NOTEBOOK.name)
    (KERNEL / "kernel-metadata.json").write_text(json.dumps({
        "id": "tishaferdous/active-tb-s-repair-generation-pilot-v1",
        "title": "ACTIVE-TB-S Disagreement Repair Pilot v1",
        "code_file": NOTEBOOK.name,
        "language": "python", "kernel_type": "notebook", "is_private": True,
        "enable_gpu": True, "enable_internet": True,
        "dataset_sources": ["tishaferdous/active-tb-s-disagreement-repair-pilot-v1"],
        "competition_sources": [], "kernel_sources": [],
    }, indent=2))
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None
        assert all("\\" not in name for name in archive.namelist())
    print("Built", archive_path, archive_path.stat().st_size)
    print("Built", NOTEBOOK)


if __name__ == "__main__":
    main()
