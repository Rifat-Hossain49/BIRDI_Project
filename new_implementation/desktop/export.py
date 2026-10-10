"""Build a credential-free source snapshot and lossless release-asset handoff."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import zipfile

SOURCE = Path(__file__).resolve().parents[2]
IMPL = SOURCE / 'new_implementation'
sys.path.insert(0, str(IMPL))
from confibench_resume import atomic_json
from monitor_resume_20261005 import archive_records, completion_audit

OUT = SOURCE / 'deliverables/desktop_handoff_20261010'
TREE = OUT / 'source/BIRDI'
ASSETS = OUT / 'release'
TAG = 'desktop-handoff-20261010'
TOKEN = re.compile(rb'(?:KGAT_[A-Za-z0-9]{16,}|hf_[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,})')
SKIP = {'.git', '__pycache__', '.pytest_cache', '.ipynb_checkpoints', 'node_modules',
        'figs', 'saves', 'AutoBenchResults', 'CorrectBenchResults', 'ConfiBenchResults',
        'discarded', 'original_data_human', 'extracted'}
KNOWN = []
REDACTED = []


def sha(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        while block := source.read(8 << 20):
            value.update(block)
    return value.hexdigest()


def unsafe(payload):
    return bool(TOKEN.search(payload) or any(secret in payload for secret in KNOWN))


def scan_file(path):
    tail = b''
    with path.open('rb') as source:
        while block := source.read(8 << 20):
            part = tail + block
            if unsafe(part):
                raise ValueError('Credential-like bytes found; refusing export: ' + str(path.relative_to(SOURCE)))
            tail = part[-1024:]


def scan_zip(path):
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            parts = Path(name.replace('\\', '/')).parts
            if any(part == '.env' or part.startswith('.env.') and part != '.env.example' for part in parts):
                raise ValueError('Environment file in archive: ' + str(path.relative_to(SOURCE)))
            if name.lower().endswith(('.json', '.jsonl', '.py', '.yaml', '.yml', '.txt', '.md', '.ipynb', '.log', '.csv')):
                with archive.open(name) as stream:
                    tail = b''
                    while block := stream.read(8 << 20):
                        part = tail + block
                        if unsafe(part):
                            raise ValueError('Credential-like content in archive member: ' + str(path.relative_to(SOURCE)) + ':' + name)
                        tail = part[-1024:]


def copy_source(path):
    relative = path.relative_to(SOURCE)
    if (path.name == '.env' or path.name.startswith('.env.') and path.name != '.env.example'
            or path.suffix in ('.pyc', '.zip', '.pt', '.npy', '.gguf')):
        return
    payload = path.read_bytes()
    if unsafe(payload):
        if 'ConfiBench' in relative.parts:
            raise ValueError('Cannot redact immutable baseline source: ' + str(relative))
        for secret in KNOWN:
            payload = payload.replace(secret, b'<REDACTED_SECRET>')
        payload = TOKEN.sub(b'<REDACTED_SECRET>', payload)
        REDACTED.append(relative.as_posix())
    target = TREE / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)


def copy_tree(path):
    for directory, dirs, names in os.walk(path):
        dirs[:] = sorted(d for d in dirs if d not in SKIP and not d.startswith('kaggle_upload'))
        for name in sorted(names):
            file = Path(directory) / name
            if file.is_symlink():
                raise ValueError('Unexpected symlink in selected source: ' + str(file))
            copy_source(file)


def make_resume_asset():
    finished = IMPL / 'confibench_finish_20261005'
    old = IMPL / 'confibench_finish_20261003/canonical_latest.zip'
    canonical = finished / 'canonical_latest.zip'
    runtime = IMPL / 'kaggle_runs/cbq-cpu-frontier-v2-oct7_collected/cbq_runtime.zip'
    baseline = IMPL / 'kaggle_upload_cbq-cpu-frontier-v2-oct7/dataset/cbq-cpu-frontier-v2-oct7/ConfiBench'
    assert baseline.is_dir(), baseline
    manifest = json.loads((finished / 'launch_manifest.json').read_text())
    audit = completion_audit(canonical, old, manifest['expected'])
    assert audit['recorded'] == 140 and audit['original_records_preserved'] == 138
    assert len(audit['missing']) == 16
    records = archive_records(runtime)
    assert {name.split('/')[0] for name in records} == set(audit['missing'])
    prepared_profile = json.loads((baseline / 'resume_profile.json').read_text())['profile']
    assert all(json.loads(payload)['profile'] == prepared_profile for name, payload in records.items() if name.endswith('/contract.json'))
    members = {'canonical_latest.zip': canonical, 'original_first_records.zip': old,
               'runtime_latest.zip': runtime, 'completion_audit.json': finished / 'completion_audit.json'}
    for file in sorted(baseline.rglob('*')):
        if file.is_file() and not any(part in SKIP for part in file.relative_to(baseline).parts):
            members['ConfiBench/' + file.relative_to(baseline).as_posix()] = file
    asset = ASSETS / 'birdi-desktop-resume-20261010.zip'
    hashes = {}
    with zipfile.ZipFile(asset.with_suffix('.tmp'), 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, path in members.items():
            scan_file(path)
            if path.suffix == '.zip':
                scan_zip(path)
            hashes[name] = sha(path)
            archive.write(path, name)
    os.replace(asset.with_suffix('.tmp'), asset)
    result = {'asset': asset.name, 'sha256': sha(asset), 'release': TAG, 'members': hashes,
              'expected': manifest['expected'], 'recorded': 140, 'remaining': audit['missing'],
              'profile': prepared_profile, 'model': 'unsloth/Qwen3.5-27B-GGUF/Qwen3.5-27B-Q4_K_M.gguf',
              'thinking': False, 'population': 20, 'iterations': 10}
    atomic_json(IMPL / 'desktop/checkpoint_manifest.json', result)
    copy_source(IMPL / 'desktop/checkpoint_manifest.json')
    print('Resume asset verified: 140 first records, 16 journals, original 138 unchanged.', flush=True)


def history_files():
    selected = set()
    for root in (IMPL / 'kaggle_runs', SOURCE / 'artifacts/kaggle_runs', SOURCE / 'output', SOURCE / 'outputs'):
        for directory, dirs, names in os.walk(root):
            dirs[:] = sorted(d for d in dirs if d not in SKIP and 'extracted' not in d)
            for name in names:
                file = Path(directory) / name
                if file.suffix.lower() in ('.zip', '.pt', '.npy', '.csv', '.json', '.jsonl', '.md', '.log', '.v', '.sv'):
                    selected.add(file)
    selected.add(IMPL / 'baselines/confibench_drive/TODAES_opensource_result.zip')
    for folder in (IMPL / 'confibench_finish_20261003', IMPL / 'confibench_finish_20261005',
                   IMPL / 'confibench_remaining_20260927', IMPL / 'confibench_remaining_20260928'):
        selected.update(p for p in folder.glob('*') if p.is_file() and p.suffix in ('.zip', '.json', '.jsonl', '.md', '.log'))
    return sorted(selected)


def make_history_assets():
    entries, seen, rejected = [], {}, []
    archive = None
    index = 0
    raw_size = 0
    try:
        for path in history_files():
            relative = path.relative_to(SOURCE).as_posix()
            fingerprint = sha(path)
            if fingerprint in seen:
                entries.append({'path': relative, 'sha256': fingerprint, 'duplicate_of': seen[fingerprint]})
                continue
            try:
                scan_file(path)
                if path.suffix == '.zip':
                    scan_zip(path)
            except ValueError as error:
                rejected.append({'path': relative, 'reason': str(error)})
                print('Credential safety hold:', relative, flush=True)
                continue
            if path.stat().st_size > 1500 * (1 << 20):
                if path.suffix not in ('.jsonl', '.json', '.csv', '.log', '.txt'):
                    raise ValueError('Large binary needs separate chunking: ' + relative)
                compressed = OUT / 'large_history_compressed' / (fingerprint + '.gz')
                compressed.parent.mkdir(exist_ok=True)
                if not compressed.exists():
                    print('Losslessly compressing oversized trace:', relative, flush=True)
                    with path.open('rb') as source, gzip.open(compressed.with_suffix('.tmp'), 'wb', compresslevel=1) as compressed_stream:
                        shutil.copyfileobj(source, compressed_stream, 8 << 20)
                    os.replace(compressed.with_suffix('.tmp'), compressed)
                stored_path = compressed
                member = 'BIRDI/' + relative + '.gz'
                encoding = 'gzip'
            else:
                stored_path, member, encoding = path, 'BIRDI/' + relative, 'identity'
            if stored_path.stat().st_size > 1500 * (1 << 20):
                raise ValueError('Compressed history still exceeds part limit: ' + relative)
            if archive is None or raw_size + stored_path.stat().st_size > 1500 * (1 << 20):
                if archive is not None:
                    archive.close()
                index += 1
                target = ASSETS / f'birdi-research-history-{index:02d}.zip'
                archive = zipfile.ZipFile(target, 'w', zipfile.ZIP_STORED)
                raw_size = 0
                print('Writing history part', index, flush=True)
            archive.write(stored_path, member)
            raw_size += stored_path.stat().st_size
            seen[fingerprint] = relative
            entries.append({'path': relative, 'sha256': fingerprint, 'asset': target.name,
                            'member': member, 'encoding': encoding})
    finally:
        if archive is not None:
            archive.close()
    atomic_json(ASSETS / 'history_inventory.json', {'entries': entries, 'excluded_for_credential_safety': rejected,
        'note': 'Duplicate archives are stored once by SHA256; excluded extracted trees are reproducible from retained ZIPs.'})
    print('History entries:', len(entries), 'unique:', len(seen), 'credential exclusions:', len(rejected), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--history', action='store_true')
    parser.add_argument('--history-only', action='store_true')
    args = parser.parse_args()
    for line in (SOURCE / '.env').read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            if any(word in key.upper() for word in ('TOKEN', 'SECRET', 'KEY', 'PASS')) and len(value.strip()) >= 16:
                KNOWN.append(value.strip().strip('"\'').encode())
    TREE.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    if args.history_only:
        make_history_assets()
        history = json.loads((ASSETS / 'history_inventory.json').read_text())
        names = {item['asset'] for item in history['entries'] if 'asset' in item}
        names.update({'birdi-source-20261010.zip', 'birdi-desktop-resume-20261010.zip', 'history_inventory.json'})
        assets = [{'name': name, 'bytes': (ASSETS / name).stat().st_size, 'sha256': sha(ASSETS / name)}
                  for name in sorted(names)]
        atomic_json(ASSETS / 'release_manifest.json', {'release': TAG, 'assets': assets})
        print('Completed history assets:', [(item['name'], round(item['bytes'] / (1 << 20), 1))
                                            for item in assets], flush=True)
        return
    for root in (SOURCE / 'birdi_jepa', SOURCE / 'notebooks',
                 SOURCE / 'deliverables/birdi-research-evolution-beamer'):
        copy_tree(root)
    for root in (IMPL / 'amp', IMPL / 'analysis', IMPL / 'dirtb', IMPL / 'safe',
                 IMPL / 'desktop', IMPL / 'baselines/AutoBench', IMPL / 'baselines/CorrectBench', IMPL / 'baselines/ConfiBench'):
        copy_tree(root)
    for file in sorted(SOURCE.iterdir()):
        if file.is_file() and file.suffix.lower() in ('.md', '.py', '.txt', '.csv', '.ipynb', '.jpg', '.png', '.pdf'):
            copy_source(file)
    for name in ('.gitignore', '.gitattributes', '.env.example'):
        copy_source(SOURCE / name)
    for file in sorted(IMPL.iterdir()):
        if file.is_file() and file.suffix.lower() in ('.py', '.md', '.txt', '.json', '.ipynb'):
            copy_source(file)
    for folder in ('confibench_finish_20261003', 'confibench_finish_20261005', 'sota_protocol_audit'):
        for file in sorted((IMPL / folder).glob('*')):
            if file.is_file() and file.suffix in ('.md', '.json', '.jsonl'):
                copy_source(file)
    make_resume_asset()
    if args.history:
        make_history_assets()
    assets = [{'name': p.name, 'bytes': p.stat().st_size, 'sha256': sha(p)} for p in sorted(ASSETS.iterdir())
              if p.is_file() and p.name != 'release_manifest.json']
    atomic_json(ASSETS / 'release_manifest.json', {'release': TAG, 'assets': assets})
    inventory = [{'path': p.relative_to(TREE).as_posix(), 'bytes': p.stat().st_size, 'sha256': sha(p)}
                 for p in sorted(TREE.rglob('*')) if p.is_file()]
    atomic_json(OUT / 'source_inventory.json', {'files': inventory, 'redacted_source_files': REDACTED})
    with zipfile.ZipFile(ASSETS / 'birdi-source-20261010.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for item in inventory:
            archive.write(TREE / item['path'], 'BIRDI/' + item['path'])
    source_asset = ASSETS / 'birdi-source-20261010.zip'
    assets = [item for item in assets if item['name'] != source_asset.name]
    assets.append({'name': source_asset.name, 'bytes': source_asset.stat().st_size, 'sha256': sha(source_asset)})
    atomic_json(ASSETS / 'release_manifest.json', {'release': TAG, 'assets': assets})
    print('Source files:', len(inventory), 'source MB:', round(sum(x['bytes'] for x in inventory) / (1 << 20), 1), flush=True)
    print('Release files:', [(x['name'], round(x['bytes'] / (1 << 20), 1)) for x in assets], flush=True)


if __name__ == '__main__':
    main()
