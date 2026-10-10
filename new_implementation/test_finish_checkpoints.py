"""Exercise notebook checkpoint publication on incomplete and completed files."""
import json
import os
import tempfile
import time
import zipfile
from pathlib import Path

from prepare_confibench_qwen import RUN


def main():
    with tempfile.TemporaryDirectory() as temp:
        work = Path(temp)
        cb = work / 'ConfiBench'
        src = work / 'source'
        src.mkdir()
        (src / 'shard_tasks.json').write_text('{"task_id":"a"}\n{"task_id":"b"}\n')
        good = cb / 'saves/run/a'
        bad = cb / 'saves/run/b'
        good.mkdir(parents=True)
        bad.mkdir(parents=True)
        (good / 'data.json').write_text('{"task_id":"a","Eval1_pass":false}')
        (good / 'wave.vcd').write_bytes(b'large simulation data')
        (bad / 'data.json').write_text('{"task_id":')
        env = {'SRC': src, 'WORK': work, 'CB': cb, 'json': json, 'zipfile': zipfile,
               'os': os, 'time': time, 'procs': []}
        exec(RUN.split('todo = ')[0], env)
        env['checkpoint']()
        assert json.loads((work / 'cbq_completion.json').read_text())['unresolved_tasks'] == ['b']
        with zipfile.ZipFile(work / 'cbq_saves.zip') as z:
            assert z.namelist() == ['saves/run/a/data.json']
            assert z.testzip() is None
        (bad / 'data.json').write_text('{"task_id":"b","Eval1_pass":true}')
        env['checkpoint']()
        assert json.loads((work / 'cbq_completion.json').read_text())['all_tasks_checkpointed']
        with zipfile.ZipFile(work / 'cbq_saves.zip') as z:
            assert len(z.namelist()) == 2 and z.testzip() is None
    print('Checkpoint tests passed: malformed file excluded, failed result retained, atomic update verified.')


if __name__ == '__main__':
    main()
