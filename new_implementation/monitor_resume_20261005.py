"""Read status and collect/audit the bounded resume jobs. Never launches GPU jobs."""
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
import shutil
import sys
import subprocess
import zipfile
from collections import Counter

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'confibench_finish_20261005'
OLD = ROOT / 'confibench_finish_20261003'
sys.path.insert(0, str(ROOT / 'dirtb'))
import kaggle_rotate as k
from confibench_resume import atomic_json, digest
from verify_resume_completion import completion_audit


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archive_records(path):
    with zipfile.ZipFile(path) as z:
        if z.testzip() is not None:
            raise ValueError(f'Corrupt archive: {path.name}')
        return {name: z.read(name) for name in z.namelist() if not name.endswith('/')}


def initialize():
    OUT.mkdir(exist_ok=True)
    manifest_file = OUT / 'launch_manifest.json'
    if manifest_file.exists():
        manifest=json.loads(manifest_file.read_text())
        staged=json.loads((OUT/'cpu_replay_manifest.json').read_text())
        if (staged['submission'] == 'accepted'
                and staged['tag'] not in {job['tag'] for job in manifest['jobs']}):
            staged.update(kind=staged.get('kind','cpu_replay'))
            manifest['jobs'].append(staged)
            atomic_json(manifest_file,manifest)
        pilot=json.loads((OLD/'gpu_pilot_manifest.json').read_text())
        if pilot['tag'] not in {job['tag'] for job in manifest['jobs']}:
            pilot.update(kind='gpu_pilot',submission='accepted')
            manifest['jobs'].append(pilot)
            atomic_json(manifest_file,manifest)
        return manifest
    pilot = json.loads((OLD / 'gpu_pilot_manifest.json').read_text())
    pilot.update(kind='gpu_pilot', submission='accepted')
    replay = json.loads((OUT / 'cpu_replay_manifest.json').read_text())
    replay.update(kind='cpu_replay', submission='accepted',
                  runtime_source=str(OUT / 'cpu_replay_seed.zip'))
    shutil.copy2(OLD / 'canonical_latest.zip', OUT / 'canonical_latest.zip')
    manifest = {'expected': json.loads((OLD / 'launch_manifest.json').read_text())['expected'],
                'jobs': [pilot, replay], 'created_at': now(),
                'gpu_resume_gate_passed': False, 'automatic_gpu_launches': False}
    atomic_json(manifest_file, manifest)
    return manifest


def audit_runtime(source_path, result_path):
    seed = archive_records(Path(source_path))
    result = archive_records(result_path)
    for name, payload in seed.items():
        if ('/calls/' in name or PurePosixPath(name).name in
                ('contract.json', 'legacy_calls.json', 'legacy_population.json')):
            if result.get(name) != payload:
                raise ValueError(f'Saved response or contract changed: {name}')
    fresh_records = []
    for name, payload in result.items():
        if '/calls/' not in name:
            continue
        record = json.loads(payload)
        if record['output_sha256'] != digest(record['output']):
            raise ValueError(f'Response checksum mismatch: {name}')
        parts = PurePosixPath(name).parts
        contract = json.loads(result[str(PurePosixPath(parts[0]) / 'contract.json')])
        if contract['task_id'] != parts[0]:
            raise ValueError('Response journal task contract mismatch: ' + name)
        if parts[-2] != digest(record['scope']) or parts[-1] != f"{record['number']:06d}.json":
            raise ValueError(f'Invalid response journal path: {name}')
        if name not in seed and not record['output'][1].get('usage_unavailable', False):
            fresh_records.append(dict(record, task_id=parts[0]))
    for name, payload in result.items():
        if name.endswith('/execution_layout.json'):
            layout=json.loads(payload)
            contract=json.loads(result[str(PurePosixPath(name).parent/'contract.json')])
            if layout['contract']!=contract or layout['payload_sha256']!=digest(layout['directories']):
                raise ValueError('Execution-layout integrity failure: '+name)
            if name in seed:
                old_layout=json.loads(seed[name])['directories']
                if any(layout['directories'].get(key)!=path for key,path in old_layout.items()):
                    raise ValueError('Saved execution directory changed: '+name)
        if name.endswith('/compiler_orders.json'):
            orders=json.loads(payload)
            contract=json.loads(result[str(PurePosixPath(name).parent/'contract.json')])
            if orders['contract']!=contract or orders['payload_sha256']!=digest(orders['orders']):
                raise ValueError('Compiler-order integrity failure: '+name)
            if name in seed:
                previous=json.loads(seed[name])['orders']
                if any(orders['orders'].get(key)!=files for key,files in previous.items()):
                    raise ValueError('Saved compiler order changed: '+name)
        if name.endswith('/iteration.json'):
            state = json.loads(payload)
            if state['payload_sha256'] != digest(state['payload']):
                raise ValueError(f'Iteration checksum mismatch: {name}')
            contract = json.loads(result[str(PurePosixPath(name).parent / 'contract.json')])
            if state['contract'] != contract:
                raise ValueError(f'Iteration contract mismatch: {name}')
    return result, fresh_records


def cpu_frontiers(job, result, completion, logs):
    """Require a verified cache miss or final record, not merely a worker exit."""
    ready = {}
    completed = set(completion['checkpointed_tasks'])
    for index, task in enumerate(job['tasks']):
        if task in completed:
            if completion['worker_exit_codes'][index] != 0:
                raise ValueError('CPU worker failed after producing a task record: ' + task)
            ready[task] = {'status': 'task_recorded'}
            continue
        name = task + '/next_request.json'
        if name not in result:
            raise ValueError('CPU replay did not reach a verified cache miss: ' + task)
        frontier = json.loads(result[name])
        contract = json.loads(result[task + '/contract.json'])
        if (frontier['contract'] != contract or frontier['reason'] != 'fresh_call_budget'
                or frontier['max_fresh'] != 0 or frontier['fresh_this_session'] != 0
                or frontier['request_sha256'] != digest(frontier['request'])
                or completion['worker_exit_codes'][index] != 1
                or 'BudgetStop: Fresh-call budget exhausted' not in logs[index]
                or 'ResumeMismatch' in logs[index]):
            raise ValueError('Invalid CPU replay frontier: ' + task)
        call_path = f"{task}/calls/{digest(frontier['scope'])}/{frontier['number']:06d}.json"
        if call_path in result:
            raise ValueError('CPU replay requests an already committed response: ' + task)
        ready[task] = {'status': 'needs_model', 'scope': frontier['scope'],
                       'number': frontier['number'],
                       'request_sha256': frontier['request_sha256'],
                       'replayed_this_session': frontier['replayed_this_session']}
    return ready


def latest_cpu_gate(manifest, unfinished):
    latest={}
    for job in manifest['jobs']:
        if job.get('collected_at') and not job.get('audit_error'):
            for task in job['tasks']: latest[task]=job
    return all(latest.get(task,{}).get('require_cpu_frontier')
               and latest[task].get('cpu_frontiers',{}).get(task,{}).get('status')=='needs_model'
               for task in unfinished)


def unpack_diagnostics(path, dest):
    allowed=re.compile(r'cbq_w\d+\.log|setup\.log|build\.log|llama_server\.log|health_probe\.log|engine_provenance\.json|gpu_server_proof\.json')
    with zipfile.ZipFile(path) as z:
        names=z.namelist()
        if z.testzip() is not None or len(names)!=len(set(names)):
            raise ValueError('Corrupt or duplicate diagnostic archive members')
        if any(not allowed.fullmatch(name) for name in names):
            raise ValueError('Unsafe diagnostic archive filename')
        for name in names:
            target=dest/name
            if not target.exists() or name.startswith('cbq_w'):
                target.write_bytes(z.read(name))


def collect(job, account):
    dest = ROOT / 'kaggle_runs' / (job['tag'] + '_collected')
    dest.mkdir(exist_ok=True)
    # Kaggle treats --file-pattern as a regex, not a shell glob. Match root
    # archives/logs only; downloading every individual journal is unnecessary.
    patterns = [r'^(?:cbq_(?:completion\.json|saves\.zip|runtime\.zip|partial\.zip|w\d+\.log)|setup\.log|build\.log|llama_server\.log|health_probe\.log|engine_provenance\.json|gpu_server_proof\.json)$']
    if job.get('packed_diagnostics'):
        patterns=[patterns[0].replace(r'w\d+\.log',r'logs\.zip')]
    for pattern in patterns:
        output = k.kaggle(['kernels','output',job['kernel_id'],'-p',str(dest),
                           '--file-pattern',pattern,'--page-size','200'], account, timeout=300)
        if any(marker in output for marker in ('NameResolutionError', 'ConnectionError',
                                               'ReadTimeout', 'ConnectTimeout')):
            raise ConnectionError('Kaggle output download temporarily unavailable')
        print(output[-400:], flush=True)
    if job.get('packed_diagnostics'):
        logs_zip=dest/'cbq_logs.zip'
        if logs_zip.exists(): unpack_diagnostics(logs_zip,dest)
    completion_file = dest / 'cbq_completion.json'
    if not completion_file.exists():
        raise ValueError('No durable completion manifest; inspect downloaded startup logs')
    completion = json.loads(completion_file.read_text())
    if set(completion['expected_tasks']) != set(job['tasks']):
        raise ValueError('Output task assignment does not match launch manifest')
    result, fresh_records = audit_runtime(job['runtime_source'], dest / 'cbq_runtime.zip')
    if job['kind'].startswith('gpu_'):
        fresh_by_task = Counter(record['task_id'] for record in fresh_records)
        if set(fresh_by_task) - set(job['tasks']):
            raise ValueError('Fresh response belongs to an unassigned task')
        if any(count > job['max_fresh_calls'] for count in fresh_by_task.values()):
            raise ValueError('GPU job exceeded its per-task fresh-response cap')
    progress = {PurePosixPath(name).parent.name: json.loads(payload)
                for name, payload in result.items() if name.endswith('/progress.json')}
    if job['kind'].startswith('cpu_'):
        if fresh_records or any(p['fresh_this_session'] for p in progress.values()):
            raise ValueError('CPU preflight unexpectedly generated fresh responses')
        if len(completion['worker_exit_codes']) != len(job['tasks']):
            raise ValueError('CPU preflight did not attempt every assigned task')
    blocked = []
    logs = []
    for index, task in enumerate(job['tasks']):
        log_file = dest / f'cbq_w{index}.log'
        log = log_file.read_text(encoding='utf-8',errors='replace') if log_file.exists() else ''
        logs.append(log)
        if 'ResumeMismatch' in log:
            blocked.append(task)
        if job['kind'] == 'gpu_pilot' and 'RESUME task=ece241_2014_q4 next_iteration=9' not in log:
            raise ValueError('GPU pilot did not restore the verified iteration checkpoint')
    if job['kind'] == 'gpu_pilot':
        if not fresh_records or len(fresh_records) > job['max_fresh_calls']:
            raise ValueError('GPU pilot produced no durable fresh response or exceeded its cap')
        if blocked:
            raise ValueError('GPU pilot encountered incompatible recovery state')
    if job.get('require_cpu_frontier'):
        job['cpu_frontiers'] = cpu_frontiers(job, result, completion, logs)
    records = {}
    for name, payload in archive_records(dest / 'cbq_saves.zip').items():
        if PurePosixPath(name).name != 'data.json':
            continue
        task = PurePosixPath(name).parent.name
        record = json.loads(payload)
        if task not in job['tasks'] or record.get('task_id') != task:
            raise ValueError('Final record task identity mismatch')
        records.setdefault(task, payload)
    if set(records) != set(completion['checkpointed_tasks']):
        raise ValueError('Completion manifest does not match actual task records')
    current = {PurePosixPath(name).parent.name: payload for name, payload in
               archive_records(OUT / 'canonical_latest.zip').items()
               if PurePosixPath(name).name == 'data.json'}
    added = []
    for task, payload in records.items():
        if task not in current:
            current[task] = payload
            added.append(task)
    temp = OUT / 'canonical_latest.tmp.zip'
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
        for task, payload in sorted(current.items()):
            z.writestr(f'saves/ConfiBench_qwen/merged/{task}/data.json',payload)
    temp.replace(OUT / 'canonical_latest.zip')
    job.update(collected_at=now(), output_dir=str(dest), checkpointed_tasks=sorted(records),
               added_task_records=added, blocked_tasks=blocked,
               durable_fresh_responses=len(fresh_records),
               runtime_archive=str(dest/'cbq_runtime.zip'),
               runtime_sha256=sha(dest/'cbq_runtime.zip'),
               worker_exit_codes=completion['worker_exit_codes'],
               runtime_progress=completion.get('runtime_progress',{}))
    if fresh_records:
        times = [r['output'][1].get('time',0) for r in fresh_records]
        job['fresh_response_seconds'] = times
        job['fresh_completion_tokens'] = sum(r['output'][1]['usage']['completion_tokens'] for r in fresh_records)
    print(job['tag'], 'audited;', len(records), 'task records;', len(fresh_records), 'durable fresh responses', flush=True)


def main():
    if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    manifest = initialize()
    accounts = k.accounts()
    for job in manifest['jobs']:
        if job.get('submission')!='accepted' or job.get('collected_at') or job.get('audit_error'):
            continue
        try:
            status = k.kaggle(['kernels','status',job['kernel_id']],accounts[job['account']],timeout=90).strip()
            if 'KernelWorkerStatus.' not in status:
                raise ConnectionError('Kaggle status unavailable; no verified status returned')
            job.update(status=status,status_checked_at=now())
            job.pop('status_error', None)
            print(status,flush=True)
            if any(word in status for word in ('COMPLETE','ERROR','CANCEL_ACKNOWLEDGED')):
                try:
                    collect(job,accounts[job['account']])
                except (ValueError,KeyError,FileNotFoundError,zipfile.BadZipFile) as error:
                    job['audit_error'] = str(error)
                    print('AUDIT STOP:',str(error),flush=True)
        except (subprocess.TimeoutExpired, ConnectionError) as error:
            job.update(status_error=type(error).__name__, last_network_error_at=now())
            print('RETRY NEXT POLL:', job['kernel_id'], type(error).__name__, flush=True)
        finally:
            atomic_json(OUT/'launch_manifest.json',manifest)
    pilot = [job for job in manifest['jobs'] if job['kind']=='gpu_pilot'][-1]
    replay = [job for job in manifest['jobs'] if job['kind']=='cpu_replay'][-1]
    manifest['gpu_resume_gate_passed'] = bool(pilot.get('collected_at') and not pilot.get('audit_error'))
    manifest['cpu_preflight_finished'] = bool(replay.get('collected_at') and not replay.get('audit_error'))
    if manifest.get('require_current_cpu_frontier'):
        recorded={PurePosixPath(name).parent.name for name in archive_records(OUT/'canonical_latest.zip')
                  if PurePosixPath(name).name=='data.json'}
        unfinished=set(manifest['expected'])-recorded
        manifest['cpu_preflight_finished']=latest_cpu_gate(manifest,unfinished)
        manifest['latest_cpu_preflight_status']='audited' if manifest['cpu_preflight_finished'] else 'needed'
    atomic_json(OUT/'launch_manifest.json',manifest)
    audit = completion_audit(OUT/'canonical_latest.zip', OLD/'canonical_latest.zip', manifest['expected'])
    audit.update(checked_at=now(),canonical_sha256=sha(OUT/'canonical_latest.zip'))
    atomic_json(OUT/'completion_audit.json',audit)
    state = {'checked_at':now(),'checkpointed':audit['recorded'],'expected':audit['expected'],
             'remaining':audit['missing'],
             'gpu_resume_gate_passed':manifest['gpu_resume_gate_passed'],
             'cpu_preflight_finished':manifest['cpu_preflight_finished'],
             'active_jobs':[job['kernel_id'] for job in manifest['jobs']
                            if job.get('submission')=='accepted' and not job.get('collected_at') and not job.get('audit_error')],
             'scheduling_disabled_accounts':manifest.get('scheduling_disabled_accounts',[]),
             'automatic_gpu_launches':manifest.get('automatic_gpu_launches',False)}
    atomic_json(OUT/'monitor_state.json',state)
    print(json.dumps(state,indent=2),flush=True)


if __name__=='__main__':
    main()
