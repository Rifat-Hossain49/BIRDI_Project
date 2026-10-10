#!/usr/bin/env python3
"""Diagnostic (dev split only): where does Eval1 fail -- resolution or generation?

For every task with candidates, on the frozen driver, compare each candidate class
with golden's behaviour per resolution unit (class X/Z bits are don't-care, as in
matches()). Per task:
  plurality_ok   every unit's largest class agrees with golden
  oracle_ok      every unit has at least one class agreeing with golden, i.e. a
                 perfect resolver over these candidates would pass Eval1
  single_ok      one candidate agrees with golden on the whole trace
Per unit bucket: unanimous-right, plurality-right (contested), select-recoverable
(plurality wrong, some class right), none-right.

Golden is read here, so this never runs on the test split.
"""
from __future__ import annotations

import argparse
import json
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dirtb.bench import load                                        # noqa: E402
from dirtb.hdl import build_driver, parse_header, simulate          # noqa: E402
from dirtb.resolve import group, simulate_candidates                # noqa: E402


def agrees(cls_rows, gold_rows) -> bool:
    for cv, gv in zip(cls_rows, gold_rows):
        if len(cv) != len(gv):
            return False
        for c, g in zip(cv, gv):
            if len(c) != len(g):
                return False
            if any(cb not in "xXzZ" and cb != gb for cb, gb in zip(c, g)):
                return False
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    cands = defaultdict(list)
    for l in args.candidates.read_text(encoding="utf-8").splitlines():
        if l.strip():
            r = json.loads(l)
            if r.get("rtl"):
                cands[r["task_id"]].append(r)
    tasks = [t for t in load("dev") if t["task_id"] in cands]
    out, totals = [], Counter()
    for t in tasks:
        iface = parse_header(t["header"])
        driver = build_driver(iface, seed=zlib.crc32(t["task_id"].encode()), marathons=True)
        traces = simulate_candidates(driver, cands[t["task_id"]])
        units, n_rows = group(iface, traces)
        gold = simulate(t["eval_golden"], driver, timeout=300)
        rec = {"task_id": t["task_id"], "circuit_type": t["circuit_type"], "n_ran": len(traces),
               "n_units": len(units), "buckets": {}}
        if not units or gold.status != "RAN" or len(gold.rows) != n_rows:
            rec.update(plurality_ok=False, oracle_ok=False, single_ok=False,
                       note="no candidate ran" if not units else f"golden {gold.status} rows {len(gold.rows)}/{n_rows}")
        else:
            b = Counter()
            for u in units:
                g = [gold.rows[i][2] for i in u.row_idx]
                ok = [agrees(k, g) for k in u.classes]
                if len(ok) == 1:
                    b["unanimous-right" if ok[0] else "none-right"] += 1
                elif ok[0]:
                    b["plurality-right"] += 1
                elif any(ok):
                    b["select-recoverable"] += 1
                else:
                    b["none-right"] += 1
            single = any(agrees([r[2] for r in tr.rows], [r[2] for r in gold.rows])
                         for tr in traces.values() if len(tr.rows) == n_rows)
            rec["buckets"] = dict(b)
            rec.update(plurality_ok=b["select-recoverable"] == 0 and b["none-right"] == 0,
                       oracle_ok=b["none-right"] == 0, single_ok=single)
            totals.update(b)
        out.append(rec)
        print(f"  {t['task_id']:22s} {t['circuit_type']} ran {rec['n_ran']}  plurality {rec['plurality_ok']!s:5s} "
              f"oracle {rec['oracle_ok']!s:5s} single {rec['single_ok']!s:5s}  {rec['buckets'] or rec.get('note')}",
              flush=True)
    args.out.write_text(json.dumps(out, indent=1), encoding="utf-8")
    for ct in ("CMB", "SEQ", None):
        rs = [r for r in out if ct is None or r["circuit_type"] == ct]
        n = len(rs)
        if n:
            print(f"  {ct or 'ALL':4s} n={n:3d}  plurality {sum(r['plurality_ok'] for r in rs)/n:.3f}  "
                  f"oracle-resolution {sum(r['oracle_ok'] for r in rs)/n:.3f}  "
                  f"oracle-single {sum(r['single_ok'] for r in rs)/n:.3f}")
    print("  units:", dict(totals))


if __name__ == "__main__":
    main()
