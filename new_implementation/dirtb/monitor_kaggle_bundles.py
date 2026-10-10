#!/usr/bin/env python3
"""Monitor arbitrary bundle/account pairs without exposing Kaggle credentials.

Usage:
    python dirtb/monitor_kaggle_bundles.py 300 bundle_dir:account [...]
"""
from __future__ import annotations

import re
import sys
import time
from datetime import datetime
from pathlib import Path

from kaggle_rotate import accounts, kaggle, kernel_id


TERMINAL = {"COMPLETE", "ERROR", "CANCELLED"}


def read_status(bundle: Path, account_no: int) -> str:
    acct = accounts()[account_no]
    output = kaggle(["kernels", "status", kernel_id(bundle, account_no)], acct)
    match = re.search(r"KernelWorkerStatus\.([A-Z_]+)", output)
    return match.group(1) if match else "UNKNOWN"


def main() -> int:
    if len(sys.argv) < 3:
        raise SystemExit("usage: monitor_kaggle_bundles.py POLL_SECONDS BUNDLE:ACCOUNT [...]")
    poll_seconds = int(sys.argv[1])
    plan = []
    for value in sys.argv[2:]:
        bundle, account = value.rsplit(":", 1)
        plan.append((Path(bundle), int(account)))
    while True:
        states = {(bundle.name, account): read_status(bundle, account)
                  for bundle, account in plan}
        stamp = datetime.now().isoformat(timespec="seconds")
        summary = " ".join(f"{bundle}:a{account}:{state}"
                           for (bundle, account), state in states.items())
        print(f"{stamp} {summary}", flush=True)
        if all(state in TERMINAL for state in states.values()):
            failed = {key: state for key, state in states.items() if state != "COMPLETE"}
            if failed:
                print(f"terminal failures: {failed}", flush=True)
                return 1
            print("all monitored kernels complete", flush=True)
            return 0
        time.sleep(poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
