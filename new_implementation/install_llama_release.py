"""Install checksum-pinned official Linux CUDA binaries, without a source build."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import urllib.request

TAG='b11399'
ASSETS=[
    ('llama-b11399-bin-ubuntu-cuda-12.8-x64.tar.gz',
     'eab8601a1a286530c289ff717ceb5976c1479e0760105bfca545cd150c7a934d'),
    ('cudart-llama-b11399-bin-ubuntu-cuda-12.8-x64.tar.gz',
     'd0e9800045ee60fc9a57ae0fe208a2f4ba33ac3181572ee8c0e763aeb7a6423d')]


def install_asset(root,name,expected):
    url=f'https://github.com/ggml-org/llama.cpp/releases/download/{TAG}/{name}'
    archive=root/name
    digest=hashlib.sha256()
    req=urllib.request.Request(url,headers={'User-Agent':'BIRDI-benchmark-runtime'})
    with urllib.request.urlopen(req,timeout=60) as response,archive.open('wb') as file:
        while block:=response.read(4*1024*1024):
            file.write(block)
            digest.update(block)
    if digest.hexdigest()!=expected:
        raise RuntimeError(f'Official release checksum mismatch: {name}')
    with tarfile.open(archive,'r:gz') as tar:
        tar.extractall(root,filter='data')
    archive.unlink()
    return {'url':url,'sha256':expected}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    args=parser.parse_args()
    root=args.root.resolve()
    root.mkdir(parents=True,exist_ok=True)
    assets=[install_asset(root,*ASSETS[0])]
    servers=list(root.rglob('llama-server'))
    backends=list(root.rglob('libggml-cuda.so*'))
    assert len(servers)==1 and backends,'Release lacks server or CUDA backend'
    directories=sorted({str(file.parent) for file in root.rglob('*.so*')})
    env=dict(os.environ,LD_LIBRARY_PATH=':'.join(directories)+':'+os.environ.get('LD_LIBRARY_PATH',''))
    dependencies=subprocess.run(['ldd',str(backends[0])],env=env,capture_output=True,text=True,check=True)
    if 'not found' in dependencies.stdout:
        assets.append(install_asset(root,*ASSETS[1]))
        directories=sorted({str(file.parent) for file in root.rglob('*.so*')})
        env['LD_LIBRARY_PATH']=':'.join(directories)+':'+os.environ.get('LD_LIBRARY_PATH','')
        dependencies=subprocess.run(['ldd',str(backends[0])],env=env,capture_output=True,text=True,check=True)
    # A CPU-only compatibility probe can legitimately lack the NVIDIA driver.
    missing=[line.strip() for line in dependencies.stdout.splitlines() if 'not found' in line]
    unexpected=[line for line in missing if not line.startswith('libcuda.so')]
    assert not unexpected, unexpected
    version=subprocess.run([str(servers[0]),'--version'],env=env,capture_output=True,text=True,timeout=30)
    assert version.returncode==0, version.stdout+version.stderr
    manifest={'release':TAG,'assets':assets,'server':str(servers[0]),
              'ld_library_path':env['LD_LIBRARY_PATH'],
              'version':version.stdout+version.stderr,'missing_driver':missing,
              'cuda_backend':str(backends[0]),'source_build':False}
    args.manifest.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(manifest,indent=2),flush=True)


if __name__=='__main__':
    main()
