#!/usr/bin/env python3
"""Build the Stage-1 IVRP Kaggle experiment (20 frozen pilot tasks).

The dataset carries sanitised specifications, the frozen testbenches and their
suites, population A's cross-method votes, and the project code. It carries no
golden RTL, official testbench, or mutants: scoring against golden happens
locally, after the arbitration decisions are hashed.
"""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT / "extracted_v1" / "active_tb_budgeted_adaptive"
UPLOAD = ROOT / "kaggle_upload_ivrp"
STAGE = UPLOAD / "dataset" / "active_tb_s_ivrp_v1"
PUBLISH = UPLOAD / "dataset_publish"
KERNEL = UPLOAD / "kernel"
NOTEBOOK = ROOT / "ACTIVE_TB_S_IVRP_Stage1_Kaggle.ipynb"
FROZEN = ROOT / "kaggle_runs/spec_only_full_synthesis_v1_complete/active_tb_s_frozen_full_v1.zip"

MISTRAL = "unsloth/mistral-7b-instruct-v0.3-bnb-4bit"
PHI = "unsloth/Phi-3.5-mini-instruct-bnb-4bit"


def code_cell(source, cid):
    return {"cell_type": "code", "execution_count": None, "id": cid,
            "metadata": {}, "outputs": [], "source": source.splitlines(keepends=True)}


def md_cell(source, cid):
    return {"cell_type": "markdown", "id": cid, "metadata": {},
            "source": source.splitlines(keepends=True)}


def main() -> None:
    pilot = set(json.loads((STAGE / "pilot_task_ids.json").read_text()))

    # copy project code
    for path in (PROJECT / "active_tb").glob("*.py"):
        dest = STAGE / "project" / "active_tb" / path.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
    for name in ["generate_spec_oracles.py", "generate_ivrp.py", "ivrp_arbitrate.py",
                 "spec_only_smoke_test.py"]:
        shutil.copy2(PROJECT / name, STAGE / "project" / name)

    # slice the frozen bundle down to seed_017 and the 20 pilot tasks
    slim = STAGE / "frozen_pilot.zip"
    with zipfile.ZipFile(FROZEN) as src, zipfile.ZipFile(slim, "w", zipfile.ZIP_DEFLATED) as dst:
        kept = 0
        for name in src.namelist():
            if not name.startswith("seed_017/frozen/"):
                continue
            parts = name.split("/")
            if len(parts) < 4 or parts[3] not in pilot:
                continue
            dst.writestr(name, src.read(name))
            kept += 1
    print("frozen entries kept:", kept)

    PUBLISH.mkdir(parents=True, exist_ok=True)
    ds_zip = PUBLISH / "active_tb_s_ivrp_v1.zip"
    with zipfile.ZipFile(ds_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in STAGE.rglob("*"):
            if path.is_file():
                archive.write(path, (Path(STAGE.name) / path.relative_to(STAGE)).as_posix())
    (PUBLISH / "dataset-metadata.json").write_text(json.dumps({
        "title": "ACTIVE TB S IVRP v1",
        "id": "tishaferdous/active-tb-s-ivrp-v1",
        "licenses": [{"name": "MIT"}],
    }, indent=2), encoding="utf-8")

    setup = """from pathlib import Path
import json, os, shutil, subprocess, sys, zipfile
os.environ['PYTHONDONTWRITEBYTECODE']='1'
os.environ['TOKENIZERS_PARALLELISM']='false'
os.environ['HF_HOME']='/kaggle/working/hf_cache'
INPUT=Path('/kaggle/input'); WORK=Path('/kaggle/working')
markers=list(INPUT.rglob('active_tb_s_ivrp_v1/IVRP_BOUNDARY.json'))
if len(markers)==1: SOURCE=markers[0].parent
else:
 arch=list(INPUT.rglob('active_tb_s_ivrp_v1.zip')); assert len(arch)==1,arch
 att=WORK/'attached_ivrp'
 with zipfile.ZipFile(arch[0]) as zf: zf.extractall(att)
 SOURCE=att/'active_tb_s_ivrp_v1'
PROJECT=WORK/'ivrp_project'
if PROJECT.exists(): shutil.rmtree(PROJECT)
shutil.copytree(SOURCE/'project',PROJECT)
OUT=WORK/'ivrp_v1'; OUT.mkdir(exist_ok=True)
SNAP=WORK/'ivrp_checkpoint.zip'
resume=list(INPUT.rglob('ivrp_checkpoint.zip'))
if len(resume)>1: raise RuntimeError(resume)
if resume:
 rd=WORK/'resume_ivrp'
 with zipfile.ZipFile(resume[0]) as zf: zf.extractall(rd)
 for m in rd.rglob('ivrp_*_candidates.jsonl'): shutil.copy2(m,OUT/m.name)
b=json.loads((SOURCE/'IVRP_BOUNDARY.json').read_text())
assert b['golden_artifacts_in_dataset'] is False
assert not list(SOURCE.rglob('*mutant*'))
assert not list(SOURCE.rglob('HDLBits*'))
spec=[json.loads(l) for l in (SOURCE/'spec_tasks_pilot.jsonl').read_text().splitlines() if l.strip()]
assert len(spec)==20 and all(set(r)=={'task_id','description','header'} for r in spec)
print('IVRP_LEAKAGE_AUDIT_PASS: 20 tasks, no golden artefacts present')
print('source',SOURCE,'resume',resume)
"""

    deps = """subprocess.run(['apt-get','update','-qq'],check=True)
subprocess.run(['apt-get','install','-y','-qq','iverilog'],check=True)
subprocess.run([sys.executable,'-m','pip','install','-q','--no-cache-dir','--force-reinstall',
 'torch==2.5.1','--index-url','https://download.pytorch.org/whl/cu121'],check=True)
subprocess.run([sys.executable,'-m','pip','uninstall','-y','-q','torchvision','torchaudio'],check=False)
subprocess.run([sys.executable,'-m','pip','install','-q','--no-cache-dir',
 'transformers==4.57.6','accelerate>=1.0,<2','bitsandbytes==0.48.2','sentencepiece','tqdm>=4.66'],check=True)
p=subprocess.run([sys.executable,'-c',
 'import torch;print(torch.__version__,torch.cuda.get_device_name(0));x=torch.ones(1,device="cuda");print("CUDA_OK",x.item())'],
 text=True,capture_output=True)
print(p.stdout)
if p.returncode: raise RuntimeError(p.stderr)
subprocess.run([sys.executable,str(PROJECT/'spec_only_smoke_test.py')],check=True,cwd=PROJECT)
"""

    gen = f"""# Population B generation. 5 candidates per family, two families, 20 tasks = 200 calls.
MODELS=[('mistral','{MISTRAL}'),('phi35','{PHI}')]
for fam,model in MODELS:
 out=OUT/f'ivrp_{{fam}}_candidates.jsonl'
 cmd=[sys.executable,str(PROJECT/'generate_ivrp.py'),
  '--tasks',str(SOURCE/'spec_tasks_pilot.jsonl'),
  '--task-ids',str(SOURCE/'pilot_task_ids.json'),
  '--output',str(out),'--model',model,'--family',fam,
  '--candidates-per-task','5','--temperature','0.40',
  '--max-new-tokens','900','--max-input-tokens','7168',
  '--repair-attempts','1','--resume',
  '--snapshot-path',str(SNAP),'--snapshot-root',str(OUT),'--snapshot-every','8']
 subprocess.run(cmd,check=True,cwd=PROJECT)
 rows=[json.loads(l) for l in out.read_text().splitlines() if l.strip()]
 print(fam,'candidates',len(rows),'compiled',sum(r['compiled'] for r in rows))
 assert len(rows)==100,(fam,len(rows))
"""

    arb = """# Simulate population B at the frozen check points and apply the frozen rules.
# Kaggle recursively expands archives inside an uploaded dataset, so the frozen
# slice arrives either as the zip or already unpacked as a directory.
frozen_zip=SOURCE/'frozen_pilot.zip'
frozen_dir=SOURCE/'frozen_pilot'
FR=WORK/'frozen_pilot'
if frozen_zip.exists():
 with zipfile.ZipFile(frozen_zip) as zf: zf.extractall(FR)
elif frozen_dir.is_dir(): FR=frozen_dir
else: raise FileNotFoundError(f'no frozen slice at {frozen_zip} or {frozen_dir}')
assert (FR/'seed_017'/'frozen').is_dir(), sorted(p.name for p in FR.iterdir())
inner=WORK/'frozen_inner.zip'
shutil.make_archive(str(inner.with_suffix('')),'zip',FR)
cmd=[sys.executable,str(PROJECT/'ivrp_arbitrate.py'),
 '--frozen-zip',str(inner),'--seed-dir','seed_017',
 '--tasks',str(SOURCE/'spec_tasks_pilot.jsonl'),
 '--task-ids',str(SOURCE/'pilot_task_ids.json'),
 '--ivrp',str(OUT/'ivrp_mistral_candidates.jsonl'),str(OUT/'ivrp_phi35_candidates.jsonl'),
 '--population-a-vote',str(SOURCE/'population_a_vote.json'),
 '--output',str(OUT)]
subprocess.run(cmd,check=True,cwd=PROJECT)
print(open(OUT/'arbitration_decisions.sha256').read())
"""

    pack = """manifest={'stage':'stage_1_screening','task_count':20,
 'models':{'mistral':'""" + MISTRAL + """','phi35':'""" + PHI + """'},
 'candidates_per_family':5,'temperature':0.40,
 'population':'B_IVRP','golden_artifacts_seen':False,
 'decisions_sha256':open(OUT/'arbitration_decisions.sha256').read().strip()}
(OUT/'ivrp_manifest.json').write_text(json.dumps(manifest,indent=2))
cache=Path(os.environ['HF_HOME'])
if cache.exists(): shutil.rmtree(cache)
arc=WORK/'ivrp_v1_results.zip'
shutil.make_archive(str(arc.with_suffix('')),'zip',OUT)
print('packaged',arc,arc.stat().st_size,'bytes')
for f in sorted(OUT.iterdir()): print('  ',f.name,f.stat().st_size)
"""

    nb = {"cells": [
        md_cell("# ACTIVE-TB-S IVRP Stage 1\n\n"
                "Frozen by `IVRP_EXPERIMENT_PREREGISTRATION.md`. Generates the Independent\n"
                "Validation RTL Population from specification and interface only, simulates it at\n"
                "the frozen check points, applies rules D/E/F/G, and hashes the decisions.\n"
                "Golden RTL is absent from this dataset and is never read here.\n", "intro"),
        code_cell(setup, "setup"),
        code_cell(deps, "deps"),
        code_cell(gen, "generate"),
        code_cell(arb, "arbitrate"),
        code_cell(pack, "package"),
    ], "metadata": {
        "accelerator": "GPU",
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.12"},
    }, "nbformat": 4, "nbformat_minor": 5}

    NOTEBOOK.write_text(json.dumps(nb, indent=1) + "\n", encoding="utf-8")
    KERNEL.mkdir(parents=True, exist_ok=True)
    shutil.copy2(NOTEBOOK, KERNEL / NOTEBOOK.name)
    (KERNEL / "kernel-metadata.json").write_text(json.dumps({
        "id": "tishaferdous/active-tb-s-ivrp-stage1",
        "title": "ACTIVE TB S IVRP Stage1",
        "code_file": NOTEBOOK.name,
        "language": "python", "kernel_type": "notebook", "is_private": True,
        "enable_gpu": True, "enable_internet": True,
        "dataset_sources": ["tishaferdous/active-tb-s-ivrp-v1"],
        "competition_sources": [], "kernel_sources": [],
    }, indent=2), encoding="utf-8")
    print("Built", ds_zip, ds_zip.stat().st_size)
    print("Built", NOTEBOOK)


if __name__ == "__main__":
    main()
