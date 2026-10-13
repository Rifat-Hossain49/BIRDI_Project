"""Resume immutable Kaggle journals in the same paths on a local GPU desktop."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
import zipfile

IMPL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(IMPL))
from confibench_resume import atomic_json, digest
from prepare_confibench_qwen import CONFIG, MODEL

WORK = Path('/kaggle/working')
CB = WORK / 'ConfiBench'
RUNTIME = WORK / 'cbq_runtime'
PROC = Path('/proc')
# The guest filesystem reports ~1 TB free even when the host drive behind the WSL disk is full.
DISK_GROWTH_LIMIT = 80 << 30


def file_sha(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        while block := source.read(4 << 20):
            value.update(block)
    return value.hexdigest()


def extract(archive_path, destination):
    destination = destination.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        if len(set(archive.namelist())) != len(archive.namelist()) or archive.testzip():
            raise ValueError('Duplicate or corrupt ZIP entries')
        for info in archive.infolist():
            path = PurePosixPath(info.filename)
            target = destination.joinpath(*path.parts)
            if ('\\' in info.orig_filename or path.is_absolute() or '..' in path.parts
                    or not target.resolve().is_relative_to(destination)
                    or (info.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError('Unsafe checkpoint archive member')
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(info))


def prepare(downloads):
    manifest = json.loads((IMPL / 'desktop/checkpoint_manifest.json').read_text())
    archive = downloads / manifest['asset']
    if not archive.exists() or file_sha(archive) != manifest['sha256']:
        raise ValueError('Download the exact checkpoint asset; its SHA256 must match')
    marker = WORK / 'desktop_import.json'
    if marker.exists():
        if json.loads(marker.read_text())['archive_sha256'] != manifest['sha256']:
            raise ValueError('Another checkpoint was already imported into this working directory')
        return manifest
    if CB.exists() or RUNTIME.exists():
        raise ValueError('Working directory is not empty; refusing to overwrite existing desktop progress')
    WORK.mkdir(parents=True, exist_ok=True)
    stage = WORK / 'desktop_seed'
    stage.mkdir(exist_ok=False)
    extract(archive, stage)
    for name, expected in manifest['members'].items():
        if file_sha(stage / name) != expected:
            raise ValueError('Checkpoint member checksum mismatch: ' + name)
    shutil.copytree(stage / 'ConfiBench', CB)
    extract(stage / 'runtime_latest.zip', RUNTIME)
    extract(stage / 'canonical_latest.zip', CB)
    shutil.copy2(stage / 'canonical_latest.zip', WORK / 'first_records_before_desktop.zip')
    atomic_json(marker, {'archive_sha256': manifest['sha256'], 'imported_at': time.time()})
    return manifest


def completed():
    result = {}
    for path in (CB / 'saves').rglob('data.json'):
        record = json.loads(path.read_text())
        task = record['task_id']
        if path.parent.name != task or task in result:
            raise ValueError('Duplicate or invalid first task record: ' + task)
        result[task] = path
    return result


def checkpoint(manifest):
    for source, filename in ((CB / 'saves', 'desktop_saves.zip'), (RUNTIME, 'desktop_runtime.zip')):
        temporary = WORK / (filename + '.tmp')
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(source.rglob('*.json')):
                if source == CB / 'saves' and path.name not in ('data.json', 'run_info.json', 'run_info_short.json'):
                    continue
                try:
                    archive.write(path, (path.relative_to(CB) if source == CB / 'saves' else path.relative_to(source)).as_posix())
                except FileNotFoundError:
                    # A live worker removed it (e.g. a consumed next_request.json); the next snapshot is current.
                    continue
        os.replace(temporary, WORK / filename)
    done = set(completed())
    atomic_json(WORK / 'desktop_completion.json', {
        'expected': manifest['expected'], 'recorded': sorted(done),
        'remaining': sorted(set(manifest['expected']) - done), 'checked_at': time.time(),
        'all_tasks_recorded': done == set(manifest['expected']),
        'note': 'Task records include failures; this is not a pass count.',
    })
    print(f'Recorded {len(done)}/{len(manifest["expected"])}; remaining {len(set(manifest["expected"]) - done)}', flush=True)


def start_server(args):
    smi = shutil.which('nvidia-smi')
    if not smi:
        raise RuntimeError('No NVIDIA GPU in container: check Docker GPU integration')
    gpu = subprocess.run([smi, '--query-gpu=name,memory.total,memory.used', '--format=csv,noheader,nounits'],
                         capture_output=True, text=True, check=True, timeout=30).stdout
    print('GPU:', gpu, flush=True)
    before = [int(line.rsplit(',', 1)[1]) for line in gpu.strip().splitlines()]
    if args.workers == 2 and max(int(line.split(',')[-2]) for line in gpu.strip().splitlines()) < 30000:
        raise RuntimeError('Two-worker configuration expects a 32 GB GPU; use --workers 1 if needed')
    engine_path = WORK / 'engine_provenance.json'
    if not engine_path.exists():
        subprocess.run([sys.executable, str(IMPL / 'install_llama_release.py'), '--root',
                        str(WORK / 'llama-runtime'), '--manifest', str(engine_path)], check=True, timeout=1200)
    engine = json.loads(engine_path.read_text())
    if engine['release'] != 'b11399' or engine['missing_driver']:
        raise RuntimeError('Pinned CUDA backend or NVIDIA driver unavailable')
    model = args.model
    if model is None:
        from huggingface_hub import hf_hub_download
        model = Path(hf_hub_download('unsloth/Qwen3.5-27B-GGUF', 'Qwen3.5-27B-Q4_K_M.gguf',
                                    local_dir=WORK / 'models'))
    if model.name != 'Qwen3.5-27B-Q4_K_M.gguf' or not model.is_file():
        raise ValueError('Use the same Qwen3.5-27B Q4_K_M GGUF, not another model or quantization')
    env = dict(os.environ, LD_LIBRARY_PATH=engine['ld_library_path'])
    log = (WORK / 'desktop_server.log').open('a')
    server = subprocess.Popen([engine['server'], '-m', str(model), '-ngl', '999', '-c',
        str(32768 * args.workers), '-np', str(args.workers), '--jinja', '--reasoning-format', 'none',
        '--host', '127.0.0.1', '--port', '8080', '-t', '4'], env=env, stdout=log,
        stderr=subprocess.STDOUT, start_new_session=True)
    try:
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline and server.poll() is None:
            try:
                with urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=5) as response:
                    if b'ok' in response.read():
                        after = subprocess.run([smi, '--query-gpu=memory.used', '--format=csv,noheader,nounits'],
                            capture_output=True, text=True, check=True, timeout=30).stdout
                        delta = sum(int(line) for line in after.strip().splitlines()) - sum(before)
                        if delta < 0.75 * model.stat().st_size / (1 << 20):
                            raise RuntimeError('Insufficient model allocation on GPU; refusing CPU-only inference')
                        atomic_json(WORK / 'desktop_engine.json', {
                            'backend': engine, 'model_sha256': file_sha(model), 'model': str(model),
                            'workers': args.workers, 'context_per_slot': 32768, 'gpu_allocated_mb': delta,
                            'thinking': False, 'hardware': gpu,
                        })
                        return server
            except (urllib.error.URLError, TimeoutError):
                pass
            time.sleep(3)
        raise RuntimeError('Model server failed or timed out; inspect desktop_server.log; try --workers 1 for OOM')
    except BaseException:
        stop(server)
        raise
    finally:
        log.close()


def stop(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)


def worker_config(task):
    """ConfiBench names save roots <prefix>_<second>; a per-task prefix keeps workers started
    in the same second apart, as the Kaggle per-worker S<shard>W<w> prefixes did."""
    return CONFIG % {'prefix': 'Desktop_' + task, 'model': MODEL, 'only': json.dumps([task])}


def reap_orphans(keep):
    """Kill processes re-parented to this PID-1 runner. ConfiBench's subproc_call kills only the
    shell or python checker it started on timeout, so an abandoned vvp grandchild can keep writing
    a deleted TBout.txt until the disk fills (2026-10-10). Workers and the server are in keep."""
    reaped = 0
    for entry in PROC.iterdir():
        if not entry.name.isdigit() or int(entry.name) in keep:
            continue
        try:
            status = (entry / 'status').read_text()
            if int(re.search(r'^PPid:\s+(\d+)', status, re.M).group(1)) != 1:
                continue
            pid = int(entry.name)
            if not re.search(r'^State:\s+Z', status, re.M):
                command = (entry / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')
                os.kill(pid, signal.SIGKILL)
                with (WORK / 'desktop_reaped.log').open('a') as log:
                    log.write(f'{time.time():.0f} {pid} {command[:300]}\n')
                reaped += 1
            os.waitpid(pid, os.WNOHANG)
        except (OSError, AttributeError, ValueError):
            pass
    return reaped


def check_disk(start_used):
    grown = shutil.disk_usage(WORK).used - start_used
    if grown > DISK_GROWTH_LIMIT:
        raise RuntimeError(f'Working disk grew {grown >> 30} GB this session; stopping before the host drive fills')


def verify_first_records():
    with zipfile.ZipFile(WORK / 'first_records_before_desktop.zip') as original:
        for name in original.namelist():
            if name.endswith('/data.json') and (CB / name).read_bytes() != original.read(name):
                raise ValueError('Existing first record was changed: ' + name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--downloads', type=Path, default=Path('/downloads'))
    parser.add_argument('--cpu-only', action='store_true')
    parser.add_argument('--workers', type=int, choices=(1, 2), default=2)
    parser.add_argument('--hours', type=float, default=12)
    parser.add_argument('--model', type=Path)
    args = parser.parse_args()
    if os.name != 'posix' or str(WORK.resolve()) != '/kaggle/working' or not 0 < args.hours <= 168:
        raise ValueError('Run in the documented Linux container with the preserved /kaggle/working mount')
    manifest = prepare(args.downloads)
    verify_first_records()
    todo = sorted(set(manifest['expected']) - set(completed()))
    expected_profile = json.loads((CB / 'resume_profile.json').read_text())['profile']
    for task in todo:
        contract = json.loads((RUNTIME / task / 'contract.json').read_text())
        if contract['profile'] != expected_profile:
            raise ValueError('Prepared baseline and checkpoint profiles differ')
    server = None
    running = {}
    outcomes = {}
    deadline = time.time() + args.hours * 3600
    last_snapshot = 0
    run_id = time.strftime('%Y%m%d_%H%M%S', time.gmtime())
    logs = {}
    try:
        if not args.cpu_only and todo:
            proof = WORK / 'desktop_cpu_audit.json'
            audit = json.loads(proof.read_text()) if proof.exists() else {}
            if audit.get('seed_sha256') != manifest['sha256'] or not set(todo) <= set(audit.get('verified', [])):
                raise RuntimeError('Run --cpu-only successfully on this desktop before starting fresh model calls')
            proof.unlink()
            server = start_server(args)
            deadline = time.time() + args.hours * 3600
        start_used = shutil.disk_usage(WORK).used
        while todo or running:
            while todo and len(running) < args.workers and time.time() < deadline:
                task = todo.pop(0)
                config = 'desktop_' + task
                (CB / 'config/configs' / (config + '.yaml')).write_text(worker_config(task))
                env = dict(os.environ, CBQ_RESUME_ROOT=str(RUNTIME),
                           QWEN_BASE_URL='http://127.0.0.1:8080/v1', PYTHONUNBUFFERED='1')
                env.pop('CBQ_NEW_CALL_DEADLINE', None)
                if args.cpu_only:
                    env['CBQ_MAX_FRESH_CALLS'] = '0'
                else:
                    env.pop('CBQ_MAX_FRESH_CALLS', None)
                    env['CBQ_NEW_CALL_DEADLINE'] = str(deadline - min(3600, args.hours * 1800))
                log_path = WORK / ('desktop_' + run_id + '_' + task + '.log')
                logs[task] = log_path
                with log_path.open('w') as log:
                    process = subprocess.Popen([sys.executable, 'main.py', '-c', config], cwd=CB,
                        env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                running[task] = process
                print('Started', task, 'CPU replay' if args.cpu_only else 'GPU continuation', flush=True)
            for task, process in list(running.items()):
                code = process.poll()
                if code is not None:
                    outcomes[task] = code
                    del running[task]
                    print('Worker exited', task, code, flush=True)
            if os.getpid() == 1:
                keep = {1} | {process.pid for process in running.values()}
                if server is not None:
                    keep.add(server.pid)
                if reaped := reap_orphans(keep):
                    print('Killed', reaped, 'orphaned simulator process(es); see desktop_reaped.log', flush=True)
            check_disk(start_used)
            if time.time() - last_snapshot >= 60 or not running:
                verify_first_records()
                checkpoint(manifest)
                last_snapshot = time.time()
            if time.time() >= deadline:
                break
            if running:
                time.sleep(2)
        if args.cpu_only:
            verified = []
            for task, code in outcomes.items():
                if task in completed() and code == 0:
                    verified.append(task)
                    continue
                frontier = RUNTIME / task / 'next_request.json'
                record = json.loads(frontier.read_text()) if frontier.exists() else {}
                log = logs[task].read_text(errors='replace')
                if (code == 1 and record.get('max_fresh') == 0 and record.get('fresh_this_session') == 0
                        and record.get('request_sha256') == digest(record.get('request'))
                        and 'BudgetStop' in log and 'ResumeMismatch' not in log):
                    verified.append(task)
            atomic_json(WORK / 'desktop_cpu_audit.json', {
                'seed_sha256': manifest['sha256'], 'verified': sorted(verified), 'outcomes': outcomes,
                'all_verified': set(verified) == set(outcomes) and not todo and not running,
            })
            if todo or running or set(verified) != set(outcomes):
                raise RuntimeError('Desktop CPU replay failed; no GPU continuation authorized')
        elif set(outcomes) - set(completed()):
            print('Some tasks remain unresolved. Preserve logs and rerun CPU replay before continuation.', flush=True)
        if not args.cpu_only:
            (WORK / 'desktop_cpu_audit.json').unlink(missing_ok=True)
    finally:
        for process in running.values():
            stop(process)
        if server is not None:
            stop(server)
        verify_first_records()
        checkpoint(manifest)


if __name__ == '__main__':
    main()
