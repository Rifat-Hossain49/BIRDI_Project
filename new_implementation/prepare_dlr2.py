#!/usr/bin/env python3
"""Bundle pilot 2 (diverse reading paths) for Kaggle 2x T4.

One session: build llama.cpp, generate checklist-path designs, then simulate them
and golden on the same 208 ConfiBench-4o sub-testbenches the direct path used.
Reuses J1b's proven hardware, build and server cells verbatim.
"""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from prepare_xjudge_j1b import CELLS as J1B_CELLS

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "kaggle_upload_dlr2"
DS = "dlr2"
FILES = ["analysis/dlr2_tasks.jsonl", "analysis/dlr2_subtbs.jsonl", "analysis/dlr2_prompt.txt",
         "analysis/j1_generate.py", "analysis/j1_generate_llamacpp.py", "analysis/ref_pilot.py",
         "DLR2_PREREGISTRATION.md"]
GOLDEN = ROOT / "kaggle_upload_safe_cbx/dataset/active_tb_safe_cbx/golden.jsonl"

GEN = """
if NP:
    p=subprocess.Popen([sys.executable,str(SRC/'j1_generate_llamacpp.py'),
       '--tasks',str(SRC/'dlr2_tasks.jsonl'),'--samples-out',str(WORK/'chk_samples.jsonl'),
       '--raw-out',str(WORK/'chk_raw.jsonl'),'--log',str(WORK/'chk_generate.log'),
       '--samples','5','--concurrency',str(NP),'--budget-hours','9.5',
       '--prompt-file',str(SRC/'dlr2_prompt.txt'),'--id-prefix','chk'],
       stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    for line in p.stdout: print(line,end='',flush=True)
    print('generate exit code', p.wait())
try: srv.kill()
except Exception: pass
"""

SIM = """
duts=[]
gold={json.loads(l)['task_id']:json.loads(l)['module_code'] for l in open(SRC/'golden.jsonl',encoding='utf-8') if l.strip()}
want={json.loads(l)['task_id'] for l in open(SRC/'dlr2_tasks.jsonl',encoding='utf-8') if l.strip()}
for t in sorted(want):
    duts.append({'task_id':t,'family':'golden','candidate_id':f'golden_{t}','rtl':gold[t]})
n_mod=0
if (WORK/'chk_samples.jsonl').is_file():
    for l in open(WORK/'chk_samples.jsonl',encoding='utf-8'):
        if not l.strip(): continue
        r=json.loads(l)
        if r.get('rtl'):
            duts.append({'task_id':r['task_id'],'family':'C_checklist','candidate_id':r['candidate_id'],'rtl':r['rtl']}); n_mod+=1
(WORK/'dlr2_duts.jsonl').write_text(''.join(json.dumps(d)+'\\n' for d in duts),encoding='utf-8')
print('checklist designs with a module:', n_mod, flush=True)
sh(f"{sys.executable} {SRC/'ref_pilot.py'} --subtbs {SRC/'dlr2_subtbs.jsonl'} --duts {WORK/'dlr2_duts.jsonl'} "
   f"--out {WORK/'dlr2_rows.jsonl'}",'dlr2_sim.log')
print(open(WORK/'dlr2_sim.log').read()[-1500:], flush=True)
with zipfile.ZipFile(WORK/'dlr2_results.zip','w',zipfile.ZIP_DEFLATED) as z:
    for f in sorted(WORK.glob('*')):
        if f.is_file() and f.suffix in ('.jsonl','.log'): z.write(f, f.name)
print('packed', (WORK/'dlr2_results.zip').stat().st_size//(1<<20), 'MB', flush=True)
"""


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    ds = OUT / "dataset" / DS
    ds.mkdir(parents=True)
    for f in FILES:
        shutil.copy2(ROOT / f, ds / Path(f).name)
    shutil.copy2(GOLDEN, ds / "golden.jsonl")
    (ds / "XJ_BOUNDARY.json").write_text(json.dumps({
        "pilot": "DLR-2 diverse reading paths", "prereg": "DLR2_PREREGISTRATION.md"}), encoding="utf-8")
    cells = [J1B_CELLS[0], J1B_CELLS[1] % {"ds": DS}, J1B_CELLS[2], GEN, SIM]
    for i, c in enumerate(cells):
        compile(c, f"<cell {i}>", "exec")
    nb = {"cells": [{"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
                     "source": c.strip("\n").splitlines(keepends=True)} for c in cells],
          "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                       "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
    k = OUT / "kernel"
    k.mkdir(parents=True)
    (k / "dlr2.ipynb").write_text(json.dumps(nb, indent=1), encoding="utf-8")
    (k / "kernel-metadata.json").write_text(json.dumps({
        "id": "tishaferdous/dlr-pilot-two", "title": "DLR Pilot Two", "code_file": "dlr2.ipynb",
        "language": "python", "kernel_type": "notebook", "is_private": True,
        "enable_gpu": True, "enable_internet": True, "machine_shape": "NvidiaTeslaT4",
        "dataset_sources": ["tishaferdous/dlr2-pilot-data"], "competition_sources": [],
        "kernel_sources": []}, indent=1), encoding="utf-8")
    pub = OUT / "dataset_publish"
    pub.mkdir(parents=True)
    with zipfile.ZipFile(pub / f"{DS}.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for f in ds.rglob("*"):
            if f.is_file():
                z.write(f, Path(DS) / f.relative_to(ds))
    (pub / "dataset-metadata.json").write_text(json.dumps({
        "title": "DLR2 Pilot Data", "id": "tishaferdous/dlr2-pilot-data",
        "licenses": [{"name": "MIT"}]}, indent=1), encoding="utf-8")
    print("bundle:", (pub / f"{DS}.zip").stat().st_size // 1024, "KB; all cells compile")


if __name__ == "__main__":
    main()
