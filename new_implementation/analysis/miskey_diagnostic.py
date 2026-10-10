#!/usr/bin/env python3
"""EXPLORATORY: does item discrimination carry any signal at all?

The pre-registered rule failed (MISKEY_PREREGISTRATION.md, both generators). This
does not rescue it and must not be read as a result. It asks one diagnostic
question: among scenarios ConfiBench masked, does `disc(s)` separate the ones
Golden passes (over-masked -- unmasking is safe) from the ones Golden fails
(rightly masked -- unmasking breaks Eval1)?

AUC 0.5 means the signal is useless at any threshold, so the direction is dead.
AUC well above 0.5 means the idea works and tau = 0 was the wrong operating
point, which would justify a NEW pre-registered test on untouched data.

ConfiBench's own confidence is scored the same way, so it is visible whether
discrimination adds anything beyond what ConfiBench already knew.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from miskey_eval import confibench_confidence, discrimination, load  # noqa: E402


def auc(pos, neg):
    if not pos or not neg:
        return float("nan")
    wins = 0.0
    for p in pos:
        for n in neg:
            wins += 1.0 if p > n else (0.5 if p == n else 0.0)
    return wins / (len(pos) * len(neg))


def main() -> None:
    zpath = Path(sys.argv[1])
    variant = sys.argv[2] if len(sys.argv) > 2 else "ConfiBench_4o"
    recs, gold, _off, _gen = load(zpath, variant)
    over_d, right_d, over_c, right_c = [], [], [], []
    undefined = {"over": 0, "right": 0}
    for (run, task), d in recs.items():
        for mb in d.get("multibench_info") or []:
            if not isinstance(mb, dict) or mb.get("scen_mask") is None:
                continue
            rs = mb.get("RSmatrix") or []
            g = gold.get((run, task, str(mb.get("iter_id"))))
            if g is None or not rs:
                continue
            conf = confibench_confidence(rs, len(mb["scen_mask"]))
            for s, keep in enumerate(mb["scen_mask"]):
                if keep:
                    continue
                label = "right" if (s + 1) in g else "over"
                dv = discrimination(rs, s)
                if dv is None:
                    undefined[label] += 1
                    continue
                (over_d if label == "over" else right_d).append(dv)
                (over_c if label == "over" else right_c).append(conf[s])
    print(f"{variant} -- masked scenarios with a Golden log")
    print(f"  over-masked  (Golden passes; unmasking is safe)   : "
          f"{len(over_d)} scored, {undefined['over']} undefined")
    print(f"  rightly masked (Golden fails; unmasking breaks it) : "
          f"{len(right_d)} scored, {undefined['right']} undefined")
    print(f"\n  AUC, item discrimination     : {auc(over_d, right_d):.3f}")
    print(f"  AUC, ConfiBench's confidence : {auc(over_c, right_c):.3f}")
    for name, xs in (("over-masked", over_d), ("rightly masked", right_d)):
        if xs:
            xs = sorted(xs)
            print(f"  disc(s) {name:15s}: median {xs[len(xs)//2]:+.3f}  "
                  f"share > 0: {sum(1 for x in xs if x > 0)/len(xs):.1%}")


if __name__ == "__main__":
    main()
