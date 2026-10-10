import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from verify_resume_completion import completion_audit


def archive(path, records):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as target:
        for name, record in records.items():
            target.writestr(name, json.dumps(record, sort_keys=True))


class CompletionAuditTests(unittest.TestCase):
    def test_failures_retained_and_coverage_not_pass_count(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = {'a/data.json': {'task_id': 'a', 'ERROR(incomplete)': True,
                                       'Eval1_pass': False, 'Eval2_pass': False}}
            archive(root/'baseline.zip', original)
            archive(root/'canonical.zip', original)
            report = completion_audit(root/'canonical.zip', root/'baseline.zip', ['a', 'b'])
            self.assertEqual(report['missing'], ['b'])
            self.assertEqual(report['error_flagged_tasks'], ['a'])
            self.assertFalse(report['all_tasks_recorded'])
            archive(root/'canonical.zip', dict(original, **{'b/data.json': {'task_id': 'b'}}))
            report = completion_audit(root/'canonical.zip', root/'baseline.zip', ['a', 'b'])
            self.assertTrue(report['all_tasks_recorded'])
            self.assertEqual(report['outcomes_unavailable_tasks'], ['b'])

    def test_rejects_identity_duplicates_and_changed_originals(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = {'a/data.json': {'task_id': 'a'}}
            archive(root/'baseline.zip', original)
            bad_records = [
                {'a/data.json': {'task_id': 'different'}},
                {'a/data.json': {'task_id': 'a'}, 'other/a/data.json': {'task_id': 'a'}},
                {'a/data.json': {'task_id': 'a', 'changed': True}},
                {'../a/data.json': {'task_id': 'a'}},
                {'unexpected/data.json': {'task_id': 'unexpected'}}
            ]
            for bad in bad_records:
                with self.subTest(bad=bad):
                    archive(root/'canonical.zip', bad)
                    with self.assertRaises(ValueError):
                        completion_audit(root/'canonical.zip', root/'baseline.zip', ['a'])


if __name__ == '__main__':
    unittest.main()
