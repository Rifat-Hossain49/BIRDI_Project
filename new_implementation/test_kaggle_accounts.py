"""Credential alias tests using synthetic values; no network or real .env."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / 'dirtb'))
import kaggle_rotate as k


class KaggleAccountTests(unittest.TestCase):
    def test_gpu_push_explicitly_requests_the_metadata_accelerator(self):
        self.assertEqual(k.kernel_push_args({'enable_gpu': True, 'machine_shape': 'NvidiaTeslaT4'}),
                         ['kernels', 'push', '-p', '.', '--accelerator', 'NvidiaTeslaT4'])
        self.assertEqual(k.kernel_push_args({'enable_gpu': True}),
                         ['kernels', 'push', '-p', '.', '--accelerator', 'NvidiaTeslaT4'])

    def test_cpu_replay_never_requests_an_accelerator(self):
        self.assertEqual(k.kernel_push_args({'enable_gpu': False, 'machine_shape': 'NvidiaTeslaT4'}),
                         ['kernels', 'push', '-p', '.'])
        self.assertEqual(k.kernel_push_args({'enable_gpu': 'false'}), ['kernels', 'push', '-p', '.'])

    def account_fixture(self, directory, text):
        root = Path(directory)
        env = root / '.env'
        env.write_text(text, encoding='utf-8')
        names = root / 'accounts.json'
        names.write_text(json.dumps({'1': 'primary', '7': 'extra'}), encoding='utf-8')
        return env, names

    def test_gpu_alias_and_existing_account_are_both_loaded(self):
        with tempfile.TemporaryDirectory() as directory:
            env, names = self.account_fixture(directory,
                'KAGGLE_API_TOKEN=primary-test\nGPU_KAGGLE_API_TOKEN=extra-test\n')
            with patch.object(k, 'ENV', env), patch.object(k, 'ACCOUNTS_FILE', names), \
                    patch.dict(os.environ, {}, clear=True):
                self.assertEqual(k.accounts(), {
                    1: {'token': 'primary-test', 'user': 'primary'},
                    7: {'token': 'extra-test', 'user': 'extra'}})

    def test_process_environment_overrides_file_without_rewriting_it(self):
        with tempfile.TemporaryDirectory() as directory:
            env, names = self.account_fixture(directory, 'GPU_KAGGLE_API_TOKEN=file-test\n')
            with patch.object(k, 'ENV', env), patch.object(k, 'ACCOUNTS_FILE', names), \
                    patch.dict(os.environ, {'GPU_KAGGLE_API_TOKEN': 'process-test'}, clear=True):
                self.assertEqual(k.accounts()[7]['token'], 'process-test')
            self.assertEqual(env.read_text(), 'GPU_KAGGLE_API_TOKEN=file-test\n')

    def test_numbered_alias_has_existing_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            env, names = self.account_fixture(directory,
                'KAGGLE_API_TOKEN_7=numbered-test\nGPU_KAGGLE_API_TOKEN=extra-test\n')
            with patch.object(k, 'ENV', env), patch.object(k, 'ACCOUNTS_FILE', names), \
                    patch.dict(os.environ, {}, clear=True):
                self.assertEqual(k.accounts()[7]['token'], 'numbered-test')

    def test_email_alone_does_not_enable_account(self):
        with tempfile.TemporaryDirectory() as directory:
            env, names = self.account_fixture(directory,
                'GPU_KAGGLE_EMAIL=synthetic@example.invalid\nGPU_KAGGLE_API_TOKEN=\n')
            with patch.object(k, 'ENV', env), patch.object(k, 'ACCOUNTS_FILE', names), \
                    patch.dict(os.environ, {}, clear=True):
                self.assertEqual(k.accounts(), {})


if __name__ == '__main__':
    unittest.main()
