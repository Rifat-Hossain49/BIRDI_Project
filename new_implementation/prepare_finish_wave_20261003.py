"""Audit the frozen checkpoint and partition only its unresolved tasks."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / 'kaggle_runs'
OUT = ROOT / 'confibench_finish_20261003'
BASE = [
    'cbq0of10_finish', 'cbq1of10_finish', 'cbq2of10_finish',
    'cbq4of10_finish', 'cbq5of10_finish', 'cbq6of10_finish',
    'cbq8of10_finish', 'cbq9of10_finish', 'cbq7of20_final',
    'cbq17of20_final', 'cbqfinisha_final', 'cbqfinishb_final',
    'cbqfinishc_final', 'cbqfinishd_final',
]
RECOVERED = ['cbq3of10_recovered_json', 'cbq7of10_recovered_json']


def main():
    OUT.mkdir(exist_ok=True)
    expected = [json.loads(line)['task_id'] for line in
                (ROOT / 'baselines/ConfiBench/data/HDLBits/HDLBits_data.jsonl')
                .read_text(encoding='utf-8').splitlines() if line.strip()]
    assert len(expected) == len(set(expected)) == 156
    selected = {}
    provenance = {}

    def retain(task, payload, origin):
        record = json.loads(payload)
        assert task in expected and record.get('task_id') == task, origin
        if task not in selected:
            selected[task] = payload
            provenance[task] = {'source': origin, 'sha256': hashlib.sha256(payload).hexdigest(),
                                'has_eval1': 'Eval1_pass' in record,
                                'has_eval2': 'Eval2_pass' in record,
                                'upstream_incomplete_flag': record.get('ERROR(incomplete)')}

    def read_archive(name):
        path = RUNS / name / 'cbq_saves.zip'
        with zipfile.ZipFile(path) as z:
            for entry in sorted(z.namelist()):
                p = PurePosixPath(entry.replace('\\', '/'))
                if p.name == 'data.json':
                    retain(p.parent.name, z.read(entry), f'{name}/{entry}')

    for name in BASE:
        read_archive(name)
    for name in RECOVERED:
        for path in sorted((RUNS / name).rglob('data.json')):
            retain(path.parent.name, path.read_bytes(), path.relative_to(RUNS).as_posix())
    for suffix in 'abcdefghij':
        read_archive(f'cbqfinal2{suffix}_complete')
    read_archive('cbqretry3a_complete')
    assert len(selected) == 136, f'Frozen coverage changed: {len(selected)}'
    remaining = [task for task in expected if task not in selected]
    assert len(remaining) == 20
    with zipfile.ZipFile(OUT / 'canonical_136.zip', 'w', zipfile.ZIP_DEFLATED) as z:
        for task in sorted(selected):
            z.writestr(f'saves/ConfiBench_qwen/merged/{task}/data.json', selected[task])
    manifest = {'date': '2026-10-03', 'expected': expected, 'checkpointed': sorted(selected),
                'remaining': remaining, 'provenance': provenance, 'jobs': []}
    assigned = []
    for index in range(10):
        tasks = remaining[index::10]
        assert len(tasks) == 2
        tag = f'cbqoct3{index:02d}'
        task_file = OUT / f'{tag}.jsonl'
        task_file.write_text(''.join(json.dumps({'task_id': task}) + '\n' for task in tasks),
                             encoding='utf-8')
        subprocess.run([sys.executable, str(ROOT / 'prepare_confibench_qwen.py'), '0', '1',
                        '--tasks-file', str(task_file), '--tag', tag,
                        '--workers', '2', '--budget-hours', '10.5'], check=True)
        bundle = ROOT / f'kaggle_upload_{tag}'
        notebook = json.loads((bundle / 'kernel' / f'{tag}.ipynb').read_text())
        for cell in notebook['cells']:
            compile(''.join(cell['source']), tag, 'exec')
        with zipfile.ZipFile(bundle / 'dataset_publish' / f'{tag}.zip') as z:
            assert all('\\' not in n and '..' not in PurePosixPath(n).parts for n in z.namelist())
            for name in z.namelist():
                if name.endswith(('.py', '.json', '.yaml', '.jsonl')):
                    assert b'KGAT_' not in z.read(name), f'Credential in {name}'
        manifest['jobs'].append({'tag': tag, 'account': index // 2 + 1, 'tasks': tasks,
                                 'bundle': str(bundle), 'submission': 'staged'})
        assigned.extend(tasks)
    assert len(assigned) == len(set(assigned)) == 20 and set(assigned) == set(remaining)
    (OUT / 'launch_manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps({'checkpointed': len(selected), 'remaining': remaining,
                      'jobs': len(manifest['jobs'])}, indent=2))


if __name__ == '__main__':
    main()
