"""Publish the audited handoff through GitHub's Git API without rewriting history."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'deliverables/desktop_handoff_20261010'
REPO = 'Rifat-Hossain49/BIRDI_Project'
TAG = 'desktop-handoff-20261010'


def gh(args, timeout=180):
    response = subprocess.run(['gh', *args], capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=timeout)
    if response.returncode:
        raise RuntimeError('GitHub operation failed: ' + response.stderr[-1000:])
    return response.stdout


def api(path, payload=None, method=None):
    args = ['api', path]
    if method:
        args += ['--method', method]
    if payload is None:
        return json.loads(gh(args))
    with tempfile.TemporaryDirectory(dir=OUT) as temporary:
        file = Path(temporary) / 'request.json'
        file.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        return json.loads(gh(args + ['--input', str(file)], timeout=300))


def sha(file):
    value = hashlib.sha256()
    with file.open('rb') as stream:
        while block := stream.read(8 << 20):
            value.update(block)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--code-only', action='store_true')
    parser.add_argument('--release-only', action='store_true')
    parser.add_argument('--changed-only', action='store_true')
    parser.add_argument('--message', default='Add BIRDI research and checkpointed 32GB desktop handoff (140/156 tasks)')
    parser.add_argument('--allow-public', action='store_true')
    args = parser.parse_args()
    if not args.execute:
        raise SystemExit('Explicit --execute required for repository publication')
    if args.release_only:
        return publish_release(args.allow_public)
    repo = api('repos/' + REPO)
    if not repo['private'] and not args.allow_public:
        raise RuntimeError('Explicit public-publication approval required')
    prefix = 'repos/' + REPO
    try:
        ref = api(prefix + '/git/ref/heads/main')
    except RuntimeError as error:
        if repo['size'] != 0 or 'HTTP 409' not in str(error):
            raise
        readme = OUT / 'source/BIRDI/README.md'
        api(prefix + '/contents/README.md', {
            'message': 'Initialize authorized BIRDI desktop repository',
            'content': base64.b64encode(readme.read_bytes()).decode('ascii'), 'branch': 'main',
        }, 'PUT')
        for attempt in range(30):
            try:
                ref = api(prefix + '/git/ref/heads/main')
                break
            except RuntimeError as error:
                if 'HTTP 409' not in str(error) or attempt == 29:
                    raise
                time.sleep(2)
    parent = ref['object']['sha']
    commit = api(prefix + '/git/commits/' + parent)
    original = api(prefix + '/git/trees/' + commit['tree']['sha'])
    tree = original['sha']
    files = json.loads((OUT / 'source_inventory.json').read_text())['files']
    existing = {}
    if args.changed_only:
        remote_tree = api(prefix + '/git/trees/' + original['sha'] + '?recursive=1')
        if remote_tree.get('truncated'):
            raise RuntimeError('Remote tree is truncated; cannot audit incremental publication')
        existing = {item['path']: item['sha'] for item in remote_tree['tree'] if item['type'] == 'blob'}
    entries, size = [], 0
    changed = 0
    def flush():
        nonlocal entries, size, tree
        if entries:
            tree = api(prefix + '/git/trees', {'base_tree': tree, 'tree': entries})['sha']
            print('Created tree batch:', len(entries), 'files', flush=True)
            entries, size = [], 0
    for item in files:
        path = OUT / 'source/BIRDI' / item['path']
        if sha(path) != item['sha256']:
            raise RuntimeError('Source changed after safety audit: ' + item['path'])
        payload = path.read_bytes()
        blob_sha = hashlib.sha1(b'blob ' + str(len(payload)).encode() + b'\0' + payload).hexdigest()
        if existing.get(item['path']) == blob_sha:
            continue
        changed += 1
        entry = {'path': item['path'], 'mode': '100644', 'type': 'blob'}
        try:
            content = payload.decode('utf-8')
        except UnicodeDecodeError:
            content = None
        if content is None or len(payload) > 512 * 1024:
            entry['sha'] = api(prefix + '/git/blobs', {
                'content': base64.b64encode(payload).decode('ascii'), 'encoding': 'base64',
            })['sha']
        else:
            entry['content'] = content
        encoded = len(json.dumps(entry, ensure_ascii=False).encode())
        if size + encoded > 3 * (1 << 20):
            flush()
        entries.append(entry)
        size += encoded
    flush()
    if changed == 0:
        print('Source is already identical to the audited snapshot.', flush=True)
        return
    new = api(prefix + '/git/commits', {
        'message': args.message,
        'tree': tree, 'parents': [parent],
    })
    if api(prefix + '/git/ref/heads/main')['object']['sha'] != parent:
        raise RuntimeError('main advanced during staging; refusing to overwrite another contributor')
    api(prefix + '/git/refs/heads/main', {'sha': new['sha'], 'force': False}, 'PATCH')
    remote = api(prefix + '/git/trees/' + new['tree']['sha'])
    owned = {item['path'].split('/')[0] for item in files}
    before = {item['path']: item['sha'] for item in original['tree'] if item['path'] not in owned}
    after = {item['path']: item['sha'] for item in remote['tree'] if item['path'] not in owned}
    if before != after:
        raise RuntimeError('Unexpected change to unrelated root entries')
    receipt = {'repository': REPO, 'commit': new['sha'], 'parent': parent,
               'source_files': len(files), 'changed_source_files': changed, 'unrelated_root_entries_preserved': True,
               'release': TAG, 'assets_uploaded': False, 'public_publication_approved': args.allow_public}
    (OUT / 'publish_receipt.json').write_text(json.dumps(receipt, indent=2))
    print('Committed:', new['sha'], flush=True)
    if args.code_only:
        return
    publish_release(args.allow_public)


def publish_release(allow_public=False):
    receipt = json.loads((OUT / 'publish_receipt.json').read_text())
    prefix = 'repos/' + REPO
    if receipt['repository'] != REPO:
        raise RuntimeError('Source receipt belongs to another repository')
    if not api(prefix)['private'] and not (allow_public and receipt.get('public_publication_approved')):
        raise RuntimeError('Public release requires explicit recorded approval')
    notes = (
        'Desktop handoff for the BIRDI RTL testbench project. Source is at repository root. '
        'Public publication of the credential-free full handoff was explicitly approved.\n\n'
        '140/156 first ConfiBench task records saved; 16 unfinished journals preserved. '
        'All 138 original first records are unchanged. Task coverage is not a pass score.\n\n'
        'Windows/NVIDIA setup and Claude continuity: read CLAUDE.md, '
        'new_implementation/desktop/CONVERSATION_HISTORY_AND_CLAUDE_HANDOFF.md '
        'and new_implementation/desktop/README.md. Download the small '
        'birdi-desktop-resume-20261010.zip for continuation; the history archives are optional. '
        'CPU preflight is mandatory before GPU continuation. Intended starting setup: '
        'one NVIDIA GPU with 32 GB VRAM, Qwen3.5-27B Q4_K_M, two workers. '
        'Actual desktop GPU fit has not been tested on the laptop.\n\n'
        'Credentials and transient pretrained-model downloads are excluded. '
        'Release manifests contain SHA256 checksums. Historical result archives are deduplicated '
        'by content hash; any credential-safety exclusions are listed in history_inventory.json.\n'
    )
    release = api(prefix + '/releases', {
        'tag_name': TAG, 'target_commitish': receipt['commit'], 'name': 'BIRDI 32GB Desktop Handoff - 10 October 2026',
        'body': notes, 'draft': True, 'prerelease': False,
    })
    assets_dir = OUT / 'release'
    manifest = json.loads((assets_dir / 'release_manifest.json').read_text())
    paths = [assets_dir / item['name'] for item in manifest['assets']]
    for item, path in zip(manifest['assets'], paths):
        if sha(path) != item['sha256'] or path.stat().st_size != item['bytes']:
            raise RuntimeError('Asset changed after audit: ' + path.name)
    paths.append(assets_dir / 'release_manifest.json')
    checkpoint = next(path for path in paths if path.name == 'birdi-desktop-resume-20261010.zip')
    print('Uploading resume checkpoint first', flush=True)
    gh(['release', 'upload', TAG, str(checkpoint), '--repo', REPO], timeout=1200)
    others = [str(path) for path in paths if path != checkpoint]
    print('Uploading historical assets:', len(others), flush=True)
    gh(['release', 'upload', TAG, *others, '--repo', REPO], timeout=14400)
    remote_assets = api(prefix + f'/releases/{release["id"]}/assets?per_page=100')
    lookup = {asset['name']: asset for asset in remote_assets}
    checksums = {item['name']: item['sha256'] for item in manifest['assets']}
    for path in paths:
        asset = lookup[path.name]
        if asset['size'] != path.stat().st_size or asset['state'] != 'uploaded':
            raise RuntimeError('Release asset upload incomplete: ' + path.name)
        digest = asset.get('digest')
        expected = checksums.get(path.name) or sha(path)
        if digest and digest != 'sha256:' + expected:
            raise RuntimeError('Server-side asset checksum mismatch: ' + path.name)
    published = api(prefix + f'/releases/{release["id"]}', {'draft': False}, 'PATCH')
    receipt.update(assets_uploaded=True, release_url=published['html_url'],
                   assets=[{'name': asset['name'], 'bytes': asset['size'], 'digest': asset.get('digest')}
                           for asset in remote_assets])
    (OUT / 'publish_receipt.json').write_text(json.dumps(receipt, indent=2))
    print('Published:', published['html_url'], flush=True)


if __name__ == '__main__':
    main()
