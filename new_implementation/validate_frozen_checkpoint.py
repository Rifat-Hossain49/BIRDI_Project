#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import zipfile
from collections import Counter
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    with zipfile.ZipFile(args.archive) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("ZIP integrity test failed")
        manifest = json.loads(archive.read("FROZEN_BEFORE_EVALUATION.json"))
        rows = list(csv.DictReader(io.StringIO(archive.read("synthesis_summary.csv").decode())))
        expected_rows = int(manifest["task_count"]) * len(manifest["methods"])
        if len(rows) != expected_rows:
            raise RuntimeError(f"Incomplete summary: {len(rows)}/{expected_rows}")
        failures = []
        checked = 0
        for row in rows:
            if row["supported"].lower() != "true":
                continue
            path = f"frozen/{row['method']}/{row['task_id']}/testbench.sv"
            digest = hashlib.sha256(archive.read(path)).hexdigest()
            checked += 1
            if digest != row["testbench_sha256"]:
                failures.append(path)
        if failures:
            raise RuntimeError(f"Frozen hash mismatches: {failures}")
        print("FROZEN_CHECKPOINT_VALID")
        print("methods", manifest["methods"])
        print("rows", len(rows), "hashes", checked)
        print("support", dict(Counter(row["method"] for row in rows if row["supported"].lower() == "true")))


if __name__ == "__main__":
    main()
