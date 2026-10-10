"""Explain exact-request replay conflicts without weakening journal checks."""
import difflib
import json
from pathlib import Path, PurePosixPath
import sys
import zipfile

from confibench_resume import digest


def main():
    archive=Path(sys.argv[1])
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for name in z.namelist():
            if '/replay_conflicts/' not in name: continue
            conflict=json.loads(z.read(name))
            task=PurePosixPath(name).parts[0]
            key=digest(conflict['scope'])
            saved=json.loads(z.read(f"{task}/calls/{key}/{conflict['number']:06d}.json"))
            old=dict(conflict['request'],messages=saved['output'][1]['messages'][:-1])
            print(task,'saved request reconstructs:',digest(old)==saved['request_sha256'])
            for before,after in zip(old['messages'],conflict['request']['messages']):
                diff='\n'.join(difflib.unified_diff(before['content'].splitlines(),after['content'].splitlines(),
                             fromfile='saved',tofile='current',n=1))
                if diff: print(diff[-7000:])


if __name__=='__main__':
    main()
