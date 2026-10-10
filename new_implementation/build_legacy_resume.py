"""Recover exact saved conversations, never guess missing algorithmic state.

Stage responses and correction conversations are scoped to their original
iteration. The first saved RTL population is frozen. Golden evaluation data is
not used for selection. Unknown/truncated conversations are reported, not used.
"""
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath

from confibench_resume import Journal, atomic_json, digest

ROOT = Path(__file__).resolve().parent
HEADER = re.compile(r'^########## (system|user|assistant) ##########\n', re.MULTILINE)
BEGIN = '############################## conversation begin ##############################\n'
KWARGS = {'temperature': 0.7, 'top_p': 0.8, 'max_tokens': 8192,
          'extra_body': {'top_k': 20, 'chat_template_kwargs': {'enable_thinking': False}}}


def conversations(text, trailing=0):
    text = text.replace('\r\n', '\n')
    if trailing:
        if not text.endswith('\n' * trailing):
            raise ValueError('Missing writer suffix')
        text = text[:-trailing]
    text = text.replace(BEGIN, '')
    matches = list(HEADER.finditer(text))
    if not matches or matches[0].start() != 0:
        raise ValueError('Not a complete saved conversation')
    messages = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[match.end():end]
        if not content.endswith('\n\n'):
            raise ValueError('Truncated message')
        messages.append({'role': match[1], 'content': content[:-2]})
    return messages


def build(task, archive, profile, problem, dest):
    journal = Journal(dest, task, profile, problem)
    bank = {}
    rejected = []
    populations = []
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:
            raise ValueError('Corrupt legacy archive')
        for name in sorted(z.namelist()):
            path = PurePosixPath(name)
            if task not in path.parts:
                continue
            relative = path.parts[path.parts.index(task) + 1:]
            if len(relative) == 2 and relative[1] == 'rtl_list.json':
                value = json.loads(z.read(name))
                if isinstance(value, list) and len(value) == 1:
                    value = value[0]
                if value.get('task_id') != task or not isinstance(value.get('llmgen_RTL'), list):
                    raise ValueError('Invalid saved population')
                populations.append((int(relative[0].split('_')[0]), value['llmgen_RTL'], name))
            if len(relative) < 2:
                continue
            stage = re.fullmatch(r'(\d+)_1_TBgen', relative[0])
            correct = re.fullmatch(r'(\d+)_3_TBcheck', relative[0])
            sim = re.fullmatch(r'(\d+)_2_TBsim', relative[0])
            if stage and len(relative) == 2 and relative[1].startswith('stage_') and path.suffix == '.txt':
                scope = f'{int(stage[1])-1}:TBgen:stage:{path.stem}:{relative[0]}'
                trailing = 0
            elif correct and len(relative) == 3 and relative[1].startswith('correct_') and relative[2] == 'conversation.txt':
                scope = f'{int(correct[1])-1}:TBcheck:correct:{relative[1]}'
                trailing = 1
            elif sim and len(relative) == 3 and relative[2].startswith('stage_') and path.suffix == '.txt':
                scope = f'{int(sim[1])-1}:TBsim:stage:{path.stem}:{relative[1]}'
                trailing = 0
            elif sim and len(relative) == 3 and relative[2] == 'debug_messages.txt':
                scope = f'{int(sim[1])-1}:TBsim:debug:{relative[1]}'
                trailing = 1
            else:
                continue
            try:
                messages = conversations(z.read(name).decode('utf-8'), trailing)
                prefix, number = [], 0
                pending = {}
                for message in messages:
                    if message['role'] == 'system' and prefix:
                        prefix = []
                    if message['role'] == 'assistant':
                        if not prefix or prefix[-1]['role'] != 'user':
                            raise ValueError('Invalid conversation roles')
                        request = {'model': 'qwen3.5-27b', 'messages': prefix.copy(), 'kwargs': KWARGS}
                        info = {'messages': prefix + [message], 'time': 0, 'system_fingerprint': None,
                                'model': 'qwen3.5-27b', 'usage': {'prompt_tokens': 0, 'completion_tokens': 0,
                                'total_tokens': 0}, 'usage_unavailable': True, 'legacy_origin': name}
                        output = [message['content'], info]
                        key = digest({'scope': scope, 'number': number})
                        if key in bank or key in pending:
                            raise ValueError('Ambiguous legacy scope')
                        pending[key] = {'scope': scope, 'number': number, 'request_sha256': digest(request),
                                     'output': output, 'output_sha256': digest(output)}
                        number += 1
                    prefix.append(message)
                bank.update(pending)
            except (ValueError, UnicodeError) as error:
                rejected.append({'path': name, 'reason': str(error)})
    atomic_json(journal.root / 'legacy_calls.json', bank)
    population = []
    if populations:
        _, population, origin = min(populations, key=lambda x: x[0])
        atomic_json(journal.root / 'legacy_population.json', {'contract': journal.contract,
                    'population': population, 'sha256': digest(population), 'origin': origin})
    report = {'task': task, 'archive': str(archive), 'archive_sha256': hashlib.sha256(Path(archive).read_bytes()).hexdigest(),
              'recoverable_calls': len(bank), 'frozen_population_size': len(population),
              'rejected_files': rejected, 'iteration_state_reconstructed': False,
              'historical_usage_available': False}
    atomic_json(journal.root / 'legacy_provenance.json', report)
    return report


def main():
    task, archive, profile_file, destination = sys.argv[1:]
    problems = [json.loads(l) for l in (ROOT / 'baselines/ConfiBench/data/HDLBits/HDLBits_data.jsonl').read_text().splitlines()]
    problem = next(p for p in problems if p['task_id'] == task)
    # AutoLine's loader merges mutants; build using its exact input instead of
    # assuming the single JSONL contains every field.
    mutants = [json.loads(l) for l in (ROOT / 'baselines/ConfiBench/data/HDLBits/HDLBits_data_mutants.jsonl').read_text().splitlines()]
    problem.update(next(p for p in mutants if p['task_id'] == task))
    profile = json.loads(Path(profile_file).read_text())['profile']
    print(json.dumps(build(task, Path(archive), profile, problem, Path(destination)), indent=2))


if __name__ == '__main__':
    main()
