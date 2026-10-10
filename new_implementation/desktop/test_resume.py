"""Offline migration tests: no Docker, network, model download or GPU."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from desktop import resume as r


class DesktopResumeTests(unittest.TestCase):
    def fixture(self, root):
        impl, work, downloads = root / 'impl', root / 'work', root / 'downloads'
        (impl / 'desktop').mkdir(parents=True)
        downloads.mkdir()
        original = root / 'canonical.zip'
        with zipfile.ZipFile(original, 'w') as archive:
            archive.writestr('saves/session/done/data.json', json.dumps({'task_id': 'done'}))
        runtime = root / 'runtime.zip'
        with zipfile.ZipFile(runtime, 'w') as archive:
            archive.writestr('pending/contract.json', json.dumps({'profile': 'frozen'}))
        payloads = {'canonical_latest.zip': original.read_bytes(), 'runtime_latest.zip': runtime.read_bytes(),
                    'ConfiBench/resume_profile.json': b'{"profile":"frozen"}'}
        asset = downloads / 'seed.zip'
        with zipfile.ZipFile(asset, 'w') as archive:
            for name, value in payloads.items():
                archive.writestr(name, value)
        manifest = {'asset': asset.name, 'sha256': r.file_sha(asset), 'expected': ['done', 'pending'],
                    'members': {name: hashlib.sha256(value).hexdigest() for name, value in payloads.items()}}
        (impl / 'desktop/checkpoint_manifest.json').write_text(json.dumps(manifest))
        return impl, work, downloads, manifest

    def context(self, impl, work):
        return patch.multiple(r, IMPL=impl, WORK=work, CB=work / 'ConfiBench', RUNTIME=work / 'cbq_runtime')

    def test_restore_preserves_originals_and_restart_preserves_new_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            impl, work, downloads, manifest = self.fixture(Path(directory))
            with self.context(impl, work):
                self.assertEqual(r.prepare(downloads), manifest)
                r.verify_first_records()
                (r.RUNTIME / 'pending/progress.json').write_text('{"fresh":1}')
                r.prepare(downloads)
                self.assertEqual((r.RUNTIME / 'pending/progress.json').read_text(), '{"fresh":1}')
                r.checkpoint(manifest)
                state = json.loads((work / 'desktop_completion.json').read_text())
                self.assertEqual(state['recorded'], ['done'])
                self.assertEqual(state['remaining'], ['pending'])

    def test_refuses_to_overwrite_an_existing_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            impl, work, downloads, _ = self.fixture(Path(directory))
            with self.context(impl, work):
                r.RUNTIME.mkdir(parents=True)
                with self.assertRaisesRegex(ValueError, 'refusing to overwrite'):
                    r.prepare(downloads)

    def test_tampered_archive_or_first_record_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            impl, work, downloads, manifest = self.fixture(Path(directory))
            with self.context(impl, work):
                asset = downloads / manifest['asset']
                original = asset.read_bytes()
                asset.write_bytes(original + b'tampered')
                with self.assertRaisesRegex(ValueError, 'SHA256'):
                    r.prepare(downloads)
                asset.write_bytes(original)
                r.prepare(downloads)
                r.completed()['done'].write_text('{"task_id":"done","changed":true}')
                with self.assertRaisesRegex(ValueError, 'first record was changed'):
                    r.verify_first_records()

    def test_archive_traversal_and_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for filename in ('../escape', '/absolute', 'nested\\escape'):
                asset = root / 'bad.zip'
                with zipfile.ZipFile(asset, 'w') as archive:
                    entry = zipfile.ZipInfo('safe')
                    entry.filename = filename
                    archive.writestr(entry, 'bad')
                with self.assertRaisesRegex(ValueError, 'Unsafe'):
                    r.extract(asset, root / 'output')
            info = zipfile.ZipInfo('link')
            info.create_system = 3
            info.external_attr = 0o120777 << 16
            with zipfile.ZipFile(asset, 'w') as archive:
                archive.writestr(info, '/escape')
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                r.extract(asset, root / 'output')


if __name__ == '__main__':
    unittest.main()
