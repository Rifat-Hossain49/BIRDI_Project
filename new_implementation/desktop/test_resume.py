"""Offline migration tests: no Docker, network, model download or GPU."""
import hashlib
import json
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

import yaml

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

    def test_checkpoint_tolerates_files_removed_by_live_workers(self):
        with tempfile.TemporaryDirectory() as directory:
            impl, work, downloads, manifest = self.fixture(Path(directory))
            with self.context(impl, work):
                r.prepare(downloads)
                frontier = r.RUNTIME / 'pending/next_request.json'
                frontier.write_text('{}')
                listed = sorted(r.RUNTIME.rglob('*.json'))
                frontier.unlink()
                with patch.object(Path, 'rglob', lambda self, pattern: iter(listed) if self == r.RUNTIME
                                  else Path.glob(self, '**/' + pattern)):
                    r.checkpoint(manifest)
                with zipfile.ZipFile(work / 'desktop_runtime.zip') as archive:
                    self.assertEqual(archive.namelist(), ['pending/contract.json'])

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

    def test_concurrent_workers_get_distinct_valid_save_prefixes(self):
        tasks = ['2013_q2bfsm', '2014_q3fsm', 'review2015_fancytimer']
        configs = [yaml.safe_load(r.worker_config(task)) for task in tasks]
        prefixes = [config['save']['pub']['prefix'] for config in configs]
        self.assertEqual(len(set(prefixes)), len(tasks))
        for task, config, prefix in zip(tasks, configs, prefixes):
            # Must stay a valid save-root name for confibench_resume.iteration_directory.
            self.assertTrue(re.fullmatch(r'[A-Za-z0-9_]+', prefix + '_20261010_100117'))
            self.assertEqual(config['autoline']['probset']['only'], [task])
            self.assertEqual(config['autoline']['itermax'], 10)
            self.assertEqual(config['autoline']['TBcheck']['rtl_num'], 20)

    def fake_process(self, proc, pid, ppid, state='S', command=b'vvp\0run.vvp\0'):
        entry = proc / str(pid)
        entry.mkdir()
        (entry / 'status').write_text(f'Name:\tx\nState:\t{state} (sleeping)\nPPid:\t{ppid}\n')
        (entry / 'cmdline').write_bytes(command)

    def test_only_orphans_outside_keep_are_killed_and_logged(self):
        with tempfile.TemporaryDirectory() as directory:
            proc, work = Path(directory) / 'proc', Path(directory) / 'work'
            proc.mkdir()
            work.mkdir()
            (proc / 'self').mkdir()
            self.fake_process(proc, 10, 1)
            self.fake_process(proc, 11, 1, command=b'python\0main.py\0')
            self.fake_process(proc, 12, 10)
            self.fake_process(proc, 13, 1, state='Z')
            with patch.multiple(r, PROC=proc, WORK=work), patch.object(r.os, 'kill') as kill, \
                    patch.object(r.os, 'waitpid') as waitpid:
                self.assertEqual(r.reap_orphans({1, 11}), 1)
            kill.assert_called_once_with(10, r.signal.SIGKILL)
            self.assertEqual(sorted(call.args[0] for call in waitpid.call_args_list), [10, 13])
            self.assertIn('vvp run.vvp', (work / 'desktop_reaped.log').read_text())

    def test_disk_growth_guard_stops_before_host_fills(self):
        with patch.object(r.shutil, 'disk_usage', return_value=SimpleNamespace(used=10 + r.DISK_GROWTH_LIMIT)):
            r.check_disk(10)
            with self.assertRaisesRegex(RuntimeError, 'stopping before the host drive fills'):
                r.check_disk(9)

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
