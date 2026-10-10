"""Build safe replay banks for unfinished Oct3 tasks; no cloud writes."""
import json
import zipfile
from pathlib import Path

from build_legacy_resume import build
from prepare_confibench_qwen import baseline_profile, CB_SRC, ROOT


def main():
    out = ROOT / 'confibench_finish_20261003'
    audit = json.loads((out / 'recovery_audit.json').read_text())
    missing = set(json.loads((out / 'monitor_state.json').read_text())['remaining'])
    problems = {p['task_id']: p for p in map(json.loads, (CB_SRC / 'data/HDLBits/HDLBits_data.jsonl').read_text().splitlines())}
    for p in map(json.loads, (CB_SRC / 'data/HDLBits/HDLBits_data_mutants.jsonl').read_text().splitlines()):
        problems[p['task_id']].update(p)
    runtime = out / 'legacy_runtime_v2'
    if runtime.exists():
        raise SystemExit('Recovery bank already exists; refusing to overwrite audit material')
    profile = baseline_profile()
    reports = []
    for job in audit['jobs']:
        for task in job['tasks']:
            if task in missing:
                report = build(task, Path(job['files']['cbq_partial.zip']['path']),
                               profile, problems[task], runtime)
                reports.append(report)
                print(task, 'saved calls:', report['recoverable_calls'], 'population:', report['frozen_population_size'],
                      'rejected files:', len(report['rejected_files']), flush=True)
    assert len(reports) == len(missing)
    (out / 'legacy_recovery_manifest_v2.json').write_text(json.dumps({'profile': profile, 'tasks': reports}, indent=2))
    with zipfile.ZipFile(out / 'legacy_runtime_v2.zip', 'w', zipfile.ZIP_DEFLATED) as z:
        for f in sorted(runtime.rglob('*.json')):
            z.write(f, f.relative_to(runtime).as_posix())
    print('Legacy recovery banks saved. No GPU jobs launched.')


if __name__ == '__main__':
    main()
