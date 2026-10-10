"""Submit the ten disjoint, audited finish kernels and persist each push outcome."""
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'confibench_finish_20261003'


def main():
    path = OUT / 'launch_manifest.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    tasks = [t for j in manifest['jobs'] for t in j['tasks']]
    assert len(tasks) == len(set(tasks)) == 20 and set(tasks) == set(manifest['remaining'])

    def submit(index):
        job = manifest['jobs'][index]
        result = subprocess.run([sys.executable, str(ROOT / 'dirtb/kaggle_rotate.py'), 'push',
                                 job['bundle'], str(job['account'])],
                                capture_output=True, text=True, timeout=1800)
        output = result.stdout + result.stderr
        (OUT / (job['tag'] + '_push.log')).write_text(output, encoding='utf-8')
        accepted = result.returncode == 0 and 'successfully pushed' in output
        return index, accepted

    pending = [i for i, job in enumerate(manifest['jobs']) if job['submission'] == 'staged']
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(submit, i): i for i in pending}
        for future in as_completed(futures):
            index = futures[future]
            try:
                _, accepted = future.result()
            except Exception:
                accepted = False
            job = manifest['jobs'][index]
            job['submission'] = 'accepted' if accepted else 'failed'
            job['submitted_at'] = datetime.now(timezone.utc).isoformat()
            tmp = path.with_suffix('.tmp')
            tmp.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
            tmp.replace(path)
            print(job['tag'], job['submission'], 'account', job['account'], flush=True)
    if any(j['submission'] != 'accepted' for j in manifest['jobs']):
        raise SystemExit('Not every kernel was accepted; see saved push logs.')


if __name__ == '__main__':
    main()
