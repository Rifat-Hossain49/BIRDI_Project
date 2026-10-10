#!/usr/bin/env python3
"""Build a CPU-only Kaggle notebook that explains *why* Eval1 fails.

For every frozen testbench it runs the golden RTL and captures the FAIL lines
the testbench emits. Each line carries the scenario, the check index, the
expected value and the observed value, which separates two very different
causes:

  * failing at check index 0 on every scenario points at a systematic harness
    or phase convention error,
  * failing at scattered later indices points at the oracle RTL being
    functionally wrong, which no harness change can repair.

It reuses the already published post-freeze evaluation dataset, so it needs no
new upload and reveals nothing that phase has not already seen.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KERNEL = ROOT / "kaggle_upload_eval1_diagnostic" / "kernel"
NOTEBOOK = ROOT / "ACTIVE_TB_S_Eval1_Diagnostic_Kaggle.ipynb"


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


SETUP = """from pathlib import Path
import json, re, shutil, subprocess, sys, zipfile, csv, collections
INPUT=Path('/kaggle/input'); WORK=Path('/kaggle/working')
markers=list(INPUT.rglob('active_tb_s_evaluation_full_v1/EVALUATION_BOUNDARY.json'))
assert len(markers)==1, markers
SOURCE=markers[0].parent
frozen_zip=SOURCE/'active_tb_s_frozen_full_v1.zip'
frozen_dir=SOURCE/'active_tb_s_frozen_full_v1'
if frozen_zip.exists():
 FROZEN=WORK/'frozen'
 with zipfile.ZipFile(frozen_zip) as zf: zf.extractall(FROZEN)
elif frozen_dir.is_dir(): FROZEN=frozen_dir
else: raise FileNotFoundError('no frozen bundle')
seeds=sorted(x.name for x in FROZEN.glob('seed_*'))
assert seeds==['seed_017','seed_029','seed_043','seed_059','seed_073'], seeds
tasks={}
for line in (SOURCE/'HDLBits_full.jsonl').read_text().splitlines():
 if line.strip():
  row=json.loads(line); tasks[row['task_id']]=row
print('tasks:',len(tasks),'frozen:',FROZEN)
subprocess.run(['apt-get','update','-qq'],check=True)
subprocess.run(['apt-get','install','-y','-qq','iverilog'],check=True)
print('iverilog ready')
"""

RUN = """SEED='seed_017'
METHODS=['typed_formal_active','single_oracle','diverse_ensemble']
OUT=WORK/'eval1_diagnostic'; OUT.mkdir(exist_ok=True)
scratch=WORK/'scratch'
rows=[]

def run_one(rtl, tb):
    if scratch.exists(): shutil.rmtree(scratch)
    scratch.mkdir(parents=True)
    (scratch/'dut.v').write_text(rtl)
    (scratch/'tb.sv').write_text(tb)
    c=subprocess.run(['iverilog','-g2012','-o','sim','dut.v','tb.sv'],cwd=scratch,
                     capture_output=True,text=True,timeout=120)
    if c.returncode: return 'COMPILE_ERROR', c.stderr[:300], []
    r=subprocess.run(['vvp','sim'],cwd=scratch,capture_output=True,text=True,timeout=120)
    fails=[l for l in r.stdout.splitlines() if l.startswith('FAIL|')]
    return ('PASS' if not fails else 'FAIL'), '', fails

for method in METHODS:
    root=FROZEN/SEED/'frozen'/method
    if not root.is_dir(): continue
    for d in sorted(root.iterdir()):
        tb_path=d/'testbench.sv'
        if not tb_path.is_file(): continue
        tb=tb_path.read_text()
        if not tb.strip(): continue
        task=d.name
        if task not in tasks: continue
        status,err,fails=run_one(str(tasks[task]['module_code']), tb)
        total_checks=len(re.findall(r'expected=', tb))
        first_idx=first_scen=first_exp=first_got=''
        if fails:
            m=re.match(r'FAIL\\|([^|]*)\\|(\\d+)\\|([^|]*)\\|expected=(\\w+)\\|got=(\\w+)', fails[0])
            if m:
                first_scen,first_idx,_,first_exp,first_got=m.groups()
        rows.append({'method':method,'task_id':task,'status':status,
                     'total_checks':total_checks,'n_fail_lines':len(fails),
                     'first_fail_index':first_idx,'first_fail_scenario':first_scen,
                     'first_expected':first_exp,'first_got':first_got,
                     'compile_error':err})
        with (OUT/'eval1_diagnostic.csv').open('w',newline='') as fh:
            w=csv.DictWriter(fh,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print('done',method,len(rows))
print('total rows',len(rows))
"""

SUMMARY = """d=collections.defaultdict(lambda: collections.Counter())
for r in rows:
    m=r['method']; d[m][r['status']]+=1
    if r['status']=='FAIL' and r['first_fail_index']!='':
        d[m]['first_check_0' if r['first_fail_index']=='0' else 'first_check_later']+=1
for m,c in d.items():
    tot=c['PASS']+c['FAIL']+c['COMPILE_ERROR']
    print(f"{m:22s} n={tot:4d} PASS={c['PASS']:4d} FAIL={c['FAIL']:4d} COMPILE_ERROR={c['COMPILE_ERROR']:3d}")
    print(f"{'':22s}   of failures: first bad check at index 0 = {c['first_check_0']}, at a later index = {c['first_check_later']}")
shutil.make_archive(str(WORK/'eval1_diagnostic'),'zip',OUT)
print('packaged')
"""


def main() -> None:
    notebook = {
        "cells": [
            markdown_cell(
                "# ACTIVE-TB-S: why does Eval1 fail?\n\n"
                "Runs each frozen testbench against the golden RTL and records the first "
                "failing check. Diagnostic only: it produces no new testbenches and "
                "changes no frozen artefact.\n",
                "intro"),
            code_cell(SETUP, "setup"),
            code_cell(RUN, "run"),
            code_cell(SUMMARY, "summary"),
        ],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.12"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    NOTEBOOK.write_text(json.dumps(notebook, indent=1) + "\n", encoding="utf-8")
    KERNEL.mkdir(parents=True, exist_ok=True)
    shutil.copy2(NOTEBOOK, KERNEL / NOTEBOOK.name)
    (KERNEL / "kernel-metadata.json").write_text(json.dumps({
        "id": "tishaferdous/active-tb-s-eval1-diagnostic",
        "title": "ACTIVE TB S Eval1 Diagnostic",
        "code_file": NOTEBOOK.name,
        "language": "python", "kernel_type": "notebook", "is_private": True,
        "enable_gpu": False, "enable_internet": True,
        "dataset_sources": ["tishaferdous/active-tb-s-post-freeze-evaluation-full-v1"],
        "competition_sources": [], "kernel_sources": [],
    }, indent=2), encoding="utf-8")
    print("Built", NOTEBOOK)


if __name__ == "__main__":
    main()
