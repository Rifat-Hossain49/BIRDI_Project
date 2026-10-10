#!/usr/bin/env python3
"""Score a cross-family judge under XJUDGE_PREREGISTRATION.md.

Reuses the verified machinery of `miskey_eval.py` -- the same log loading, the
same "start from ConfiBench's recorded result and apply only the flips the logs
prove" scoring -- with exactly one difference: the new mask comes from the judge.

Rule (fixed in the pre-registration, not tuned here): for each scenario
ConfiBench masks, p(s) = share of judge RTLs that RAN whose checker failure list
omits s. With at least 3 such RTLs, unmask iff p(s) >= 0.5.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from miskey_eval import (eval2_pass, load, paired_boot, per_task,  # noqa: E402
                         rejects)
from miskey_diagnostic import auc  # noqa: E402

MIN_RAN = 3
P_MIN = 0.5


def judge_votes(path: Path):
    """(variant, run, task, iter_id) -> list of failure lists from RTLs that ran."""
    votes = defaultdict(list)
    status = Counter()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        status[r["status"].split(":")[0]] += 1
        if r["status"] == "RAN" and r["failed"] is not None:
            votes[(r["variant"], r["run"], r["task_id"], str(r["iter_id"]))].append(set(r["failed"]))
    return votes, status


def judge_mask(recorded, fails_list):
    if len(fails_list) < MIN_RAN:
        return list(recorded), [], {}
    new, changed, p = list(recorded), [], {}
    for i, keep in enumerate(recorded):
        if keep:
            continue
        s = i + 1
        ps = sum(1 for f in fails_list if s not in f) / len(fails_list)
        p[i] = ps
        if ps >= P_MIN:
            new[i] = True
            changed.append(i)
    return new, changed, p


def score_variant(zpath: Path, variant: str, votes):
    recs, gold, off, gen = load(zpath, variant)
    base, meth = {}, {}
    audit = Counter()
    pos, neg = [], []            # p(s) for over-masked / rightly masked
    for (run, task), d in recs.items():
        e1 = bool(d.get("Eval1_pass"))
        failed = set(d.get("Eval2_failed_mutant_idxes") or [])
        n_mut = len(d.get("mutants") or [])
        base[(run, task)] = (e1, eval2_pass(task, e1, n_mut, sorted(failed)))
        subs = [mb for mb in (d.get("multibench_info") or [])
                if isinstance(mb, dict) and mb.get("scen_mask") is not None
                and any((run, task, i, str(mb.get("iter_id"))) in gen
                        for i in range(1, n_mut + 1))]
        if not subs or not e1:
            meth[(run, task)] = base[(run, task)]
            continue
        rec_m, new_m = {}, {}
        for mb in subs:
            sid = str(mb["iter_id"])
            rec_m[sid] = list(mb["scen_mask"])
            fl = votes.get((variant, run, task, sid), [])
            nm, ch, p = judge_mask(mb["scen_mask"], fl)
            new_m[sid] = nm
            audit["scenarios masked by ConfiBench"] += sum(1 for v in mb["scen_mask"] if not v)
            audit["scenarios with >= 3 judge votes"] += len(p)
            audit["scenarios unmasked"] += len(ch)
            g = gold.get((run, task, sid))
            if g is not None:
                for i, ps in p.items():
                    (neg if (i + 1) in g else pos).append(ps)
        e1_new = e1
        for sid, nm in new_m.items():
            if nm == rec_m[sid]:
                continue
            g = gold.get((run, task, sid))
            if g is None:
                e1_new = False
                audit["Eval1 charged: golden log missing"] += 1
                break
            if rejects(g, nm):
                e1_new = False
                audit["Eval1 broken by an unmask"] += 1
                break
        failed_new = set(failed)
        for i in range(1, n_mut + 1):
            o = off.get((run, task, i))
            if o is None:
                continue
            rb = ra = False
            ok = True
            for sid in new_m:
                f = gen.get((run, task, i, sid))
                vb, va = rejects(f, rec_m[sid]), rejects(f, new_m[sid])
                if vb is None or va is None:
                    ok = False
                    break
                rb, ra = rb or vb, ra or va
            if not ok:
                continue
            before, after = (not rb), (not ra)
            if (o != before) != (i in failed):
                audit["mutant skipped: reconstruction disagrees"] += 1
                continue
            if before and not after:
                if o is False:
                    failed_new.discard(i)
                    audit["missed detection recovered"] += 1
                else:
                    failed_new.add(i)
                    audit["FALSE rejection introduced"] += 1
        meth[(run, task)] = (e1_new, eval2_pass(task, e1_new, n_mut, sorted(failed_new)))
    return base, meth, audit, pos, neg


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", type=Path, required=True)
    ap.add_argument("--judge", type=Path, required=True, help="xjudge_run.py output")
    ap.add_argument("--name", default="judge")
    ap.add_argument("--bootstrap", type=int, default=10000)
    args = ap.parse_args()

    votes, status = judge_votes(args.judge)
    print(f"{args.name}: simulation outcomes {dict(status)}\n")
    verdict = {}
    for variant in ("ConfiBench_4o", "ConfiBench_4omini"):
        base, meth, audit, pos, neg = score_variant(args.zip, variant, votes)
        print(f"== {variant} ==")
        print(f"  diagnostic AUC of p(s) (over- vs rightly masked): {auc(pos, neg):.3f}"
              f"   [{len(pos)} over-masked, {len(neg)} rightly masked]"
              f"   ConfiBench's own confidence on 4o: 0.614")
        for name, idx in (("Eval1", 0), ("Eval2", 1)):
            b, m = per_task(base, idx), per_task(meth, idx)
            d, lo, hi, k = paired_boot(m, b, args.bootstrap)
            print(f"  {name}: ConfiBench {sum(b.values())/len(b):.4f}  with judge "
                  f"{sum(m.values())/len(m):.4f}  delta {d:+.4f}  95% CI [{lo:+.4f}, {hi:+.4f}]")
            if name == "Eval2":
                verdict[variant] = (d, lo)
        for k2, v in audit.items():
            print(f"    {v:6d}  {k2}")
        print()
    d4, lo4 = verdict["ConfiBench_4o"]
    dm, _ = verdict["ConfiBench_4omini"]
    ok = lo4 > 0 and dm > 0
    print(f"PRE-REGISTERED CRITERION (4o CI lower > 0 and 4o-mini delta > 0): "
          f"{'PASS' if ok else 'FAIL'}   (4o lower {lo4:+.4f}, 4o-mini {dm:+.4f})")


if __name__ == "__main__":
    main()
