#!/usr/bin/env python3
"""Equal-model baseline: ConfiBench's own code, with Qwen3.5-27B in place of GPT-4o.

Everything about ConfiBench is kept (prompts, pipeline, TBcheck discriminator, RTL
population of 20, e_rank_super confidence, multibench masks, its own Eval1/Eval2).
Only the LLM endpoint changes, via four minimal patches applied to a copy:

  LLM_call.py      model names starting with "qwen" go to a local OpenAI-compatible
                   llama-server; pricing 0. Thinking is off: GPT-4o is a
                   non-reasoning model and ConfiBench's prompts expect direct answers.
                   Sampling: Qwen's recommended non-thinking settings (T 0.7, top_p
                   0.8, top_k 20) when ConfiBench passes no temperature; max 8192
                   output tokens per call to bound runaway generations. JSON stages
                   use explicit prompt constraints instead of llama.cpp grammar mode,
                   which is not reliable for this model/backend combination.
  iverilog_call.py iverilog / vvp from PATH instead of ~/bin/bin.
  config           confibench.yaml with model = rtlgen_model = qwen3.5-27b and no
                   pre-generated GPT-4o RTLs, so ConfiBench generates its 20-RTL
                   population with Qwen itself (rtl_num 20, as its README describes).

ConfiBench has no multithreading, so the session runs one ConfiBench process per
server slot, each on a disjoint task list. Resumable across sessions: pass --prev with
a previous cbq_saves.zip; tasks with a data.json are skipped.

usage: python prepare_confibench_qwen.py <shard> <n_shards> [--prev cbq_saves.zip]
       [--workers N] [--budget-hours H] [--tasks-file tasks.jsonl] [--tag slug]
"""
from __future__ import annotations

import json
import hashlib
import os
import stat
import shutil
import sys
import zipfile
from pathlib import Path, PurePosixPath

from prepare_xjudge_j1b import CELLS as J1B_CELLS
from confibench_resume_patch import patch_task_source
from confibench_resume import digest

ROOT = Path(__file__).resolve().parent
CB_SRC = ROOT / "baselines" / "ConfiBench"
MODEL = "qwen3.5-27b"
SKIP_DIRS = {".git", "__pycache__", "figs", "saves", "AutoBenchResults", "CorrectBenchResults", "ConfiBenchResults",
             "discarded", "original_data_human", "demo"}
KEEP_HDLBITS = {"HDLBits_data.jsonl", "HDLBits_data_mutants.jsonl"}

QWEN_CALL = '''def qwen_call(input_messages, model, system_message = None, temperature = None, json_mode = False):
    """Equal-model baseline patch: a local OpenAI-compatible llama-server serving Qwen3.5-27B."""
    client = OpenAI(base_url=os.environ.get("QWEN_BASE_URL", "http://127.0.0.1:8080/v1"),
                    api_key="none", timeout=4 * 3600)
    has_sysmessage = any(m["role"] == "system" for m in input_messages)
    if not has_sysmessage:
        messages = [{"role": "system", "content": DEFAULT_SYS_MESSAGE if system_message is None else system_message}]
    else:
        messages = []
    messages.extend(dict(message) for message in input_messages)
    kwargs = {"temperature": 0.7 if temperature is None else temperature, "top_p": 0.8, "max_tokens": 8192,
              "extra_body": {"top_k": 20, "chat_template_kwargs": {"enable_thinking": False}}}
    if json_mode:
        # llama.cpp returned HTTP 400 "Failed to initialize samplers" for every
        # grammar-constrained JSON request with Qwen3.5-27B. ConfiBench's prompts
        # already define the JSON schema, so preserve the requested semantics with
        # a prompt constraint, as its Claude adapter does, without a server grammar.
        for message in reversed(messages):
            if message.get("role") == "user":
                message["content"] += "\\nReturn exactly one valid JSON object and no surrounding prose or Markdown."
                break
    def provide():
        with Timer(print_en=False) as gpt_response:
            completion = client.chat.completions.create(model=model, messages=messages, **kwargs)
        answer = completion.choices[0].message.content or ""
        if "</think>" in answer:
            answer = answer.split("</think>", 1)[1].lstrip()
        transcript = messages + [{"role": "assistant", "content": answer}]
        usage = {"completion_tokens": completion.usage.completion_tokens, "prompt_tokens": completion.usage.prompt_tokens,
                 "total_tokens": completion.usage.total_tokens}
        other_infos = {"messages": transcript, "time": round(gpt_response.interval, 2), "system_fingerprint": None,
                       "model": model, "usage": usage}
        return [answer, other_infos]
    from confibench_resume import scoped_call
    return scoped_call({"model": model, "messages": messages, "kwargs": kwargs}, provide)

'''

CONFIG = """run:
    mode: autoline
save:
    en: True
    pub:
        prefix: "%(prefix)s"
        subdir: ConfiBench_qwen
        dir: 'saves'
    log:
        debug_en: False
gpt:
    model: %(model)s
    rtlgen_model: %(model)s
autoline:
    probset:
        path: data/HDLBits/HDLBits_data.jsonl
        mutant_path: data/HDLBits/HDLBits_data_mutants.jsonl
        more_info_paths: []
        only: %(only)s
    promptscript: pychecker
    timeout: 40
    save_compile: False
    debug:
        max: 3
    itermax: 10
    update_desc: False
    TBcheck:
        rtl_num: 20
        discrim_mode: col_70_wrong_row_25_correct
confibench:
    en: True
    save_fig: False
    conf_bool:
        strategy: e_rank_super
        e_rank_super:
            threshold: 0.15
            K: 8
    multibench:
        en: True
        min_tb: 2
        min_ratio: 0.8
"""


def patch(text: str, old: str, new: str, what: str) -> str:
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"patch '{what}': expected 1 occurrence, found {n}")
    return text.replace(old, new)


def remove_readonly(func, path, _error) -> None:
    """Allow deterministic rebuilds of old bundles containing read-only Git objects."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def baseline_profile():
    baseline_hashes = {str(f.relative_to(CB_SRC)): hashlib.sha256(f.read_bytes()).hexdigest()
                       for f in sorted(CB_SRC.rglob('*.py')) if not any(p in SKIP_DIRS for p in f.parts)}
    return hashlib.sha256(json.dumps({'baseline': baseline_hashes, 'config': CONFIG,
                         'model': MODEL, 'sampler': {'temperature': 0.7, 'top_p': 0.8,
                         'top_k': 20, 'max_tokens': 8192, 'enable_thinking': False},
                         'backend_setup': J1B_CELLS[2]}, sort_keys=True).encode()).hexdigest()


def copy_confibench(dst: Path) -> None:
    def ignore(d, names):
        out = {n for n in names if n in SKIP_DIRS}
        if Path(d).name == "HDLBits":
            out |= {n for n in names if n.endswith(".jsonl") and n not in KEEP_HDLBITS}
            out |= {n for n in names if n.endswith((".log", ".txt"))}
        return out
    shutil.copytree(CB_SRC, dst, ignore=ignore)
    key = json.loads((dst / "config" / "key_API.json").read_text(encoding="utf-8"))
    if any(str(v) for v in key.values()):
        raise SystemExit("config/key_API.json is not empty -- refusing to bundle a key")
    llm = (dst / "LLM_call.py").read_text(encoding="utf-8")
    llm = patch(llm, "PRICING_MODELS = {\n", f'PRICING_MODELS = {{\n    "{MODEL}": [0.0, 0.0],\n', "pricing")
    llm = patch(llm, '    elif model.startswith("gpt"):\n',
                '    elif model.startswith("qwen"):\n'
                '        output = qwen_call(input_messages, model, system_message, temperature, json_mode)\n'
                '    elif model.startswith("gpt"):\n', "dispatch")
    llm = patch(llm, "def claude_call(input_messages", QWEN_CALL + "def claude_call(input_messages", "qwen_call")
    (dst / "LLM_call.py").write_text(llm, encoding="utf-8")
    iv = (dst / "iverilog_call.py").read_text(encoding="utf-8")
    iv = patch(iv, 'IVERILOG_PATH = "~/bin/bin/iverilog"', 'IVERILOG_PATH = "iverilog"', "iverilog")
    iv = patch(iv, 'IVERILOG_VVP_PATH = "~/bin/bin/vvp"', 'IVERILOG_VVP_PATH = "vvp"', "vvp")
    iv = patch(iv, '    return v_list\n',
               '    from confibench_resume import compiler_file_order\n'
               '    return compiler_file_order(dir, v_list)\n', 'durable compiler input order')
    (dst / "iverilog_call.py").write_text(iv, encoding="utf-8")
    shutil.copy2(ROOT / 'confibench_timeout_guard.py', dst / 'confibench_timeout_guard.py')
    shutil.copy2(ROOT / 'confibench_resume.py', dst / 'confibench_resume.py')
    profile = baseline_profile()
    task_file = dst / 'autoline/TB_autoline.py'
    task_file.write_text(patch_task_source(task_file.read_text(encoding='utf-8'), profile), encoding='utf-8')
    (dst / 'resume_profile.json').write_text(json.dumps({'profile': profile}), encoding='utf-8')
    utils_file = dst / 'utils/utils.py'
    utils_file.write_text(utils_file.read_text(encoding='utf-8') +
                          '\n# Pure parser timeout calls need a killable process on Kaggle.\n'
                          'from confibench_timeout_guard import run_with_timeout\n', encoding='utf-8')
    for f in dst.rglob("*.py"):
        s = f.read_text(encoding="utf-8", errors="replace")
        for d in ("AutoBenchResults", "CorrectBenchResults", "ConfiBenchResults"):
            if f"import" in s and f"{d}" in s and ("from data." + d) in s:
                raise SystemExit(f"{f} imports excluded directory {d}")
        compile(s, str(f), "exec")


SETUP = """
CB = WORK/'ConfiBench'
if not CB.exists():
    shutil.copytree(SRC/'ConfiBench', CB)
boundary = json.loads((SRC/'XJ_BOUNDARY.json').read_text())
if MAX_FRESH_CALLS is not None:
    os.environ['CBQ_MAX_FRESH_CALLS'] = str(MAX_FRESH_CALLS)
os.environ['CBQ_RESUME_ROOT'] = str(WORK/'cbq_runtime')
if (SRC/'resume_runtime').exists():
    shutil.copytree(SRC/'resume_runtime', WORK/'cbq_runtime', dirs_exist_ok=True)
expected_checkpoints = int(boundary.get('checkpoint_tasks', 0))
resume_saves = SRC/'resume_saves'
if expected_checkpoints:
    # Kaggle expands nested ZIP files during dataset ingestion. Mount checkpoint
    # records as ordinary dataset files instead of looking for prev_saves.zip.
    assert resume_saves.is_dir(), f'missing resume_saves: {resume_saves}'
    shutil.copytree(resume_saves, CB/'saves', dirs_exist_ok=True)
restored = {p.parent.name for p in (CB/'saves').rglob('data.json')}
assert len(restored) == expected_checkpoints, (len(restored), expected_checkpoints, resume_saves)
print('checkpoint tasks restored:', len(restored), flush=True)
sh(f'{sys.executable} -m pip install -q loguru==0.7.3 anthropic==0.49.0 openai==1.66.3 httpx==0.27.2 tiktoken','setup.log')
r = subprocess.run(['iverilog','-V'],capture_output=True,text=True); print('iverilog:', (r.stdout or r.stderr).splitlines()[0])
if NP:
    os.environ['QWEN_BASE_URL'] = 'http://127.0.0.1:8080/v1'
    sys.path.insert(0, str(CB))
    smoke_cwd = Path.cwd()
    try:
        # LLM_call creates its manager at import time and resolves the deliberately
        # empty key file relative to the ConfiBench project directory.
        os.chdir(CB)
        from confibench_timeout_guard import self_test
        self_test()
        from confibench_resume import self_test as resume_self_test
        resume_self_test()
        probe_code = ('import json; from LLM_call import qwen_call; '
                      'text,_=qwen_call([{"role":"user","content":"Return a JSON object whose key ok has Boolean value true."}], '
                      '"qwen3.5-27b", json_mode=True); '
                      'start,end=text.find("{"),text.rfind("}")+1; '
                      'assert start>=0 and end>start and json.loads(text[start:end]).get("ok") is True, repr(text)')
        with open(WORK/'health_probe.log','w') as probe_log:
            probe_worker=subprocess.Popen([sys.executable,'-c',probe_code],cwd=CB,
                                          stdout=probe_log,stderr=subprocess.STDOUT,start_new_session=True)
            try:
                assert probe_worker.wait(timeout=180)==0, 'JSON health probe failed; see health_probe.log'
            except subprocess.TimeoutExpired:
                import signal
                os.killpg(probe_worker.pid,signal.SIGKILL)
                probe_worker.wait(timeout=10)
                raise TimeoutError('JSON health probe exceeded three minutes')
    finally:
        os.chdir(smoke_cwd)
    print('JSON_MODE_SMOKE_OK = True', flush=True)

# The running server no longer needs compiler objects or the cloned repository
# metadata. Removing them leaves working-disk headroom for ConfiBench artifacts.
removed_bytes = 0
for pattern in ('*.o', '*.a'):
    for artifact in Path('/tmp/llama.cpp/build').rglob(pattern):
        try:
            removed_bytes += artifact.stat().st_size
            artifact.unlink()
        except OSError:
            pass
git_dir = Path('/tmp/llama.cpp/.git')
if git_dir.exists():
    removed_bytes += sum(p.stat().st_size for p in git_dir.rglob('*') if p.is_file())
    shutil.rmtree(git_dir, ignore_errors=True)
print('build cleanup MB:', round(removed_bytes / (1 << 20), 1),
      'disk free GB:', round(shutil.disk_usage(WORK).free / (1 << 30), 2), flush=True)
"""

RUN = """
import signal
all_tasks = [json.loads(l)['task_id'] for l in (SRC/'shard_tasks.json').read_text().splitlines() if l.strip()]
KEEP_TASK_FILES = {'data.json', 'run_info.json', 'run_info_short.json', 'task_log.log'}

def compact_completed():
    # Keep scoring/checkpoint files and remove bulky completed-task intermediates.
    reclaimed = 0
    saves = CB/'saves'
    if not saves.exists():
        return reclaimed
    for data_file in list(saves.rglob('data.json')):
        try:
            record = json.loads(data_file.read_text())
            if record.get('task_id') != data_file.parent.name:
                continue
        except (OSError, ValueError):
            continue
        task_dir = data_file.parent
        for child in list(task_dir.iterdir()):
            if child.name in KEEP_TASK_FILES:
                continue
            try:
                if child.is_dir():
                    reclaimed += sum(p.stat().st_size for p in child.rglob('*') if p.is_file())
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    reclaimed += child.stat().st_size
                    child.unlink()
            except OSError:
                pass
    return reclaimed

def done_tasks():
    s = set()
    if (CB/'saves').exists():
        for p in (CB/'saves').rglob('data.json'):
            if p.parent.name in all_tasks:
                try:
                    record = json.loads(p.read_text())
                    if record.get('task_id') == p.parent.name:
                        s.add(p.parent.name)
                except (OSError, ValueError):
                    pass
    return s

def checkpoint():
    completed = done_tasks()
    tmp = WORK/'cbq_saves.tmp.zip'
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
        for data_file in sorted((CB/'saves').rglob('data.json')):
            if data_file.parent.name not in completed:
                continue
            for f in sorted(data_file.parent.iterdir()):
                if f.is_file() and f.name in KEEP_TASK_FILES:
                    z.write(f, f.relative_to(CB).as_posix())
    os.replace(tmp, WORK/'cbq_saves.zip')
    runtime = WORK/'cbq_runtime'
    runtime_tmp = WORK/'cbq_runtime.tmp.zip'
    with zipfile.ZipFile(runtime_tmp, 'w', zipfile.ZIP_DEFLATED) as z:
        if runtime.exists():
            for f in sorted(runtime.rglob('*.json')):
                z.write(f, f.relative_to(runtime).as_posix())
    os.replace(runtime_tmp, WORK/'cbq_runtime.zip')
    manifest = {
        'expected_tasks': all_tasks, 'checkpointed_tasks': sorted(completed),
        'unresolved_tasks': sorted(set(all_tasks) - completed),
        'all_tasks_checkpointed': len(completed) == len(all_tasks),
        'worker_exit_codes': [p.poll() for p in procs],
        'time': time.time(),
    }
    runtime_progress = {}
    if runtime.exists():
        for progress_file in sorted(runtime.glob('*/progress.json')):
            progress = json.loads(progress_file.read_text())
            state_file = progress_file.with_name('iteration.json')
            state = json.loads(state_file.read_text())['payload'] if state_file.exists() else {}
            runtime_progress[progress_file.parent.name] = {
                'fresh_this_session': progress.get('fresh_this_session', 0),
                'replayed_this_session': progress.get('replayed_this_session', 0),
                'scope': progress.get('scope'),
                'next_iteration': state.get('next_iteration', 0),
                'eval_ready': state.get('eval_ready', False),
            }
    manifest['runtime_progress'] = runtime_progress
    print('durable progress:', json.dumps(runtime_progress, sort_keys=True), flush=True)
    manifest_tmp = WORK/'cbq_completion.tmp.json'
    manifest_tmp.write_text(json.dumps(manifest, indent=2))
    os.replace(manifest_tmp, WORK/'cbq_completion.json')

todo = [t for t in all_tasks if t not in done_tasks()]
initial_reclaimed = compact_completed()
print('initial checkpoint compaction MB:', round(initial_reclaimed / (1 << 20), 1),
      'disk free GB:', round(shutil.disk_usage(WORK).free / (1 << 30), 2), flush=True)
print(len(all_tasks), 'tasks in shard,', len(todo), 'to run', flush=True)
procs = []
checkpoint()
assert NP or not todo, 'Model server unavailable: unfinished tasks cannot run'
if NP and todo:
    nw = min(MAX_WORKERS, NP, len(todo))
    pending = list(todo)
    def launch_next():
        w = len(procs)
        only = [pending.pop(0)]
        (CB/'config'/'configs'/f'cbq_w{w}.yaml').write_text(CONFIG %% {'prefix': f'S%(shard)dW{w}', 'model': '%(model)s', 'only': json.dumps(only)})
        env = dict(os.environ, QWEN_BASE_URL='http://127.0.0.1:8080/v1', PYTHONUNBUFFERED='1')
        if int(env.get('CBQ_MAX_FRESH_CALLS', '0')) > 0:
            grace = min(3600, BUDGET_HOURS*3600/2)
            env['CBQ_NEW_CALL_DEADLINE'] = str(deadline - grace)
        with open(WORK/f'cbq_w{w}.log','a') as worker_log:
            procs.append(subprocess.Popen([sys.executable, 'main.py', '-c', f'cbq_w{w}'], cwd=str(CB), env=env,
                         stdout=worker_log, stderr=subprocess.STDOUT, start_new_session=True))
        print('started task:', only[0], 'worker log:', f'cbq_w{w}.log', flush=True)
    t_run = time.time()
    deadline = min(t_run + BUDGET_HOURS*3600, t0 + 11.25*3600)
    last_status = 0
    while (pending or any(p.poll() is None for p in procs)) and time.time() < deadline:
        while pending and sum(p.poll() is None for p in procs) < nw:
            launch_next()
        time.sleep(min(60, max(0, deadline - time.time())))
        checkpoint()
        if time.time() - last_status < 600:
            continue
        last_status = time.time()
        reclaimed = compact_completed()
        print(f'{(time.time()-t_run)/3600:.2f}h  done {len(done_tasks())}/{len(all_tasks)}  '
              f'compact {reclaimed/(1<<20):.1f} MB  free {shutil.disk_usage(WORK).free/(1<<30):.2f} GB',
              flush=True)
    for p in procs:
        if p.poll() is None:
            try: os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError: pass
    for p in procs:
        try: p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try: os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            p.wait(timeout=10)
print('finished tasks:', len(done_tasks()), '/', len(all_tasks), flush=True)
try: srv.kill()
except Exception: pass
compact_completed()
checkpoint()
# Preserve unfinished diagnostics separately; they must not count as task results.
partial_bytes = 0
finished = done_tasks()
with zipfile.ZipFile(WORK/'cbq_partial.zip', 'w', zipfile.ZIP_DEFLATED) as z:
    for f in sorted((CB/'saves').rglob('*')):
        if (f.is_file() and f.suffix in ('.json', '.txt', '.log', '.py', '.v', '.sv')
                and not any(part in finished for part in f.parts)):
            size = f.stat().st_size
            if size <= 4*1024*1024 and partial_bytes + size <= 128*1024*1024:
                z.write(f, f.relative_to(CB).as_posix())
                partial_bytes += size
shutil.rmtree(CB, ignore_errors=True)
with zipfile.ZipFile(WORK/'cbq_logs.zip', 'w', zipfile.ZIP_DEFLATED) as z:
    diagnostic_files = list(WORK.glob('cbq_w*.log'))
    diagnostic_files += [WORK/name for name in ('setup.log', 'build.log', 'llama_server.log',
        'health_probe.log', 'engine_provenance.json', 'gpu_server_proof.json')]
    for f in sorted(diagnostic_files):
        if f.is_file(): z.write(f, f.name)
print('packed', flush=True)
"""

LADDER_OLD = "((131072,8),(98304,6),(65536,4),(32768,2))"
# Some TBcheck prompts exceed 16k tokens. Four slots retain 32k tokens per
# independent call at the preferred 131k aggregate context.
LADDER_NEW = "((131072,4),(98304,4),(65536,2))"


def bounded_startup_cell(tag: str) -> str:
    cell = J1B_CELLS[1] % {'ds': tag}
    old = '''def sh(cmd, log, timeout=None):
    with open(WORK/log,'a') as f:
        r=subprocess.run(cmd,shell=True,stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
    return r.returncode'''
    new = '''def sh(cmd, log, timeout=1200):
    import signal
    remaining = 1800 - (time.time() - t0)
    if remaining <= 0:
        raise TimeoutError('Startup exceeded its 30-minute budget')
    with open(WORK/log,'a') as f:
        p = subprocess.Popen(cmd, shell=True, stdout=f, stderr=subprocess.STDOUT,
                             start_new_session=True)
        try:
            return p.wait(timeout=min(timeout, remaining))
        except subprocess.TimeoutExpired:
            try: os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            p.wait(timeout=10)
            raise TimeoutError('Bounded startup command timed out; no task generation started')'''
    cell = patch(cell, old, new, 'bounded startup subprocess groups')
    old_download = '''    from huggingface_hub import hf_hub_download
    MODEL=hf_hub_download('unsloth/Qwen3.5-27B-GGUF','Qwen3.5-27B-Q4_K_M.gguf',local_dir='/tmp/models')'''
    new_download = '''    import shlex
    download = "from huggingface_hub import hf_hub_download; hf_hub_download('unsloth/Qwen3.5-27B-GGUF','Qwen3.5-27B-Q4_K_M.gguf',local_dir='/tmp/models')"
    assert sh(f'{sys.executable} -c {shlex.quote(download)}', 'setup.log', timeout=900) == 0, 'Model download failed'
    MODEL='/tmp/models/Qwen3.5-27B-Q4_K_M.gguf' '''
    return patch(cell, old_download, new_download.rstrip(), 'bounded model download')


def prebuilt_startup_cell(tag: str) -> str:
    return '''
from pathlib import Path
import json, subprocess, sys, zipfile, time, shutil, os, signal, shlex
INPUT=Path('/kaggle/input'); WORK=Path('/kaggle/working')
matches=list(INPUT.rglob('%(ds)s/XJ_BOUNDARY.json'))
assert len(matches)==1, matches
SRC=matches[0].parent
t0=time.time()
def sh(cmd,log,timeout=900):
    remaining=1800-(time.time()-t0)
    if remaining<=0: raise TimeoutError('Startup exceeded its 30-minute budget')
    with open(WORK/log,'a') as file:
        p=subprocess.Popen(cmd,shell=True,stdout=file,stderr=subprocess.STDOUT,start_new_session=True)
        try: return p.wait(timeout=min(timeout,remaining))
        except subprocess.TimeoutExpired:
            try: os.killpg(p.pid,signal.SIGKILL)
            except ProcessLookupError: pass
            p.wait(timeout=10)
            raise TimeoutError('Bounded startup subprocess timed out')
assert sh('apt-get update -qq && apt-get install -y -qq iverilog','setup.log',timeout=300)==0
installer=shlex.quote(str(SRC/'install_llama_release.py'))
assert sh(f'{sys.executable} {installer} --root /tmp/llama-runtime --manifest /kaggle/working/engine_provenance.json','build.log',timeout=600)==0, 'Pinned binary compatibility check failed'
engine=json.loads((WORK/'engine_provenance.json').read_text())
assert not engine['missing_driver'], engine['missing_driver']
SERVER=engine['server']
os.environ['LD_LIBRARY_PATH']=engine['ld_library_path']
devices=subprocess.run([SERVER,'--list-devices'],capture_output=True,text=True,timeout=60)
device_text=devices.stdout+devices.stderr
assert devices.returncode==0 and 'CUDA0' in device_text and 'CUDA1' in device_text, device_text
engine['gpu_devices']=device_text
(WORK/'engine_provenance.json').write_text(json.dumps(engine,indent=2))
BUILT=True
assert sh(f'{sys.executable} -m pip install -q -U huggingface_hub hf_transfer','setup.log',timeout=300)==0
os.environ['HF_HUB_ENABLE_HF_TRANSFER']='1'
download="from huggingface_hub import hf_hub_download; hf_hub_download('unsloth/Qwen3.5-27B-GGUF','Qwen3.5-27B-Q4_K_M.gguf',local_dir='/tmp/models')"
assert sh(f'{sys.executable} -c {shlex.quote(download)}','setup.log',timeout=900)==0, 'Model download failed'
MODEL='/tmp/models/Qwen3.5-27B-Q4_K_M.gguf'
print('Pinned prebuilt server:',SERVER,'model MB:',Path(MODEL).stat().st_size//(1<<20),flush=True)
''' % {'ds':tag}


def merge_checkpoint_archives(paths: list[Path], dest: Path, allowed_tasks: set[str]) -> int:
    """Materialize compact deterministic resume files from earlier outputs."""
    selected: dict[str, bytes] = {}
    for archive in paths:
        if not archive.is_file():
            raise SystemExit(f"checkpoint archive not found: {archive}")
        with zipfile.ZipFile(archive) as src:
            for name in src.namelist():
                path = PurePosixPath(name.replace("\\", "/"))
                if path.name != "data.json" or len(path.parts) < 2:
                    continue
                task = path.parent.name
                if task not in allowed_tasks or task in selected:
                    continue
                payload = src.read(name)
                json.loads(payload)
                selected[task] = payload
    for task in sorted(selected):
        target = dest / "ConfiBench_qwen" / "merged" / task / "data.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(selected[task])
    return len(selected)


def main() -> None:
    shard, n_shards = int(sys.argv[1]), int(sys.argv[2])
    prevs = [Path(sys.argv[i + 1]) for i, arg in enumerate(sys.argv[:-1]) if arg == "--prev"]
    runtime_prev = Path(sys.argv[sys.argv.index('--runtime-prev') + 1]) if '--runtime-prev' in sys.argv else None
    max_fresh = int(sys.argv[sys.argv.index('--max-fresh-calls') + 1]) if '--max-fresh-calls' in sys.argv else None
    prebuilt_server = '--prebuilt-server' in sys.argv
    if max_fresh is not None and max_fresh < 0:
        raise SystemExit('--max-fresh-calls must be nonnegative')
    workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 4
    budget_hours = float(sys.argv[sys.argv.index("--budget-hours") + 1]) if "--budget-hours" in sys.argv else 10.5
    tasks_file = Path(sys.argv[sys.argv.index("--tasks-file") + 1]) if "--tasks-file" in sys.argv else None
    custom_tag = sys.argv[sys.argv.index("--tag") + 1] if "--tag" in sys.argv else None
    if workers < 1 or workers > 4:
        raise SystemExit("--workers must be in [1, 4]")
    if budget_hours <= 0 or budget_hours > 10.5:
        raise SystemExit("--budget-hours must be in (0, 10.5]")
    if custom_tag and not all(c.isalnum() or c == "-" for c in custom_tag):
        raise SystemExit("--tag must contain only letters, digits, and hyphens")
    tag = custom_tag or f"cbq{shard}of{n_shards}"
    out = ROOT / f"kaggle_upload_{tag}"
    if out.exists():
        shutil.rmtree(out, onexc=remove_readonly)
    ds = out / "dataset" / tag
    ds.mkdir(parents=True)
    copy_confibench(ds / "ConfiBench")
    shutil.copy2(ROOT/'install_llama_release.py', ds/'install_llama_release.py')
    tasks = [json.loads(l)["task_id"] for l in (CB_SRC / "data/HDLBits/HDLBits_data.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    if tasks_file:
        mine = []
        for line in tasks_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            mine.append(value["task_id"] if isinstance(value, dict) else value)
        if len(mine) != len(set(mine)):
            raise SystemExit(f"duplicate task in {tasks_file}")
        unknown = sorted(set(mine) - set(tasks))
        if unknown:
            raise SystemExit(f"unknown tasks in {tasks_file}: {unknown}")
    else:
        mine = [t for i, t in enumerate(tasks) if i % n_shards == shard]
    (ds / "shard_tasks.json").write_text("".join(json.dumps({"task_id": t}) + "\n" for t in mine), encoding="utf-8")
    checkpoint_tasks = merge_checkpoint_archives(prevs, ds / "resume_saves", set(mine)) if prevs else 0
    if runtime_prev:
        profile=baseline_profile()
        problems={p['task_id']:p for p in map(json.loads,(CB_SRC/'data/HDLBits/HDLBits_data.jsonl').read_text().splitlines())}
        for problem in map(json.loads,(CB_SRC/'data/HDLBits/HDLBits_data_mutants.jsonl').read_text().splitlines()):
            problems[problem['task_id']].update(problem)
        with zipfile.ZipFile(runtime_prev) as z:
            if z.testzip() is not None:
                raise SystemExit('Corrupt runtime checkpoint ZIP')
            for name in z.namelist():
                path = PurePosixPath(name)
                if ('\\' in name or path.is_absolute() or '..' in path.parts
                        or len(path.parts) < 2 or path.parts[0] not in mine or path.suffix != '.json'):
                    raise SystemExit(f'Unsafe runtime checkpoint member: {name}')
                payload = z.read(name)
                record=json.loads(payload)
                if path.name=='contract.json':
                    expected={'version':1,'task_id':path.parts[0],'profile':profile,
                              'problem_sha256':digest(problems[path.parts[0]])}
                    if record!=expected: raise SystemExit('Runtime checkpoint contract mismatch: '+name)
                if '/calls/' in name and record['output_sha256']!=digest(record['output']):
                    raise SystemExit('Response journal checksum mismatch: '+name)
                if path.name=='iteration.json' and record['payload_sha256']!=digest(record['payload']):
                    raise SystemExit('Iteration checksum mismatch: '+name)
                target = ds / 'resume_runtime' / Path(*path.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
    (ds / "XJ_BOUNDARY.json").write_text(json.dumps({"baseline": "ConfiBench, equal model", "model": MODEL,
                                                     "shard": shard, "n_shards": n_shards, "tasks": len(mine),
                                                     "checkpoint_tasks": checkpoint_tasks,
                                                     "tag": tag, "custom_tasks": bool(tasks_file),
                                                     "workers": workers,
                                                     "budget_hours": budget_hours}), encoding="utf-8")
    server_cell = J1B_CELLS[2]
    if server_cell.count(LADDER_OLD) != 1:
        raise SystemExit("server ladder not found in J1B cell 2")
    server_cell = server_cell.replace(LADDER_OLD, LADDER_NEW)
    server_cell = patch(server_cell, 'if healthy(900):', 'if healthy(180):', 'bounded server health wait')
    if prebuilt_server:
        memory_probe='''def gpu_memory_mb():
    result=subprocess.run(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],capture_output=True,text=True,check=True,timeout=30)
    values=[int(line.strip()) for line in result.stdout.splitlines() if line.strip()]
    assert len(values)==2, values
    return values
before_gpu_memory=gpu_memory_mb()
'''
        server_cell=patch(server_cell,'NP=None\n',memory_probe+'NP=None\n','GPU allocation baseline')
        server_cell += '''
if NP:
    after_gpu_memory=gpu_memory_mb()
    deltas=[after-before for before,after in zip(before_gpu_memory,after_gpu_memory)]
    model_mb=Path(MODEL).stat().st_size/(1<<20)
    proof={'before_mb':before_gpu_memory,'after_mb':after_gpu_memory,'allocated_mb':deltas,
           'model_file_mb':model_mb,'requested_gpu_layers':999,'server_pid':srv.pid}
    (WORK/'gpu_server_proof.json').write_text(json.dumps(proof,indent=2))
    assert min(deltas)>1024 and sum(deltas)>.75*model_mb, 'Refusing inference without substantial model allocation on both GPUs'
    print('GPU allocation proof:',json.dumps(proof),flush=True)
'''
    config_def = ("CONFIG = " + repr(CONFIG) + "\n" +
                  f"MAX_WORKERS = {workers}\nBUDGET_HOURS = {budget_hours!r}\nMAX_FRESH_CALLS = {max_fresh!r}\n")
    startup = prebuilt_startup_cell(tag) if prebuilt_server else bounded_startup_cell(tag)
    cells = [J1B_CELLS[0], startup, server_cell, config_def + SETUP,
             RUN % {"shard": shard, "model": MODEL}]
    for i, c in enumerate(cells):
        compile(c, f"<cell {i}>", "exec")
    nb = {"cells": [{"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
                     "source": c.strip("\n").splitlines(keepends=True)} for c in cells],
          "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                       "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
    k = out / "kernel"
    k.mkdir(parents=True)
    (k / f"{tag}.ipynb").write_text(json.dumps(nb, indent=1), encoding="utf-8")
    kernel_slug = f"confibench-qwen-{tag}" if tasks_file else f"confibench-qwen-shard-{shard}-of-{n_shards}"
    kernel_title = f"ConfiBench Qwen {tag}" if tasks_file else f"ConfiBench Qwen Shard {shard} of {n_shards}"
    (k / "kernel-metadata.json").write_text(json.dumps({
        "id": f"tishaferdous/{kernel_slug}",
        "title": kernel_title, "code_file": f"{tag}.ipynb",
        "language": "python", "kernel_type": "notebook", "is_private": True,
        "enable_gpu": True, "enable_internet": True, "machine_shape": "NvidiaTeslaT4",
        "dataset_sources": [f"tishaferdous/{tag}-data"], "competition_sources": [],
        "kernel_sources": []}, indent=1), encoding="utf-8")
    pub = out / "dataset_publish"
    pub.mkdir(parents=True)
    with zipfile.ZipFile(pub / f"{tag}.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for f in ds.rglob("*"):
            if f.is_file():
                z.write(f, (PurePosixPath(tag) / PurePosixPath(f.relative_to(ds).as_posix())).as_posix())
    (pub / "dataset-metadata.json").write_text(json.dumps({
        "title": f"ConfiBench Qwen {shard} of {n_shards} Data", "id": f"tishaferdous/{tag}-data",
        "licenses": [{"name": "MIT"}]}, indent=1), encoding="utf-8")
    print(f"{out.name}: {len(mine)} tasks; {checkpoint_tasks} checkpointed; "
          f"zip {(pub / f'{tag}.zip').stat().st_size >> 10} KB; all cells compile")


if __name__ == "__main__":
    main()
