"""Offline audit and worker-queue regression tests; no model or network access."""
import json
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
import zipfile
from unittest.mock import patch

from confibench_resume import digest
from monitor_resume_20261005 import audit_runtime, cpu_frontiers, latest_cpu_gate, unpack_diagnostics
from prepare_confibench_qwen import RUN
from launch_resumed_finish_wave import pending_and_sources, session_budgets


def write_zip(path, records):
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        for name,value in records.items():
            z.writestr(name,json.dumps(value,sort_keys=True))


class ResumeCollectionTests(unittest.TestCase):
    def test_packed_diagnostics_restore_logs_and_reject_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            path=root/'logs.zip'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('cbq_w0.log','BudgetStop: Fresh-call budget exhausted')
            unpack_diagnostics(path,root)
            self.assertIn('BudgetStop',(root/'cbq_w0.log').read_text())
            with zipfile.ZipFile(path,'w') as z: z.writestr('../outside.log','unsafe')
            with self.assertRaises(ValueError): unpack_diagnostics(path,root)

    def test_parallel_sessions_reserve_quota_and_reject_invalid_readings(self):
        self.assertEqual(session_budgets(30,4,2),[4,4])
        self.assertEqual(session_budgets(3.77,2,2),[2])
        self.assertEqual(session_budgets(1.16,4,2),[])
        budgets=session_budgets(6.5,4,2)
        self.assertAlmostEqual(sum(budgets)+.75*len(budgets),6.5)
        for available in (float('nan'),float('inf'),-1):
            with self.assertRaises(ValueError): session_budgets(available,4,2)

    def test_cpu_gate_becomes_stale_after_gpu_progress(self):
        cpu={'tasks':['a','b'],'collected_at':'now','require_cpu_frontier':True,
             'cpu_frontiers':{'a':{'status':'needs_model'},'b':{'status':'needs_model'}}}
        manifest={'jobs':[cpu]}
        self.assertTrue(latest_cpu_gate(manifest,{'a','b'}))
        manifest['jobs'].append({'tasks':['a'],'collected_at':'later','kind':'gpu_wave'})
        self.assertFalse(latest_cpu_gate(manifest,{'a','b'}))
        self.assertTrue(latest_cpu_gate(manifest,{'b'}))
        manifest['jobs'].append(dict(cpu, tasks=['a'],collected_at='latest'))
        self.assertTrue(latest_cpu_gate(manifest,{'a','b'}))
        manifest['jobs'][-1]['audit_error']='corrupt'
        self.assertFalse(latest_cpu_gate(manifest,{'a','b'}))
    def test_gpu_gate_requires_latest_audited_cpu_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_zip(root / 'canonical_latest.zip', {})
            runtime = root / 'runtime.zip'
            write_zip(runtime, {'probe/contract.json': {'task_id': 'probe'}})
            job = {'tag': 'cpu', 'kind': 'cpu_replay', 'submission': 'accepted',
                   'collected_at': 'now', 'tasks': ['probe'], 'runtime_archive': str(runtime),
                   'require_cpu_frontier': True,
                   'runtime_sha256': hashlib.sha256(runtime.read_bytes()).hexdigest(),
                   'cpu_frontiers': {'probe': {'status': 'needs_model'}}}
            manifest = {'expected': ['probe'], 'jobs': [job],
                        'cpu_preflight_finished': True, 'gpu_resume_gate_passed': True,
                        'require_current_cpu_frontier': True}
            with patch('launch_resumed_finish_wave.OUT', root):
                self.assertEqual(pending_and_sources(manifest)[0], ['probe'])
                job['runtime_sha256'] = 'changed'
                with self.assertRaises(SystemExit): pending_and_sources(manifest)
                job['runtime_sha256'] = hashlib.sha256(runtime.read_bytes()).hexdigest()
                job['cpu_frontiers']['probe']['status'] = 'crashed'
                with self.assertRaises(SystemExit): pending_and_sources(manifest)
                job['cpu_frontiers']['probe']['status'] = 'needs_model'
                manifest['jobs'].append(dict(job, kind='gpu_wave', require_cpu_frontier=False))
                with self.assertRaises(SystemExit): pending_and_sources(manifest)
                manifest['cpu_preflight_finished']=False
                self.assertEqual(pending_and_sources(manifest,cpu_replay=True)[0],['probe'])

    def test_cpu_gate_rejects_crash_and_corrupt_or_stale_frontier(self):
        contract = {'task_id': 'probe', 'profile': 'frozen'}
        request = {'input': 'next prompt'}
        frontier = {'contract': contract, 'reason': 'fresh_call_budget',
                    'scope': '3:TBcheck:', 'number': 1, 'request': request,
                    'request_sha256': digest(request), 'max_fresh': 0,
                    'fresh_this_session': 0, 'replayed_this_session': 5}
        records = {'probe/contract.json': json.dumps(contract),
                   'probe/next_request.json': json.dumps(frontier)}
        completion = {'worker_exit_codes': [1], 'checkpointed_tasks': []}
        logs = ['BudgetStop: Fresh-call budget exhausted at 3:TBcheck: #1']
        job = {'tasks': ['probe']}
        self.assertEqual(cpu_frontiers(job, records, completion, logs)['probe']['status'], 'needs_model')
        with self.assertRaises(ValueError): cpu_frontiers(job, records, completion, ['Unexpected crash'])
        completion['worker_exit_codes'] = [-15]
        with self.assertRaises(ValueError): cpu_frontiers(job, records, completion, logs)
        completion['worker_exit_codes'] = [1]
        frontier['request_sha256'] = 'tampered'
        records['probe/next_request.json'] = json.dumps(frontier)
        with self.assertRaises(ValueError): cpu_frontiers(job, records, completion, logs)
        frontier['request_sha256'] = digest(request)
        records['probe/next_request.json'] = json.dumps(frontier)
        records[f"probe/calls/{digest(frontier['scope'])}/000001.json"] = 'committed'
        with self.assertRaises(ValueError): cpu_frontiers(job, records, completion, logs)
        records.pop('probe/next_request.json')
        with self.assertRaises(ValueError): cpu_frontiers(job, records, completion, logs)

    def test_integrity_and_fresh_response_accounting(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            contract={'task_id':'probe','profile':'frozen'}
            old={'probe/contract.json':contract}
            write_zip(root/'seed.zip',old)
            scope='9:TBgen:stage:stage_4'
            output=['answer',{'usage':{'completion_tokens':10},'time':1}]
            record={'scope':scope,'number':0,'request_sha256':digest({'input':'prompt'}),
                    'output':output,'output_sha256':digest(output)}
            result=dict(old)
            result[f'probe/calls/{digest(scope)}/000000.json']=record
            payload={'next_iteration':10}
            result['probe/iteration.json']={'contract':contract,'payload':payload,
                                          'payload_sha256':digest(payload)}
            write_zip(root/'result.zip',result)
            _,fresh=audit_runtime(root/'seed.zip',root/'result.zip')
            self.assertEqual(len(fresh),1)
            result['probe/contract.json']={'task_id':'changed'}
            write_zip(root/'result.zip',result)
            with self.assertRaises(ValueError): audit_runtime(root/'seed.zip',root/'result.zip')
            result['probe/contract.json']=contract
            record['output'][0]='tampered'
            write_zip(root/'result.zip',result)
            with self.assertRaises(ValueError): audit_runtime(root/'seed.zip',root/'result.zip')

    def test_failed_worker_does_not_skip_other_tasks(self):
        with tempfile.TemporaryDirectory() as temp:
            work=Path(temp)
            cb=work/'ConfiBench'
            (cb/'config/configs').mkdir(parents=True)
            (cb/'saves').mkdir()
            src=work/'source'
            src.mkdir()
            tasks=[f'task{i}' for i in range(17)]
            (src/'shard_tasks.json').write_text(''.join(json.dumps({'task_id':t})+'\n' for t in tasks))
            started=[]

            class FailedWorker:
                def __init__(self,args,**kwargs):
                    cfg=cb/'config/configs'/f'{args[-1]}.yaml'
                    started.extend(json.loads(cfg.read_text())['only'])
                    kwargs['stdout'].close()
                def poll(self): return 1
                def wait(self,timeout=None): return 1

            env={'SRC':src,'WORK':work,'CB':cb,'json':json,'zipfile':zipfile,'os':os,'sys':sys,
                 'shutil':shutil,'NP':4,'MAX_WORKERS':4,'BUDGET_HOURS':.25,
                 'time':SimpleNamespace(time=lambda:1000,sleep=lambda _:None),
                 't0':1000,'subprocess':SimpleNamespace(Popen=FailedWorker,STDOUT=-2),
                 'CONFIG':'{"only": %(only)s}'}
            exec(RUN % {'shard':0,'model':'qwen3.5-27b'},env)
            self.assertEqual(started,tasks)
            completion=json.loads((work/'cbq_completion.json').read_text())
            self.assertEqual(len(completion['worker_exit_codes']),17)
            self.assertEqual(completion['checkpointed_tasks'],[])


if __name__=='__main__':
    unittest.main()
