#!/usr/bin/env python3
"""Bundle J1b: Qwen3.5-27B via llama.cpp on Kaggle 2x T4 (Amendment 1).

Lessons from the first J1 run are built in: every process writes to a FILE in
/kaggle/working (the kernel log came back empty and lost vLLM's root cause), the
model and build live in /tmp so the 17 GB weights are not saved as output, and the
optional vLLM diagnosis runs last, time-boxed, so it cannot eat generation time.
"""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "kaggle_upload_xjudge_j1b"
DS = "xjudge_j1b"
FILES = [
    "analysis/j1_tasks.jsonl", "analysis/j1_generate.py", "analysis/j1_generate_llamacpp.py",
    "analysis/j1_post.py", "analysis/xjudge_run.py", "analysis/xjudge_subtbs.jsonl",
    "analysis/j1_samples_prev.jsonl",
    "XJUDGE_PREREGISTRATION.md",
]
GOLDEN = ROOT / "kaggle_upload_safe_cbx/dataset/active_tb_safe_cbx/golden.jsonl"

CELLS = [
"""
import subprocess
out = subprocess.run(['nvidia-smi','--query-gpu=name,memory.total,driver_version',
                      '--format=csv,noheader'], capture_output=True, text=True).stdout
print(out)
gpus = [l for l in out.splitlines() if l.strip()]
assert len(gpus) >= 2 and all('T4' in g for g in gpus), f'need 2x T4, got: {gpus}'
""",
"""
from pathlib import Path
import json, subprocess, sys, zipfile, time, shutil, os
INPUT=Path('/kaggle/input'); WORK=Path('/kaggle/working'); TMP=Path('/tmp')
m=list(INPUT.rglob('%(ds)s/XJ_BOUNDARY.json'))
if len(m)==1: SRC=m[0].parent
else:
 a=list(INPUT.rglob('%(ds)s.zip')); assert len(a)==1, a
 with zipfile.ZipFile(a[0]) as zf: zf.extractall(TMP/'att')
 SRC=TMP/'att'/'%(ds)s'
def sh(cmd, log, timeout=None):
    with open(WORK/log,'a') as f:
        r=subprocess.run(cmd,shell=True,stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
    return r.returncode
t0=time.time()
sh('apt-get update -qq && apt-get install -y -qq iverilog cmake build-essential git','setup.log')
nvcc=shutil.which('nvcc') or ('/usr/local/cuda/bin/nvcc' if Path('/usr/local/cuda/bin/nvcc').exists() else None)
print('nvcc:', nvcc)
# The first J1b run compiled every CUDA object and then failed to LINK:
#   /usr/bin/ld: cannot find -lCUDA::cuda_driver
# Kaggle's slim CUDA toolkit ships no libcuda stub, so CMake never defined that
# target. Fix: locate the real driver library, expose it as libcuda.so in a stub
# directory, point CMake at it explicitly, and build without the VMM pool (the
# part of ggml-cuda that needs the driver API at all).
sh('find / -xdev -name "libcuda.so*" 2>/dev/null | head -20','build.log')
cands=[]
for d in ('/usr/local/cuda/lib64/stubs','/usr/local/cuda/targets/x86_64-linux/lib/stubs',
          '/usr/lib/x86_64-linux-gnu','/usr/local/nvidia/lib64','/usr/lib64','/usr/local/cuda/compat'):
    if Path(d).is_dir(): cands += sorted(str(f) for f in Path(d).glob('libcuda.so*'))
print('libcuda candidates:', cands, flush=True)
stub=Path('/tmp/cudastub'); stub.mkdir(exist_ok=True)
driver=next((c for c in cands if 'stubs' in c and c.endswith('libcuda.so')), None)
if driver is None and cands:
    link=stub/'libcuda.so'
    if link.exists() or link.is_symlink(): link.unlink()
    os.symlink(cands[0], link); driver=str(link)
print('linking against:', driver, flush=True)
os.environ['LIBRARY_PATH']=f"{stub}:{os.environ.get('LIBRARY_PATH','')}"
SERVER='/tmp/llama.cpp/build/bin/llama-server'
sh('git clone --depth 1 https://github.com/ggml-org/llama.cpp /tmp/llama.cpp','build.log')
extra=f' -DCUDA_cuda_driver_LIBRARY={driver}' if driver else ''
sh(f'cmake -S /tmp/llama.cpp -B /tmp/llama.cpp/build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=75 '
   f'-DGGML_CUDA_NO_VMM=ON -DLLAMA_CURL=OFF -DCMAKE_BUILD_TYPE=Release '
   f'-DCMAKE_CUDA_COMPILER={nvcc} -DCMAKE_LIBRARY_PATH={stub}{extra}','build.log')
sh('cmake --build /tmp/llama.cpp/build -j 4 --target llama-server','build.log')
BUILT=Path(SERVER).exists()
print('llama-server built:', BUILT, f'({time.time()-t0:.0f}s)', flush=True)
MODEL=None
if BUILT:
    sh(f'{SERVER} --version','build.log')
    sh(f'{sys.executable} -m pip install -q -U huggingface_hub hf_transfer','setup.log')
    os.environ['HF_HUB_ENABLE_HF_TRANSFER']='1'
    from huggingface_hub import hf_hub_download
    MODEL=hf_hub_download('unsloth/Qwen3.5-27B-GGUF','Qwen3.5-27B-Q4_K_M.gguf',local_dir='/tmp/models')
    print('model:', MODEL, Path(MODEL).stat().st_size//(1<<20),'MB', f'({time.time()-t0:.0f}s)', flush=True)
else:
    print('BUILD FAILED -- skipping model download; see build.log', flush=True)
""",
"""
import urllib.request
def healthy(limit):
    t=time.time()
    while time.time()-t<limit:
        if srv.poll() is not None: return False
        try:
            with urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=10) as r:
                if b'ok' in r.read(): return True
        except Exception: pass
        time.sleep(5)
    return False
NP=None
for ctx,np_ in (((131072,8),(98304,6),(65536,4),(32768,2)) if (BUILT and MODEL) else ()):
    logf=open(WORK/'llama_server.log','a')
    logf.write(f'\\n===== starting with -c {ctx} -np {np_} =====\\n'); logf.flush()
    srv=subprocess.Popen([SERVER,'-m',MODEL,'-ngl','999','-c',str(ctx),'-np',str(np_),
        '--jinja','--reasoning-format','none','--host','127.0.0.1','--port','8080','-t','4'],
        stdout=logf,stderr=subprocess.STDOUT)
    if healthy(900):
        NP=np_; print(f'server up: -c {ctx} -np {np_}', flush=True); break
    print(f'server failed at -c {ctx} -np {np_}; exit={srv.poll()}', flush=True)
    srv.kill(); time.sleep(5)
print('NP =', NP)
""",
"""
prev=SRC/'j1_samples_prev.jsonl'
if prev.is_file() and not (WORK/'j1_samples.jsonl').is_file():
    shutil.copy2(prev, WORK/'j1_samples.jsonl')
    print('resuming from', sum(1 for _ in open(prev)), 'completed samples', flush=True)
if NP:
    p=subprocess.Popen([sys.executable,str(SRC/'j1_generate_llamacpp.py'),
       '--tasks',str(SRC/'j1_tasks.jsonl'),'--samples-out',str(WORK/'j1_samples.jsonl'),
       '--raw-out',str(WORK/'j1_raw.jsonl'),'--log',str(WORK/'j1_generate.log'),
       '--samples','5','--concurrency',str(NP),'--budget-hours','8.0'],
       stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    for line in p.stdout: print(line,end='',flush=True)
    print('generate exit code', p.wait())
try: srv.kill()
except Exception: pass
""",
"""
if (WORK/'j1_raw.jsonl').is_file():
    sh(f"{sys.executable} {SRC/'j1_post.py'} --raw {WORK/'j1_raw.jsonl'} --golden {SRC/'golden.jsonl'} "
       f"--candidates {WORK/'j1_candidates.jsonl'} --official {WORK/'j1_official.jsonl'}",'post.log')
    print(open(WORK/'post.log').read()[-3000:])
if (WORK/'j1_candidates.jsonl').is_file():
    sh(f"{sys.executable} {SRC/'xjudge_run.py'} --subtbs {SRC/'xjudge_subtbs.jsonl'} "
       f"--candidates {WORK/'j1_candidates.jsonl'} --out {WORK/'j1_results.jsonl'}",'xjudge_run.log')
    print(open(WORK/'xjudge_run.log').read()[-1500:])
""",
"""
def pack():
    with zipfile.ZipFile(WORK/'xjudge_j1b_results.zip','w',zipfile.ZIP_DEFLATED) as z:
        for f in sorted(WORK.glob('*')):
            if f.is_file() and f.suffix in ('.jsonl','.log') : z.write(f, f.name)
    print('packed', (WORK/'xjudge_j1b_results.zip').stat().st_size//1024, 'KB', flush=True)
pack()
""",
"""
# Documentation only, time-boxed: why vLLM would not start on this GPU.
code = '''
import traceback
try:
    from vllm import LLM
    LLM(model="Qwen/Qwen3.5-27B-GPTQ-Int4", tensor_parallel_size=2, dtype="float16",
        enforce_eager=True, max_model_len=8192, gpu_memory_utilization=0.9,
        limit_mm_per_prompt={"image": 0, "video": 0})
    print("VLLM_LOADED_OK")
except Exception:
    traceback.print_exc()
'''
(TMP/'vllm_diag.py').write_text(code)
try:
    sh(f'{sys.executable} -m pip install -q -U vllm','vllm_diag.log',timeout=900)
    env_cmd=f'VLLM_ENABLE_V1_MULTIPROCESSING=0 VLLM_LOGGING_LEVEL=DEBUG {sys.executable} {TMP/"vllm_diag.py"}'
    sh(env_cmd,'vllm_diag.log',timeout=900)
except Exception as e:
    print('vllm diag stopped:', e)
pack()
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
        "judge": "J1b", "model": "unsloth/Qwen3.5-27B-GGUF Q4_K_M", "engine": "llama.cpp",
        "fine_tuned": False, "prereg": "XJUDGE_PREREGISTRATION.md (Amendment 1)"}, indent=1),
        encoding="utf-8")
    nb = {"cells": [{"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
                     "source": (c % {"ds": DS} if "%(ds)s" in c else c)
                     .strip("\n").splitlines(keepends=True)} for c in CELLS],
          "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python",
                                      "name": "python3"}, "language_info": {"name": "python"}},
          "nbformat": 4, "nbformat_minor": 5}
    k = OUT / "kernel"
    k.mkdir(parents=True)
    (k / "xjudge_j1b.ipynb").write_text(json.dumps(nb, indent=1), encoding="utf-8")
    (k / "kernel-metadata.json").write_text(json.dumps({
        "id": "tishaferdous/xjudge-j1b", "title": "XJUDGE J1b",
        "code_file": "xjudge_j1b.ipynb", "language": "python", "kernel_type": "notebook",
        "is_private": True, "enable_gpu": True, "enable_internet": True,
        "machine_shape": "NvidiaTeslaT4",
        "dataset_sources": ["tishaferdous/xjudge-j1b-data"],
        "competition_sources": [], "kernel_sources": []}, indent=1), encoding="utf-8")
    pub = OUT / "dataset_publish"
    pub.mkdir(parents=True)
    with zipfile.ZipFile(pub / f"{DS}.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for f in ds.rglob("*"):
            if f.is_file():
                z.write(f, Path(DS) / f.relative_to(ds))
    (pub / "dataset-metadata.json").write_text(json.dumps({
        "title": "XJUDGE J1b Data", "id": "tishaferdous/xjudge-j1b-data",
        "licenses": [{"name": "MIT"}]}, indent=1), encoding="utf-8")
    print("bundle:", (pub / f"{DS}.zip").stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
