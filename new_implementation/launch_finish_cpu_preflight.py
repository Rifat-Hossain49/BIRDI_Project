"""Replay only audited unfinished work on CPU; never start a model server."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from confibench_resume import atomic_json
from launch_resumed_finish_wave import pending_and_sources, runtime_for
from monitor_resume_20261005 import ROOT, OUT, now, sha

sys.path.insert(0, str(ROOT / 'dirtb'))
import kaggle_rotate as k


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser()
    parser.add_argument('--tag', required=True)
    args = parser.parse_args()
    if not all(c.isalnum() or c == '-' for c in args.tag):
        raise SystemExit('Unsafe CPU preflight tag')
    manifest_path = OUT / 'launch_manifest.json'
    manifest = json.loads(manifest_path.read_text())
    if args.tag in {job['tag'] for job in manifest['jobs']}:
        raise SystemExit('CPU preflight tag already recorded; inspect before retrying')
    tasks, sources, blocked = pending_and_sources(manifest, cpu_replay=True)
    if blocked:
        raise SystemExit('Checkpoint conflict requires review before CPU replay')
    if not tasks:
        print('No unfinished tasks; no CPU notebook submitted', flush=True)
        return
    seed = OUT / (args.tag + '_input.zip')
    runtime_for(tasks, sources, seed)
    subprocess.run([sys.executable, str(ROOT / 'prepare_cpu_resume_remaining.py'),
                    '--tag', args.tag, '--runtime-archive', str(seed)], check=True)
    staged_path = OUT / 'cpu_replay_manifest.json'
    job = json.loads(staged_path.read_text())
    bundle = Path(job['bundle'])
    metadata = json.loads((bundle / 'kernel/kernel-metadata.json').read_text())
    if metadata['enable_gpu'] is not False or job['max_fresh_calls'] != 0:
        raise SystemExit('CPU replay unexpectedly enables GPU or fresh generation')
    job.update(notebook_sha256=sha(bundle / 'kernel' / metadata['code_file']),
               dataset_sha256=sha(bundle / 'dataset_publish' / (args.tag + '.zip')))
    manifest['jobs'].append(job)
    manifest.update(cpu_preflight_finished=False, latest_cpu_preflight_tag=args.tag,
                    latest_cpu_preflight_status='staged')
    atomic_json(manifest_path, manifest)
    try:
        k.push(bundle, job['account'])
    except (Exception, SystemExit) as error:
        job.update(submission='failed', submission_error=type(error).__name__)
        atomic_json(manifest_path, manifest)
        raise
    job.update(submission='accepted', submitted_at=now())
    atomic_json(staged_path, job)
    manifest['latest_cpu_preflight_status'] = 'submitted'
    atomic_json(manifest_path, manifest)
    print('Submitted CPU-only latest-checkpoint replay:', job['kernel_id'], flush=True)


if __name__ == '__main__':
    main()
