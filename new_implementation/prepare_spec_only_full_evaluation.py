#!/usr/bin/env python3
"""Build the isolated five-seed post-freeze 156-task evaluation phase."""
from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROJECT = ROOT / "extracted_v1" / "active_tb_budgeted_adaptive"
HDLBITS = ROOT / "baselines" / "CorrectBench" / "data" / "HDLBits"
UPLOAD = ROOT / "kaggle_upload_spec_only_full_evaluation"
STAGE = UPLOAD / "dataset" / "active_tb_s_evaluation_full_v1"
PUBLISH = UPLOAD / "dataset_publish"
KERNEL = UPLOAD / "kernel"
NOTEBOOK = ROOT / "ACTIVE_TB_S_Evaluation_Full_Kaggle.ipynb"


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
    return {
        "cell_type": "markdown", "id": cell_id, "metadata": {},
        "source": source.splitlines(keepends=True),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--synthesis-output", required=True, type=Path)
    args = parser.parse_args()
    frozen = locate(args.synthesis_output, "active_tb_s_frozen_full_v1.zip")
    tasks = HDLBITS / "HDLBits_data.jsonl"
    mutants = HDLBITS / "HDLBits_data_mutants.jsonl"
    task_rows = [json.loads(x) for x in tasks.read_text(encoding="utf-8").splitlines() if x.strip()]
    mutant_rows = [json.loads(x) for x in mutants.read_text(encoding="utf-8").splitlines() if x.strip()]
    if len(task_rows) != 156 or len(mutant_rows) != 156:
        raise RuntimeError((len(task_rows), len(mutant_rows)))

    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    for path in (PROJECT / "active_tb").glob("*.py"):
        copy_file(path, STAGE / "project" / path.relative_to(PROJECT))
    copy_file(PROJECT / "run_spec_only_evaluation.py", STAGE / "project" / "run_spec_only_evaluation.py")
    copy_file(PROJECT / "sota_eval" / "__init__.py", STAGE / "project" / "sota_eval" / "__init__.py")
    copy_file(PROJECT / "sota_eval" / "eval2_adapter.py", STAGE / "project" / "sota_eval" / "eval2_adapter.py")
    copy_file(frozen, STAGE / "active_tb_s_frozen_full_v1.zip")
    copy_file(tasks, STAGE / "HDLBits_full.jsonl")
    copy_file(mutants, STAGE / "HDLBits_mutants_full.jsonl")
    seeds = [17, 29, 43, 59, 73]
    (STAGE / "EVALUATION_BOUNDARY.json").write_text(json.dumps({
        "phase": "post_freeze_evaluation",
        "frozen_before_golden_access": True,
        "task_count": 156,
        "seeds": seeds,
        "metrics": [
            "Eval1", "official_Eval2_exact", "official_Eval2_loose",
            "raw_mutant_rejection", "paired_bootstrap_delta", "cost", "latency",
        ],
    }, indent=2), encoding="utf-8")

    PUBLISH.mkdir(parents=True, exist_ok=True)
    dataset_zip = PUBLISH / "active_tb_s_evaluation_full_v1.zip"
    with zipfile.ZipFile(dataset_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in STAGE.rglob("*"):
            if path.is_file():
                archive.write(path, (Path(STAGE.name) / path.relative_to(STAGE)).as_posix())
    (PUBLISH / "dataset-metadata.json").write_text(json.dumps({
        "title": "ACTIVE-TB-S Post-Freeze Evaluation Full v1",
        "id": "tishaferdous/active-tb-s-post-freeze-evaluation-full-v1",
        "licenses": [{"name": "MIT"}],
    }, indent=2), encoding="utf-8")

    notebook = {
        "cells": [
            markdown_cell("""# ACTIVE-TB-S: Full Five-Seed Post-Freeze Evaluation

This phase receives hash-frozen testbenches from five predeclared synthesis seeds plus VerilogEval golden RTL, official testbenches, and the released CorrectBench mutant bank. Generated suites cannot be modified here.
""", "intro"),
            code_cell("""from pathlib import Path
import json, shutil, subprocess, sys, zipfile
INPUT=Path('/kaggle/input'); WORK=Path('/kaggle/working')
markers=list(INPUT.rglob('active_tb_s_evaluation_full_v1/EVALUATION_BOUNDARY.json'))
if len(markers)==1: SOURCE=markers[0].parent
else:
 archives=list(INPUT.rglob('active_tb_s_evaluation_full_v1.zip')); assert len(archives)==1,archives
 attached=WORK/'attached_full_evaluation_source'
 with zipfile.ZipFile(archives[0]) as zf: zf.extractall(attached)
 SOURCE=attached/'active_tb_s_evaluation_full_v1'
PROJECT=WORK/'active_tb_s_evaluation_full_project'
if PROJECT.exists(): shutil.rmtree(PROJECT)
shutil.copytree(SOURCE/'project',PROJECT)
# Kaggle recursively expands archives inside an uploaded dataset, so the frozen
# bundle may arrive either as the original zip or already unpacked as a directory.
frozen_zip=SOURCE/'active_tb_s_frozen_full_v1.zip'
frozen_dir=SOURCE/'active_tb_s_frozen_full_v1'
if frozen_zip.exists():
 FROZEN=WORK/'active_tb_s_frozen_full_v1'
 with zipfile.ZipFile(frozen_zip) as zf: zf.extractall(FROZEN)
elif frozen_dir.is_dir(): FROZEN=frozen_dir
else: raise FileNotFoundError(f'No frozen bundle at {frozen_zip} or {frozen_dir}')
assert sorted(x.name for x in FROZEN.glob('seed_*'))==['seed_017','seed_029','seed_043','seed_059','seed_073'],sorted(x.name for x in FROZEN.glob('seed_*'))
print('Frozen bundle:',FROZEN)
OUT=WORK/'active_tb_s_evaluation_full_v1'
CHECKPOINT=WORK/'active_tb_s_evaluation_full_checkpoint.zip'
resume=list(INPUT.rglob('active_tb_s_evaluation_full_checkpoint.zip'))
if len(resume)>1: raise RuntimeError(resume)
if OUT.exists(): shutil.rmtree(OUT)
if resume:
 with zipfile.ZipFile(resume[0]) as zf: zf.extractall(OUT)
else: OUT.mkdir()
print('Evaluation source:',SOURCE,'resume:',resume)
""", "setup"),
            code_cell("""boundary=json.loads((SOURCE/'EVALUATION_BOUNDARY.json').read_text())
assert boundary['frozen_before_golden_access'] is True
assert boundary['task_count']==156 and len(boundary['seeds'])==5
for seed in boundary['seeds']:
 manifest=json.loads((FROZEN/f'seed_{seed:03d}'/'FROZEN_BEFORE_EVALUATION.json').read_text())
 assert manifest['generation_input_fields']==['task_id','description','header']
 assert manifest['random_seed']==seed
print('FULL_POST_FREEZE_PROVENANCE_AUDIT_PASS:',boundary['task_count'],'tasks',boundary['seeds'])
""", "audit"),
            code_cell("""subprocess.run(['apt-get','update','-qq'],check=True)
subprocess.run(['apt-get','install','-y','-qq','iverilog'],check=True)
for seed in boundary['seeds']:
 seed_out=OUT/f'seed_{seed:03d}'; seed_out.mkdir(parents=True,exist_ok=True)
 cmd=[sys.executable,str(PROJECT/'run_spec_only_evaluation.py'),
  '--frozen-root',str(FROZEN/f'seed_{seed:03d}'/'frozen'),
  '--tasks',str(SOURCE/'HDLBits_full.jsonl'),
  '--mutants',str(SOURCE/'HDLBits_mutants_full.jsonl'),
  '--output',str(seed_out),'--timeout','30','--resume']
 subprocess.run(cmd,check=True,cwd=PROJECT)
 shutil.make_archive(str(CHECKPOINT.with_suffix('')),'zip',OUT)
 print('Completed evaluation seed',seed,'checkpoint bytes',CHECKPOINT.stat().st_size)
""", "evaluate"),
            code_cell("""import numpy as np, pandas as pd
aggregates=[]; per_tasks=[]
for seed in boundary['seeds']:
 aggregate=pd.read_csv(OUT/f'seed_{seed:03d}'/'spec_only_eval2_aggregate.csv'); aggregate['seed']=seed; aggregates.append(aggregate)
 per_task=pd.read_csv(OUT/f'seed_{seed:03d}'/'spec_only_eval2_per_task.csv'); per_task['seed']=seed; per_tasks.append(per_task)
aggregate=pd.concat(aggregates,ignore_index=True); per_task=pd.concat(per_tasks,ignore_index=True)
aggregate.to_csv(OUT/'spec_only_eval2_aggregate_all_seeds.csv',index=False)
per_task.to_csv(OUT/'spec_only_eval2_per_task_all_seeds.csv',index=False)
metric_cols=['synthesis_success_rate','eval1_pass_at_1','eval2_exact_pass_at_1','eval2_loose_pass_at_1_0_8','raw_mutant_rejection_rate']
rows=[]
for method,group in aggregate.groupby('method'):
 for metric in metric_cols:
  values=group[metric].astype(float).to_numpy(); mean=float(values.mean())
  half=float(2.776*values.std(ddof=1)/np.sqrt(len(values))) if len(values)>1 else 0.0
  rows.append({'method':method,'metric':metric,'mean':mean,'ci95_low':mean-half,'ci95_high':mean+half,'seeds':len(values)})
ci=pd.DataFrame(rows); ci.to_csv(OUT/'spec_only_method_ci.csv',index=False)
print(ci.to_string(index=False))

# Paired task-level bootstrap: typed/formal versus the strongest pilot control.
rng=np.random.default_rng(20260901); typed='typed_formal_active'; control='single_oracle'
wide=per_task.pivot_table(index=['seed','task_id'],columns='method',values=['eval1_pass','eval2_exact_pass','eval2_loose_pass_0_8','eval2_ratio'],aggfunc='first')
boot=[]
for metric in ['eval1_pass','eval2_exact_pass','eval2_loose_pass_0_8','eval2_ratio']:
 pairs=wide[metric][[typed,control]].dropna().astype(float).to_numpy(); observed=float((pairs[:,0]-pairs[:,1]).mean())
 samples=[]
 for _ in range(10000):
  idx=rng.integers(0,len(pairs),len(pairs)); samples.append(float((pairs[idx,0]-pairs[idx,1]).mean()))
 boot.append({'metric':metric,'typed_minus_single':observed,'ci95_low':float(np.quantile(samples,.025)),'ci95_high':float(np.quantile(samples,.975)),'paired_rows':len(pairs)})
bootstrap=pd.DataFrame(boot); bootstrap.to_csv(OUT/'typed_vs_single_paired_bootstrap.csv',index=False)
print(bootstrap.to_string(index=False))
archive=WORK/'active_tb_s_evaluation_full_v1.zip'
shutil.make_archive(str(archive.with_suffix('')),'zip',OUT)
print('Full evaluation checkpoint:',archive,archive.stat().st_size,'bytes')
""", "results"),
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
        "id": "tishaferdous/active-tb-s-evaluation-full-v1",
        "title": "ACTIVE-TB-S Evaluation Full v1",
        "code_file": NOTEBOOK.name,
        "language": "python", "kernel_type": "notebook", "is_private": True,
        "enable_gpu": False, "enable_internet": True,
        "dataset_sources": ["tishaferdous/active-tb-s-post-freeze-evaluation-full-v1"],
        "competition_sources": [], "kernel_sources": [],
    }, indent=2), encoding="utf-8")
    with zipfile.ZipFile(dataset_zip) as archive:
        if archive.testzip() is not None or any("\\" in name for name in archive.namelist()):
            raise RuntimeError("Invalid full evaluation dataset archive")
    print("Built", dataset_zip, dataset_zip.stat().st_size)
    print("Built", NOTEBOOK)


if __name__ == "__main__":
    main()
