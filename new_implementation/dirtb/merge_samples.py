#!/usr/bin/env python3
"""Merge Stage 3 sample files from every session and round into one candidate pool.

Sessions are resumable and carry earlier samples forward, so the same sample appears in
several files. Rows are keyed by (task_id, path, sample_idx); a row with a module wins
over one without, otherwise the first seen is kept. Reports coverage against the target
number of samples per task.

usage: python dirtb/merge_samples.py --out merged.jsonl --samples 10 [--tasks dirtb/tasks_all.jsonl] in1.jsonl in2.jsonl ...
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--samples", type=int, default=10, help="target samples per task (sample_idx 0..N-1)")
    ap.add_argument("--tasks", type=Path, default=Path(__file__).with_name("tasks_all.jsonl"))
    args = ap.parse_args()

    rows = {}
    seen = 0
    for p in args.inputs:
        for l in p.read_text(encoding="utf-8").splitlines():
            if not l.strip():
                continue
            r = json.loads(l)
            seen += 1
            if r.get("sample_idx", 0) >= args.samples:
                continue
            k = (r["task_id"], r.get("path", "direct"), r["sample_idx"])
            if k not in rows or (r.get("rtl") and not rows[k].get("rtl")):
                rows[k] = r
    tasks = [json.loads(l)["task_id"] for l in args.tasks.read_text(encoding="utf-8").splitlines() if l.strip()]
    with args.out.open("w", encoding="utf-8", newline="\n") as f:
        for k in sorted(rows):
            f.write(json.dumps(rows[k]) + "\n")

    n = Counter(k[0] for k in rows)
    mods = Counter(k[0] for k, r in rows.items() if r.get("rtl"))
    short = {t: n.get(t, 0) for t in tasks if n.get(t, 0) < args.samples}
    no_module = [t for t in tasks if mods.get(t, 0) == 0]
    print(f"read {seen} rows from {len(args.inputs)} files -> {len(rows)} unique samples, "
          f"{sum(1 for r in rows.values() if r.get('rtl'))} with a module")
    print(f"tasks complete ({args.samples} samples): {len(tasks) - len(short)}/{len(tasks)}; "
          f"missing samples: {sum(args.samples - c for c in short.values())}")
    print(f"tasks with no module at all: {len(no_module)} {no_module[:20]}")
    if short:
        print("incomplete:", dict(sorted(short.items())[:40]))
    print("modes:", dict(Counter(r.get("mode") for r in rows.values())))


if __name__ == "__main__":
    main()
