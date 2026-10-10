"""Record the verified CPU-only allocations without accepting benchmark results."""
import json
from pathlib import Path
import zipfile

from confibench_resume import atomic_json
from continue_resumed_finish import reviewed_cpu_path_recovery
from monitor_resume_20261005 import OUT, ROOT, archive_records, now, sha


def main():
    manifest_path = OUT / 'launch_manifest.json'
    manifest = json.loads(manifest_path.read_text())
    jobs = {job['tag']: job for job in manifest['jobs']}
    cpu = jobs['cbq-cpu-frontier-v2-oct7']
    assert cpu.get('collected_at') and not cpu.get('audit_error')
    assert len(cpu['cpu_frontiers']) == 16
    assert all(frontier['status'] == 'needs_model' for frontier in cpu['cpu_frontiers'].values())
    canonical = archive_records(OUT / 'canonical_latest.zip')
    assert sum(Path(name).name == 'data.json' for name in canonical) == 140

    old_cpu = jobs['cbq-cpu-frontier-oct7']
    bad_runtime = ROOT / 'kaggle_runs/cbq-cpu-frontier-oct7_collected/cbq_runtime.zip'
    with zipfile.ZipFile(bad_runtime) as archive:
        conflicts = [name for name in archive.namelist() if '/replay_conflicts/' in name]
    assert len(conflicts) == 1 and conflicts[0].startswith('circuit10/')
    old_cpu['cpu_path_recovery_review'] = {
        'kind': 'path_restored_and_cpu_reverified', 'task_id': 'circuit10',
        'recovery_tag': cpu['tag'], 'runtime_archive': str(bad_runtime),
        'runtime_sha256': sha(bad_runtime), 'conflict_member': conflicts[0], 'reviewed_at': now(),
    }
    assert reviewed_cpu_path_recovery(old_cpu, manifest['jobs'])

    probe_path = OUT / 'hardware_probe_oct7_output/hardware_probe.json'
    probe = json.loads(probe_path.read_text())
    assert probe == {'nvidia_smi': None, 'gpu_count': 0}
    quotas = json.loads((OUT / 'quota_verified_20261007.json').read_text())
    quota = next(row for row in quotas['accounts'] if row['account'] == 7)
    assert quota['remaining'] == '30.00h'
    seed = archive_records(Path(cpu['runtime_archive']))
    for tag in ('cbq-resume-r5a7s1-oct7', 'cbq-resume-r5a7s2-oct7'):
        job = jobs[tag]
        assert job['submission'] == 'accepted' and 'KernelWorkerStatus.ERROR' in job['status']
        directory = ROOT / 'kaggle_runs' / (tag + '_collected')
        log = directory / (job['kernel_id'].split('/', 1)[1] + '.log')
        messages = json.loads(log.read_text())
        output = ''.join(message.get('data', '') for message in messages)
        assert 'Exception encountered at "In [1]"' in output
        assert "FileNotFoundError: [Errno 2] No such file or directory: 'nvidia-smi'" in output
        assert not list(directory.glob('cbq_*.zip')) and not (directory / 'cbq_completion.json').exists()
        source = archive_records(Path(job['runtime_source']))
        expected = {name: payload for name, payload in seed.items() if name.split('/')[0] in job['tasks']}
        assert source == expected
        bundle = Path(job['bundle']) / 'kernel'
        metadata = json.loads((bundle / 'kernel-metadata.json').read_text())
        notebook = json.loads((bundle / metadata['code_file']).read_text())
        first_cell = ''.join(notebook['cells'][0]['source'])
        assert 'nvidia-smi' in first_cell and len(first_cell.splitlines()) <= 10
        assert sha(bundle / metadata['code_file']) == job['notebook_sha256']
        job['startup_failure_review'] = {
            'kind': 'cpu_only_allocation_before_model_start', 'reviewed_at': now(),
            'kernel_log': str(log), 'kernel_log_sha256': sha(log),
            'runtime_sha256': sha(Path(job['runtime_source'])),
            'hardware_probe': str(probe_path), 'hardware_probe_sha256': sha(probe_path),
            'model_started': False, 'new_task_records': 0,
        }

    manifest['scheduling_disabled_accounts'] = sorted(set(manifest.get('scheduling_disabled_accounts', [])) | {7})
    manifest['automatic_gpu_launches'] = False
    manifest['hardware_allocation_hold'] = {
        'account': 7, 'observed_at': now(), 'gpu_count': 0,
        'reason': 'No GPUs assigned even with explicit NvidiaTeslaT4 request; cause not yet established.',
        'release_requires': 'Verified T4 x2 hardware allocation, startup evidence review and unchanged checkpoint audit.',
    }
    atomic_json(manifest_path, manifest)
    account_path = OUT / 'extra_gpu_account_20261007.json'
    account = json.loads(account_path.read_text())
    account.update(launched=True, gpu_jobs_accepted=2, gpu_jobs_status='ERROR before model startup',
                   preflight_status='16 verified CPU frontiers, zero fresh task calls',
                   hardware_allocation_status='CPU only despite requested T4 x2',
                   gpu_hours_observed=30.0, tests_passed=38, reviewed_at=now())
    atomic_json(account_path, account)
    atomic_json(OUT / 'hardware_failure_review_20261007.json', {
        'reviewed_at': now(), 'checkpointed': 140, 'remaining': 16,
        'cpu_replay_validated': 16, 'fresh_task_responses': 0,
        'new_account_gpu_hours_remaining': 30.0, 'new_account_gpu_hours_used': 0.0,
        'gpu_jobs': [jobs[tag]['kernel_id'] for tag in ('cbq-resume-r5a7s1-oct7', 'cbq-resume-r5a7s2-oct7')],
        'hardware_probe_kernel': 'sahanzparvintopy/confibench-hardware-probe-oct7',
        'scheduling_disabled_accounts': manifest['scheduling_disabled_accounts'],
        'automatic_gpu_launches': False, 'tests_passed': 38,
    })
    print('Saved strict CPU recovery review and hardware hold. 140/156; 16 unresolved; no fresh model calls.')


if __name__ == '__main__':
    main()
