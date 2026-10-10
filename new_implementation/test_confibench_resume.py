"""CPU-only interruption/replay tests, including the real upstream loop."""
import ast
import copy
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from confibench_resume import (BudgetStop, Journal, ResumeMismatch, begin_task,
                               commit_iteration, encode, decode, digest, compiler_file_order,
                               prepare_iteration_path)
from confibench_resume_patch import patch_task_source
from build_legacy_resume import conversations, build, KWARGS

ROOT = Path(__file__).resolve().parent


class Interrupted(BaseException):
    pass


def actual_core():
    source = (ROOT / 'baselines/ConfiBench/autoline/TB_autoline.py').read_text()
    tree = ast.parse(patch_task_source(source, 'test-profile'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'AutoLine_Task')
    core = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'run_stages_core')
    env = {'commit_iteration': commit_iteration, 'prepare_iteration_path': prepare_iteration_path,
           'logger': SimpleNamespace(info=lambda *a: None,
                                                                           error=lambda *a: None)}
    exec(compile(ast.Module(body=[core], type_ignores=[]), 'upstream-loop', 'exec'), env)
    return env['run_stages_core']


class FakeTask:
    run_stages_core = actual_core()

    def __init__(self, providers, interrupt_at=None, next_action='reboot'):
        self.task_id = 'probe'
        self.prob_data = {'task_id': 'probe', 'description': 'CPU resume test'}
        self.config = SimpleNamespace(autoline=SimpleNamespace(onlyrun=None))
        self.iter_max = 3
        self.autoline_iter_now = 0
        self.next_action = next_action
        self.multibench_en = True
        self.multibench_min_tb = 2
        self.multibench_min_ratio = 0.8
        self.multibench_info = []
        self.sum_valid_ratio = 0
        self.op_record = []
        self.rtlgen_list = None
        self.TBgen = self.TBsim = self.TBcheck = None
        self.providers = providers
        self.interrupt_at = interrupt_at
        self.evaluations = 0
        begin_task(self, 'test-profile')

    def run_TBgen(self, path=None):
        self.TBgen = SimpleNamespace()
        self.stage_now = 'TBgen'
        i = self.autoline_iter_now
        self.TB_code_v = self._resume.call(f'{i}:gen', {'request': i},
            lambda: self.providers.append(('gen', i)) or f'code-{i}')
        self.op_record.append('gen')

    def run_TBsim(self, path=None):
        self.TBsim = SimpleNamespace(pychecker_en=True, sim_pass=True)
        self.op_record.append('sim')

    def run_TBcheck(self, path=None):
        self.TBcheck = SimpleNamespace()
        i = self.autoline_iter_now
        self.TB_code_py = self._resume.call(f'{i}:check', {'request': i},
            lambda: self.providers.append(('check', i)) or f'checker-{i}')
        if i == self.interrupt_at:
            raise Interrupted()
        self.op_record.append('check')

    def update_multibench(self):
        self.multibench_info.append({'iter_id': self.autoline_iter_now+1,
                                    'TB_code_v': self.TB_code_v, 'TB_code_py': self.TB_code_py})
        self.sum_valid_ratio += 0.4

    def run_TBeval(self, path=None):
        self.evaluations += 1
        self.final_codes = copy.deepcopy(self.multibench_info)


class ResumeTests(unittest.TestCase):
    def test_late_new_call_stops_but_cached_responses_still_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            initial=Journal(directory,'probe','profile',{})
            initial.call('cached',{'input':'x'},lambda:['saved',{}])
            with patch.dict(os.environ,{'CBQ_NEW_CALL_DEADLINE':'1'}):
                journal=Journal(directory,'probe','profile',{},max_fresh=48)
            self.assertEqual(journal.call('cached',{'input':'x'},lambda:self.fail('Repeated generation')),['saved',{}])
            with self.assertRaises(BudgetStop):
                journal.call('new',{'input':'next'},lambda:self.fail('Late provider call started'))
            self.assertEqual(journal.fresh,0)
    def test_python_traceback_directory_restored_without_changing_request(self):
        base = '/kaggle/working/ConfiBench/saves/ConfiBench_qwen/'
        historical = base + 'S0W0_20261006_064012/probe'
        request = {'messages': [{'role': 'user', 'content':
                    'File "' + historical + '/3_2_TBsim/debug_1/probe_tb.py", line 383\nIndentationError'}]}
        output = ['answer', {'messages': request['messages'] + [{'role': 'assistant', 'content': 'answer'}]}]
        with tempfile.TemporaryDirectory() as directory:
            first = Journal(directory, 'probe', 'profile', {})
            first.call('2:TBsim:debug:debug_2', request, lambda: output)
            saved = {p: p.read_bytes() for p in (first.root / 'calls').rglob('*.json')}
            resumed = Journal(directory, 'probe', 'profile', {}, max_fresh=0)
            self.assertEqual(resumed.iteration_directory(2, base + 'new_session/probe'), historical)
            self.assertEqual(resumed.call('2:TBsim:debug:debug_2', request, lambda: self.fail('Provider reached')), output)
            for path, payload in saved.items(): self.assertEqual(path.read_bytes(), payload)
            third = Journal(directory, 'probe', 'profile', {}, max_fresh=0)
            self.assertEqual(third.iteration_directory(2, base + 'another_session/probe'), historical)
            with self.assertRaises(ResumeMismatch):
                third.call('2:TBsim:debug:debug_2', {'messages': []}, lambda: self.fail('Hash guard bypassed'))

    def test_conflicting_or_unsafe_python_script_paths_fail_closed(self):
        base = '/kaggle/working/ConfiBench/saves/ConfiBench_qwen/'
        with tempfile.TemporaryDirectory() as directory:
            journal = Journal(directory, 'probe', 'profile', {})
            for index, root in enumerate(('first', 'second')):
                output = ['answer', {'messages': [{'role': 'user', 'content':
                    'File "' + base + root + '/probe/debug/code.py", line 1'},
                    {'role': 'assistant', 'content': 'answer'}]}]
                journal.call(f'2:TBsim:debug:debug_{index}', {'index': index}, lambda: output)
            with self.assertRaises(ResumeMismatch): journal.iteration_directory(2, base + 'current/probe')
            with self.assertRaises(ResumeMismatch): journal.iteration_directory(3, '/tmp/probe')

    def test_relative_upstream_save_root_resolves_before_persisting(self):
        directory_path='/kaggle/working/ConfiBench/saves/ConfiBench_qwen/new_session/probe'
        with tempfile.TemporaryDirectory() as directory:
            journal=Journal(directory,'probe','profile',{})
            with patch('confibench_resume.Path.resolve',return_value=Path(directory_path)):
                result=journal.iteration_directory(0,'saves/ConfiBench_qwen/new_session/probe')
            self.assertEqual(result,directory_path)

    def test_cpu_frontier_records_request_without_calling_provider(self):
        with tempfile.TemporaryDirectory() as root:
            journal = Journal(root, 'probe', 'profile', {'spec': 'test'}, max_fresh=0)
            request = {'messages': [{'role': 'user', 'content': 'next input'}]}
            with self.assertRaises(BudgetStop):
                journal.call('2:TBcheck:', request, lambda: self.fail('Provider reached'))
            frontier = json.loads(journal.frontier.read_text())
            self.assertEqual(frontier['request_sha256'], digest(request))
            self.assertEqual(frontier['request'], request)
            self.assertEqual(frontier['number'], 0)
            self.assertEqual(frontier['fresh_this_session'], 0)
            self.assertEqual(frontier['contract'], journal.contract)
            journal.max_fresh = 1
            journal.call('2:TBcheck:', request, lambda: ['answer', {}])
            self.assertFalse(journal.frontier.exists())
            journal.frontier.write_text('stale')
            Journal(root, 'probe', 'profile', {'spec': 'test'}, max_fresh=0)
            self.assertFalse(journal.frontier.exists())

    def test_compiler_file_order_survives_restart(self):
        with tempfile.TemporaryDirectory() as root:
            first=Journal(root,'probe','profile',{},max_fresh=0)
            directory=Path(root)/'probe/1_2_TBsim/debug_1'
            with patch('confibench_resume._active',first):
                self.assertEqual(compiler_file_order(directory,['tb.v\n','dut.v\n']),['tb.v\n','dut.v\n'])
            second=Journal(root,'probe','profile',{},max_fresh=0)
            with patch('confibench_resume._active',second):
                self.assertEqual(compiler_file_order(directory,['dut.v\n','tb.v\n']),['tb.v\n','dut.v\n'])
                with self.assertRaises(ResumeMismatch): compiler_file_order(directory,['other.v\n'])

    def test_mismatched_legacy_candidate_is_never_replayed(self):
        with tempfile.TemporaryDirectory() as root:
            journal = Journal(root,'probe','profile',{'problem':'test'},max_fresh=0)
            scope='0:TBsim:debug:debug_1'
            candidate={'request_sha256':digest({'error':'old'}),
                       'output':['old answer',{}], 'output_sha256':digest(['old answer',{}])}
            journal.legacy[digest({'scope':scope,'number':0})]=candidate
            with self.assertRaises(BudgetStop):
                journal.call(scope,{'error':'new'},lambda:self.fail('CPU cap bypassed'))
            self.assertEqual(journal.replayed,0)
            self.assertTrue(list((journal.root/'rejected_legacy').rglob('*.json')))
            journal.max_fresh=1
            self.assertEqual(journal.call(scope,{'error':'new'},lambda:['new answer',{}]),['new answer',{}])
            self.assertEqual(journal.fresh,1)
            journal.counters={}
            with self.assertRaises(ResumeMismatch):
                journal.call(scope,{'error':'changed again'},lambda:self.fail('Committed call replaced'))

    def test_killed_process_response_is_replayed_without_provider(self):
        with tempfile.TemporaryDirectory() as temp:
            child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--child', temp])
            try:
                deadline = time.monotonic()+15
                while not (Path(temp)/'ready').exists() and time.monotonic()<deadline:
                    if child.poll() is not None:
                        self.fail('Child exited before checkpoint')
                    time.sleep(.05)
                self.assertTrue((Path(temp)/'ready').exists())
                child.terminate()
                child.wait(timeout=5)
                j = Journal(temp, 'probe', 'test', {'input': 'x'}, max_fresh=0)
                value = j.call('stage', {'message': 'x'}, lambda: self.fail('Provider called again'))
                self.assertEqual(value, ['first response', {'tokens': 12}])
                self.assertEqual(j.replayed, 1)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)

    def test_actual_loop_resume_equivalent_and_no_repeated_generation(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'CBQ_RESUME_ROOT': temp}):
            providers = []
            task = FakeTask(providers, interrupt_at=1)
            with self.assertRaises(Interrupted):
                task.run_stages_core()
            saved = json.loads(task._resume.state.read_text())['payload']
            self.assertEqual(saved['next_iteration'], 1)
            resumed = FakeTask(providers)
            resumed.run_stages_core()
            self.assertEqual(resumed.evaluations, 1)
            self.assertEqual(providers, [('gen', 0), ('check', 0), ('gen', 1), ('check', 1), ('gen', 2), ('check', 2)])
            with tempfile.TemporaryDirectory() as control, patch.dict(os.environ, {'CBQ_RESUME_ROOT': control}):
                expected = FakeTask([])
                expected.run_stages_core()
            self.assertEqual(resumed.final_codes, expected.final_codes)
            self.assertEqual(resumed.op_record, expected.op_record)

    def test_break_checkpoint_resumes_directly_at_evaluation(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'CBQ_RESUME_ROOT': temp}):
            providers = []
            original = FakeTask(providers, next_action='pass')
            original.run_stages_core()
            self.assertTrue(json.loads(original._resume.state.read_text())['payload']['eval_ready'])
            resumed = FakeTask(providers, next_action='pass')
            resumed.run_stages_core()
            self.assertEqual(len(providers), 4)
            self.assertEqual(resumed.final_codes, original.final_codes)

    def test_mismatch_corruption_and_budget_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            j = Journal(temp, 'probe', 'p', {'x': 1})
            j.call('s', {'x': 1}, lambda: 'saved')
            with self.assertRaises(ResumeMismatch):
                Journal(temp, 'probe', 'different', {'x': 1})
            with self.assertRaises(ResumeMismatch):
                Journal(temp, 'probe', 'p', {'x': 2})
            replay = Journal(temp, 'probe', 'p', {'x': 1}, max_fresh=0)
            with self.assertRaises(ResumeMismatch):
                replay.call('s', {'x': 2}, lambda: self.fail('Mismatch reached provider'))
            replay = Journal(temp, 'probe', 'p', {'x': 1}, max_fresh=0)
            with self.assertRaises(BudgetStop):
                replay.call('unknown', {'x': 2}, lambda: self.fail('Budget reached provider'))
            record_file = next((j.root/'calls').rglob('*.json'))
            record = json.loads(record_file.read_text())
            record['output'] = 'tampered'
            record_file.write_text(json.dumps(record))
            with self.assertRaises(ResumeMismatch):
                Journal(temp, 'probe', 'p', {'x': 1}).call('s', {'x': 1}, lambda: None)

    def test_array_roundtrip(self):
        import numpy as np
        value = {'matrix': np.array([[0, 1], [1, 0]], dtype=np.int64)}
        result = decode(encode(value))
        self.assertTrue(np.array_equal(result['matrix'], value['matrix']))

    def test_legacy_saved_text_exact_whitespace_and_zero_fresh_calls(self):
        import zipfile
        messages = [{'role': 'system', 'content': 'system'}, {'role': 'user', 'content': 'question\n'},
                    {'role': 'assistant', 'content': 'answer\n'}]
        text = ''.join('########## %s ##########\n%s\n\n' % (m['role'], m['content']) for m in messages)
        self.assertEqual(conversations(text), messages)
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp)/'partial.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('saves/run/probe/1_1_TBgen/stage_0.txt', text)
            report = build('probe', archive, 'p', {'spec': 's'}, Path(temp)/'runtime')
            self.assertEqual(report['recoverable_calls'], 1)
            j = Journal(Path(temp)/'runtime', 'probe', 'p', {'spec': 's'}, max_fresh=0)
            request = {'model': 'qwen3.5-27b', 'messages': messages[:-1], 'kwargs': KWARGS}
            output = j.call('0:TBgen:stage:stage_0:1_1_TBgen', request,
                            lambda: self.fail('Legacy stage regenerated'))
            self.assertEqual(output[0], 'answer\n')
            self.assertEqual(j.fresh, 0)
            self.assertEqual(j.replayed, 1)


if __name__ == '__main__':
    if '--child' in sys.argv:
        root = sys.argv[-1]
        j = Journal(root, 'probe', 'test', {'input': 'x'})
        j.call('stage', {'message': 'x'}, lambda: ['first response', {'tokens': 12}])
        (Path(root)/'ready').write_text('committed')
        time.sleep(60)
    else:
        unittest.main()
