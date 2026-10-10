#!/usr/bin/env python3
"""Bundle the J1 judge run (Qwen3.5-27B zero-shot) for a Kaggle 2x T4 session."""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "kaggle_upload_xjudge_j1"
DS = "xjudge_j1"
FILES = [
    "analysis/j1_tasks.jsonl", "analysis/j1_generate.py", "analysis/j1_post.py",
    "analysis/xjudge_run.py", "analysis/xjudge_subtbs.jsonl",
    "XJUDGE_PREREGISTRATION.md",
]
GOLDEN = ROOT / "kaggle_upload_safe_cbx/dataset/active_tb_safe_cbx/golden.jsonl"

CELLS = [
"""
# Hardware check first: a wrong accelerator must fail in minutes, not hours.
import subprocess
out = subprocess.run(['nvidia-smi','--query-gpu=name,memory.total,driver_version',
                      '--format=csv,noheader'], capture_output=True, text=True).stdout
print(out)
gpus = [l for l in out.splitlines() if l.strip()]
assert len(gpus) >= 2 and all('T4' in g for g in gpus), f'need 2x T4, got: {gpus}'
""",
"""
from pathlib import Path
import json, subprocess, sys, zipfile, time, shutil
INPUT=Path('/kaggle/input'); WORK=Path('/kaggle/working')
m=list(INPUT.rglob('%(ds)s/XJ_BOUNDARY.json'))
if len(m)==1: SRC=m[0].parent
else:
 a=list(INPUT.rglob('%(ds)s.zip')); assert len(a)==1, a
 with zipfile.ZipFile(a[0]) as zf: zf.extractall(WORK/'att')
 SRC=WORK/'att'/'%(ds)s'
t0=time.time()
subprocess.run(['apt-get','update','-qq'],check=True)
subprocess.run(['apt-get','install','-y','-qq','iverilog'],check=True)
r=subprocess.run([sys.executable,'-m','pip','install','-q','-U','vllm'],capture_output=True,text=True)
print(r.stdout[-1500:], r.stderr[-2500:])
r=subprocess.run([sys.executable,'-c','import vllm,torch,transformers;print(vllm.__version__,torch.__version__,transformers.__version__)'],capture_output=True,text=True)
print('versions:', r.stdout.strip(), r.stderr[-800:])
print(f'setup {time.time()-t0:.0f}s', flush=True)
""",
"""
# Generation: streamed so progress is visible, saved chunk by chunk.
p=subprocess.Popen([sys.executable,str(SRC/'j1_generate.py'),
   '--tasks',str(SRC/'j1_tasks.jsonl'),'--out',str(WORK/'j1_raw.jsonl'),
   '--log',str(WORK/'j1_generate.log'),'--samples','5','--budget-hours','8.5'],
   stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
for line in p.stdout: print(line,end='',flush=True)
print('generate exit code', p.wait())
""",
"""
if (WORK/'j1_raw.jsonl').is_file():
    r=subprocess.run([sys.executable,str(SRC/'j1_post.py'),'--raw',str(WORK/'j1_raw.jsonl'),
       '--golden',str(SRC/'golden.jsonl'),'--candidates',str(WORK/'j1_candidates.jsonl'),
       '--official',str(WORK/'j1_official.jsonl')],capture_output=True,text=True)
    print(r.stdout[-4000:], r.stderr[-2000:])
""",
"""
if (WORK/'j1_candidates.jsonl').is_file():
    r=subprocess.run([sys.executable,str(SRC/'xjudge_run.py'),'--subtbs',str(SRC/'xjudge_subtbs.jsonl'),
       '--candidates',str(WORK/'j1_candidates.jsonl'),'--out',str(WORK/'j1_results.jsonl')],
       capture_output=True,text=True)
    print(r.stdout[-4000:], r.stderr[-2000:])
""",
"""
with zipfile.ZipFile(WORK/'xjudge_j1_results.zip','w',zipfile.ZIP_DEFLATED) as z:
    for f in ('j1_raw.jsonl','j1_generate.log','j1_candidates.jsonl','j1_official.jsonl','j1_results.jsonl'):
        if (WORK/f).is_file(): z.write(WORK/f, f)
print('packed', (WORK/'xjudge_j1_results.zip').stat().st_size//1024, 'KB')
""",
]


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    ds = OUT / "dataset" / DS
    ds.mkdir(parents=True)
    for f in FILES:
        shutil.copy2(ROOT / f, ds / Path(f).name)
    shutil.copy2(GOLDEN, ds / "golden.jsonl")
    (ds / "XJ_BOUNDARY.json").write_text(json.dumps({
        "judge": "J1", "model": "Qwen/Qwen3.5-27B-GPTQ-Int4", "fine_tuned": False,
        "prereg": "XJUDGE_PREREGISTRATION.md"}, indent=1), encoding="utf-8")
    nb = {"cells": [{"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
                     "source": (c % {"ds": DS}).strip("\n").splitlines(keepends=True)}
                    for c in CELLS],
          "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python",
                                      "name": "python3"}, "language_info": {"name": "python"}},
          "nbformat": 4, "nbformat_minor": 5}
    k = OUT / "kernel"
    k.mkdir(parents=True)
    (k / "xjudge_j1.ipynb").write_text(json.dumps(nb, indent=1), encoding="utf-8")
    (k / "kernel-metadata.json").write_text(json.dumps({
        "id": "tishaferdous/xjudge-j1", "title": "XJUDGE J1",
        "code_file": "xjudge_j1.ipynb", "language": "python", "kernel_type": "notebook",
        "is_private": True, "enable_gpu": True, "enable_internet": True,
        "machine_shape": "NvidiaTeslaT4",
        "dataset_sources": ["tishaferdous/xjudge-j1-data"],
        "competition_sources": [], "kernel_sources": []}, indent=1), encoding="utf-8")
    pub = OUT / "dataset_publish"
    pub.mkdir(parents=True)
    with zipfile.ZipFile(pub / f"{DS}.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for f in ds.rglob("*"):
            if f.is_file():
                z.write(f, Path(DS) / f.relative_to(ds))
    (pub / "dataset-metadata.json").write_text(json.dumps({
        "title": "XJUDGE J1 Data", "id": "tishaferdous/xjudge-j1-data",
        "licenses": [{"name": "MIT"}]}, indent=1), encoding="utf-8")
    print("bundle:", (pub / f"{DS}.zip").stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
