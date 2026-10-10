"""Fail-closed JSON checkpoints for the copied ConfiBench baseline.

Persist each completed model response before returning it, plus task state at
iteration boundaries. No pickle, best-of selection, or change to scoring rules.
"""
from __future__ import annotations

import copy
from collections import Counter
import hashlib
import inspect
import json
import os
from pathlib import Path, PurePosixPath
import re
import time
from types import SimpleNamespace


class ResumeMismatch(BaseException):
    """Bypass upstream's catch-and-reboot loop on unsafe recovery."""


class BudgetStop(BaseException):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    with tmp.open('w', encoding='utf-8', newline='\n') as f:
        json.dump(value, f, sort_keys=True, ensure_ascii=True, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class Journal:
    def __init__(self, root, task_id, profile, problem, max_fresh=None):
        if not task_id or Path(task_id).name != task_id or task_id in ('.', '..'):
            raise ResumeMismatch('Unsafe task id')
        self.root = Path(root) / task_id
        self.contract = {'version': 1, 'task_id': task_id, 'profile': profile,
                         'problem_sha256': digest(problem)}
        self.root.mkdir(parents=True, exist_ok=True)
        contract_file = self.root / 'contract.json'
        if contract_file.exists():
            if json.loads(contract_file.read_text()) != self.contract:
                raise ResumeMismatch('Checkpoint model/config/problem contract changed')
        else:
            atomic_json(contract_file, self.contract)
        self.counters = {}
        self.max_fresh = max_fresh
        self.fresh = self.replayed = 0
        self.new_call_deadline = float(os.environ.get('CBQ_NEW_CALL_DEADLINE', '0'))
        self.frontier = self.root / 'next_request.json'
        self.frontier.unlink(missing_ok=True)
        self.layout_file = self.root / 'execution_layout.json'
        self.layout = {}
        if self.layout_file.exists():
            layout = json.loads(self.layout_file.read_text())
            if (layout['contract'] != self.contract
                    or layout['payload_sha256'] != digest(layout['directories'])):
                raise ResumeMismatch('Execution-layout checkpoint mismatch')
            self.layout = layout['directories']
        self.state = self.root / 'iteration.json'
        legacy_file = self.root / 'legacy_calls.json'
        self.legacy = json.loads(legacy_file.read_text()) if legacy_file.exists() else {}
        self.order_file=self.root/'compiler_orders.json'
        self.compiler_orders={}
        if self.order_file.exists():
            orders=json.loads(self.order_file.read_text())
            if orders['contract']!=self.contract or orders['payload_sha256']!=digest(orders['orders']):
                raise ResumeMismatch('Compiler-order checkpoint mismatch')
            self.compiler_orders=orders['orders']

    def call(self, scope, request, provider):
        number = self.counters.get(scope, 0)
        scope_key = digest(scope)
        path = self.root / 'calls' / scope_key / f'{number:06d}.json'
        request_hash = digest(request)
        if path.exists():
            record = json.loads(path.read_text())
            if (record['scope'] != scope or record['request_sha256'] != request_hash
                    or record['output_sha256'] != digest(record['output'])):
                atomic_json(self.root/'replay_conflicts'/scope_key/f'{number:06d}_{request_hash}.json',{
                    'scope':scope,'number':number,'request':request,
                    'request_sha256':request_hash,
                    'saved_request_sha256':record.get('request_sha256'),
                    'reason':'Committed call mismatch; execution stopped without replacement'})
                raise ResumeMismatch(f'Call replay mismatch: {scope} #{number}')
            output = record['output']
            self.replayed += 1
        else:
            if any(p.stem.isdigit() and int(p.stem) > number for p in path.parent.glob('*.json')):
                raise ResumeMismatch('Missing response inside an existing call journal')
            legacy = self.legacy.get(digest({'scope': scope, 'number': number}))
            if legacy is not None:
                if legacy['output_sha256'] != digest(legacy['output']):
                    raise ResumeMismatch('Legacy response checksum mismatch')
                if legacy['request_sha256'] != request_hash:
                    # Historical transcripts are candidates, not committed calls.
                    # Never replay a response to a different debug/error prompt.
                    atomic_json(self.root / 'rejected_legacy' / scope_key /
                                f'{number:06d}_{request_hash}.json', {
                        'scope': scope, 'number': number, 'request': request,
                        'request_sha256': request_hash,
                        'legacy_request_sha256': legacy['request_sha256'],
                        'reason': 'Historical candidate request differs; fresh generation required'})
                    print(f'LEGACY_CACHE_MISS: {scope} #{number}; candidate retained, not replayed', flush=True)
                    legacy = None
            if legacy is not None:
                output = legacy['output']
                self.replayed += 1
            else:
                if self.max_fresh is not None and self.fresh >= self.max_fresh:
                    atomic_json(self.frontier, {
                        'contract': self.contract, 'reason': 'fresh_call_budget',
                        'scope': scope, 'number': number, 'request': request,
                        'request_sha256': request_hash, 'max_fresh': self.max_fresh,
                        'fresh_this_session': self.fresh,
                        'replayed_this_session': self.replayed,
                    })
                    raise BudgetStop(f'Fresh-call budget exhausted at {scope} #{number}; checkpoint retained')
                if self.new_call_deadline and time.time() >= self.new_call_deadline:
                    raise BudgetStop(f'New-call cutoff reached at {scope} #{number}; no late provider call started')
                output = provider()
                self.fresh += 1
            # Commit before exposing the response to downstream code.
            record = {'scope': scope, 'number': number, 'request_sha256': request_hash,
                      'output': output, 'output_sha256': digest(output)}
            atomic_json(path, record)
        self.counters[scope] = number + 1
        self.frontier.unlink(missing_ok=True)
        atomic_json(self.root / 'progress.json', {'fresh_this_session': self.fresh,
                    'replayed_this_session': self.replayed, 'scope': scope,
                    'scope_call': number, 'counters': self.counters})
        return copy.deepcopy(output)

    def iteration_directory(self, iteration, current):
        """Restore actual script paths so Python tracebacks replay byte-for-byte."""
        base = PurePosixPath('/kaggle/working/ConfiBench/saves/ConfiBench_qwen')
        prefix = str(iteration) + ':'
        captured = set()
        for file in (self.root / 'calls').rglob('*.json'):
            record = json.loads(file.read_text())
            if not record['scope'].startswith(prefix):
                continue
            if record['output_sha256'] != digest(record['output']):
                raise ResumeMismatch('Response checksum mismatch while restoring script paths')
            output = record['output']
            if not isinstance(output, list) or len(output) < 2 or not isinstance(output[1], dict):
                continue
            for message in output[1].get('messages', [])[:-1]:
                for match in re.finditer(r'^\s*File "([^"\n]+)", line \d+', message['content'], re.MULTILINE):
                    path = PurePosixPath(match.group(1))
                    if path.parts[:len(base.parts)] != base.parts:
                        continue
                    tail = path.parts[len(base.parts):]
                    if ('..' in tail or len(tail) < 3 or tail[1] != self.contract['task_id']
                            or not re.fullmatch(r'[A-Za-z0-9_]+', tail[0])):
                        raise ResumeMismatch('Unsafe historical script path')
                    captured.add(str(base / tail[0] / tail[1]))
        if len(captured) > 1:
            raise ResumeMismatch('Conflicting script roots within one saved iteration')
        key = str(iteration)
        selected = self.layout.get(key)
        if selected and captured and captured != {selected}:
            raise ResumeMismatch('Saved script path differs from execution layout')
        current_path = PurePosixPath(str(current))
        if not current_path.is_absolute():
            current_path = PurePosixPath(Path(current).resolve().as_posix())
        selected = selected or next(iter(captured), str(current_path))
        path = PurePosixPath(selected)
        tail = path.parts[len(base.parts):]
        if (path.parts[:len(base.parts)] != base.parts or len(tail) != 2
                or '..' in tail or tail[1] != self.contract['task_id']
                or not re.fullmatch(r'[A-Za-z0-9_]+', tail[0])):
            raise ResumeMismatch('Execution directory is outside the active task save root')
        self.layout[key] = selected
        atomic_json(self.layout_file, {'contract': self.contract, 'directories': self.layout,
                                     'payload_sha256': digest(self.layout)})
        return selected


# Only data needed across iterations; executable managers are rebuilt normally.
FIELDS = ('autoline_iter_now', 'next_action', 'TB_code_v', 'TB_code_py', 'RSmatrix',
          'scen_mask', 'syntax_error', 'multibench_info', 'sum_valid_ratio',
          'rtlgen_list', 'circuit_type', 'scenario_dict', 'scenario_num',
          'checklist_worked', 'TB_corrected', 'incomplete_running', 'full_pass',
          'TBcheck_rtl_newly_gen_num', 'op_record', 'funccheck_op_record',
          'funccheck_iters', 'scen_mask_worked', 'confidence', 'stage_now')
SIM_FIELDS = ('pychecker_en', 'Eval0_pass', 'sim_pass', 'debug_iter_iv_now',
              'iv_runing_time', 'py_pass', 'debug_iter_py_now', 'py_runing_time')
_active = None


def prepare_iteration_path(task, iteration):
    if not hasattr(task, 'task_dir'):
        return
    task.task_dir = task._resume.iteration_directory(iteration, task.task_dir)
    task.working_dir = task.task_dir
    Path(task.task_dir).mkdir(parents=True, exist_ok=True)


def compiler_file_order(directory, filenames):
    if _active is None:
        return filenames
    task=_active.contract['task_id']
    parts=Path(directory).parts
    indexes=[index for index,value in enumerate(parts) if value==task]
    if not indexes:
        raise ResumeMismatch('Compiler directory is outside the active task')
    key='/'.join(parts[indexes[-1]+1:]) or '.'
    previous=_active.compiler_orders.get(key)
    if previous is not None:
        if Counter(previous)!=Counter(filenames):
            raise ResumeMismatch('Compiler input file set changed at '+key)
        return list(previous)
    _active.compiler_orders[key]=list(filenames)
    atomic_json(_active.order_file,{'contract':_active.contract,'orders':_active.compiler_orders,
                                 'payload_sha256':digest(_active.compiler_orders)})
    return filenames


def encode(value):
    if hasattr(value, 'dtype') and hasattr(value, 'tolist'):
        return {'__array__': value.tolist(), 'dtype': str(value.dtype)}
    if isinstance(value, dict):
        return {k: encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode(v) for v in value]
    return value


def decode(value):
    if isinstance(value, dict) and set(value) == {'__array__', 'dtype'}:
        import numpy as np
        return np.array(value['__array__'], dtype=value['dtype'])
    if isinstance(value, dict):
        return {k: decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decode(v) for v in value]
    return value


def begin_task(task, profile):
    global _active
    limit = os.environ.get('CBQ_MAX_FRESH_CALLS')
    _active = Journal(os.environ.get('CBQ_RESUME_ROOT', 'resume_runtime'), task.task_id,
                      profile, task.prob_data, int(limit) if limit is not None else None)
    task._resume = _active
    task._resume_start = 0
    task._resume_eval_ready = False
    population = _active.root / 'legacy_population.json'
    if not _active.state.exists() and population.exists():
        recovered = json.loads(population.read_text())
        if recovered.get('contract') != _active.contract or digest(recovered['population']) != recovered['sha256']:
            raise ResumeMismatch('Recovered RTL population contract mismatch')
        task.rtlgen_list = recovered['population']
    if _active.state.exists():
        record = json.loads(_active.state.read_text())
        if record.get('contract') != _active.contract or record['payload_sha256'] != digest(record['payload']):
            raise ResumeMismatch('Corrupt or incompatible iteration checkpoint')
        payload = record['payload']
        task._resume_start = payload['next_iteration']
        task._resume_eval_ready = payload['eval_ready']
        if not 0 <= task._resume_start <= task.iter_max:
            raise ResumeMismatch('Invalid iteration cursor')
        for name, value in payload['fields'].items():
            if name not in FIELDS:
                raise ResumeMismatch('Unknown state field')
            setattr(task, name, decode(value))
        task.TBsim = SimpleNamespace(**payload['sim']) if payload['sim'] is not None else None
        task.TBgen = SimpleNamespace() if payload['had_gen'] else None
        task.TBcheck = SimpleNamespace() if payload['had_check'] else None
        _active.counters = payload['counters']
        if payload.get('usage'):
            from LLM_call import llm_manager
            for name, value in payload['usage'].items():
                setattr(llm_manager, name, value)
        print(f'RESUME task={task.task_id} next_iteration={task._resume_start} '
              f'eval_ready={task._resume_eval_ready}', flush=True)


def commit_iteration(task, next_iteration, eval_ready):
    usage = {}
    if 'LLM_call' in __import__('sys').modules:
        from LLM_call import llm_manager
        usage = {n: getattr(llm_manager, n) for n in ('tokens_in_section', 'tokens_out_section',
                 'tokens_both_section', 'cost_section')}
    payload = {'next_iteration': next_iteration, 'eval_ready': eval_ready,
               'fields': {n: encode(getattr(task, n)) for n in FIELDS if hasattr(task, n)},
               'sim': {n: getattr(task.TBsim, n) for n in SIM_FIELDS if hasattr(task.TBsim, n)}
                       if task.TBsim is not None else None,
               'had_gen': task.TBgen is not None, 'had_check': task.TBcheck is not None,
               'counters': task._resume.counters, 'usage': usage}
    atomic_json(task._resume.state, {'contract': task._resume.contract,
                'payload': payload, 'payload_sha256': digest(payload)})


def scoped_call(request, provider):
    if _active is None:
        return provider()  # Startup smoke request is not a benchmark task.
    frame = inspect.currentframe().f_back
    task = None
    detail = ''
    try:
        while frame is not None:
            obj = frame.f_locals.get('self')
            if frame.f_code.co_name == 'stage_operation':
                stage = frame.f_locals.get('stage')
                detail = 'stage:' + stage.stage_name
                directory = frame.f_locals.get('conversation_dir')
                if directory:
                    # Keep the logical path, not a session-specific save root.
                    detail += ':' + Path(directory).name
            if frame.f_code.co_name == 'correct':
                detail = 'correct:' + Path(frame.f_locals.get('working_dir') or '').name
            if frame.f_code.co_name in ('_debug_iv', '_debug_py'):
                detail = 'debug:' + Path(obj.working_dir).name
            if obj is not None and getattr(obj, '_resume', None) is _active:
                task = obj
            frame = frame.f_back
    finally:
        del frame
    if task is None:
        raise ResumeMismatch('Model call outside bound task context')
    scope = f'{task.autoline_iter_now}:{task.stage_now}:{detail}'
    return _active.call(scope, request, provider)


def self_test():
    import tempfile
    with tempfile.TemporaryDirectory() as temp:
        calls = []
        first = Journal(temp, 'probe', 'profile', {'spec': 'x'})
        expected = first.call('stage', {'input': 'x'}, lambda: calls.append(1) or ['answer', {}])
        resumed = Journal(temp, 'probe', 'profile', {'spec': 'x'}, max_fresh=0)
        assert resumed.call('stage', {'input': 'x'}, lambda: calls.append(2)) == expected
        assert calls == [1] and resumed.replayed == 1
    print('CALL_RESUME_SMOKE_OK', flush=True)
