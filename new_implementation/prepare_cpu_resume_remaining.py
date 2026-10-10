"""Replay remaining historical work on CPU before spending GPU quota."""
import json
from pathlib import Path
import subprocess
import sys
import zipfile

from prepare_confibench_qwen import ROOT, CONFIG, RUN

TAG = 'cbq-replay-remaining-oct5'
OUT = ROOT / 'confibench_finish_20261005'

BOOT = '''
from pathlib import Path
import json, subprocess, sys, zipfile, time, shutil, os
INPUT=Path('/kaggle/input'); WORK=Path('/kaggle/working')
matches=list(INPUT.rglob('cbq-replay-remaining-oct5/XJ_BOUNDARY.json'))
assert len(matches)==1, matches
SRC=matches[0].parent
CB=WORK/'ConfiBench'
t0=time.time()
subprocess.run(['apt-get','update','-qq'],check=True,timeout=180)
subprocess.run(['apt-get','install','-y','-qq','iverilog'],check=True,timeout=180)
subprocess.run([sys.executable,'-m','pip','install','-q','loguru==0.7.3',
  'anthropic==0.49.0','openai==1.66.3','httpx==0.27.2','tiktoken'],check=True,timeout=300)
shutil.copytree(SRC/'ConfiBench',CB)
shutil.copytree(SRC/'resume_runtime',WORK/'cbq_runtime')
for old_progress in (WORK/'cbq_runtime').glob('*/progress.json'): old_progress.unlink()
os.environ['CBQ_RESUME_ROOT']=str(WORK/'cbq_runtime')
os.environ['CBQ_MAX_FRESH_CALLS']='0'
os.environ['OMP_NUM_THREADS']='1'
os.environ['OPENBLAS_NUM_THREADS']='1'
NP=4
sys.path.insert(0,str(CB))
from confibench_resume import self_test
self_test()
print('CPU replay: zero fresh calls, no model download, no GPU',flush=True)
'''


def main():
    global TAG
    if '--tag' in sys.argv:
        TAG = sys.argv[sys.argv.index('--tag')+1]
        assert all(c.isalnum() or c=='-' for c in TAG)
    OUT.mkdir(exist_ok=True)
    old = ROOT / 'confibench_finish_20261003'
    manifest = json.loads((OUT / 'launch_manifest.json').read_text())
    from monitor_resume_20261005 import archive_records
    from pathlib import PurePosixPath
    recorded = {PurePosixPath(name).parent.name
                for name in archive_records(OUT / 'canonical_latest.zip')
                if PurePosixPath(name).name == 'data.json'}
    remaining = sorted(set(manifest['expected']) - recorded)
    active = [job for job in manifest['jobs'] if job['submission'] == 'accepted'
              and not job.get('collected_at') and not job.get('audit_error')]
    if active:
        raise SystemExit('Collect active jobs before replaying their checkpoints')
    tasks = remaining
    diagnostic='--tasks-file' in sys.argv
    if diagnostic:
        selected=Path(sys.argv[sys.argv.index('--tasks-file')+1])
        tasks=[json.loads(line)['task_id'] for line in selected.read_text().splitlines() if line.strip()]
        assert set(tasks)<=set(remaining)
    assert len(tasks)==len(set(tasks)) and tasks
    task_file = OUT / 'cpu_replay_tasks.jsonl'
    task_file.write_text(''.join(json.dumps({'task_id': task})+'\n' for task in tasks))
    runtime = OUT / ('cpu_replay_seed.zip' if TAG=='cbq-replay-remaining-oct5' else TAG+'_seed.zip')
    if '--runtime-archive' in sys.argv:
        supplied=Path(sys.argv[sys.argv.index('--runtime-archive')+1])
        with zipfile.ZipFile(supplied) as z:
            assert z.testzip() is None
            payloads={name:z.read(name) for name in z.namelist() if name.split('/')[0] in tasks}
        with zipfile.ZipFile(runtime,'w',zipfile.ZIP_DEFLATED) as z:
            for name,payload in payloads.items(): z.writestr(name,payload)
    else:
        if TAG != 'cbq-replay-remaining-oct5':
            raise SystemExit('An explicit latest --runtime-archive is required for a new replay')
        with zipfile.ZipFile(runtime, 'w', zipfile.ZIP_DEFLATED) as z:
            for task in tasks:
                source = old / 'legacy_runtime_v2' / task
                assert (source / 'contract.json').is_file()
                for file in sorted(source.rglob('*.json')):
                    z.write(file, file.relative_to(old / 'legacy_runtime_v2').as_posix())
    subprocess.run([sys.executable,str(ROOT/'prepare_confibench_qwen.py'),'0','1',
                    '--tasks-file',str(task_file),'--tag',TAG,'--workers','4',
                    '--budget-hours','2','--max-fresh-calls','0',
                    '--runtime-prev',str(runtime)],check=True)
    bundle = ROOT / f'kaggle_upload_{TAG}'
    nb_file = bundle / 'kernel' / f'{TAG}.ipynb'
    nb = json.loads(nb_file.read_text())
    run = 'CONFIG = '+repr(CONFIG)+'\nMAX_WORKERS=4\nBUDGET_HOURS=2\n'+RUN % {'shard':0,'model':'qwen3.5-27b'}
    cells = [BOOT.replace('cbq-replay-remaining-oct5',TAG), run]
    for index, cell in enumerate(cells): compile(cell,f'<cpu replay {index}>','exec')
    nb['cells'] = [{'cell_type':'code','execution_count':None,'metadata':{},'outputs':[],
                    'source':cell.strip('\n').splitlines(keepends=True)} for cell in cells]
    nb_file.write_text(json.dumps(nb,indent=1),encoding='utf-8')
    metadata_file = bundle / 'kernel/kernel-metadata.json'
    meta = json.loads(metadata_file.read_text())
    meta.update(enable_gpu=False, title='ConfiBench Qwen '+TAG)
    meta.pop('machine_shape',None)
    metadata_file.write_text(json.dumps(meta,indent=1),encoding='utf-8')
    (OUT / 'cpu_replay_manifest.json').write_text(json.dumps({
        'tag':TAG,'bundle':str(bundle),'kernel_id':meta['id'],'account':1,
        'tasks':tasks,'gpu_enabled':False,'max_fresh_calls':0,
        'kind':'cpu_diagnostic' if diagnostic else 'cpu_replay',
        'require_cpu_frontier':True,
        'packed_diagnostics':True,
        'runtime_source':str(runtime),
        'submission':'staged'},indent=2),encoding='utf-8')
    print(f'Staged {len(tasks)}-task CPU replay; fresh generation forbidden.')


if __name__ == '__main__':
    main()
