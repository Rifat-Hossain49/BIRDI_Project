#!/usr/bin/env python3
"""Regression tests pinning the published Eval2 semantics.

Required by the ACTIVE-TB-AMP brief section 0. These lock our port of
analyze.py against known verdict vectors so a future refactor cannot silently
substitute a different scoring rule.

The distinction under test: published Eval2 is agreement with the golden
testbench's verdicts at a 0.8 threshold, NOT raw mutant detection, and NOT the
stored strict `Eval2_pass` boolean.
"""
from __future__ import annotations

import sys

from metric_reconciliation import (
    eval0_pass,
    loose_eval2_pass,
    published_eval2,
    strict_all_verdicts_agree,
)

ok = True


def check(label, got, want):
    global ok
    good = got == want
    ok = ok and good
    print(f"  [{'ok' if good else 'FAIL'}] {label}: got {got!r}, want {want!r}")


def row(task="generic", ratio=None, strict=False, eval1=True,
        iv=True, py=True, failed_idxes=None):
    d = {"task_id": task, "Eval1_pass": eval1, "Eval2_pass": strict,
         "Eval0_iv_pass": iv, "Eval0_py_pass": py}
    if ratio is not None:
        d["Eval2_ratio"] = ratio
    if failed_idxes is not None:
        d["Eval2_failed_mutant_idxes"] = failed_idxes
    return d


def main() -> int:
    print("Agreement thresholds (LOOSE_FACTOR = 0.8)")
    check("10/10 passes", published_eval2(row(ratio="10/10")), True)
    check("9/10 passes", published_eval2(row(ratio="9/10")), True)
    check("8/10 passes (exactly at threshold)", published_eval2(row(ratio="8/10")), True)
    check("7/10 FAILS (below threshold)", published_eval2(row(ratio="7/10")), False)
    check("4/5 passes", published_eval2(row(ratio="4/5")), True)
    check("3/5 fails", published_eval2(row(ratio="3/5")), False)

    print("Published Eval2 is not the strict boolean")
    r = row(ratio="8/10", strict=False)
    check("8/10 published passes", published_eval2(r), True)
    check("8/10 strict fails", strict_all_verdicts_agree(r), False)
    check("this divergence is the 0.7013 vs 0.5231 gap", published_eval2(r) != strict_all_verdicts_agree(r), True)

    print("Stored strict flag short-circuits regardless of ratio")
    check("strict True with no ratio passes", published_eval2(row(strict=True)), True)
    check("missing ratio and strict False fails", published_eval2(row()), False)

    print("Golden rejection (Eval1 fail) is scored separately, not by Eval2")
    r = row(ratio="10/10", eval1=False)
    check("Eval2 alone still True on the ratio", published_eval2(r), True)
    check("gated on Eval0 and Eval1 it is False",
          bool(eval0_pass(r) and r["Eval1_pass"] and published_eval2(r)), False)

    print("Compile failure (Eval0 fail)")
    r = row(ratio="10/10", iv=False)
    check("Eval0 gate False", eval0_pass(r), False)
    check("gated score False", bool(eval0_pass(r) and r["Eval1_pass"] and published_eval2(r)), False)

    print("Task-specific exception: m2014_q3")
    check("exact failed-index vector passes despite 4/10",
          published_eval2(row(task="m2014_q3", ratio="4/10",
                              failed_idxes=[3, 4, 7, 8, 9, 10])), True)
    check("same vector on another task fails",
          published_eval2(row(task="count10", ratio="4/10",
                              failed_idxes=[3, 4, 7, 8, 9, 10])), False)
    check("m2014_q3 with a different failing set still fails",
          published_eval2(row(task="m2014_q3", ratio="4/10",
                              failed_idxes=[1, 2, 3, 4, 5, 6])), False)
    check("m2014_q3 above threshold passes normally",
          published_eval2(row(task="m2014_q3", ratio="9/10")), True)

    print("Known-equivalent alternative: golden TB also accepts the mutant")
    # Agreement counts accepting a mutant the golden TB accepts. A testbench
    # that rejects such a mutant LOSES agreement, so 'detection' and 'agreement'
    # are different measurements and must not be conflated.
    check("agreeing on an accepted mutant keeps 10/10",
          published_eval2(row(ratio="10/10")), True)
    check("over-rejecting it drops to 9/10 but still passes",
          published_eval2(row(ratio="9/10")), True)
    check("over-rejecting three drops to 7/10 and fails",
          published_eval2(row(ratio="7/10")), False)

    print("Real surviving bug: missed detections reduce agreement")
    check("missing 2 of 10 real bugs -> 8/10 still passes published Eval2",
          published_eval2(row(ratio="8/10")), True)
    check("  (so published Eval2 tolerates real escapes; H(B) does not)",
          strict_all_verdicts_agree(row(ratio="8/10")), False)

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
