#!/usr/bin/env python3
"""Why is a <=30B model wrong on a third of sequential scenarios? (dev set, 4o)

Every scenario with >=3 Qwen3.5-27B designs falls into one bucket. Each bucket
calls for different machinery, so their sizes decide what the pipeline must do:

  unanimous-correct   nothing to fix
  majority-correct    samples disagree, voting already works
  select-recoverable  samples disagree, majority wrong, but SOME design matches
                      golden -> a better adjudicator (not a better model) fixes it
  shared-misreading   every sample agrees and all are wrong -> sampling can never
                      expose it; needs the spec re-read in a different way
  none-correct        samples disagree and none is right -> needs regeneration

For wrong references it also measures locality: where the first divergence from
golden happens and how much of the trace it corrupts. If one early divergence
typically corrupts the rest, fixing a single localized decision repairs the whole
scenario; if errors are scattered, it does not.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def analyze(gold, fam, stats, ct):
    if gold is None or len(fam) < 3:
        return
    scen = defaultdict(list)
    for i, g in enumerate(gold):
        try:
            scen[json.loads(g).get("scenario", "?")].append(i)
        except Exception:
            scen["?"].append(i)
    n = len(fam)
    for sc, idx in scen.items():
        s = stats[ct]
        traces = [tuple(r[i] if i < len(r) else None for i in idx) for r in fam]
        gt = tuple(gold[i] for i in idx)
        c = Counter(traces)
        top, cnt = c.most_common(1)[0]
        any_ok = gt in c
        if cnt == n and top == gt:
            b = "unanimous-correct"
        elif cnt == n:
            b = "shared-misreading"
        elif cnt * 2 > n and top == gt:
            b = "majority-correct"
        elif any_ok:
            b = "select-recoverable"
        else:
            b = "none-correct"
        s[b] += 1
        s["scenarios"] += 1
        if b in ("shared-misreading", "none-correct", "select-recoverable"):
            ref = top
            diffs = [k for k in range(len(idx)) if ref[k] != gt[k]]
            if diffs and len(idx) >= 4:
                first = diffs[0]
                after = len(idx) - first
                s["loc n"] += 1
                s["loc first_frac_sum"] += first / len(idx)
                s["loc corrupted_after_sum"] += len(diffs) / after
                if len(diffs) / after >= 0.5:
                    s["loc propagates (>=50% of later rows wrong)"] += 1
                if len(diffs) == 1:
                    s["loc single-row error"] += 1


def main() -> None:
    stats = defaultdict(Counter)
    cur, gold, fam, ct = None, None, [], "?"
    with Path(sys.argv[1]).open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            key = (r["run"], r["task_id"], r["iter_id"])
            if key != cur:
                if cur is not None:
                    analyze(gold, fam, stats, ct)
                cur, gold, fam, ct = key, None, [], r["circuit_type"]
            if r["status"] != "RAN" or r["rows"] is None:
                continue
            if r["family"] == "golden":
                gold = r["rows"]
            elif r["family"].startswith("A"):
                fam.append(r["rows"])
        if cur is not None:
            analyze(gold, fam, stats, ct)

    order = ["unanimous-correct", "majority-correct", "select-recoverable",
             "shared-misreading", "none-correct"]
    for ctp in ("CMB", "SEQ"):
        s = stats[ctp]
        n = s["scenarios"]
        if not n:
            continue
        print(f"== {ctp}: {n} scenarios ==")
        for b in order:
            print(f"   {s[b]:5d}  {s[b]/n:6.1%}  {b}")
        if s["loc n"]:
            k = s["loc n"]
            print(f"   locality over {k} wrong scenarios (>=4 rows):")
            print(f"      mean position of first divergence : {s['loc first_frac_sum']/k:.0%} into the trace")
            print(f"      mean share of later rows corrupted: {s['loc corrupted_after_sum']/k:.0%}")
            print(f"      errors that propagate (>=50%)     : {s['loc propagates (>=50% of later rows wrong)']/k:.0%}")
            print(f"      single-row errors                 : {s['loc single-row error']/k:.0%}")


if __name__ == "__main__":
    main()
