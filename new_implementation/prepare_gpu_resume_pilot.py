"""Stage one bounded GPU pilot from the verified CPU checkpoint; no network calls."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'confibench_finish_20261003'
TAG = 'cbq-resume-gpu-oct5'
TASK = 'ece241_2014_q4'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    global TAG
    if '--tag' in sys.argv:
        TAG=sys.argv[sys.argv.index('--tag')+1]
        assert all(c.isalnum() or c=='-' for c in TAG)
    prebuilt='--prebuilt-server' in sys.argv
    if prebuilt:
        probe=ROOT/'confibench_finish_20261005/runtime_probe/engine_provenance.json'
        evidence=json.loads(probe.read_text())
        assert evidence['release']=='b11399' and not evidence['source_build']
    evidence = ROOT / 'kaggle_runs/cbq_cpu_resume_oct4_v2'
    report = json.loads((evidence / 'cpu_resume_report.json').read_text())
    assert report['task'] == TASK and report['iteration_boundary_restore_verified']
    assert report['saved_responses_unchanged'] and report['fresh_model_calls'] == 0
    runtime = evidence / 'cpu_runtime.zip'
    with zipfile.ZipFile(runtime) as z:
        assert z.testzip() is None
        state = json.loads(z.read(f'{TASK}/iteration.json'))
        assert state['payload']['next_iteration'] == 9
    command=[sys.executable, str(ROOT / 'prepare_confibench_qwen.py'), '0', '1',
                    '--tasks-file', str(OUT / 'cpu_pilot_task.jsonl'), '--tag', TAG,
                    '--workers', '1', '--budget-hours', '1.5',
                    '--runtime-prev', str(runtime), '--max-fresh-calls', '8']
    if prebuilt: command.append('--prebuilt-server')
    subprocess.run(command,check=True)
    bundle = ROOT / f'kaggle_upload_{TAG}'
    metadata = json.loads((bundle / 'kernel/kernel-metadata.json').read_text())
    approval = {
        'kernel_id': metadata['id'], 'account': 1,
        'notebook_sha256': sha(bundle / 'kernel' / metadata['code_file']),
        'dataset_sha256': sha(bundle / 'dataset_publish' / f'{TAG}.zip'),
        'tasks': [TASK], 'worker_budget_hours': 1.5, 'max_fresh_calls': 8,
        'reason': 'User authorized finishing remaining tasks on 2026-10-05; one capped resume pilot first.'}
    approval_file = OUT / 'GPU_APPROVED_BUNDLES.json'
    entries = json.loads(approval_file.read_text()) if approval_file.exists() else []
    entries = [entry for entry in entries if entry['kernel_id'] != metadata['id']]
    entries.append(approval)
    approval_file.write_text(json.dumps(entries, indent=2), encoding='utf-8')
    manifest = dict(approval, tag=TAG, bundle=str(bundle), submission='staged',
                    runtime_source=str(runtime), runtime_source_sha256=sha(runtime),
                    initial_next_iteration=9, canonical_records=138,
                    remaining_tasks=18, startup_budget_minutes=30,
                    server_health_wait_seconds_per_attempt=180,
                    prebuilt_server=prebuilt, startup_health_probe_calls=1)
    (OUT / 'gpu_pilot_manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    sys.path.insert(0, str(ROOT / 'dirtb'))
    from kaggle_rotate import check_launch_hold
    check_launch_hold(bundle, 1)
    print('Verified exact bundle approval; one task, iteration 10, eight fresh calls maximum.')


if __name__ == '__main__':
    main()
