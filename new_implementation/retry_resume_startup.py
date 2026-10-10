"""One explicitly reviewed retry for a terminal job with no execution artifacts."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from confibench_resume import atomic_json
from monitor_resume_20261005 import OUT, ROOT, OLD, now, sha
sys.path.insert(0, str(ROOT / 'dirtb'))
import kaggle_rotate as k


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser()
    parser.add_argument('original_tag')
    parser.add_argument('retry_tag')
    args = parser.parse_args()
    manifest = json.loads((OUT / 'launch_manifest.json').read_text())
    original = next(j for j in manifest['jobs'] if j['tag'] == args.original_tag)
    if any(j.get('retry_of') == original['tag'] or j['tag'] == args.retry_tag for j in manifest['jobs']):
        raise SystemExit('An initial retry already exists; no repeated startup retry allowed.')
    if (original.get('audit_error') != 'No durable completion manifest; inspect downloaded startup logs'
            or 'KernelWorkerStatus.ERROR' not in original.get('status', '')):
        raise SystemExit('Only a reviewed terminal missing-artifact submission is eligible.')
    log = ROOT / 'kaggle_runs' / (original['tag'] + '_collected') / (original['kernel_id'].split('/')[1] + '.log')
    assert json.loads(log.read_bytes()) == []
    assert not list(log.parent.glob('cbq_*.zip')) and not (log.parent / 'cbq_completion.json').exists()
    account = k.accounts()[original['account']]
    status = k.kaggle(['kernels', 'status', original['kernel_id']], account, timeout=90)
    assert 'KernelWorkerStatus.ERROR' in status, 'Original job must remain terminal before retry.'
    output = k.kaggle(['quota', '--format', 'json'], account, timeout=90)
    quota = json.loads(output[output.index('['):])
    available = float(next(q['remaining'] for q in quota if q['resource'] == 'GPU').removesuffix('h'))
    budget = min(original['worker_budget_hours'], available - .75)
    assert budget >= .75, 'Insufficient quota for even the bounded startup retry.'
    tasks_file = OUT / (args.retry_tag + '.jsonl')
    tasks_file.write_text(''.join(json.dumps({'task_id': t}) + '\n' for t in original['tasks']))
    runtime = OUT / (args.retry_tag + '_runtime.zip')
    shutil.copy2(original['runtime_source'], runtime)
    assert sha(runtime) == sha(Path(original['runtime_source']))
    subprocess.run([sys.executable, str(ROOT / 'prepare_confibench_qwen.py'), '0', '1',
                    '--tasks-file', str(tasks_file), '--tag', args.retry_tag,
                    '--workers', str(len(original['tasks'])), '--budget-hours', str(budget),
                    '--max-fresh-calls', str(original['max_fresh_calls']),
                    '--runtime-prev', str(runtime), '--prebuilt-server'], check=True)
    bundle = ROOT / ('kaggle_upload_' + args.retry_tag)
    metadata = json.loads((bundle / 'kernel/kernel-metadata.json').read_text())
    approval = {'kernel_id': metadata['id'], 'account': original['account'],
                'notebook_sha256': sha(bundle / 'kernel' / metadata['code_file']),
                'dataset_sha256': sha(bundle / 'dataset_publish' / (args.retry_tag + '.zip')),
                'reason': 'One user-authorized reviewed missing-output retry; identical audited runtime; no score selection.'}
    approvals = json.loads((OLD / 'GPU_APPROVED_BUNDLES.json').read_text())
    approvals.append(approval)
    atomic_json(OLD / 'GPU_APPROVED_BUNDLES.json', approvals)
    retry = dict(approval, kernel_id=account['user'] + '/' + metadata['id'].split('/')[1],
                 kind='gpu_wave', tag=args.retry_tag, retry_of=original['tag'], round=original['round'],
                 bundle=str(bundle), tasks=original['tasks'], submission='staged',
                 runtime_source=str(runtime), max_fresh_calls=original['max_fresh_calls'],
                 worker_budget_hours=budget, startup_health_probe_calls=1,
                 available_gpu_hours_at_submission=available)
    manifest['jobs'].append(retry)
    atomic_json(OUT / 'launch_manifest.json', manifest)
    try:
        k.push(bundle, original['account'])
    except (Exception, SystemExit) as error:
        retry.update(submission='failed', submission_error=type(error).__name__)
        atomic_json(OUT / 'launch_manifest.json', manifest)
        raise
    retry.update(submission='accepted', submitted_at=now())
    original['startup_retry_review'] = {
        'kind': 'missing_artifacts_single_retry', 'reviewed_at': now(), 'retry_tag': retry['tag'],
        'kernel_log': str(log), 'kernel_log_sha256': sha(log), 'runtime_sha256': sha(runtime),
        'cause_known': False, 'fresh_generation_known': False,
        'reason': 'API failure_message empty; empty kernel log; no downloadable execution artifacts. One capped retry only.'}
    atomic_json(OUT / 'launch_manifest.json', manifest)
    print('Accepted single startup retry:', retry['kernel_id'], flush=True)


if __name__ == '__main__':
    main()
