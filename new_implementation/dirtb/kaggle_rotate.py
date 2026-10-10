#!/usr/bin/env python3
"""Run Kaggle sessions across several accounts, one at a time.

Accounts come from F:\\BIRDI_Project\\.env:
    KAGGLE_API_TOKEN     (+ optional KAGGLE_USERNAME, default tishaferdous)
    KAGGLE_API_TOKEN_2   KAGGLE_USERNAME_2
    KAGGLE_API_TOKEN_3   KAGGLE_USERNAME_3
    BACKUP_KAGGLE_API_TOKEN
    SECOND_BACKUP_KAGGLE_API_TOKEN
    NEW_KAGGLE_API_TOKEN
    GPU_KAGGLE_API_TOKEN
Tokens are read here and passed to the CLI through the environment only; they are
never printed or written anywhere.

A private dataset is visible only to the account that owns it, so a bundle is
re-published under whichever account runs it: this rewrites the dataset id, the
kernel id and the kernel's dataset source to that account's username before pushing.

usage:
  python dirtb/kaggle_rotate.py accounts
  python dirtb/kaggle_rotate.py push   <bundle_dir> <account#>
  python dirtb/kaggle_rotate.py status <bundle_dir> <account#>
  python dirtb/kaggle_rotate.py fetch  <bundle_dir> <account#> <dest_dir> [file-pattern]
"""
from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ENV = Path("F:/BIRDI_Project/.env")
ACCOUNTS_FILE = Path(__file__).with_name("kaggle_accounts.json")
# The former account-2 credential was retired. The replacement credential was
# verified through Kaggle token introspection as `naimahjyoti` on 2026-09-20.
DISABLED_PUSH_ACCOUNTS = set()


def accounts():
    """Tokens from .env (never printed); usernames from dirtb/kaggle_accounts.json.

    Accepts both naming schemes: KAGGLE_API_TOKEN_2 / _3 / _4 and
    SECOND_KAGGLE_API_TOKEN / THIRD_KAGGLE_API_TOKEN /
    BACKUP_KAGGLE_API_TOKEN / SECOND_BACKUP_KAGGLE_API_TOKEN.
    NEW_KAGGLE_API_TOKEN is used for scheduler account 6.
    GPU_KAGGLE_API_TOKEN is used for scheduler account 7.
    """
    env = dict(os.environ)
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            # An explicitly supplied process environment wins over the file. This
            # supports CI/ephemeral credentials without writing secrets to disk.
            env.setdefault(k.strip(), v.strip())
    names = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
    tokens = {1: env.get("KAGGLE_API_TOKEN"),
              2: env.get("KAGGLE_API_TOKEN_2") or env.get("SECOND_KAGGLE_API_TOKEN"),
              3: env.get("KAGGLE_API_TOKEN_3") or env.get("THIRD_KAGGLE_API_TOKEN"),
              4: env.get("KAGGLE_API_TOKEN_4") or env.get("BACKUP_KAGGLE_API_TOKEN"),
              5: env.get("KAGGLE_API_TOKEN_5") or env.get("SECOND_BACKUP_KAGGLE_API_TOKEN"),
              6: env.get("KAGGLE_API_TOKEN_6") or env.get("NEW_KAGGLE_API_TOKEN"),
              7: env.get("KAGGLE_API_TOKEN_7") or env.get("GPU_KAGGLE_API_TOKEN")}
    return {n: {"token": t, "user": names[str(n)]} for n, t in tokens.items() if t and str(n) in names}


def kaggle(args, acct, cwd=None, timeout=1800):
    e = dict(os.environ, KAGGLE_API_TOKEN=acct["token"], PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, "-m", "kaggle"] + args, cwd=cwd, env=e,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return (r.stdout + r.stderr).replace("\r", "")


def retarget(bundle: Path, user: str) -> Path:
    """Copy the bundle with every id rewritten to this account."""
    work = Path(tempfile.mkdtemp(prefix=f"kr_{user}_"))
    shutil.copytree(bundle, work / bundle.name)
    b = work / bundle.name
    dm = b / "dataset_publish" / "dataset-metadata.json"
    km = b / "kernel" / "kernel-metadata.json"
    d = json.loads(dm.read_text(encoding="utf-8"))
    k = json.loads(km.read_text(encoding="utf-8"))
    d["id"] = f"{user}/{d['id'].split('/', 1)[1]}"
    k["id"] = f"{user}/{k['id'].split('/', 1)[1]}"
    k["dataset_sources"] = [f"{user}/{s.split('/', 1)[1]}" for s in k["dataset_sources"]]
    dm.write_text(json.dumps(d, indent=1), encoding="utf-8")
    km.write_text(json.dumps(k, indent=1), encoding="utf-8")
    return b


def check_launch_hold(bundle: Path, n: int, launch_hold: Path | None = None) -> None:
    if launch_hold is None:
        launch_hold = Path(__file__).resolve().parent.parent / 'confibench_finish_20261003/GPU_LAUNCH_HOLD'
    source_meta = json.loads((bundle / 'kernel/kernel-metadata.json').read_text())
    if (launch_hold.exists() and source_meta.get('enable_gpu')
            and 'confibench-qwen' in source_meta.get('id', '')):
        approvals = launch_hold.with_name('GPU_APPROVED_BUNDLES.json')
        entries = json.loads(approvals.read_text(encoding='utf-8')) if approvals.exists() else []
        notebook = bundle / 'kernel' / source_meta['code_file']
        datasets = sorted((bundle / 'dataset_publish').glob('*.zip'))
        actual = {'kernel_id': source_meta['id'], 'account': n,
                  'notebook_sha256': hashlib.sha256(notebook.read_bytes()).hexdigest(),
                  'dataset_sha256': hashlib.sha256(datasets[0].read_bytes()).hexdigest()
                  if len(datasets) == 1 else None}
        if not any(all(entry.get(key) == value for key, value in actual.items()) for entry in entries):
            raise SystemExit('ConfiBench GPU launch hold: this exact bundle/account is not approved')


def kernel_push_args(metadata):
    args = ["kernels", "push", "-p", "."]
    if metadata.get("enable_gpu") in (True, "true"):
        args.extend(["--accelerator", metadata.get("machine_shape") or "NvidiaTeslaT4"])
    return args


def push(bundle: Path, n: int) -> None:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    check_launch_hold(bundle, n)
    if n in DISABLED_PUSH_ACCOUNTS:
        raise SystemExit(f"Account {n} is disabled for new pushes by local scheduling policy")
    acct = accounts()[n]
    b = retarget(bundle, acct["user"])
    d = json.loads((b / "dataset_publish" / "dataset-metadata.json").read_text())
    k = json.loads((b / "kernel" / "kernel-metadata.json").read_text())
    st = kaggle(["datasets", "status", d["id"]], acct)
    if "ready" in st or "processing" in st:
        print(kaggle(["datasets", "version", "-p", ".", "-m", "update"], acct, cwd=b / "dataset_publish")[-300:])
    else:
        print(kaggle(["datasets", "create", "-p", "."], acct, cwd=b / "dataset_publish")[-300:])
    boundary_files = list((b / "dataset").rglob("XJ_BOUNDARY.json"))
    expected_checkpoints = 0
    if len(boundary_files) == 1:
        expected_checkpoints = int(json.loads(boundary_files[0].read_text(encoding="utf-8")).get("checkpoint_tasks", 0))
    remote_checkpoint_count = None
    for _ in range(90):
        ready = "ready" in kaggle(["datasets", "status", d["id"]], acct)
        if ready and expected_checkpoints:
            listing = kaggle(["datasets", "files", d["id"], "--page-size", "200", "--format", "json"], acct)
            start = listing.find("[")
            try:
                files = json.loads(listing[start:]) if start >= 0 else []
                remote_checkpoint_count = sum(
                    "/resume_saves/" in f.get("name", "") and f.get("name", "").endswith("/data.json")
                    for f in files
                )
            except json.JSONDecodeError:
                remote_checkpoint_count = None
            ready = remote_checkpoint_count == expected_checkpoints
        if ready:
            break
        time.sleep(20)
    else:
        raise SystemExit(
            f"Dataset did not expose expected checkpoint count for {d['id']}: "
            f"expected {expected_checkpoints}, observed {remote_checkpoint_count}"
        )
    out = kaggle(kernel_push_args(k), acct, cwd=b / "kernel")
    print(out[-300:])
    # Never report success on an error: the CLI exits 0 even when Kaggle refuses
    # the push (e.g. "Maximum batch GPU session count of 2 reached").
    if "successfully pushed" not in out:
        raise SystemExit(f"PUSH FAILED for {k['id']} under account {n} ({acct['user']})")
    print(f"pushed {k['id']} under account {n} ({acct['user']})")


def kernel_id(bundle: Path, n: int) -> str:
    k = json.loads((bundle / "kernel" / "kernel-metadata.json").read_text())
    return f"{accounts()[n]['user']}/{k['id'].split('/', 1)[1]}"


def main() -> None:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    cmd = sys.argv[1]
    if cmd == "accounts":
        for n, a in accounts().items():
            print(f"account {n}: {a['user']}")
        return
    bundle, n = Path(sys.argv[2]), int(sys.argv[3])
    if cmd == "push":
        push(bundle, n)
    elif cmd == "status":
        print(kaggle(["kernels", "status", kernel_id(bundle, n)], accounts()[n]).strip().splitlines()[-1])
    elif cmd == "fetch":
        dest = Path(sys.argv[4]); dest.mkdir(parents=True, exist_ok=True)
        args = ["kernels", "output", kernel_id(bundle, n), "-p", str(dest), "--page-size", "200"]
        if len(sys.argv) > 5:
            args += ["--file-pattern", sys.argv[5]]
        print(kaggle(args, accounts()[n], timeout=3600)[-500:])


if __name__ == "__main__":
    main()
