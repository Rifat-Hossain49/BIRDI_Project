#!/usr/bin/env python3
"""Go / no-go for the repair pipeline: how accurate is a two-family consensus?

Reads ref_pilot.py output. Per (sub-testbench, row):
  golden     the golden design's row
  A, B       the majority row within each judge family (a strict majority of the
             family's designs that ran; no majority -> that family abstains)
  consensus  A == B, both present

Reported by circuit type:
  coverage   rows with a consensus / all rows
  precision  consensus rows matching golden / consensus rows
  single-family precision, for comparison -- the gain from requiring agreement
  scenario-level: scenarios whose every row has a correct consensus

Decision rule, fixed here before reading any result:
  the repair pipeline is worth building if two-family precision is >= 0.99 on
  BOTH combinational and sequential rows. Below that, replacing ConfiBench's
  expected values with the consensus would break Eval1 more often than it fixes
  it, and judge accuracy must be improved first.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def majority(rows_by_dut, i):
    vals = [r[i] for r in rows_by_dut if i < len(r)]
    if not vals:
        return None
    v, c = Counter(vals).most_common(1)[0]
    return v if c * 2 > len(vals) else None


def main() -> None:
    path = Path(sys.argv[1])
    groups = defaultdict(lambda: {"golden": None, "A": [], "B": [], "ct": "?"})
    status = Counter()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        status[(r["family"], r["status"].split(":")[0])] += 1
        g = groups[(r["run"], r["task_id"], r["iter_id"])]
        g["ct"] = r["circuit_type"]
        if r["status"] != "RAN" or r["rows"] is None:
            continue
        if r["family"] == "golden":
            g["golden"] = r["rows"]
        elif r["family"].startswith("A"):
            g["A"].append(r["rows"])
        else:
            g["B"].append(r["rows"])

    print("simulation outcomes:")
    for (fam, st), n in sorted(status.items()):
        print(f"   {fam:14s} {st:16s} {n}")

    stats = defaultdict(Counter)
    for key, g in groups.items():
        gold = g["golden"]
        if gold is None or len(g["A"]) < 2 or len(g["B"]) < 2:
            stats[g["ct"]]["sub-testbenches skipped (too few designs ran)"] += 1
            continue
        ct = g["ct"]
        scen_ok, scen_all = defaultdict(lambda: True), set()
        for i, grow in enumerate(gold):
            a, b = majority(g["A"], i), majority(g["B"], i)
            s = stats[ct]
            s["rows"] += 1
            try:
                scen = json.loads(grow).get("scenario", "?")
            except Exception:
                scen = "?"
            scen_all.add(scen)
            if a is not None:
                s["A rows"] += 1
                s["A correct"] += (a == grow)
            if b is not None:
                s["B rows"] += 1
                s["B correct"] += (b == grow)
            if a is not None and b is not None and a == b:
                s["consensus rows"] += 1
                if a == grow:
                    s["consensus correct"] += 1
                else:
                    scen_ok[scen] = False
            else:
                scen_ok[scen] = False
        stats[ct]["scenarios"] += len(scen_all)
        stats[ct]["scenarios fully covered and correct"] += sum(1 for sc in scen_all if scen_ok[sc])

    print()
    verdict = {}
    for ct in ("CMB", "SEQ"):
        s = stats[ct]
        if not s["rows"]:
            print(f"{ct}: no rows")
            continue
        cp = s["consensus correct"] / max(1, s["consensus rows"])
        verdict[ct] = cp
        print(f"== {ct} ==  rows {s['rows']}")
        print(f"   family A alone : precision {s['A correct']/max(1,s['A rows']):.4f}  "
              f"coverage {s['A rows']/s['rows']:.3f}")
        print(f"   family B alone : precision {s['B correct']/max(1,s['B rows']):.4f}  "
              f"coverage {s['B rows']/s['rows']:.3f}")
        print(f"   TWO-FAMILY     : precision {cp:.4f}  coverage {s['consensus rows']/s['rows']:.3f}  "
              f"(wrong consensus rows: {s['consensus rows'] - s['consensus correct']})")
        print(f"   scenarios fully covered and correct: "
              f"{s['scenarios fully covered and correct']}/{s['scenarios']}")
        if s["sub-testbenches skipped (too few designs ran)"]:
            print(f"   sub-testbenches skipped: {s['sub-testbenches skipped (too few designs ran)']}")
    print()
    go = all(verdict.get(ct, 0) >= 0.99 for ct in ("CMB", "SEQ"))
    print(f"DECISION (two-family precision >= 0.99 on CMB and SEQ): {'GO' if go else 'NO-GO'}  "
          + "  ".join(f"{ct} {v:.4f}" for ct, v in verdict.items()))


if __name__ == "__main__":
    main()
