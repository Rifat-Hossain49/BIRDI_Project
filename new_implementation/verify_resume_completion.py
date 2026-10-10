"""Validate final task-record coverage without selecting or changing scored outcomes."""
import json
from pathlib import Path, PurePosixPath
import zipfile


def task_records(path, expected):
    records = {}
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError('Corrupt final task-record archive')
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('Duplicate ZIP member in final task records')
        for name in names:
            member = PurePosixPath(name)
            if member.name != 'data.json':
                continue
            if member.is_absolute() or '..' in member.parts or '\\' in name:
                raise ValueError('Invalid final task-record path')
            task = member.parent.name
            payload = archive.read(name)
            record = json.loads(payload)
            if not isinstance(record, dict) or record.get('task_id') != task or task not in expected:
                raise ValueError('Unexpected or mismatched final task identity: ' + task)
            if task in records:
                raise ValueError('Multiple final records for task: ' + task)
            records[task] = payload
    return records


def completion_audit(canonical, baseline, expected):
    if len(expected) != len(set(expected)):
        raise ValueError('Expected task list contains duplicates')
    recorded = task_records(canonical, set(expected))
    originals = task_records(baseline, set(expected))
    if any(recorded.get(task) != payload for task, payload in originals.items()):
        raise ValueError('An original first task record was changed or removed')
    errors, unavailable = [], []
    for task, payload in recorded.items():
        record = json.loads(payload)
        if record.get('ERROR(incomplete)'):
            errors.append(task)
        if any(not isinstance(record.get(key), bool) for key in ('Eval1_pass', 'Eval2_pass')):
            unavailable.append(task)
    missing = sorted(set(expected) - recorded.keys())
    return {'expected': len(expected), 'recorded': len(recorded), 'missing': missing,
            'all_tasks_recorded': not missing, 'original_records_preserved': len(originals),
            'error_flagged_tasks': sorted(errors), 'outcomes_unavailable_tasks': sorted(unavailable),
            'note': ('Task coverage includes saved failures and is not a pass count. Error flags are preserved '
                     'raw metadata: upstream does not clear incomplete_running on its normal multibench path, '
                     'so this flag alone must not be interpreted as an evaluation failure. '
                     'Unavailable evaluation fields must be reported explicitly, not filled as successes.')}


if __name__ == '__main__':
    from monitor_resume_20261005 import OUT, OLD, now, sha
    from confibench_resume import atomic_json
    manifest = json.loads((OUT / 'launch_manifest.json').read_text())
    report = completion_audit(OUT / 'canonical_latest.zip', OLD / 'canonical_latest.zip', manifest['expected'])
    report.update(checked_at=now(), canonical_sha256=sha(OUT / 'canonical_latest.zip'))
    atomic_json(OUT / 'completion_audit.json', report)
    print(json.dumps(report, indent=2))
