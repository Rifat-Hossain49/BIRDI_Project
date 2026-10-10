#!/usr/bin/env python3
"""Package the Step-E sealed evaluation for Kaggle (CPU, Icarus Verilog).

The dataset carries the frozen suites, their hash manifest, the frozen checker
sources, Golden RTL and Hidden Bank A. Golden and hidden artefacts appear here
and only here: search ran locally and never read them.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AMP = ROOT / "amp"
HDL = ROOT / "baselines/ConfiBench/data/HDLBits"
RECORDS = ROOT / "baselines/ConfiBench/data/CorrectBenchResults/run_info_and_codes.jsonl"
UPLOAD = ROOT / "kaggle_upload_distill"
STAGE = UPLOAD / "dataset" / "active_tb_distill_v1"
PUBLISH = UPLOAD / "dataset_publish"
KERNEL = UPLOAD / "kernel"
NOTEBOOK = ROOT / "ACTIVE_TB_Distill_Sealed_Kaggle.ipynb"


def code_cell(src, cid):
    return {"cell_type": "code", "execution_count": None, "id": cid,
            "metadata": {}, "outputs": [], "source": src.splitlines(keepends=True)}


def md_cell(src, cid):
    return {"cell_type": "markdown", "id": cid, "metadata": {},
            "source": src.splitlines(keepends=True)}


def main() -> None:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)

    manifest = json.loads((AMP / "distill_manifest.json").read_text())
    pilot = set(json.loads((AMP / "pilot_tasks.json").read_text()))

    # suites and manifest
    shutil.copytree(AMP / "distill_suites", STAGE / "suites")
    shutil.copy2(AMP / "distill_manifest.json", STAGE / "suite_manifest.json")
    shutil.copy2(AMP / "distill_manifest.sha256", STAGE / "suite_manifest.sha256")
    shutil.copy2(AMP / "sealed_evaluator.py", STAGE / "sealed_evaluator.py")

    # frozen checker sources, pilot tasks only
    seen, out = set(), []
    for line in RECORDS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r["task_id"] in pilot and r["task_id"] not in seen:
            seen.add(r["task_id"])
            out.append({"task_id": r["task_id"], "tb_py_checker": r["tb_py_checker"]})
    (STAGE / "checkers.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in out), encoding="utf-8")

    # golden and hidden bank A, restricted to the pilot
    for src, dst, keep in ((HDL / "HDLBits_data.jsonl", "golden.jsonl",
                            ("task_id", "module_code")),
                           (HDL / "HDLBits_data_mutants.jsonl", "hidden_bank_a.jsonl",
                            ("task_id", "mutants"))):
        rows = []
        for line in src.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r["task_id"] in pilot:
                rows.append({k: r[k] for k in keep if k in r})
        (STAGE / dst).write_text("".join(json.dumps(r) + "\n" for r in rows),
                                 encoding="utf-8")
        print(f"  {dst}: {len(rows)} tasks")

    (STAGE / "SEALED_BOUNDARY.json").write_text(json.dumps({
        "phase": "distill_sealed_evaluation",
        "suites_frozen_before_golden_contact": True,
        "manifest_sha256": (AMP / "distill_manifest.sha256").read_text().strip(),
        "suite_count": len(manifest["suites"]),
        "hidden_bank": "Hidden Bank A - existing benchmark RTL mutant bank",
        "search_code_present": False,
    }, indent=2), encoding="utf-8")

    PUBLISH.mkdir(parents=True, exist_ok=True)
    ds = PUBLISH / "active_tb_distill_v1.zip"
    with zipfile.ZipFile(ds, "w", zipfile.ZIP_DEFLATED) as z:
        for p in STAGE.rglob("*"):
            if p.is_file():
                z.write(p, (Path(STAGE.name) / p.relative_to(STAGE)).as_posix())
    (PUBLISH / "dataset-metadata.json").write_text(json.dumps({
        "title": "ACTIVE TB Distill v1",
        "id": "tishaferdous/active-tb-distill-v1",
        "licenses": [{"name": "MIT"}],
    }, indent=2), encoding="utf-8")

    setup = """from pathlib import Path
import json, os, shutil, subprocess, sys, zipfile
INPUT=Path('/kaggle/input'); WORK=Path('/kaggle/working')
m=list(INPUT.rglob('active_tb_distill_v1/SEALED_BOUNDARY.json'))
if len(m)==1: SRC=m[0].parent
else:
 a=list(INPUT.rglob('active_tb_distill_v1.zip')); assert len(a)==1,a
 d=WORK/'attached'
 with zipfile.ZipFile(a[0]) as zf: zf.extractall(d)
 SRC=d/'active_tb_distill_v1'
sz=SRC/'suites'
sd=SRC/'suites.zip'
if not sz.is_dir() and sd.exists():
 sz=WORK/'suites'
 with zipfile.ZipFile(sd) as zf: zf.extractall(sz)
b=json.loads((SRC/'SEALED_BOUNDARY.json').read_text())
print('boundary:',b)
print('suite files:',len(list(sz.glob('*.v'))))
subprocess.run(['apt-get','update','-qq'],check=True)
subprocess.run(['apt-get','install','-y','-qq','iverilog'],check=True)
print('iverilog ready')
"""

    run = """OUT=WORK/'distill_results'; OUT.mkdir(exist_ok=True)
cmd=[sys.executable,str(SRC/'sealed_evaluator.py'),
 '--suites',str(sz),
 '--manifest',str(SRC/'suite_manifest.json'),
 '--checkers',str(SRC/'checkers.jsonl'),
 '--golden',str(SRC/'golden.jsonl'),
 '--mutants',str(SRC/'hidden_bank_a.jsonl'),
 '--out',str(OUT/'sealed_records.csv')]
r=subprocess.run(cmd,text=True,capture_output=True)
print(r.stdout[-4000:])
if r.returncode: print(r.stderr[-4000:]); raise SystemExit('evaluator failed')
shutil.copy2(SRC/'suite_manifest.json',OUT/'suite_manifest.json')
shutil.make_archive(str(WORK/'distill_results'),'zip',OUT)
print('packaged')
"""

    nb = {"cells": [
        md_cell("# ACTIVE-TB Step E: sealed evaluation\n\n"
                "Verifies frozen suite hashes, then runs Golden RTL and Hidden Bank A "
                "through the frozen CorrectBench checkers with Icarus Verilog. "
                "No search or generation code is present in this dataset.\n", "intro"),
        code_cell(setup, "setup"),
        code_cell(run, "run"),
    ], "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.12"},
    }, "nbformat": 4, "nbformat_minor": 5}
    NOTEBOOK.write_text(json.dumps(nb, indent=1) + "\n", encoding="utf-8")
    KERNEL.mkdir(parents=True, exist_ok=True)
    shutil.copy2(NOTEBOOK, KERNEL / NOTEBOOK.name)
    (KERNEL / "kernel-metadata.json").write_text(json.dumps({
        "id": "tishaferdous/active-tb-distill-sealed",
        "title": "ACTIVE TB Distill Sealed",
        "code_file": NOTEBOOK.name,
        "language": "python", "kernel_type": "notebook", "is_private": True,
        "enable_gpu": False, "enable_internet": True,
        "dataset_sources": ["tishaferdous/active-tb-distill-v1"],
        "competition_sources": [], "kernel_sources": [],
    }, indent=2), encoding="utf-8")
    print("Built", ds, ds.stat().st_size)
    print("Built", NOTEBOOK)


if __name__ == "__main__":
    main()
