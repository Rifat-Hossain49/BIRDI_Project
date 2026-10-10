"""Bounded collect-audit-resume controller. Secrets stay in the Kaggle CLI environment."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import os
import hashlib
import re
import zipfile
import subprocess
import sys
import time

from confibench_resume import atomic_json, digest
from monitor_resume_20261005 import OUT, ROOT, now, audit_runtime, sha


def evidence_path(value):
    path = Path(value)
    return path if path.is_absolute() else ROOT.parent / path


def verified_missing_output_evidence(job, review):
    if job.get('audit_error') != 'No durable completion manifest; inspect downloaded startup logs':
        return False
    if 'KernelWorkerStatus.ERROR' not in job.get('status', ''):
        return False
    try:
        log_path = evidence_path(review['kernel_log'])
        log = log_path.read_bytes()
        if json.loads(log) != [] or hashlib.sha256(log).hexdigest() != review['kernel_log_sha256']:
            return False
        if any(log_path.parent.glob('cbq_*.zip')):
            return False
        if (log_path.parent / 'cbq_completion.json').exists():
            return False
        return hashlib.sha256(evidence_path(job['runtime_source']).read_bytes()).hexdigest() == review['runtime_sha256']
    except (OSError, ValueError, KeyError):
        return False


def reviewed_startup_retry(job, jobs):
    review = job.get('startup_retry_review')
    if not review or review.get('kind') != 'missing_artifacts_single_retry':
        return False
    if not verified_missing_output_evidence(job, review):
        return False
    retries = [j for j in jobs if j.get('retry_of') == job['tag']]
    if len(retries) != 1:
        return False
    retry = retries[0]
    if (retry['submission'] != 'accepted' or retry['tag'] != review['retry_tag']
            or retry['account'] != job['account'] or retry['tasks'] != job['tasks']
            or retry['max_fresh_calls'] > job['max_fresh_calls']
            or retry['worker_budget_hours'] > job['worker_budget_hours']):
        return False
    try:
        return hashlib.sha256(evidence_path(retry['runtime_source']).read_bytes()).hexdigest() == review['runtime_sha256']
    except (OSError, ValueError, KeyError):
        return False


def quarantined_missing_output(job, manifest):
    review = job.get('missing_output_review')
    return bool(review and review.get('kind') == 'missing_artifacts_quarantined_account'
                and job['account'] in manifest.get('scheduling_disabled_accounts', [])
                and verified_missing_output_evidence(job, review))


def reviewed_cpu_path_recovery(job, jobs):
    review=job.get('cpu_path_recovery_review',{})
    if (review.get('kind')!='path_restored_and_cpu_reverified' or not job['kind'].startswith('cpu_')
            or job.get('audit_error')!='CPU replay did not reach a verified cache miss: '+review.get('task_id','')):
        return False
    replacements=[j for j in jobs if j['tag']==review.get('recovery_tag')]
    if len(replacements)!=1: return False
    recovered=replacements[0]
    if (not recovered.get('collected_at') or recovered.get('audit_error')
            or not recovered.get('require_cpu_frontier') or not recovered['kind'].startswith('cpu_')
            or not set(job['tasks'])<=set(recovered['tasks'])
            or any(recovered.get('cpu_frontiers',{}).get(t,{}).get('status') not in
                   ('needs_model','task_recorded') for t in job['tasks'])):
        return False
    try:
        bad=Path(review['runtime_archive'])
        if sha(bad)!=review['runtime_sha256']: return False
        records,fresh=audit_runtime(job['runtime_source'],bad)
        if fresh: return False
        conflict=json.loads(records[review['conflict_member']])
        task=review['task_id']
        saved=json.loads(records[f"{task}/calls/{digest(conflict['scope'])}/{conflict['number']:06d}.json"])
        actual=conflict['request']
        previous=dict(actual,messages=saved['output'][1]['messages'][:-1])
        if (digest(previous)!=saved['request_sha256'] or digest(actual)!=conflict['request_sha256']
                or digest(actual)==digest(previous)):
            return False
        # Audit-only comparison; request hashes and provider inputs are never normalized.
        pattern=(r'^(\s*File ")/kaggle/working/ConfiBench/saves/ConfiBench_qwen/'
                 r'[A-Za-z0-9_]+/'+re.escape(task)+r'(/[^"\n]+", line \d+)')
        def path_only(request):
            return dict(request,messages=[dict(m,content=re.sub(pattern,r'\1<restored-task-root>\2',
                        m['content'],flags=re.MULTILINE)) for m in request['messages']])
        if digest(path_only(previous))!=digest(path_only(actual)): return False
        latest=Path(recovered['runtime_archive'])
        if sha(latest)!=recovered['runtime_sha256']: return False
        _,new_fresh=audit_runtime(bad,latest)
        return not new_fresh
    except (OSError,ValueError,KeyError,zipfile.BadZipFile):
        return False


def decision(manifest, state, waves, max_waves):
    if not state['remaining']:
        return 'complete', 'All expected first task records collected.'
    # Historical failed startup pilots remain evidence; inspect only uncollected
    # non-startup jobs and the latest pilot, not superseded pilots.
    pilots = [j for j in manifest['jobs'] if j['kind'] == 'gpu_pilot']
    latest_pilot = pilots[-1] if pilots else None
    blocked = set()
    for job in manifest['jobs']:
        if job['kind'] == 'gpu_pilot' and job is not latest_pilot:
            continue
        if (job.get('audit_error') and not reviewed_startup_retry(job, manifest['jobs'])
                and not quarantined_missing_output(job, manifest)
                and not reviewed_cpu_path_recovery(job,manifest['jobs'])):
            return 'stop', 'Checkpoint audit requires review: ' + job['tag']
        if job.get('collected_at'):
            blocked.difference_update(job['tasks'])
            blocked.update(job.get('blocked_tasks', []))
        if job.get('submission') == 'staged':
            return 'stop', 'Unconfirmed submission requires review: ' + job['tag']
        if job.get('submission') == 'failed' and (job['kind'] == 'gpu_wave' or job['kind'].startswith('cpu_')):
            return 'stop', 'Submission requires review: ' + job['tag']
        if job.get('collected_at') and job['kind'] == 'gpu_wave':
            if not job.get('durable_fresh_responses') and not job.get('added_task_records'):
                return 'stop', 'GPU wave made no durable model progress: ' + job['tag']
    if blocked.intersection(state['remaining']):
        return 'stop', 'Latest recovered task checkpoint requires review: ' + ', '.join(sorted(blocked))
    if state['active_jobs']:
        return 'wait', 'Remote jobs still running; no overlapping launch.'
    if not state['cpu_preflight_finished'] or not state['gpu_resume_gate_passed']:
        if manifest.get('require_current_cpu_frontier') and state['gpu_resume_gate_passed']:
            return 'preflight', 'Replay latest checkpoints on CPU before fresh GPU use.'
        return 'stop', 'Resume gates have not both passed.'
    if waves >= max_waves:
        return 'stop', 'Controller wave limit reached; collected checkpoints retained.'
    return 'launch', 'Both resume gates passed; schedule disjoint unfinished tasks.'


def run_script(name, *args):
    subprocess.run([sys.executable, str(ROOT / name), *args], check=True, timeout=7200)


def restored_controller(previous, pid):
    if previous['status'] == 'running':
        raise ValueError('Controller still recorded as running; inspect its PID first.')
    if datetime.now(timezone.utc) >= datetime.fromisoformat(previous['deadline']):
        raise ValueError('Original controller deadline elapsed; no automatic extension.')
    state = dict(previous)
    restarts = list(state.get('restarts', []))
    restarts.append({'restarted_at': now(), 'previous_pid': previous['pid'],
                     'previous_status': previous['status'], 'reason': previous.get('reason')})
    for key in ('ended_at', 'error_type', 'action', 'reason'):
        state.pop(key, None)
    state.update(status='running', pid=pid, restarts=restarts)
    return state


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser()
    parser.add_argument('--max-waves', type=int, default=6)
    parser.add_argument('--max-hours', type=float, default=18)
    parser.add_argument('--poll-seconds', type=int, default=300)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--gpu-accounts',type=int,nargs='+')
    parser.add_argument('--sessions-per-account',type=int,default=1)
    parser.add_argument('--tasks-per-job',type=int,default=2)
    parser.add_argument('--worker-budget-hours',type=float,default=2)
    parser.add_argument('--max-fresh-calls',type=int,default=16)
    args = parser.parse_args()
    if not (1 <= args.max_waves <= 8 and 1 <= args.max_hours <= 24 and args.poll_seconds >= 60):
        raise SystemExit('Controller bounds must be <=8 waves, <=24 hours and >=60s polling.')
    if not (1<=args.sessions_per_account<=2 and 1<=args.tasks_per_job<=4
            and .75<=args.worker_budget_hours<=6 and 1<=args.max_fresh_calls<=96):
        raise SystemExit('Invalid bounded GPU session settings')
    path = OUT / 'controller_state.json'
    if path.exists() and json.loads(path.read_text()).get('status') == 'running':
        raise SystemExit('Controller already recorded as running; review its PID before restarting.')
    deadline = datetime.now(timezone.utc) + timedelta(hours=args.max_hours)
    state = {'status': 'running', 'pid': os.getpid(), 'started_at': now(),
             'deadline': deadline.isoformat(), 'waves_launched': 0,
             'max_waves': args.max_waves, 'max_hours': args.max_hours}
    state['gpu_options']={'accounts':args.gpu_accounts,'sessions_per_account':args.sessions_per_account,
                          'tasks_per_job':args.tasks_per_job,'worker_budget_hours':args.worker_budget_hours,
                          'max_fresh_calls':args.max_fresh_calls}
    if args.resume:
        state = restored_controller(json.loads(path.read_text()), os.getpid())
        deadline = datetime.fromisoformat(state['deadline'])
        args.max_waves = state['max_waves']
        options=state.get('gpu_options',{})
        args.gpu_accounts=options.get('accounts',args.gpu_accounts)
        for key in ('sessions_per_account','tasks_per_job','worker_budget_hours','max_fresh_calls'):
            setattr(args,key,options.get(key,getattr(args,key)))
    manifest_path = OUT / 'launch_manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['automatic_gpu_launches'] = True
    atomic_json(manifest_path, manifest)
    atomic_json(path, state)
    try:
        while datetime.now(timezone.utc) < deadline:
            run_script('monitor_resume_20261005.py')
            manifest = json.loads(manifest_path.read_text())
            snapshot = json.loads((OUT / 'monitor_state.json').read_text())
            action, reason = decision(manifest, snapshot, state['waves_launched'], args.max_waves)
            state.update(checked_at=now(), action=action, reason=reason,
                         checkpointed=snapshot['checkpointed'], remaining=snapshot['remaining'])
            atomic_json(path, state)
            print(action.upper(), reason, flush=True)
            if action in ('complete', 'stop'):
                state['status'] = action
                break
            if action == 'preflight':
                tag='cbq-cpu-frontier-'+datetime.now(timezone.utc).strftime('%m%d-%H%M%S')
                run_script('launch_finish_cpu_preflight.py','--tag',tag)
            if action == 'launch':
                before = sum(j['kind'] == 'gpu_wave' and j['submission'] == 'accepted'
                             for j in manifest['jobs'])
                options=['--launch','--max-jobs','5','--sessions-per-account',str(args.sessions_per_account),
                         '--tasks-per-job',str(args.tasks_per_job),'--worker-budget-hours',str(args.worker_budget_hours),
                         '--max-fresh-calls',str(args.max_fresh_calls)]
                if args.gpu_accounts: options+=['--accounts',*map(str,args.gpu_accounts)]
                run_script('launch_resumed_finish_wave.py',*options)
                manifest = json.loads(manifest_path.read_text())
                after = sum(j['kind'] == 'gpu_wave' and j['submission'] == 'accepted'
                            for j in manifest['jobs'])
                if after <= before:
                    state.update(status='stop', reason='No account had sufficient verified quota; no launch.')
                    break
                state['waves_launched'] += 1
                atomic_json(path, state)
            time.sleep(args.poll_seconds)
        else:
            state.update(status='stop', reason='Controller deadline reached; remote checkpoints remain collectible.')
    except BaseException as error:
        state.update(status='error', error_type=type(error).__name__, reason=str(error))
        raise
    finally:
        state['ended_at'] = now()
        atomic_json(path, state)
        manifest = json.loads(manifest_path.read_text())
        manifest['automatic_gpu_launches'] = False
        atomic_json(manifest_path, manifest)
        print(json.dumps(state, indent=2), flush=True)


if __name__ == '__main__':
    main()
