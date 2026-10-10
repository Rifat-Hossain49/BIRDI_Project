#!/usr/bin/env python3
"""Bundle Stage 3 candidate generation (direct path, all 156 tasks), one shard per session.

Frozen configuration: Qwen3.5-27B Q4_K_M via llama.cpp, J1 prompt, 5 samples per
task, thinking on, budget forcing (8000 reasoning tokens, 3000 answer tokens).

Sharding lets several Kaggle accounts generate in parallel; resumability lets a shard
continue in a later session: pass --prev to carry already-completed samples forward.

usage: python prepare_stage3_gen.py <shard_index> <n_shards> [--prev samples.jsonl] [--samples N]

--samples N (default 5) is the total designs per task; with --prev the generator only fills
the missing sample indices, so a second round is --samples 10 on top of round-one samples.
"""
from __future__ import annotations

import json
import shutil
import sys
import zipfile
from pathlib import Path

from prepare_xjudge_j1b import CELLS as J1B_CELLS

ROOT = Path(__file__).resolve().parent

SMOKE = """
# Smoke test of budget forcing before any real work: render the chat template, then
# force-close a deliberately tiny reasoning budget and check a module comes back.
import urllib.request
sys.path.insert(0, str(SRC))
if NP:
    from generate import render, generate_one
    from j1_generate import extract_rtl
    pr = render('http://127.0.0.1:8080', 'Write a Verilog module top_module with input a, output b, where b = ~a.')
    print('rendered prompt tail:', repr(pr[-120:]))
    text, ntok, mode, stop = generate_one('http://127.0.0.1:8080',
        'Write a Verilog module top_module(input a, output b) where b = ~a. Return it in a verilog code block.',
        seed=7, budget=48, answer_budget=400)
    print('smoke: mode', mode, 'stop', stop, 'tokens', ntok, 'module extracted:', bool(extract_rtl(text)))
    SMOKE_OK = mode in ('forced', 'natural', 'continued')
else:
    SMOKE_OK = False
print('SMOKE_OK =', SMOKE_OK, flush=True)
"""

GEN = """
prev = SRC/'prev_samples.jsonl'
if prev.is_file() and not (WORK/'gen_samples.jsonl').is_file():
    shutil.copy2(prev, WORK/'gen_samples.jsonl')
    print('resuming from', sum(1 for _ in open(prev)), 'samples', flush=True)
if NP and SMOKE_OK:
    p=subprocess.Popen([sys.executable,str(SRC/'generate.py'),'--tasks',str(SRC/'shard_tasks.jsonl'),
       '--out',str(WORK/'gen_samples.jsonl'),'--path','direct','--samples','%(samples)d',
       '--budget','8000','--answer-budget','3000','--concurrency',str(NP),'--budget-hours','%(hours)s'],
       stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    for line in p.stdout: print(line,end='',flush=True)
    print('generate exit code', p.wait())
try: srv.kill()
except Exception: pass
with zipfile.ZipFile(WORK/'stage3_gen_results.zip','w',zipfile.ZIP_DEFLATED) as z:
    for f in sorted(WORK.glob('*')):
        if f.is_file() and f.suffix in ('.jsonl','.log'): z.write(f, f.name)
print('packed', flush=True)
"""


def main() -> None:
    shard, n_shards = int(sys.argv[1]), int(sys.argv[2])
    prev = Path(sys.argv[sys.argv.index("--prev") + 1]) if "--prev" in sys.argv else None
    samples = int(sys.argv[sys.argv.index("--samples") + 1]) if "--samples" in sys.argv else 5
    # generation hours before packing; lower it when an account is near its weekly GPU quota
    hours = float(sys.argv[sys.argv.index("--hours") + 1]) if "--hours" in sys.argv else 10.5
    tag = f"s3gen{shard}of{n_shards}" + (f"n{samples}" if samples != 5 else "")
    out = ROOT / f"kaggle_upload_{tag}"
    ds_name = tag
    if out.exists():
        shutil.rmtree(out)
    ds = out / "dataset" / ds_name
    ds.mkdir(parents=True)
    tasks = [json.loads(l) for l in (ROOT / "dirtb/tasks_all.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    mine = [t for i, t in enumerate(tasks) if i % n_shards == shard]
    (ds / "shard_tasks.jsonl").write_text("".join(json.dumps(t) + "\n" for t in mine), encoding="utf-8")
    for f in ("dirtb/generate.py", "analysis/j1_generate.py"):
        shutil.copy2(ROOT / f, ds / Path(f).name)
    if prev and prev.is_file():
        mine_ids = {str(task["task_id"]) for task in mine}
        previous_rows = [
            json.loads(line)
            for line in prev.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        previous_rows = [row for row in previous_rows if str(row["task_id"]) in mine_ids]
        keys = [(str(row["task_id"]), row.get("path", "direct"), int(row["sample_idx"])) for row in previous_rows]
        if len(keys) != len(set(keys)):
            raise RuntimeError(f"Duplicate resume keys in {prev}")
        (ds / "prev_samples.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in previous_rows), encoding="utf-8"
        )
    (ds / "XJ_BOUNDARY.json").write_text(json.dumps({"stage": 3, "shard": shard, "n_shards": n_shards,
                                                     "tasks": len(mine), "samples": samples}), encoding="utf-8")
    cells = [J1B_CELLS[0], J1B_CELLS[1] % {"ds": ds_name}, J1B_CELLS[2], SMOKE, GEN % {"samples": samples, "hours": hours}]
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
        "id": f"tishaferdous/stage3-gen-shard-{shard}-of-{n_shards}" + (f"-n{samples}" if samples != 5 else ""),
        "title": f"Stage3 Gen Shard {shard} of {n_shards}" + (f" N{samples}" if samples != 5 else ""),
        "code_file": f"{tag}.ipynb",
        "language": "python", "kernel_type": "notebook", "is_private": True,
        "enable_gpu": True, "enable_internet": True, "machine_shape": "NvidiaTeslaT4",
        "dataset_sources": [f"tishaferdous/{tag}-data"], "competition_sources": [],
        "kernel_sources": []}, indent=1), encoding="utf-8")
    pub = out / "dataset_publish"
    pub.mkdir(parents=True)
    with zipfile.ZipFile(pub / f"{ds_name}.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for f in ds.rglob("*"):
            if f.is_file():
                z.write(f, Path(ds_name) / f.relative_to(ds))
    (pub / "dataset-metadata.json").write_text(json.dumps({
        "title": f"Stage3 Gen {shard} of {n_shards} Data", "id": f"tishaferdous/{tag}-data",
        "licenses": [{"name": "MIT"}]}, indent=1), encoding="utf-8")
    print(f"{out.name}: {len(mine)} tasks, {len(mine) * samples} samples; all cells compile")


if __name__ == "__main__":
    main()
