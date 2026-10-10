#!/usr/bin/env python3
"""Monitor the ten-way ConfiBench-Qwen finish wave without exposing tokens."""
from __future__ import annotations

import re
import sys
import time
from datetime import datetime
from pathlib import Path

from kaggle_rotate import accounts, kaggle, kernel_id


PLAN = [(0, 1), (1, 1), (2, 2), (3, 2), (4, 3),
        (5, 3), (6, 4), (7, 4), (8, 5), (9, 5)]
TERMINAL = {"COMPLETE", "ERROR", "CANCELLED"}


def read_status(shard: int, account_no: int) -> str:
    bundle = Path(f"kaggle_upload_cbq{shard}of10")
    acct = accounts()[account_no]
    output = kaggle(["kernels", "status", kernel_id(bundle, account_no)], acct)
    match = re.search(r"KernelWorkerStatus\.([A-Z_]+)", output)
    return match.group(1) if match else "UNKNOWN"


def main() -> int:
    poll_seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    while True:
        states = {(shard, account): read_status(shard, account)
                  for shard, account in PLAN}
        stamp = datetime.now().isoformat(timespec="seconds")
        summary = " ".join(f"s{shard}:a{account}:{state}"
                           for (shard, account), state in states.items())
        print(f"{stamp} {summary}", flush=True)
        if all(state in TERMINAL for state in states.values()):
            failed = {key: state for key, state in states.items() if state != "COMPLETE"}
            if failed:
                print(f"terminal failures: {failed}", flush=True)
                return 1
            print("all ten kernels complete", flush=True)
            return 0
        time.sleep(poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
