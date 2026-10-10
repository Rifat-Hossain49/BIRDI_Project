#!/usr/bin/env python3
"""Bundle the pilot 1 rerun with budget forcing (DLR Amendment 1), one shard per session.

usage: python prepare_dlr1f.py <shard_index> <n_shards> [--prev answers.jsonl]
"""
from __future__ import annotations

import json
import shutil
import sys
import zipfile
from pathlib import Path

from prepare_xjudge_j1b import CELLS as J1B_CELLS

ROOT = Path(__file__).resolve().parent
FILES = ["analysis/dlr_questions.jsonl", "analysis/dlr_ask.py", "analysis/dlr_ask_forced.py",
         "DLR_PREREGISTRATION.md"]

ASK = """
prev = SRC/'prev_answers.jsonl'
if prev.is_file() and not (WORK/'dlr_answers_forced.jsonl').is_file():
    shutil.copy2(prev, WORK/'dlr_answers_forced.jsonl')
sys.path.insert(0, str(SRC))
if NP:
    p=subprocess.Popen([sys.executable,str(SRC/'dlr_ask_forced.py'),'--questions',str(SRC/'dlr_questions.jsonl'),
       '--out',str(WORK/'dlr_answers_forced.jsonl'),'--shard','%(shard)d','--n-shards','%(n)d',
       '--concurrency',str(NP),'--budget-hours','10.5'],
       stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,cwd=str(SRC))
    for line in p.stdout: print(line,end='',flush=True)
    print('ask exit code', p.wait())
try: srv.kill()
except Exception: pass
with zipfile.ZipFile(WORK/'dlr1f_results.zip','w',zipfile.ZIP_DEFLATED) as z:
    for f in sorted(WORK.glob('*')):
        if f.is_file() and f.suffix in ('.jsonl','.log'): z.write(f, f.name)
print('packed', flush=True)
"""


def main() -> None:
    shard, n = int(sys.argv[1]), int(sys.argv[2])
    prev = Path(sys.argv[sys.argv.index("--prev") + 1]) if "--prev" in sys.argv else None
    tag = f"dlr1f{shard}of{n}"
    out = ROOT / f"kaggle_upload_{tag}"
    if out.exists():
        shutil.rmtree(out)
    ds = out / "dataset" / tag
    ds.mkdir(parents=True)
    for f in FILES:
        shutil.copy2(ROOT / f, ds / Path(f).name)
    if prev and prev.is_file():
        shutil.copy2(prev, ds / "prev_answers.jsonl")
    (ds / "XJ_BOUNDARY.json").write_text(json.dumps({
        "pilot": "DLR-1 rerun, budget forcing", "prereg": "DLR_PREREGISTRATION.md Amendment 1",
        "shard": shard, "n_shards": n, "model": "unsloth/Qwen3.5-27B-GGUF Q4_K_M"}), encoding="utf-8")
    cells = [J1B_CELLS[0], J1B_CELLS[1] % {"ds": tag}, J1B_CELLS[2], ASK % {"shard": shard, "n": n}]
    for i, c in enumerate(cells):
        compile(c, f"<cell {i}>", "exec")
    nb = {"cells": [{"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
                     "source": c.strip("\n").splitlines(keepends=True)} for c in cells],
          "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                       "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
    k = out / "kernel"
    k.mkdir(parents=True)
    (k / f"{tag}.ipynb").write_text(json.dumps(nb, indent=1), encoding="utf-8")
    (k / "kernel-metadata.json").write_text(json.dumps({
        "id": f"tishaferdous/dlr-forced-shard-{shard}-of-{n}", "title": f"DLR Forced Shard {shard} of {n}",
        "code_file": f"{tag}.ipynb", "language": "python", "kernel_type": "notebook", "is_private": True,
        "enable_gpu": True, "enable_internet": True, "machine_shape": "NvidiaTeslaT4",
        "dataset_sources": [f"tishaferdous/{tag}-data"], "competition_sources": [],
        "kernel_sources": []}, indent=1), encoding="utf-8")
    pub = out / "dataset_publish"
    pub.mkdir(parents=True)
    with zipfile.ZipFile(pub / f"{tag}.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for f in ds.rglob("*"):
            if f.is_file():
                z.write(f, Path(tag) / f.relative_to(ds))
    (pub / "dataset-metadata.json").write_text(json.dumps({
        "title": f"DLR1 Forced {shard} of {n} Data", "id": f"tishaferdous/{tag}-data",
        "licenses": [{"name": "MIT"}]}, indent=1), encoding="utf-8")
    print(f"{out.name}: all cells compile")


if __name__ == "__main__":
    main()
