#!/usr/bin/env python3
"""Bundle the improved ACTIVE-TB-SAFE release and its ablation arms for Kaggle.

The kernel runs four arms per frontend, all on the same tasks, the same candidate
pool and the same solver budget, so any difference between them is attributable
to the one thing that differs:

  control      the shipped SAFE: Case-A "blessed" gate, fixed pair order, no
               repair. Present so the previous result is REPRODUCED in the same
               run rather than quoted from an earlier one.
  improved     translation gate, baseline-aware pair order, assertion-level
               repair.
  fixedorder   improved, minus baseline-aware ordering. Isolates what the
               ordering alone contributes.
  random       improved, with the differential-BMC witness replaced by random
               stimulus matched test-for-test and cycle-for-cycle to `improved`.
               Isolates what the formal search contributes.

Scoring runs once over all arms together (`reconcile_eval.py --arm ...`), which
both guarantees a shared execution path and lets Channel 1 -- byte-identical
across arms -- be simulated once instead of four times.
"""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
import os
FRONTEND_SET = os.environ.get("SAFE_FRONTENDS", "correctbench,autobench")
TAG = os.environ.get("SAFE_TAG", "v3")
OUT = ROOT / f"kaggle_upload_safe_{TAG}"
DS = f"active_tb_safe_{TAG}"
SRC_BUNDLE = ROOT / "kaggle_upload_safe_full" / "dataset" / "active_tb_safe_full_v1"

CODE = [
    ("amp/frontend_adapter.py", "amp/frontend_adapter.py"),
    ("amp/checker_state.py", "amp/checker_state.py"),
    ("amp/vexpr.py", "amp/vexpr.py"),
    ("amp/all_tasks.json", "amp/all_tasks.json"),
    ("safe/shadow_verify.py", "safe/shadow_verify.py"),
    ("safe/formal_witness.py", "safe/formal_witness.py"),
    ("safe/run_safe.py", "safe/run_safe.py"),
    ("safe/reconcile_eval.py", "safe/reconcile_eval.py"),
    ("safe/funnel.py", "safe/funnel.py"),
    ("safe/sealed_dual_eval.py", "safe/sealed_dual_eval.py"),
    ("safe/sota_compare.py", "safe/sota_compare.py"),
    ("safe/synthetic_cases.py", "safe/synthetic_cases.py"),
]
DATA = [
    "baselines/ConfiBench/data/AutoBenchResults/run_info_and_codes.jsonl",
    "baselines/ConfiBench/data/CorrectBenchResults/run_info_and_codes.jsonl",
    "baselines/ConfiBench/data/ConfiBenchResults/run_info_and_codes.jsonl",
    "METHOD_FREEZE_v3.json",
    "golden.jsonl",
    "hidden_bank_a.jsonl",
    "kaggle_runs/spec_only_full_repair_v2_complete/active_tb_s_repaired_oracles_full_v1/codegemma_candidates.jsonl",
    "kaggle_runs/spec_only_full_repair_v2_complete/active_tb_s_repaired_oracles_full_v1/llama_candidates.jsonl",
    "kaggle_runs/spec_only_full_repair_v2_complete/active_tb_s_repaired_oracles_full_v1/qwen_candidates.jsonl",
]

ARMS = [
    ("control",    ["--gate", "blessed", "--pair-order", "fixed", "--no-repair"]),
    ("improved",   ["--gate", "translation", "--pair-order", "baseline-aware"]),
    ("fixedorder", ["--gate", "translation", "--pair-order", "fixed"]),
]

CELL_SETUP = """
from pathlib import Path
import json, subprocess, sys, zipfile, time, shutil
INPUT=Path('/kaggle/input'); WORK=Path('/kaggle/working')
m=list(INPUT.rglob('%(ds)s/SAFE_BOUNDARY.json'))
if len(m)==1: SRC=m[0].parent
else:
 a=list(INPUT.rglob('%(ds)s.zip')); assert len(a)==1, a
 d=WORK/'att'
 with zipfile.ZipFile(a[0]) as zf: zf.extractall(d)
 SRC=d/'%(ds)s'
print(json.loads((SRC/'SAFE_BOUNDARY.json').read_text()))
subprocess.run(['apt-get','update','-qq'],check=True)
subprocess.run(['apt-get','install','-y','-qq','yosys','iverilog','z3'],check=True)
print('tools ready', flush=True)

_ALL={'correctbench':'CorrectBenchResults','autobench':'AutoBenchResults',
      'confibench':'ConfiBenchResults'}
FRONTENDS=tuple((f,_ALL[f]) for f in %(frontends)r.split(','))
BUDGET=['--bounds','4,8,16,32','--timeout','60','--max-pairs','4']
def run(label,*a):
    t0=time.time(); print('='*20,label,'='*20,flush=True)
    r=subprocess.run([sys.executable,*a],text=True,capture_output=True,cwd=SRC)
    print(r.stdout[-6000:])
    if r.returncode: print('STDERR:',r.stderr[-4000:])
    print(f'{label} {time.time()-t0:.0f}s',flush=True)
    return r.returncode
"""

CELL_GEN = """
# Stage 1: three formal arms per frontend, identical budget.
ARMS=%(arms)r
for fe,_ in FRONTENDS:
    for name,flags in ARMS:
        out=WORK/f'{fe}__{name}'
        run(f'{fe}/{name}', str(SRC/'safe'/'run_safe.py'),
            '--frontend',fe,'--tasks',str(SRC/'amp'/'all_tasks.json'),
            *BUDGET,*flags,'--out',str(out))
"""

CELL_RANDOM = """
# Stage 2: the stimulus ablation, matched test-for-test to `improved`.
for fe,_ in FRONTENDS:
    ref=WORK/f'{fe}__improved'/'safe_manifest.json'
    if not ref.is_file():
        print('no improved manifest for',fe,'- skipping random arm',flush=True); continue
    run(f'{fe}/random', str(SRC/'safe'/'run_safe.py'),
        '--frontend',fe,'--tasks',str(SRC/'amp'/'all_tasks.json'),
        *BUDGET,'--gate','translation','--stimulus','random',
        '--match-manifest',str(ref),'--seed','0',
        '--out',str(WORK/f'{fe}__random'))
"""

CELL_FUNNEL = """
# Stage 3: the complete loss funnel, per arm.
FN=WORK/'funnels'; FN.mkdir(exist_ok=True)
for fe,_ in FRONTENDS:
    specs=[]
    for name in ('control','improved','fixedorder','random'):
        p=WORK/f'{fe}__{name}'/'safe_manifest.json'
        if p.is_file(): specs+= ['--manifest',f'{fe}/{name}={p}']
    if specs:
        run(f'funnel/{fe}', str(SRC/'safe'/'funnel.py'),
            '--tasks',str(SRC/'amp'/'all_tasks.json'),*specs,
            '--out',str(FN/f'{fe}_funnel.md'))
"""

CELL_EVAL = """
# Stage 4: one scoring pass over every arm, shared execution path.
EV=WORK/'reconcile'; EV.mkdir(exist_ok=True)
for fe,dirn in FRONTENDS:
    arms=[]
    for name in ('control','improved','fixedorder','random'):
        p=WORK/f'{fe}__{name}'
        if (p/'safe_manifest.json').is_file(): arms += ['--arm',f'{name}={p}']
    if not arms:
        print('no arms for',fe,flush=True); continue
    run(f'reconcile/{fe}', str(SRC/'safe'/'reconcile_eval.py'),
        '--frontend-records',str(SRC/'baselines/ConfiBench/data'/dirn/'run_info_and_codes.jsonl'),
        *arms,'--golden',str(SRC/'golden.jsonl'),
        '--mutants',str(SRC/'hidden_bank_a.jsonl'),
        '--tasks',str(SRC/'amp'/'all_tasks.json'),
        '--out',str(EV/f'{fe}_reconcile.csv'))
"""

CELL_PACK = """
# Stage 5: pack every manifest, funnel and score for download.
import tarfile
res=WORK/'safe_v3_results'; res.mkdir(exist_ok=True)
for fe,_ in FRONTENDS:
    for name in ('control','improved','fixedorder','random'):
        p=WORK/f'{fe}__{name}'
        if (p/'safe_manifest.json').is_file():
            d=res/f'{fe}__{name}'; d.mkdir(parents=True,exist_ok=True)
            shutil.copy2(p/'safe_manifest.json', d/'safe_manifest.json')
            n=len(list((p/'suites').glob('*.v'))) if (p/'suites').is_dir() else 0
            print(f'{fe}/{name}: {n} suite file(s)')
for d in ('funnels','reconcile'):
    if (WORK/d).is_dir(): shutil.copytree(WORK/d, res/d, dirs_exist_ok=True)
with zipfile.ZipFile(WORK/'safe_v3_results.zip','w',zipfile.ZIP_DEFLATED) as z:
    for f in res.rglob('*'):
        if f.is_file(): z.write(f, f.relative_to(res))
print('packed', (WORK/'safe_v3_results.zip').stat().st_size//1024, 'KB')
"""


def cell(src: str) -> dict:
    return {"cell_type": "code", "execution_count": None, "metadata": {},
            "outputs": [], "source": src.strip("\n").splitlines(keepends=True)}


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    ds = OUT / "dataset" / DS
    ds.mkdir(parents=True)

    missing = []
    for src, dst in CODE:
        s = ROOT / src
        if not s.is_file():
            missing.append(src)
            continue
        (ds / dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, ds / dst)
    for rel in DATA:
        s = ROOT / rel
        if not s.is_file():
            s = SRC_BUNDLE / Path(rel).name
            if not s.is_file():
                cand = list(SRC_BUNDLE.rglob(Path(rel).name))
                s = cand[0] if cand else None
        if not s or not s.is_file():
            missing.append(rel)
            continue
        (ds / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, ds / rel)
    if missing:
        raise SystemExit("missing inputs:\n  " + "\n  ".join(missing))

    (ds / "SAFE_BOUNDARY.json").write_text(json.dumps({
        "release": "ACTIVE-TB-SAFE v3",
        "channel1": "frozen generator bytes, shipped verbatim",
        "channel2": "differential BMC -> frozen-checker adjudication -> warnings",
        "gate": "translation fidelity (candidate-free); Case-A retained as control",
        "arms": [a for a, _ in ARMS] + ["random"],
        "golden_used_at_generation": False,
    }, indent=1), encoding="utf-8")

    nb = {"cells": [cell(CELL_SETUP % {"ds": DS, "frontends": FRONTEND_SET}),
                    cell(CELL_GEN % {"arms": ARMS}),
                    cell(CELL_RANDOM), cell(CELL_FUNNEL),
                    cell(CELL_EVAL), cell(CELL_PACK)],
          "metadata": {"kernelspec": {"display_name": "Python 3",
                                      "language": "python", "name": "python3"},
                       "language_info": {"name": "python"}},
          "nbformat": 4, "nbformat_minor": 5}
    kdir = OUT / "kernel"
    kdir.mkdir(parents=True)
    nbname = f"ACTIVE_TB_SAFE_{TAG}_Kaggle.ipynb"
    (kdir / nbname).write_text(json.dumps(nb, indent=1), encoding="utf-8")
    (kdir / "kernel-metadata.json").write_text(json.dumps({
        "id": f"tishaferdous/active-tb-safe-{TAG}",
        "title": f"ACTIVE TB SAFE {TAG}",
        "code_file": nbname, "language": "python", "kernel_type": "notebook",
        "is_private": True, "enable_gpu": False, "enable_internet": True,
        "dataset_sources": [f"tishaferdous/active-tb-safe-{TAG}-data"],
        "competition_sources": [], "kernel_sources": [],
    }, indent=1), encoding="utf-8")

    pub = OUT / "dataset_publish"
    pub.mkdir(parents=True)
    zpath = pub / f"{DS}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in ds.rglob("*"):
            if f.is_file():
                z.write(f, Path(DS) / f.relative_to(ds))
    (pub / "dataset-metadata.json").write_text(json.dumps({
        "title": f"ACTIVE TB SAFE {TAG} Data",
        "id": f"tishaferdous/active-tb-safe-{TAG}-data",
        "licenses": [{"name": "MIT"}],
    }, indent=1), encoding="utf-8")

    n = sum(1 for f in ds.rglob("*") if f.is_file())
    print(f"bundle: {n} files, zip {zpath.stat().st_size // 1024} KB")
    print(f"  dataset  {pub}")
    print(f"  kernel   {kdir}")


if __name__ == "__main__":
    main()
