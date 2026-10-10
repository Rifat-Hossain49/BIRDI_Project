#!/usr/bin/env python3
"""Where does ConfiBench actually lose points? Measured from its own archive.

Every number here comes from ConfiBench's released run tree -- its per-mutant
logs, its scenario masks, its recorded verdicts. Nothing is re-simulated and no
model is consulted, so the analysis describes ConfiBench as it ran, not as we
would re-run it.

ConfiBench's verdict on a design is

    AND over sub-testbenches i ( no failure on an UNMASKED scenario of TB_i )

where the confidence estimator masks scenarios it judges suspicious. A masked
scenario's failures are ignored. The checker prints its raw failure list BEFORE
the mask is applied, so for every mutant we can recover what ConfiBench caught
and what the mask then threw away.

Questions, in order:
  Q1  Where does the Eval2 shortfall come from: Eval1 failures, or Eval2 failures
      on testbenches that did pass Eval1?
  Q2  For each Eval2 disagreement, which direction: a MISSED detection (official
      rejects the mutant, ConfiBench accepts) or a FALSE rejection (official
      accepts, ConfiBench rejects)?
  Q3  Of the missed detections, how many were caught by ConfiBench's own
      stimulus and checker and then discarded by its mask?
  Q4  Combinational versus sequential.
  Q5  Is failure systematic (every run) or stochastic (some runs)?
"""
from __future__ import annotations

import argparse
import json
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

MISMATCH_RE = re.compile(r"Mismatches:\s*(\d+)\s+in\s+(\d+)\s+samples")
LOOSE = 0.8


def official_accepts(txt: str):
    m = MISMATCH_RE.search(txt)
    return None if not m else int(m.group(1)) == 0


def raw_failed_scenarios(txt: str):
    """The checker's own failure list, before any mask. None if unreadable."""
    a, b = txt.rfind("["), txt.rfind("]")
    if a == -1 or b == -1 or b < a:
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


def loose_eval2(d: dict) -> bool:
    if not d.get("Eval1_pass"):
        return False
    if d.get("Eval2_pass"):
        return True
    r = d.get("Eval2_ratio") or ""
    if "/" not in r:
        return False
    a, b = r.split("/")
    ok = float(b) > 0 and float(a) / float(b) >= LOOSE
    if d["task_id"] == "m2014_q3":
        return d.get("Eval2_failed_mutant_idxes", []) == [3, 4, 7, 8, 9, 10] or ok
    return ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", type=Path, required=True)
    ap.add_argument("--variant", default="ConfiBench_4o")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    z = zipfile.ZipFile(args.zip)
    base = f"saves_inEDA/TODAES/{args.variant}/"
    names = [n for n in z.namelist() if n.startswith(base)]

    # Index per (run, task): data.json and the per-mutant eval files.
    data, golden_tb, gen_tb = {}, defaultdict(dict), defaultdict(lambda: defaultdict(dict))
    for n in names:
        p = n[len(base):].split("/")
        if len(p) < 3:
            continue
        run, task = p[0], p[1]
        key = (run, task)
        if n.endswith("/data.json"):
            data[key] = n
            continue
        m = re.search(r"eval2_GoldenTB_and_mutants/mutant_(\d+)/(GoldenTB|GeneratedTB)(?:/(\d+))?/(run_info(?:_py)?\.txt)$", n)
        if not m:
            continue
        idx, kind, sub, fname = int(m.group(1)), m.group(2), m.group(3), m.group(4)
        if kind == "GoldenTB" and fname == "run_info.txt":
            golden_tb[key][idx] = n
        elif kind == "GeneratedTB" and fname == "run_info_py.txt":
            gen_tb[key][idx][sub or "0"] = n

    rec = []
    for key, dpath in sorted(data.items()):
        d = json.loads(z.read(dpath).decode("utf-8", "replace"))
        masks = {str(mb.get("iter_id")): mb.get("scen_mask")
                 for mb in (d.get("multibench_info") or []) if isinstance(mb, dict)}
        muts = []
        for idx in sorted(golden_tb.get(key, {})):
            off = official_accepts(z.read(golden_tb[key][idx]).decode("utf-8", "replace"))
            subs = gen_tb.get(key, {}).get(idx, {})
            raw_any, masked_only, readable = False, False, bool(subs)
            verdict_accept = True
            for sub, path in subs.items():
                fails = raw_failed_scenarios(z.read(path).decode("utf-8", "replace"))
                if fails is None:
                    readable = False
                    continue
                if not fails:
                    continue
                raw_any = True
                mask = masks.get(sub)
                if mask is not None and all(0 < s <= len(mask) and mask[s - 1] is False
                                            for s in fails):
                    masked_only = True        # caught, then discarded by the mask
                else:
                    verdict_accept = False    # a surviving failure: rejected
            muts.append({"idx": idx, "official_accepts": off,
                         "cb_accepts": verdict_accept if readable else None,
                         "caught_raw": raw_any,
                         "discarded_by_mask": masked_only and verdict_accept})
        rec.append({"run": key[0], "task": key[1],
                    "circuit": d.get("circuit_type", "?"),
                    "eval1": bool(d.get("Eval1_pass")),
                    "eval2": loose_eval2(d),
                    "ratio": d.get("Eval2_ratio") or "",
                    "mask_used": any(m is not None and not all(m)
                                     for m in masks.values()),
                    "n_subtb": len(masks) or 1,
                    "mutants": muts})

    n = len(rec)
    e1 = sum(r["eval1"] for r in rec)
    e2 = sum(r["eval2"] for r in rec)
    print(f"{args.variant}: {n} (run, task) records over "
          f"{len({r['run'] for r in rec})} runs\n")

    print("== Q1. Where the Eval2 shortfall comes from ==")
    lost_e1 = n - e1
    lost_e2 = e1 - e2
    print(f"  Eval2 = {e2}/{n} = {e2/n:.4f}; shortfall {n-e2} records")
    print(f"    testbench rejects the CORRECT design (Eval1 fail)    : {lost_e1:4d}  "
          f"({lost_e1/(n-e2):.0%} of shortfall)")
    print(f"    passes Eval1 but disagrees on >20% of mutants        : {lost_e2:4d}  "
          f"({lost_e2/(n-e2):.0%} of shortfall)")

    print("\n== Q2. Direction of every Eval2 disagreement (Eval1-passing records) ==")
    dirs = Counter()
    for r in rec:
        if not r["eval1"]:
            continue
        for m in r["mutants"]:
            o, c = m["official_accepts"], m["cb_accepts"]
            if o is None or c is None:
                dirs["unscoreable"] += 1
            elif o == c:
                dirs["agree"] += 1
            elif (not o) and c:
                dirs["MISSED  (official rejects, ConfiBench accepts)"] += 1
            else:
                dirs["FALSE-REJECT (official accepts, ConfiBench rejects)"] += 1
    tot = sum(v for k, v in dirs.items() if k != "unscoreable")
    for k, v in dirs.most_common():
        print(f"    {v:5d}  {k}" + (f"   {v/tot:.1%}" if k != "unscoreable" and tot else ""))

    print("\n== Q3. Missed detections the mask threw away ==")
    missed = discarded = 0
    for r in rec:
        if not r["eval1"]:
            continue
        for m in r["mutants"]:
            if m["official_accepts"] is False and m["cb_accepts"] is True:
                missed += 1
                if m["discarded_by_mask"]:
                    discarded += 1
    print(f"    missed detections                      : {missed}")
    print(f"    ...of which caught, then masked away   : {discarded}"
          + (f"  ({discarded/missed:.1%})" if missed else ""))
    print(f"    ...genuinely never caught (stimulus)   : {missed - discarded}")
    used = sum(r["mask_used"] for r in rec)
    print(f"    records where a mask was active        : {used}/{n}")

    # Would un-masking flip Eval2? Recompute the loose ratio per record with the
    # masked-away catches counted as rejections.
    flip = 0
    for r in rec:
        if not r["eval1"] or r["eval2"]:
            continue
        ms = [m for m in r["mutants"] if m["official_accepts"] is not None
              and m["cb_accepts"] is not None]
        if not ms:
            continue
        agree = sum(1 for m in ms if m["official_accepts"] ==
                    (m["cb_accepts"] and not m["discarded_by_mask"]))
        if agree / len(ms) >= LOOSE:
            flip += 1
    print(f"    Eval2-failing records that would PASS if every masked\n"
          f"    catch were kept                        : {flip}")

    print("\n== Q4. By circuit type ==")
    by = defaultdict(lambda: [0, 0, 0])
    for r in rec:
        b = by[r["circuit"]]
        b[0] += 1; b[1] += r["eval1"]; b[2] += r["eval2"]
    for c, (k, a, b) in sorted(by.items()):
        print(f"    {c:6s} n={k:4d}  Eval1={a/k:.4f}  Eval2={b/k:.4f}")

    print("\n== Q5. Systematic versus stochastic, per task ==")
    per_task = defaultdict(list)
    for r in rec:
        per_task[r["task"]].append(r["eval2"])
    runs = max(len(v) for v in per_task.values())
    hist = Counter(sum(v) for v in per_task.values())
    for k in range(runs + 1):
        print(f"    Eval2 passed in {k}/{runs} runs : {hist.get(k, 0):4d} tasks")
    oracle = sum(1 for v in per_task.values() if any(v)) / len(per_task)
    mean = sum(sum(v) / len(v) for v in per_task.values()) / len(per_task)
    print(f"    mean over runs = {mean:.4f};  best-of-{runs} (oracle) = {oracle:.4f}")

    if args.out:
        args.out.write_text(json.dumps(rec, indent=0), encoding="utf-8")
        print(f"\nper-record detail -> {args.out}")


if __name__ == "__main__":
    main()
