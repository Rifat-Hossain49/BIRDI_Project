"""Read-only cloud recovery and runtime audit. Never pushes datasets or kernels."""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'dirtb'))
import kaggle_rotate as k

OUT = ROOT / 'confibench_finish_20261003'


def recover(job):
    dest = ROOT / 'kaggle_runs' / (job['tag'] + '_oct3_diagnostics')
    dest.mkdir(exist_ok=True)
    required = ['cbq_completion.json', 'cbq_partial.zip', 'cbq_saves.zip', 'cbq_w0.log', 'cbq_w1.log']
    if not all((dest / name).is_file() for name in required):
        result = k.kaggle(['kernels', 'output', k.kernel_id(Path(job['bundle']), job['account']),
                           '-p', str(dest), '--file-pattern', 'cbq_*', '--page-size', '200'],
                          k.accounts()[job['account']], timeout=600)
        if not all((dest / name).is_file() for name in required):
            raise RuntimeError(f"{job['tag']}: missing recovery files; {result[-200:]}")
    entry = {'tag': job['tag'], 'tasks': job['tasks'], 'files': {}, 'task_audit': {}}
    for name in required:
        path = dest / name
        entry['files'][name] = {'path': str(path), 'bytes': path.stat().st_size,
                               'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        if path.suffix == '.zip':
            with zipfile.ZipFile(path) as z:
                if z.testzip() is not None:
                    raise ValueError(f'Bad archive: {path}')
                entry['files'][name]['members'] = len(z.namelist())
    entry['completion'] = json.loads((dest / 'cbq_completion.json').read_text())
    for task in job['tasks']:
        lines = []
        for worker in ('cbq_w0.log', 'cbq_w1.log'):
            lines.extend(line for line in (dest / worker).read_text(errors='replace').splitlines()
                         if f'[{task}]' in line)
        gen_seconds = sum(float(x) for line in lines
                          for x in re.findall(r'ends \(([0-9.]+)s used\)', line))
        corrections = []
        for line in lines:
            stamp = re.match(r'(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+)', line)
            if stamp and 'naive corrector mode' in line:
                corrections.append((datetime.fromisoformat(stamp[1]), 'begins' in line))
        correction_seconds, start = 0.0, None
        for stamp, begins in corrections:
            if begins:
                start = stamp
            elif start is not None:
                correction_seconds += (stamp - start).total_seconds()
                start = None
        with zipfile.ZipFile(dest / 'cbq_partial.zip') as z:
            files = [n for n in z.namelist() if f'/{task}/' in n]
        entry['task_audit'][task] = {
            'checkpointed': task in entry['completion']['checkpointed_tasks'],
            'partial_files': len(files), 'recorded_generation_stage_seconds': round(gen_seconds, 1),
            'recorded_correction_seconds': round(correction_seconds, 1),
            'generation_iterations_started': sum('[TBgen] stage_0 ends' in line for line in lines),
            'correction_attempts_started': sum('naive corrector mode begins' in line for line in lines),
            'last_log_lines': lines[-4:],
        }
    print(f"Recovered {job['tag']}: {len(entry['completion']['checkpointed_tasks'])}/2 final records", flush=True)
    return entry


def main():
    manifest = json.loads((OUT / 'launch_manifest.json').read_text())
    jobs = [j for j in manifest['jobs'] if j['tag'].startswith('cbqoct3') and j['submission'] == 'accepted']
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(recover, jobs))
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'gpu_jobs_launched': 0, 'jobs': results}
    (OUT / 'recovery_audit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('Recovery audit saved; no GPU jobs launched.', flush=True)


if __name__ == '__main__':
    main()
