"""Execute upstream prompt builders and patched adapter with zero model calls."""
import ast
import copy
import json
import re
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from confibench_resume import begin_task
from prepare_confibench_qwen import ROOT, CB_SRC, QWEN_CALL


def literal_assignments(tree, env):
    for node in tree.body:
        if isinstance(node, ast.Assign):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    env[target.id] = value


def prompt_environment():
    env = {'json': json, 're': re, 'copy': copy}
    llm = ast.parse((CB_SRC/'LLM_call.py').read_text())
    literal_assignments(llm, env)
    functions = [n for n in llm.body if isinstance(n, ast.FunctionDef)
                 and n.name in ('extract_code', 'message_to_conversation')]
    exec(compile(ast.Module(body=functions, type_ignores=[]), 'baseline-helpers', 'exec'), env)
    base = ast.parse((CB_SRC/'prompt_scripts/base_script.py').read_text())
    literal_assignments(base, env)
    classes = [n for n in base.body if isinstance(n, ast.ClassDef) and n.name == 'BaseScriptStage']
    exec(compile(ast.Module(body=classes, type_ignores=[]), 'baseline-stage', 'exec'), env)
    stages = ast.parse((CB_SRC/'prompt_scripts/script_pychecker.py').read_text())
    literal_assignments(stages, env)
    classes = [n for n in stages.body if isinstance(n, ast.ClassDef) and n.name in ('Stage0','Stage1','Stage2','Stage3')]
    exec(compile(ast.Module(body=classes, type_ignores=[]), 'baseline-prompts', 'exec'), env)

    def forbidden(**kwargs):
        raise AssertionError('Unexpected fresh model request')

    env['OpenAI'] = lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=forbidden)))
    env['os'] = __import__('os')
    exec(QWEN_CALL, env)
    env['llm_call'] = lambda input_messages, model, **kwargs: env['qwen_call'](
        input_messages, model, kwargs.get('system_message'), kwargs.get('temperature'), kwargs.get('json_mode', False))
    return env


class Harness:
    def __init__(self, problem, profile):
        self.task_id = problem['task_id']
        self.prob_data = problem
        self.iter_max = 10
        self.autoline_iter_now = 0
        self.stage_now = 'TBgen'
        self.rtlgen_list = None
        begin_task(self, profile)

    def stage_operation(self, stage, conversation_dir):
        stage.make_prompt()
        stage.call_gpt()


def main():
    out = ROOT/'confibench_finish_20261003'
    manifest = json.loads((out/'legacy_recovery_manifest_v2.json').read_text())
    problems = {p['task_id']: p for p in map(json.loads, (CB_SRC/'data/HDLBits/HDLBits_data.jsonl').read_text().splitlines())}
    for p in map(json.loads, (CB_SRC/'data/HDLBits/HDLBits_data_mutants.jsonl').read_text().splitlines()):
        problems[p['task_id']].update(p)
    env = prompt_environment()
    model_kwargs = {'gpt_model': 'qwen3.5-27b', 'api_key_path': 'config/key_API.json'}
    results = []
    for entry in manifest['tasks']:
        task = entry['task']
        with tempfile.TemporaryDirectory() as temp, patch.dict(__import__('os').environ,
              {'CBQ_RESUME_ROOT': temp, 'CBQ_MAX_FRESH_CALLS': '0'}):
            shutil.copytree(out/'legacy_runtime_v2'/task, Path(temp)/task)
            harness = Harness(problems[task], manifest['profile'])
            bank = json.loads((Path(temp)/task/'legacy_calls.json').read_text())
            iterations = sorted({int(v['scope'].split(':')[0]) for v in bank.values()
                                 if ':TBgen:stage:stage_0:' in v['scope']})
            if not iterations:
                raise AssertionError(f'{task}: no saved stage0')
            harness.autoline_iter_now = iterations[0]
            directory = f'{iterations[0]+1}_1_TBgen'
            stages = [env['Stage0'](problems[task], **model_kwargs),
                      env['Stage1'](problems[task], **model_kwargs)]
            for stage in stages:
                harness.stage_operation(stage, directory)
            second = env['Stage2'](problems[task], stages[1].response, **model_kwargs)
            harness.stage_operation(second, directory)
            second.postprocessing()
            third = env['Stage3'](problems[task], stages[1].response, second.response, **model_kwargs)
            harness.stage_operation(third, directory)
            assert harness._resume.fresh == 0 and harness._resume.replayed == 4
            results.append({'task': task, 'iteration': iterations[0]+1, 'real_prompt_stages_replayed': 4,
                            'fresh_model_calls': 0, 'earlier_missing_iterations': iterations[0]})
            print(task, 'four upstream stages replayed; zero fresh calls', flush=True)
    (out/'legacy_prompt_validation.json').write_text(json.dumps({'tasks': results,
                         'simulation_verified': False, 'gpu_jobs_launched': 0}, indent=2))


if __name__ == '__main__':
    main()
