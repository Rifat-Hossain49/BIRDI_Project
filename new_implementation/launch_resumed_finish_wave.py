"""Stage/launch disjoint bounded jobs only after audited CPU and GPU resume gates."""
import argparse
import json
import math
from pathlib import Path, PurePosixPath
import subprocess
import sys
import zipfile

from confibench_resume import atomic_json
from monitor_resume_20261005 import ROOT, OUT, OLD, archive_records, now, sha
sys.path.insert(0,str(ROOT/'dirtb'))
import kaggle_rotate as k


def pending_and_sources(manifest, *, cpu_replay=False):
    canonical=archive_records(OUT/'canonical_latest.zip')
    done={PurePosixPath(name).parent.name for name in canonical if PurePosixPath(name).name=='data.json'}
    if not cpu_replay and (not manifest['gpu_resume_gate_passed'] or not manifest['cpu_preflight_finished']):
        raise SystemExit('Resume gates have not both passed; no GPU wave may launch')
    active=[job for job in manifest['jobs'] if job['submission']=='accepted'
            and not job.get('collected_at') and not job.get('audit_error')]
    if active:
        raise SystemExit('Collect and audit the active jobs before scheduling another wave')
    sources={}
    source_jobs={}
    blocked=set()
    for job in manifest['jobs']:
        if not job.get('collected_at') or job.get('audit_error'): continue
        for task in job['tasks']:
            sources[task]=job['runtime_archive']
            source_jobs[task]=job
            blocked.discard(task)
        blocked.update(job.get('blocked_tasks',[]))
    pending=sorted(set(manifest['expected'])-done-blocked)
    for task in pending:
        if task not in sources: raise SystemExit('Missing audited runtime for '+task)
        if not cpu_replay and manifest.get('require_current_cpu_frontier'):
            job=source_jobs[task]
            frontier=job.get('cpu_frontiers',{}).get(task,{})
            if (not job.get('require_cpu_frontier') or frontier.get('status')!='needs_model'
                    or job.get('runtime_sha256')!=sha(Path(sources[task]))):
                raise SystemExit('A latest-checkpoint CPU frontier is required before GPU use: '+task)
    def priority(task):
        attempts=sum(job['kind']=='gpu_wave' and job['submission']=='accepted' and task in job['tasks']
                     for job in manifest['jobs'])
        records=archive_records(Path(sources[task]))
        state=json.loads(records[f'{task}/iteration.json']) if f'{task}/iteration.json' in records else None
        cursor=state['payload']['next_iteration'] if state else 0
        return attempts,-cursor,task
    pending.sort(key=priority)
    return pending,sources,blocked


def session_budgets(available, requested, sessions, reserve=.75):
    """Reserve setup/shutdown quota separately for each planned GPU session."""
    if (not all(math.isfinite(value) for value in (available,requested,reserve))
            or available<0 or not .75<=requested<=6 or not .75<=reserve<=1
            or not 1<=sessions<=2):
        raise ValueError('Invalid quota or session budget')
    budgets=[]
    for _ in range(sessions):
        budget=min(requested,available-reserve)
        if budget<.75: break
        budgets.append(budget)
        available-=budget+reserve
    return budgets


def runtime_for(tasks,sources,dest):
    output={}
    for task in tasks:
        records=archive_records(Path(sources[task]))
        selected={name:payload for name,payload in records.items() if PurePosixPath(name).parts[0]==task}
        if f'{task}/contract.json' not in selected:
            raise ValueError('Missing task contract: '+task)
        output.update(selected)
    with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED) as z:
        for name,payload in sorted(output.items()): z.writestr(name,payload)


def main():
    if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    parser=argparse.ArgumentParser()
    parser.add_argument('--launch',action='store_true')
    parser.add_argument('--max-jobs',type=int,default=5)
    parser.add_argument('--accounts',type=int,nargs='+')
    parser.add_argument('--sessions-per-account',type=int,default=1)
    parser.add_argument('--tasks-per-job',type=int,default=2)
    parser.add_argument('--worker-budget-hours',type=float,default=2)
    parser.add_argument('--max-fresh-calls',type=int,default=16)
    args=parser.parse_args()
    assert 1<=args.max_jobs<=5
    assert 1<=args.sessions_per_account<=2 and 1<=args.tasks_per_job<=4
    assert .75<=args.worker_budget_hours<=6 and 1<=args.max_fresh_calls<=96
    manifest=json.loads((OUT/'launch_manifest.json').read_text())
    pending,sources,blocked=pending_and_sources(manifest)
    print('Eligible unresolved tasks:',pending,'blocked checkpoints:',sorted(blocked),flush=True)
    if not args.launch: return
    round_index=1+max([job.get('round',0) for job in manifest['jobs']]+[0])
    launched=0
    for account,credentials in k.accounts().items():
        if not pending or launched>=args.max_jobs: break
        if args.accounts and account not in args.accounts: continue
        if account in manifest.get('scheduling_disabled_accounts', []):
            print('Skipping reviewed unavailable account', account, flush=True)
            continue
        output=k.kaggle(['quota','--format','json'],credentials,timeout=90)
        quotas=json.loads(output[output.index('['):])
        available=float(next(q['remaining'] for q in quotas if q['resource']=='GPU').removesuffix('h'))
        budgets=session_budgets(available,args.worker_budget_hours,args.sessions_per_account)
        for slot,budget in enumerate(budgets,1):
            if not pending or launched>=args.max_jobs: break
            launch_session(manifest,pending,sources,account,credentials,round_index,slot,budget,available,args)
            del pending[:args.tasks_per_job]
            launched+=1
    print('Launched',launched,'bounded jobs; unassigned eligible tasks:',pending,flush=True)


def launch_session(manifest,pending,sources,account,credentials,round_index,slot,budget,available,args):
    tasks=pending[:args.tasks_per_job]
    tag=f'cbq-resume-r{round_index}a{account}s{slot}-oct7'
    task_file=OUT/(tag+'.jsonl')
    task_file.write_text(''.join(json.dumps({'task_id':task})+'\n' for task in tasks))
    runtime=OUT/(tag+'_runtime.zip')
    runtime_for(tasks,sources,runtime)
    subprocess.run([sys.executable,str(ROOT/'prepare_confibench_qwen.py'),'0','1',
                    '--tasks-file',str(task_file),'--tag',tag,'--workers',str(len(tasks)),
                    '--budget-hours',str(budget),'--max-fresh-calls',str(args.max_fresh_calls),
                    '--runtime-prev',str(runtime),'--prebuilt-server'],check=True)
    bundle=ROOT/f'kaggle_upload_{tag}'
    metadata=json.loads((bundle/'kernel/kernel-metadata.json').read_text())
    approval={'kernel_id':metadata['id'],'account':account,
              'notebook_sha256':sha(bundle/'kernel'/metadata['code_file']),
              'dataset_sha256':sha(bundle/'dataset_publish'/f'{tag}.zip'),
              'reason':'User-authorized completion; both resume gates passed; disjoint audited checkpoints.'}
    approval_file=OLD/'GPU_APPROVED_BUNDLES.json'
    approvals=json.loads(approval_file.read_text())
    approvals.append(approval)
    atomic_json(approval_file,approvals)
    job=dict(approval,tag=tag,bundle=str(bundle),round=round_index,tasks=tasks,
             kind='gpu_wave',submission='staged',runtime_source=str(runtime),
             max_fresh_calls=args.max_fresh_calls,worker_budget_hours=budget,
             max_workers=len(tasks),session_slot=slot,
             packed_diagnostics=True,
             startup_health_probe_calls=1,
             kernel_id=f"{credentials['user']}/{metadata['id'].split('/',1)[1]}",
             available_gpu_hours_at_submission=available)
    manifest['jobs'].append(job)
    atomic_json(OUT/'launch_manifest.json',manifest)
    try:
        k.push(bundle,account)
    except (Exception,SystemExit) as error:
        job.update(submission='failed',submission_error=type(error).__name__)
        atomic_json(OUT/'launch_manifest.json',manifest)
        raise
    job.update(submission='accepted',submitted_at=now())
    atomic_json(OUT/'launch_manifest.json',manifest)
    print('Accepted',job['kernel_id'],'tasks',tasks,'budget',budget,'hours',flush=True)


if __name__=='__main__':
    main()
