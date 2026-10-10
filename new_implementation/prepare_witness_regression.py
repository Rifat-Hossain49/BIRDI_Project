#!/usr/bin/env python3
"""Package the Phase-1 witness regression for Kaggle (CPU).

Self-contained by design: the formal toolchain is absent locally, so every
iteration costs a remote round-trip. This kernel installs yosys/z3/iverilog,
runs all ten synthetic cases, and emits the complete funnel in one go rather
than requiring interactive debugging.

No benchmark data is involved. Golden RTL here is hand-written synthetic code.
"""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SAFE = ROOT / "safe"
UPLOAD = ROOT / "kaggle_upload_witness"
STAGE = UPLOAD / "dataset" / "active_tb_witness_v1"
PUBLISH = UPLOAD / "dataset_publish"
KERNEL = UPLOAD / "kernel"
NOTEBOOK = ROOT / "ACTIVE_TB_Witness_Regression_Kaggle.ipynb"


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
    for name in ("synthetic_cases.py", "formal_witness.py", "witness_regression.py"):
        shutil.copy2(SAFE / name, STAGE / name)
    (STAGE / "PHASE1_BOUNDARY.json").write_text(json.dumps({
        "phase": "phase_1_witness_regression",
        "benchmark_data_present": False,
        "golden_rtl": "hand-written synthetic cases only",
        "gate": "SAT-to-replay >= 90% on supported cases",
    }, indent=2), encoding="utf-8")

    PUBLISH.mkdir(parents=True, exist_ok=True)
    ds = PUBLISH / "active_tb_witness_v1.zip"
    with zipfile.ZipFile(ds, "w", zipfile.ZIP_DEFLATED) as z:
        for p in STAGE.rglob("*"):
            if p.is_file():
                z.write(p, (Path(STAGE.name) / p.relative_to(STAGE)).as_posix())
    (PUBLISH / "dataset-metadata.json").write_text(json.dumps({
        "title": "ACTIVE TB Witness v1",
        "id": "tishaferdous/active-tb-witness-v1",
        "licenses": [{"name": "MIT"}],
    }, indent=2), encoding="utf-8")

    setup = """from pathlib import Path
import json, subprocess, sys, zipfile, shutil
INPUT=Path('/kaggle/input'); WORK=Path('/kaggle/working')
m=list(INPUT.rglob('active_tb_witness_v1/PHASE1_BOUNDARY.json'))
if len(m)==1: SRC=m[0].parent
else:
 a=list(INPUT.rglob('active_tb_witness_v1.zip')); assert len(a)==1,a
 d=WORK/'attached'
 with zipfile.ZipFile(a[0]) as zf: zf.extractall(d)
 SRC=d/'active_tb_witness_v1'
print(json.loads((SRC/'PHASE1_BOUNDARY.json').read_text()))
subprocess.run(['apt-get','update','-qq'],check=True)
subprocess.run(['apt-get','install','-y','-qq','yosys','iverilog','z3'],check=True)
for t in ('yosys','yosys-smtbmc','iverilog','vvp','z3'):
    p=subprocess.run(['which',t],capture_output=True,text=True)
    print(f'{t:14s}', p.stdout.strip() or 'MISSING')
subprocess.run(['yosys','-V'],check=False)
subprocess.run([sys.executable,'-m','pip','install','-q','--no-cache-dir','pyyaml','click'],check=False)
"""

    run = """OUT=WORK/'witness_out'; OUT.mkdir(exist_ok=True)
r=subprocess.run([sys.executable,str(SRC/'witness_regression.py'),
                  '--bounds','4,8,16,32','--timeout','90',
                  '--out',str(OUT/'witness_funnel.csv')],
                 text=True,capture_output=True,cwd=SRC)
print(r.stdout[-6000:])
if r.returncode: print('STDERR:', r.stderr[-3000:])
shutil.make_archive(str(WORK/'witness_out'),'zip',OUT)
print('packaged')
"""

    nb = {"cells": [
        md_cell("# Phase 1: formal witness pipeline regression\n\n"
                "Ten synthetic Golden/mutant pairs with known distinguishing inputs. "
                "Gate: >=90% SAT-to-replay on supported cases, funnel accounting for "
                "100% of calls. No benchmark data involved.\n", "intro"),
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
        "id": "tishaferdous/active-tb-witness-regression",
        "title": "ACTIVE TB Witness Regression",
        "code_file": NOTEBOOK.name,
        "language": "python", "kernel_type": "notebook", "is_private": True,
        "enable_gpu": False, "enable_internet": True,
        "dataset_sources": ["tishaferdous/active-tb-witness-v1"],
        "competition_sources": [], "kernel_sources": [],
    }, indent=2), encoding="utf-8")
    print("Built", ds, ds.stat().st_size)


if __name__ == "__main__":
    main()
