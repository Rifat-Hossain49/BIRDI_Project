"""Check the official binary's Linux ABI on Kaggle CPU before another GPU launch."""
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
TAG='cbq-runtime-probe-oct5'


def main():
    subprocess.run([sys.executable,str(ROOT/'prepare_confibench_qwen.py'),'0','1',
                    '--tasks-file',str(ROOT/'confibench_finish_20261003/cpu_pilot_task.jsonl'),
                    '--tag',TAG,'--workers','1','--budget-hours','.25',
                    '--max-fresh-calls','0','--prebuilt-server'],check=True)
    bundle=ROOT/f'kaggle_upload_{TAG}'
    code='''
from pathlib import Path
import json,subprocess,sys
roots=list(Path('/kaggle/input').rglob('cbq-runtime-probe-oct5/install_llama_release.py'))
assert len(roots)==1, roots
subprocess.run([sys.executable,str(roots[0]),'--root','/tmp/llama-runtime',
 '--manifest','/kaggle/working/engine_provenance.json'],check=True,timeout=600)
print('CPU-only binary compatibility probe passed; no model download or generation.',flush=True)
'''
    compile(code,'<runtime probe>','exec')
    nb_file=bundle/'kernel'/f'{TAG}.ipynb'
    nb=json.loads(nb_file.read_text())
    nb['cells']=[{'cell_type':'code','execution_count':None,'metadata':{},'outputs':[],
                  'source':code.strip('\n').splitlines(keepends=True)}]
    nb_file.write_text(json.dumps(nb,indent=1),encoding='utf-8')
    meta_file=bundle/'kernel/kernel-metadata.json'
    meta=json.loads(meta_file.read_text())
    meta['enable_gpu']=False
    meta.pop('machine_shape',None)
    meta_file.write_text(json.dumps(meta,indent=1),encoding='utf-8')
    print('Staged private CPU-only binary probe; GPU and model downloads disabled.')


if __name__=='__main__':
    main()
