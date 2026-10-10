"""The launch hold permits only the exact approved GPU bundle and account."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent / 'dirtb'))
from kaggle_rotate import check_launch_hold


class LaunchHoldTests(unittest.TestCase):
    def test_exact_bundle_only(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            hold = root / 'GPU_LAUNCH_HOLD'
            hold.touch()
            bundle = root / 'bundle'
            kernel = bundle / 'kernel'
            dataset = bundle / 'dataset_publish'
            kernel.mkdir(parents=True)
            dataset.mkdir()
            metadata = {'id': 'owner/confibench-qwen-pilot', 'enable_gpu': True,
                        'code_file': 'pilot.ipynb'}
            (kernel / 'kernel-metadata.json').write_text(json.dumps(metadata))
            (kernel / 'pilot.ipynb').write_bytes(b'notebook')
            (dataset / 'pilot.zip').write_bytes(b'dataset')
            with self.assertRaises(SystemExit):
                check_launch_hold(bundle, 1, hold)
            approval = {'kernel_id': metadata['id'], 'account': 1,
                        'notebook_sha256': hashlib.sha256(b'notebook').hexdigest(),
                        'dataset_sha256': hashlib.sha256(b'dataset').hexdigest()}
            hold.with_name('GPU_APPROVED_BUNDLES.json').write_text(json.dumps([approval]))
            check_launch_hold(bundle, 1, hold)
            with self.assertRaises(SystemExit):
                check_launch_hold(bundle, 2, hold)
            (dataset / 'pilot.zip').write_bytes(b'changed')
            with self.assertRaises(SystemExit):
                check_launch_hold(bundle, 1, hold)
            metadata['enable_gpu'] = False
            (kernel / 'kernel-metadata.json').write_text(json.dumps(metadata))
            check_launch_hold(bundle, 1, hold)


if __name__ == '__main__':
    unittest.main()
