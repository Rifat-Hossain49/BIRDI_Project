#!/usr/bin/env python3
"""Bundle DLR pilot 1 for Kaggle 2x T4.

Reuses J1b's hardware check, llama.cpp build (with the libcuda link fix) and
server start-up cells verbatim, so the only new moving part is the question pass.
"""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from prepare_xjudge_j1b import CELLS as J1B_CELLS

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "kaggle_upload_dlr1"
DS = "dlr1"
FILES = ["analysis/dlr_questions.jsonl", "analysis/dlr_ask.py", "DLR_PREREGISTRATION.md"]

ASK = """
if NP:
    p=subprocess.Popen([sys.executable,str(SRC/'dlr_ask.py'),'--questions',str(SRC/'dlr_questions.jsonl'),
       '--out',str(WORK/'dlr_answers.jsonl'),'--concurrency',str(NP),'--budget-hours','10.5'],
       stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    for line in p.stdout: print(line,end='',flush=True)
    print('ask exit code', p.wait())
try: srv.kill()
except Exception: pass
with zipfile.ZipFile(WORK/'dlr1_results.zip','w',zipfile.ZIP_DEFLATED) as z:
    for f in sorted(WORK.glob('*')):
        if f.is_file() and f.suffix in ('.jsonl','.log'): z.write(f, f.name)
print('packed', flush=True)
"""


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    ds = OUT / "dataset" / DS
    ds.mkdir(parents=True)
    for f in FILES:
        shutil.copy2(ROOT / f, ds / Path(f).name)
    (ds / "XJ_BOUNDARY.json").write_text(json.dumps({
        "pilot": "DLR-1 localized resolution", "prereg": "DLR_PREREGISTRATION.md",
        "model": "unsloth/Qwen3.5-27B-GGUF Q4_K_M"}), encoding="utf-8")
    cells = [J1B_CELLS[0], J1B_CELLS[1] % {"ds": DS}, J1B_CELLS[2], ASK]
    nb = {"cells": [{"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
                     "source": c.strip("\n").splitlines(keepends=True)} for c in cells],
          "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                       "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
    k = OUT / "kernel"
    k.mkdir(parents=True)
    (k / "dlr1.ipynb").write_text(json.dumps(nb, indent=1), encoding="utf-8")
    (k / "kernel-metadata.json").write_text(json.dumps({
        "id": "tishaferdous/dlr-pilot-one", "title": "DLR Pilot One", "code_file": "dlr1.ipynb",
        "language": "python", "kernel_type": "notebook", "is_private": True,
        "enable_gpu": True, "enable_internet": True, "machine_shape": "NvidiaTeslaT4",
        "dataset_sources": ["tishaferdous/dlr1-data"], "competition_sources": [],
        "kernel_sources": []}, indent=1), encoding="utf-8")
    pub = OUT / "dataset_publish"
    pub.mkdir(parents=True)
    with zipfile.ZipFile(pub / f"{DS}.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for f in ds.rglob("*"):
            if f.is_file():
                z.write(f, Path(DS) / f.relative_to(ds))
    (pub / "dataset-metadata.json").write_text(json.dumps({
        "title": "DLR1 Data", "id": "tishaferdous/dlr1-data",
        "licenses": [{"name": "MIT"}]}, indent=1), encoding="utf-8")
    for i, c in enumerate(cells):
        compile(c, f"<cell {i}>", "exec")
    print("bundle:", (pub / f"{DS}.zip").stat().st_size // 1024, "KB; all cells compile")


if __name__ == "__main__":
    main()
