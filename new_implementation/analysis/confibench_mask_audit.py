#!/usr/bin/env python3
"""Was each masked scenario masked for a good reason?

`confibench_weakness.py` found that almost half of ConfiBench's missed
detections were caught by its own testbench and then discarded by its scenario
mask. That is only a weakness if the mask was WRONG to discard them.

The mask exists to hide scenarios whose expected value is suspected to be
incorrect. Golden's own run records the checker's failure list before the mask
is applied, so each masked scenario falls into one of two cases:

  over-masked      Golden PASSES the scenario. The checker's expectation was
                   right; the suspicion was false. Unmasking costs nothing on
                   Eval1 and recovers every catch the scenario made.

  rightly masked   Golden FAILS the scenario. The expectation is genuinely wrong,
                   so unmasking would break Eval1 -- but the STIMULUS is not the
                   problem, only the expected value. Repairing the value would
                   keep the scenario's detection power.

Both are oracle quantities (they need Golden to tell apart) and are reported as
upper bounds on what a golden-free method could recover, never as results.

Also verified first: that re-deriving ConfiBench's per-mutant verdicts from its
logs reproduces its own recorded `Eval2_failed_mutant_idxes`. If it did not, no
number below could be trusted.
"""
from __future__ import annotations

import json
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ZIP = ROOT / "baselines/confibench_drive/TODAES_opensource_result.zip"
REC = ROOT / "analysis/confibench_4o_records.json"
BASE = "saves_inEDA/TODAES/ConfiBench_4o/"
LOOSE = 0.8


def raw_failed(txt: str):
    a, b = txt.rfind("["), txt.rfind("]")
    if a == -1 or b < a:
        return None
    body = txt[a + 1:b].replace("'", "").strip()
    if not body:
        return []
    out = []
    for tok in body.split(","):
        d = "".join(ch for ch in tok if ch.isdigit())
        if d:
            out.append(int(d))
    return out


def main() -> None:
    z = zipfile.ZipFile(ZIP)
    recs = json.loads(REC.read_text())
    names = z.namelist()

    # Golden's pre-mask failures per (run, task, sub-testbench).
    gold = {}
    for n in names:
        if not n.startswith(BASE):
            continue
        m = re.search(r"^([^/]+)/([^/]+)/\d+_\d+_TBeval/eval1_GoldenRTL/(\d+)/run_info_py\.txt$",
                      n[len(BASE):])
        if m:
            gold[(m.group(1), m.group(2), m.group(3))] = raw_failed(
                z.read(n).decode("utf-8", "replace"))

    # Scenario masks and recorded failed-mutant lists from data.json.
    meta = {}
    for n in names:
        if n.startswith(BASE) and n.endswith("/data.json"):
            p = n[len(BASE):].split("/")
            d = json.loads(z.read(n).decode("utf-8", "replace"))
            masks = {str(mb.get("iter_id")): mb.get("scen_mask")
                     for mb in (d.get("multibench_info") or []) if isinstance(mb, dict)}
            meta[(p[0], p[1])] = (masks, d.get("Eval2_failed_mutant_idxes"))

    # Per-mutant, per-scenario catches that the mask discarded.
    per_mut = defaultdict(lambda: defaultdict(set))
    for n in names:
        if not n.startswith(BASE):
            continue
        m = re.search(r"^([^/]+)/([^/]+)/\d+_\d+_TBeval/eval2_GoldenTB_and_mutants/"
                      r"mutant_(\d+)/GeneratedTB/(\d+)/run_info_py\.txt$", n[len(BASE):])
        if m:
            f = raw_failed(z.read(n).decode("utf-8", "replace"))
            if f:
                per_mut[(m.group(1), m.group(2), int(m.group(3)))][m.group(4)] |= set(f)

    # 1. Consistency: reconstructed disagreements vs ConfiBench's own record.
    match = mism = skipped = 0
    for r in recs:
        if not r["eval1"]:
            continue
        rec_failed = meta.get((r["run"], r["task"]), ({}, None))[1]
        if rec_failed is None:
            skipped += 1
            continue
        ours = sorted(m["idx"] for m in r["mutants"]
                      if m["official_accepts"] is not None and m["cb_accepts"] is not None
                      and m["official_accepts"] != m["cb_accepts"])
        if ours == sorted(rec_failed):
            match += 1
        else:
            mism += 1
    print("== Consistency with ConfiBench's own Eval2_failed_mutant_idxes ==")
    print(f"   records matching exactly : {match}")
    print(f"   records differing        : {mism}")
    print(f"   no recorded list         : {skipped}\n")

    # 2. Classify every discarded catch by whether its scenario was rightly masked.
    kinds = Counter()
    rec_over, rec_right = defaultdict(set), defaultdict(set)
    for r in recs:
        if not r["eval1"]:
            continue
        masks = meta.get((r["run"], r["task"]), ({}, None))[0]
        for m in r["mutants"]:
            if not (m["official_accepts"] is False and m["discarded_by_mask"]):
                continue
            catches = per_mut.get((r["run"], r["task"], m["idx"]), {})
            over = right = unknown = False
            for sub, scen in catches.items():
                mask = masks.get(sub)
                g = gold.get((r["run"], r["task"], sub))
                for s in scen:
                    if mask is None or not (0 < s <= len(mask)) or mask[s - 1]:
                        continue                      # not a masked scenario
                    if g is None:
                        unknown = True
                    elif s in g:
                        right = True                  # Golden fails it: rightly masked
                    else:
                        over = True                   # Golden passes it: over-masked
            if over:
                kinds["over-masked (Golden passes the scenario)"] += 1
                rec_over[(r["run"], r["task"])].add(m["idx"])
            elif right:
                kinds["rightly masked (Golden fails the scenario)"] += 1
                rec_right[(r["run"], r["task"])].add(m["idx"])
            else:
                kinds["undetermined"] += 1
    tot = sum(kinds.values())
    print("== Why were the discarded catches discarded? ==")
    for k, v in kinds.most_common():
        print(f"   {v:4d}  {k}   {v/tot:.1%}")

    # 3. Oracle upper bounds on Eval2, per mode of recovery.
    def eval2_if(recover):
        passed = 0
        for r in recs:
            if not r["eval1"]:
                continue
            ms = [m for m in r["mutants"] if m["official_accepts"] is not None
                  and m["cb_accepts"] is not None]
            if not ms:
                continue
            got = recover.get((r["run"], r["task"]), set())
            agree = 0
            for m in ms:
                cb = m["cb_accepts"] and not (m["idx"] in got)
                agree += (m["official_accepts"] == cb)
            if agree / len(ms) >= LOOSE:
                passed += 1
        return passed / len(recs)

    both = defaultdict(set)
    for k in set(rec_over) | set(rec_right):
        both[k] = rec_over.get(k, set()) | rec_right.get(k, set())
    print("\n== Oracle upper bounds on ConfiBench Eval2 (NOT results) ==")
    print(f"   as released                                   : {eval2_if({}):.4f}")
    print(f"   + unmask only over-masked scenarios           : {eval2_if(rec_over):.4f}"
          "   (Eval1 unaffected)")
    print(f"   + also repair rightly-masked scenarios        : {eval2_if(both):.4f}"
          "   (needs a correct repaired value)")


if __name__ == "__main__":
    main()
