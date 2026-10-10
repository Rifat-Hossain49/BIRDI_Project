"""Collect the authorized finish wave and retry unresolved tasks within live quotas.

Run with --once to inspect/collect without launching retries. Normal mode polls
every 60 seconds and writes its state locally; it never persists credentials.
"""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'dirtb'))
import kaggle_rotate as k

OUT = ROOT / 'confibench_finish_20261003'
MANIFEST = OUT / 'launch_manifest.json'
STATE = OUT / 'monitor_state.json'


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, indent=2), encoding='utf-8')
    tmp.replace(path)


def log(message):
    print(now(), message, flush=True)


def collect(job, account):
    dest = ROOT / 'kaggle_runs' / (job['tag'] + '_oct3_collected')
    dest.mkdir(exist_ok=True)
    identifier = k.kernel_id(Path(job['bundle']), job['account'])
    archive = dest / 'cbq_saves.zip'
    # Check archives rather than CLI exit status (some download errors exit 0).
    for attempt in range(3):
        try:
            with zipfile.ZipFile(archive) as z:
                if z.testzip() is not None:
                    raise ValueError('Archive checksum failure')
                records = {}
                for name in z.namelist():
                    p = PurePosixPath(name)
                    if p.name == 'data.json':
                        record = json.loads(z.read(name))
                        task = p.parent.name
                        assert task in job['tasks'] and record.get('task_id') == task
                        records.setdefault(task, z.read(name))
                job['archive'] = str(archive)
                job['checkpointed_tasks'] = sorted(records)
                return records
        except (FileNotFoundError, zipfile.BadZipFile, ValueError):
            if attempt == 2:
                return None
            k.kaggle(['kernels', 'output', identifier, '-p', str(dest),
                      '--file-pattern', 'cbq_saves.zip', '--page-size', '200'], account, timeout=240)
    return None


def canonical(manifest):
    records = {}
    with zipfile.ZipFile(OUT / 'canonical_136.zip') as z:
        for name in z.namelist():
            records[PurePosixPath(name).parent.name] = z.read(name)
    for job in manifest['jobs']:
        if job.get('archive'):
            with zipfile.ZipFile(job['archive']) as z:
                for name in z.namelist():
                    p = PurePosixPath(name)
                    if p.name == 'data.json':
                        # First audited record wins; never select by pass score.
                        records.setdefault(p.parent.name, z.read(name))
    expected = set(manifest['expected'])
    assert set(records) <= expected
    temp = OUT / 'canonical_latest.tmp.zip'
    with zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED) as z:
        for task in sorted(records):
            z.writestr(f'saves/ConfiBench_qwen/merged/{task}/data.json', records[task])
    temp.replace(OUT / 'canonical_latest.zip')
    return sorted(expected - set(records)), len(records)


def main():
    if (ROOT/'confibench_finish_20261005/launch_manifest.json').exists():
        subprocess.run([sys.executable,str(ROOT/'monitor_resume_20261005.py')],check=True)
        log('October 5 resume run supersedes this monitor; old automatic retries remain disabled.')
        return
    once = '--once' in sys.argv
    limit = time.monotonic() + 36 * 3600
    round_number = 0
    while time.monotonic() < limit:
        manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
        accounts = k.accounts()
        active = False
        collection_pending = False
        for job in manifest['jobs']:
            if job.get('checkpointed_tasks') is not None:
                continue
            if job['submission'] != 'accepted':
                continue
            try:
                status = k.kaggle(['kernels', 'status', k.kernel_id(Path(job['bundle']), job['account'])],
                                  accounts[job['account']], timeout=90)
                job['status_checked_at'] = now()
                job['status'] = status.strip().splitlines()[-1] if status.strip() else 'UNKNOWN'
                if any(word in status for word in ('RUNNING', 'QUEUED')):
                    active = True
                elif any(word in status for word in ('COMPLETE', 'ERROR', 'CANCEL_ACKNOWLEDGED')):
                    result = collect(job, accounts[job['account']])
                    collection_pending |= result is None
                    log(f"{job['tag']}: " + (f'collected {len(result)} checkpoints' if result is not None else 'output pending'))
                else:
                    active = True
            except Exception as error:
                log(f"{job['tag']}: {type(error).__name__}; will retry status/collection")
                active = True
            save(MANIFEST, manifest)
        missing, count = canonical(manifest)
        summary = {'checked_at': now(), 'checkpointed': count, 'expected': 156,
                   'remaining': missing, 'active': active,
                   'collection_pending': collection_pending}
        save(STATE, summary)
        log(f'Checkpoint {count}/156; remaining={len(missing)}; active={active}; output_pending={collection_pending}')
        if not missing:
            summary['state'] = 'all_task_records_collected'
            save(STATE, summary)
            log('All 156 task records collected. Ready for CPU metric aggregation.')
            return
        if once:
            log(f'Checkpoint {count}/156; {len(missing)} unresolved')
            return
        if not active and not collection_pending:
            if (OUT / 'GPU_LAUNCH_HOLD').exists():
                summary['state'] = 'held_pending_resume_validation'
                save(STATE, summary)
                log('GPU launch hold active. Collect-only mode; no retries launched.')
                return
            round_number += 1
            launched = 0
            pending = list(missing)
            for number, account in accounts.items():
                if not pending:
                    break
                output = k.kaggle(['quota', '--format', 'json'], account, timeout=90)
                try:
                    quotas = json.loads(output[output.index('['):])
                    available = float(next(q['remaining'] for q in quotas if q['resource'] == 'GPU').removesuffix('h'))
                except (ValueError, StopIteration):
                    continue
                budget = min(10.5, available - 0.75)
                if budget < 1.5:
                    continue
                tasks = pending[:2]
                tag = f'cbqoct3r{round_number}a{number}'
                task_file = OUT / f'{tag}.jsonl'
                task_file.write_text(''.join(json.dumps({'task_id': task}) + '\n' for task in tasks))
                subprocess.run([sys.executable, str(ROOT / 'prepare_confibench_qwen.py'), '0', '1',
                                '--tasks-file', str(task_file), '--tag', tag, '--workers', str(len(tasks)),
                                '--budget-hours', str(budget)], check=True)
                job = {'tag': tag, 'account': number, 'tasks': tasks,
                       'bundle': str(ROOT / f'kaggle_upload_{tag}'), 'submission': 'staged'}
                manifest['jobs'].append(job)
                save(MANIFEST, manifest)
                try:
                    with contextlib.redirect_stdout(io.StringIO()) as capture:
                        k.push(Path(job['bundle']), number)
                    job['submission'] = 'accepted'
                    job['submitted_at'] = now()
                    pending = pending[len(tasks):]
                    launched += 1
                    log(f'{tag}: accepted, tasks={tasks}, budget={budget:.2f}h')
                except (Exception, SystemExit) as error:
                    job['submission'] = 'failed'
                    log(f'{tag}: launch failed ({type(error).__name__})')
                save(MANIFEST, manifest)
            if not launched:
                summary['state'] = 'blocked_on_gpu_capacity'
                save(STATE, summary)
                log(f'No usable GPU capacity. Preserved {count}/156; {len(missing)} unresolved.')
                return
        if (OUT / 'STOP_MONITOR').exists():
            log('Local stop flag detected; cloud jobs continue.')
            return
        time.sleep(60)
    log('Monitor wall-time limit reached; state preserved.')


if __name__ == '__main__':
    main()
