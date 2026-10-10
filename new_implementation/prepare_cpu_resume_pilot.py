"""Stage one interruption/replay pilot. GPU and fresh model calls are disabled."""
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from prepare_confibench_qwen import ROOT, CONFIG

TAG = 'cbq-replay-cpu-oct4'
TASK = 'ece241_2014_q4'

BOOT = '''
from pathlib import Path
import json, subprocess, sys, zipfile, time, shutil, os, signal
INPUT=Path('/kaggle/input'); WORK=Path('/kaggle/working')
matches=list(INPUT.rglob('cbq-replay-cpu-oct4/XJ_BOUNDARY.json'))
assert len(matches)==1, matches
SRC=matches[0].parent
CB=WORK/'ConfiBench'
shutil.copytree(SRC/'ConfiBench', CB)
subprocess.run(['apt-get','update','-qq'],check=True,timeout=180)
subprocess.run(['apt-get','install','-y','-qq','iverilog'],check=True,timeout=180)
subprocess.run([sys.executable,'-m','pip','install','-q','loguru==0.7.3',
  'anthropic==0.49.0','openai==1.66.3','httpx==0.27.2','tiktoken'],check=True,timeout=300)
shutil.copytree(SRC/'resume_runtime', WORK/'cbq_runtime')
initial_state=WORK/'cbq_runtime'/'ece241_2014_q4'/'iteration.json'
initial_next_iteration=json.loads(initial_state.read_text())['payload']['next_iteration'] if initial_state.exists() else 0
assert initial_next_iteration==EXPECTED_NEXT_ITERATION, 'Mounted stale runtime checkpoint'
initial_progress=WORK/'cbq_runtime'/'ece241_2014_q4'/'progress.json'
if initial_progress.exists(): initial_progress.unlink()
os.environ['CBQ_RESUME_ROOT']=str(WORK/'cbq_runtime')
os.environ['CBQ_MAX_FRESH_CALLS']='0'
sys.path.insert(0,str(CB))
from confibench_resume import self_test
self_test()
print('CPU ONLY: no model server, no model download, zero fresh-call budget',flush=True)
'''

PILOT = '''
task='ece241_2014_q4'
(CB/'config/configs/cpu_replay.yaml').write_text(CONFIG % {'prefix':'CPUReplay',
 'model':'qwen3.5-27b','only':json.dumps([task])})
env=dict(os.environ, PYTHONUNBUFFERED='1')
def start(log):
 return subprocess.Popen([sys.executable,'main.py','-c','cpu_replay'],cwd=CB,
   env=env,stdout=open(WORK/log,'w'),stderr=subprocess.STDOUT,start_new_session=True)
def stop(p):
 if p.poll() is None:
  os.killpg(p.pid,signal.SIGTERM)
  try: p.wait(timeout=5)
  except subprocess.TimeoutExpired:
   os.killpg(p.pid,signal.SIGKILL); p.wait(timeout=5)
progress=WORK/'cbq_runtime'/task/'progress.json'
p=start('cpu_phase1.log')
deadline=time.monotonic()+180
phase1={}
while p.poll() is None and time.monotonic()<deadline:
 if progress.exists():
  phase1=json.loads(progress.read_text())
  if phase1['replayed_this_session']>=4: break
 time.sleep(.05)
stop(p)
assert phase1.get('replayed_this_session',0)>=4, 'First phase never reached four replayed calls'
assert phase1.get('fresh_this_session')==0
calls_dir=WORK/'cbq_runtime'/task/'calls'
first_records={str(f.relative_to(calls_dir)):f.read_bytes() for f in calls_dir.rglob('*.json')}
print('Forced interruption after',phase1['replayed_this_session'],'replayed calls; saved',len(first_records),flush=True)
progress.unlink()
p=start('cpu_phase2.log')
try: p.wait(timeout=300)
except subprocess.TimeoutExpired: stop(p)
assert progress.exists(), 'Restart produced no new replay heartbeat; inspect cpu_phase2.log'
phase2=json.loads(progress.read_text())
assert phase2['fresh_this_session']==0
assert phase2['replayed_this_session']>=4, 'Restart did not replay the saved prefix'
for name,payload in first_records.items():
 assert (calls_dir/name).read_bytes()==payload, 'Response changed across resume'
report={'task':task,'gpu_enabled':False,'model_downloaded':False,'fresh_model_calls':0,
 'initial_next_iteration':initial_next_iteration,
 'phase1_replayed':phase1['replayed_this_session'],'phase2_replayed':phase2['replayed_this_session'],
 'phase2_exit_code':p.returncode,'saved_responses_unchanged':True,
 'restarted_prefix_replayed':True,
 'full_task_completed':any((CB/'saves').rglob('data.json')),
 'phase2_last_log':(WORK/'cpu_phase2.log').read_text()[-2500:]}
if initial_next_iteration:
 marker='next_iteration='+str(initial_next_iteration)
 assert marker in (WORK/'cpu_phase1.log').read_text(), 'First phase did not restore iteration state'
 assert marker in (WORK/'cpu_phase2.log').read_text(), 'Second phase did not restore iteration state'
 report['iteration_boundary_restore_verified']=True
(WORK/'cpu_resume_report.json').write_text(json.dumps(report,indent=2))
with zipfile.ZipFile(WORK/'cpu_runtime.zip','w',zipfile.ZIP_DEFLATED) as z:
 for f in (WORK/'cbq_runtime').rglob('*.json'): z.write(f,f.relative_to(WORK/'cbq_runtime').as_posix())
print(json.dumps(report,indent=2),flush=True)
print('This is a replay validation artifact, NOT a new scored benchmark result.',flush=True)
'''


def main():
    out=ROOT/'confibench_finish_20261003'
    tasks=out/'cpu_pilot_task.jsonl'
    tasks.write_text(json.dumps({'task_id':TASK})+'\n')
    runtime=out/'cpu_pilot_runtime.zip'
    expected_next = 0
    if '--runtime-archive' in sys.argv:
        supplied=Path(sys.argv[sys.argv.index('--runtime-archive')+1])
        with zipfile.ZipFile(supplied) as z:
            assert z.testzip() is None
            record=json.loads(z.read(TASK+'/iteration.json'))
            expected_next=record['payload']['next_iteration']
            assert expected_next>0
        shutil.copy2(supplied,runtime)
    else:
        with zipfile.ZipFile(runtime,'w',zipfile.ZIP_DEFLATED) as z:
            for f in (out/'legacy_runtime_v2'/TASK).rglob('*.json'):
                z.write(f,f.relative_to(out/'legacy_runtime_v2').as_posix())
    subprocess.run([sys.executable,str(ROOT/'prepare_confibench_qwen.py'),'0','1','--tasks-file',str(tasks),
                    '--tag',TAG,'--workers','1','--budget-hours','0.25','--max-fresh-calls','0',
                    '--runtime-prev',str(runtime)],check=True)
    bundle=ROOT/f'kaggle_upload_{TAG}'
    nb_file=bundle/'kernel'/f'{TAG}.ipynb'
    nb=json.loads(nb_file.read_text())
    cells=['EXPECTED_NEXT_ITERATION = '+repr(expected_next)+'\n'+BOOT,'CONFIG = '+repr(CONFIG)+'\n'+PILOT]
    for i,c in enumerate(cells): compile(c,f'<cpu pilot cell {i}>','exec')
    nb['cells']=[{'cell_type':'code','metadata':{},'execution_count':None,'outputs':[],
                  'source':c.splitlines(keepends=True)} for c in cells]
    nb_file.write_text(json.dumps(nb,indent=1))
    meta_file=bundle/'kernel/kernel-metadata.json'
    meta=json.loads(meta_file.read_text())
    meta['enable_gpu']=False
    meta.pop('machine_shape',None)
    meta['title']='ConfiBench CPU-only interruption replay validation'
    meta['id']='tishaferdous/confibench-cpu-only-interruption-replay-validation'
    meta_file.write_text(json.dumps(meta,indent=1))
    assert meta['enable_gpu'] is False
    print('CPU-only pilot staged. Zero GPU quota; zero fresh model requests.')


if __name__=='__main__': main()
