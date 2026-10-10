#!/usr/bin/env python3
"""Score pilot 2 exactly as DLR2_PREREGISTRATION.md §5 specifies.

Joins the direct-path rows (reference pilot) with the checklist-path rows one
sub-testbench at a time. Both files list sub-testbenches in the same order (the
pilot-2 list is a filtered copy of the reference-pilot list), so a streaming merge
keeps memory to a single sub-testbench.

Also checks that golden's rows are identical in both runs -- if they are not, the
two simulations are not comparable and nothing below should be trusted.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "kaggle_runs/ref_pilot/ref_rows.jsonl"
SEL = json.loads((ROOT / "analysis/dlr2_tasks.json").read_text())
TARGETS, CONTROLS = SEL["targets"], SEL["controls"]
WANT = set(TARGETS) | set(CONTROLS)


def groups(path: Path, fam_filter):
    cur, recs = None, []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            if r["task_id"] not in WANT:
                if cur is not None:
                    yield cur, recs
                    cur, recs = None, []
                continue
            key = (r["run"], r["task_id"], r["iter_id"])
            if key != cur:
                if cur is not None:
                    yield cur, recs
                cur, recs = key, []
            if fam_filter(r["family"]):
                recs.append(r)
        if cur is not None:
            yield cur, recs


def scen_index(gold):
    s = defaultdict(list)
    for i, g in enumerate(gold):
        try:
            s[json.loads(g).get("scenario", "?")].append(i)
        except Exception:
            s["?"].append(i)
    return s


def majority(traces):
    if len(traces) < 3:
        return None
    t, c = Counter(traces).most_common(1)[0]
    return t if c * 2 > len(traces) else None


def main() -> None:
    chk_path = Path(sys.argv[1])
    ref_it = groups(REF, lambda f: f == "golden" or f.startswith("A"))
    st = Counter()
    fix = defaultdict(lambda: [0, 0])          # target task -> [fixed, shared-misread]
    expose = defaultdict(lambda: [0, 0])
    ctrl = Counter()
    mixed_ok = Counter()
    for key, chk in groups(chk_path, lambda f: True):
        for rkey, ref in ref_it:
            if rkey == key:
                break
        else:
            st["checklist groups with no direct-path match"] += 1
            break
        g_ref = next((r["rows"] for r in ref if r["family"] == "golden" and r["status"] == "RAN"), None)
        g_chk = next((r["rows"] for r in chk if r["family"] == "golden" and r["status"] == "RAN"), None)
        if g_ref is None or g_chk is None:
            st["groups missing golden"] += 1
            continue
        st["groups matched"] += 1
        if g_ref != g_chk:
            st["GOLDEN ROWS DIFFER BETWEEN RUNS"] += 1
            continue
        direct = [r["rows"] for r in ref if r["family"].startswith("A") and r["status"] == "RAN" and r["rows"]]
        check = [r["rows"] for r in chk if r["family"].startswith("C") and r["status"] == "RAN" and r["rows"]]
        task = key[1]
        for sc, idx in scen_index(g_ref).items():
            gt = tuple(g_ref[i] for i in idx)
            dtr = [tuple(r[i] if i < len(r) else None for i in idx) for r in direct]
            ctr = [tuple(r[i] if i < len(r) else None for i in idx) for r in check]
            if len(dtr) < 3:
                continue
            dmaj, cmaj = majority(dtr), majority(ctr)
            shared = len(set(dtr)) == 1 and dtr[0] != gt
            if task in TARGETS and shared:
                fix[task][1] += 1
                fix[task][0] += (cmaj == gt)
                expose[task][1] += 1
                expose[task][0] += any(t != dtr[0] for t in ctr)
            if task in CONTROLS:
                ctrl["scenarios"] += 1
                ctrl["direct correct"] += (dmaj == gt)
                ctrl["checklist correct"] += (cmaj == gt)
            mixed_ok["scenarios"] += 1
            mixed_ok["direct correct"] += (dmaj == gt)
            mixed_ok["mixed correct"] += (majority(dtr + ctr) == gt)

    print("join:", dict(st))
    if st["GOLDEN ROWS DIFFER BETWEEN RUNS"]:
        print("WARNING: golden rows differ between runs in some groups; those groups were excluded")
    print("\n== PRIMARY: target tasks, shared-misreading scenarios ==")
    fixed = 0
    for t in TARGETS:
        f, n = fix[t]
        e, _ = expose[t]
        rate = f / n if n else 0.0
        fixed += rate >= 0.5 and n > 0
        print(f"   {t:18s} shared-misread {n:4d}   fixed by checklist {f:4d} ({rate:.0%})   "
              f"exposed by mixed pool {e:4d} ({e/max(1,n):.0%})   {'FIXED' if rate >= 0.5 and n else ''}")
    tot_f = sum(v[0] for v in fix.values()); tot_n = sum(v[1] for v in fix.values())
    print(f"   pooled: {tot_f}/{tot_n} = {tot_f/max(1,tot_n):.1%}   tasks fixed: {fixed}/{len(TARGETS)}")
    print("\n== GUARD: control tasks ==")
    dacc = ctrl["direct correct"] / max(1, ctrl["scenarios"])
    cacc = ctrl["checklist correct"] / max(1, ctrl["scenarios"])
    print(f"   scenarios {ctrl['scenarios']}   direct {dacc:.3f}   checklist {cacc:.3f}   delta {cacc-dacc:+.3f}")
    print("\n== SECONDARY: all 12 tasks, mixed pool (direct + checklist) ==")
    n = mixed_ok["scenarios"]
    print(f"   scenarios {n}   direct majority {mixed_ok['direct correct']/max(1,n):.3f}   "
          f"mixed majority {mixed_ok['mixed correct']/max(1,n):.3f}")
    go = fixed >= 3 and (cacc - dacc) >= -0.05 and st["groups matched"] > 0
    print(f"\nDECISION (>=3/6 targets fixed and control drop <= 5 pts): {'GO' if go else 'NO-GO'}")


if __name__ == "__main__":
    main()
