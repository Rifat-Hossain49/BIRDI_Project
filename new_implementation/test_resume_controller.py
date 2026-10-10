"""Offline scheduler safety tests; no credentials, network or GPUs."""
import unittest
from datetime import datetime, timedelta, timezone
import hashlib
import json
import zipfile
from pathlib import Path
import tempfile
from unittest.mock import patch

from continue_resumed_finish import (decision, restored_controller, quarantined_missing_output,
                                    reviewed_cpu_path_recovery)
from confibench_resume import digest


class ResumeControllerTests(unittest.TestCase):
    def test_relative_evidence_uses_workspace_not_current_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            implementation = workspace / 'new_implementation'
            implementation.mkdir()
            log = implementation / 'kernel.log'
            log.write_bytes(b'[]')
            runtime = implementation / 'runtime.zip'
            runtime.write_bytes(b'saved-runtime')
            job = {'account': 3, 'runtime_source': 'new_implementation/runtime.zip',
                   'status': 'KernelWorkerStatus.ERROR',
                   'audit_error': 'No durable completion manifest; inspect downloaded startup logs',
                   'missing_output_review': {'kind': 'missing_artifacts_quarantined_account',
                       'kernel_log': 'new_implementation/kernel.log',
                       'kernel_log_sha256': hashlib.sha256(log.read_bytes()).hexdigest(),
                       'runtime_sha256': hashlib.sha256(runtime.read_bytes()).hexdigest()}}
            with patch('continue_resumed_finish.ROOT', implementation):
                self.assertTrue(quarantined_missing_output(job, {'scheduling_disabled_accounts': [3]}))
                log.write_bytes(b'["unexpected execution"]')
                self.assertFalse(quarantined_missing_output(job, {'scheduling_disabled_accounts': [3]}))

    def test_cpu_recovery_requires_path_only_difference_and_reverified_responses(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            contract={'task_id':'probe','profile':'frozen'}
            base='/kaggle/working/ConfiBench/saves/ConfiBench_qwen/'
            before={'model':'frozen','messages':[{'role':'user','content':
                    'File "'+base+'old_session/probe/debug/code.py", line 3\nIndentationError'}]}
            actual={'model':'frozen','messages':[{'role':'user','content':
                    'File "'+base+'new_session/probe/debug/code.py", line 3\nIndentationError'}]}
            scope='2:TBsim:debug:debug_2'
            output=['answer',{'messages':before['messages']+[{'role':'assistant','content':'answer'}]}]
            saved={'scope':scope,'number':0,'request_sha256':digest(before),
                   'output':output,'output_sha256':digest(output)}
            seed={'probe/contract.json':contract,f'probe/calls/{digest(scope)}/000000.json':saved}
            member=f'probe/replay_conflicts/{digest(scope)}/conflict.json'
            conflict={'scope':scope,'number':0,'request':actual,'request_sha256':digest(actual)}
            bad=dict(seed,**{member:conflict})
            def write(path,records):
                with zipfile.ZipFile(path,'w') as z:
                    for name,value in records.items(): z.writestr(name,json.dumps(value,sort_keys=True))
            write(root/'seed.zip',seed)
            write(root/'bad.zip',bad)
            write(root/'latest.zip',bad)
            old={'tag':'old','kind':'cpu_replay','tasks':['probe'],'runtime_source':str(root/'seed.zip'),
                 'audit_error':'CPU replay did not reach a verified cache miss: probe',
                 'cpu_path_recovery_review':{'kind':'path_restored_and_cpu_reverified','task_id':'probe',
                    'recovery_tag':'latest','runtime_archive':str(root/'bad.zip'),
                    'runtime_sha256':hashlib.sha256((root/'bad.zip').read_bytes()).hexdigest(),
                    'conflict_member':member}}
            latest={'tag':'latest','kind':'cpu_replay','tasks':['probe'],'require_cpu_frontier':True,
                    'collected_at':'now','cpu_frontiers':{'probe':{'status':'needs_model'}},
                    'runtime_archive':str(root/'latest.zip'),
                    'runtime_sha256':hashlib.sha256((root/'latest.zip').read_bytes()).hexdigest()}
            jobs=[old,latest]
            self.assertTrue(reviewed_cpu_path_recovery(old,jobs))
            latest['cpu_frontiers']={}
            self.assertFalse(reviewed_cpu_path_recovery(old,jobs))
            latest['cpu_frontiers']={'probe':{'status':'needs_model'}}
            latest['audit_error']='corrupt'
            self.assertFalse(reviewed_cpu_path_recovery(old,jobs))
            latest.pop('audit_error')
            actual['messages'][0]['content']+='\nDifferent program error'
            conflict['request_sha256']=digest(actual)
            write(root/'bad.zip',bad)
            old['cpu_path_recovery_review']['runtime_sha256']=hashlib.sha256((root/'bad.zip').read_bytes()).hexdigest()
            self.assertFalse(reviewed_cpu_path_recovery(old,jobs))

    def test_reviewed_retry_does_not_ignore_integrity_or_second_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / 'kernel.log'
            log.write_bytes(b'[]')
            source = root / 'runtime.zip'
            source.write_bytes(b'identical-runtime')
            manifest = self.manifest()
            original = {'kind': 'gpu_wave', 'tag': 'startup-failed', 'tasks': ['b'],
                        'account': 3, 'submission': 'accepted', 'max_fresh_calls': 16,
                        'worker_budget_hours': 2, 'runtime_source': str(source),
                        'status': 'KernelWorkerStatus.ERROR',
                        'audit_error': 'No durable completion manifest; inspect downloaded startup logs',
                        'startup_retry_review': {'kind': 'missing_artifacts_single_retry',
                            'retry_tag': 'retry', 'kernel_log': str(log),
                            'kernel_log_sha256': hashlib.sha256(log.read_bytes()).hexdigest(),
                            'runtime_sha256': hashlib.sha256(source.read_bytes()).hexdigest()}}
            retry = {'kind': 'gpu_wave', 'tag': 'retry', 'retry_of': original['tag'],
                     'tasks': ['b'], 'account': 3, 'submission': 'accepted',
                     'max_fresh_calls': 16, 'worker_budget_hours': 2, 'runtime_source': str(source)}
            manifest['jobs'].extend([original, retry])
            state = self.snapshot()
            state['active_jobs'] = ['retry']
            self.assertEqual(decision(manifest, state, 1, 4)[0], 'wait')
            retry['max_fresh_calls'] = 17
            self.assertEqual(decision(manifest, state, 1, 4)[0], 'stop')
            retry['max_fresh_calls'] = 16
            retry['audit_error'] = 'Second failure'
            self.assertEqual(decision(manifest, state, 1, 4)[0], 'stop')
            retry.pop('audit_error')
            log.write_bytes(b'["unexpected execution"]')
            self.assertEqual(decision(manifest, state, 1, 4)[0], 'stop')
            log.write_bytes(b'[]')
            original['audit_error'] = 'Checksum mismatch'
            self.assertEqual(decision(manifest, state, 1, 4)[0], 'stop')

    def test_quarantine_only_allows_reviewed_missing_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / 'kernel.log'
            log.write_bytes(b'[]')
            runtime = root / 'runtime.zip'
            runtime.write_bytes(b'saved-runtime')
            job = {'account': 3, 'runtime_source': str(runtime),
                   'status': 'KernelWorkerStatus.ERROR',
                   'audit_error': 'No durable completion manifest; inspect downloaded startup logs',
                   'missing_output_review': {'kind': 'missing_artifacts_quarantined_account',
                       'kernel_log': str(log), 'kernel_log_sha256': hashlib.sha256(log.read_bytes()).hexdigest(),
                       'runtime_sha256': hashlib.sha256(runtime.read_bytes()).hexdigest()}}
            self.assertFalse(quarantined_missing_output(job, {}))
            manifest = {'scheduling_disabled_accounts': [3]}
            self.assertTrue(quarantined_missing_output(job, manifest))
            job['audit_error'] = 'Response checksum mismatch'
            self.assertFalse(quarantined_missing_output(job, manifest))
            job['audit_error'] = 'No durable completion manifest; inspect downloaded startup logs'
            (root / 'cbq_runtime.zip').write_bytes(b'actual-execution-artifact')
            self.assertFalse(quarantined_missing_output(job, manifest))

    def test_restart_preserves_budget_and_records_error_history(self):
        previous = {'status': 'error', 'pid': 123, 'waves_launched': 1,
                    'max_waves': 6, 'max_hours': 18, 'started_at': 'original',
                    'deadline': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                    'reason': 'network timeout', 'ended_at': 'then', 'error_type': 'CalledProcessError'}
        restored = restored_controller(previous, 456)
        for key in ('waves_launched', 'max_waves', 'max_hours', 'started_at', 'deadline'):
            self.assertEqual(restored[key], previous[key])
        self.assertEqual(restored['status'], 'running')
        self.assertEqual(restored['restarts'][0]['reason'], 'network timeout')
        self.assertNotIn('error_type', restored)
        previous['status'] = 'running'
        with self.assertRaises(ValueError): restored_controller(previous, 456)
        previous['status'] = 'error'
        previous['deadline'] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        with self.assertRaises(ValueError): restored_controller(previous, 456)

    def snapshot(self):
        return {'remaining': ['a', 'b'], 'active_jobs': [],
                'gpu_resume_gate_passed': True, 'cpu_preflight_finished': True}

    def manifest(self):
        return {'jobs': [
            {'kind': 'gpu_pilot', 'tag': 'failed-old', 'submission': 'accepted',
             'tasks': ['a'], 'audit_error': 'old startup'},
            {'kind': 'cpu_replay', 'tag': 'cpu-old', 'submission': 'accepted',
             'tasks': ['a', 'b'], 'collected_at': 'old', 'blocked_tasks': ['b']},
            {'kind': 'cpu_replay', 'tag': 'cpu-new', 'submission': 'accepted',
             'tasks': ['a', 'b'], 'collected_at': 'new', 'blocked_tasks': []},
            {'kind': 'gpu_pilot', 'tag': 'pilot-new', 'submission': 'accepted',
             'tasks': ['a'], 'collected_at': 'newest', 'durable_fresh_responses': 2}
        ]}

    def test_superseded_failures_do_not_block_audited_recovery(self):
        self.assertEqual(decision(self.manifest(), self.snapshot(), 0, 6)[0], 'launch')

    def test_new_cpu_replay_needed_before_next_gpu_wave(self):
        manifest=self.manifest()
        manifest['require_current_cpu_frontier']=True
        state=self.snapshot()
        state['cpu_preflight_finished']=False
        self.assertEqual(decision(manifest,state,1,6)[0],'preflight')
        state['active_jobs']=['cpu-running']
        self.assertEqual(decision(manifest,state,1,6)[0],'wait')
        state['active_jobs']=[]
        state['gpu_resume_gate_passed']=False
        self.assertEqual(decision(manifest,state,1,6)[0],'stop')
        state['gpu_resume_gate_passed']=True
        manifest['jobs'].append({'kind':'cpu_replay','tag':'failed','submission':'failed','tasks':['a']})
        self.assertEqual(decision(manifest,state,1,6)[0],'stop')

    def test_active_gate_limit_and_completion(self):
        state = self.snapshot()
        state['active_jobs'] = ['running']
        self.assertEqual(decision(self.manifest(), state, 0, 6)[0], 'wait')
        state['active_jobs'] = []
        state['gpu_resume_gate_passed'] = False
        self.assertEqual(decision(self.manifest(), state, 0, 6)[0], 'stop')
        state['gpu_resume_gate_passed'] = True
        self.assertEqual(decision(self.manifest(), state, 6, 6)[0], 'stop')
        state['remaining'] = []
        self.assertEqual(decision(self.manifest(), state, 6, 6)[0], 'complete')

    def test_latest_conflict_and_no_gpu_progress_stop(self):
        for extra in ({'blocked_tasks': ['b'], 'durable_fresh_responses': 3},
                      {'audit_error': 'checksum'},
                      {'durable_fresh_responses': 0, 'added_task_records': []},
                      {'submission': 'staged'}, {'submission': 'failed'}):
            with self.subTest(extra=extra):
                manifest = self.manifest()
                job = {'kind': 'gpu_wave', 'tag': 'wave', 'tasks': ['b'],
                       'submission': 'accepted', 'collected_at': 'last'}
                job.update(extra)
                manifest['jobs'].append(job)
                self.assertEqual(decision(manifest, self.snapshot(), 0, 6)[0], 'stop')


if __name__ == '__main__':
    unittest.main()
