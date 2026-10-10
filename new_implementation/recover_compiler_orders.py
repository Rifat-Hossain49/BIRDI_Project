"""Restore the first CPU replay's actual compiler order, without response edits."""
import json
from pathlib import Path, PurePosixPath
import sys
import zipfile

from confibench_resume import digest


def main():
    runtime,partial,target=map(Path,sys.argv[1:])
    with zipfile.ZipFile(runtime) as z:
        assert z.testzip() is None
        records={name:z.read(name) for name in z.namelist()}
    tasks={PurePosixPath(name).parts[0] for name in records if name.endswith('/contract.json')}
    orders={task:{} for task in tasks}
    with zipfile.ZipFile(partial) as z:
        assert z.testzip() is None
        for name in sorted(z.namelist()):
            path=PurePosixPath(name)
            if path.name!='vlist.txt': continue
            matches=[(index,part) for index,part in enumerate(path.parts) if part in tasks]
            if not matches: continue
            index,task=matches[-1]
            key='/'.join(path.parts[index+1:-1]) or '.'
            files=z.read(name).decode('utf-8').splitlines(keepends=True)
            if key in orders[task] and orders[task][key]!=files:
                raise ValueError('Ambiguous compiler order: '+task+'/'+key)
            orders[task][key]=files
    for task,mapping in orders.items():
        if not mapping: continue
        contract=json.loads(records[f'{task}/contract.json'])
        record={'contract':contract,'orders':mapping,'payload_sha256':digest(mapping)}
        name=f'{task}/compiler_orders.json'
        if name in records: raise ValueError('Refusing to replace existing compiler checkpoint')
        records[name]=json.dumps(record,sort_keys=True).encode('utf-8')
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
        for name,payload in sorted(records.items()): z.writestr(name,payload)
    print('Added historical compiler order for',sum(bool(v) for v in orders.values()),
          'tasks;',sum(len(v) for v in orders.values()),'directories; saved responses unchanged.')


if __name__=='__main__':
    main()
