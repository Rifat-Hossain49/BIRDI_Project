# Step E: Analysis Definitions, Frozen Before Result Inspection

Written **before** any Golden or hidden-fault result was inspected. The sealed
run had completed at this point; its output was not opened until this document
was committed.

Authoritative suite manifest: `99d6b241afb147ee6b18801314eec7857a7ec34b2ef0e6a4929380c6a7660daa`.
No frozen suite is modified or regenerated.

---

## 1. Saturated vs sparse grouping, all 15 tasks resolved

Rule, as pre-registered in `STEP_E_PREREGISTRATION.md` section 10: new states
reachable within budget <= 2 is **Group A (state-saturated)**; > 2 is **Group B
(state-rich)**.

Measured from frozen artefacts only: the state set reached by the frozen
`STATE_ONLY` B=32 suite, minus the state set reached by the ORIGINAL stimulus,
both computed through the frozen checker. No hidden or Golden data involved.

| Task | Original states | Amplified states (B=32) | New states | Group |
| --- | --- | --- | --- | --- |
| 2014_q4a | 2 | 2 | 0 | A |
| circuit8 | 4 | 4 | 0 | A |
| circuit9 | 7 | 7 | 0 | A |
| circuit10 | 4 | 4 | 0 | A |
| count15 | 16 | 16 | 0 | A |
| countslow | 10 | 10 | 0 | A |
| dualedge | 2 | 2 | 0 | A |
| ece241_2014_q5b | 4 | 4 | 0 | A |
| lemmings3 | 4 | 4 | 0 | A |
| m2014_q4k | 14 | 5 | 0 | A |
| review2015_count1k | 1000 | 32 | 0 | A |
| review2015_shiftcount | 14 | 16 | **2** | A (rule: <= 2) |
| **dff8ar** | 9 | 32 | **27** | **B** |
| **ece241_2013_q4** | 25 | 28 | **16** | **B** |
| mt2015_muxdff | - | - | - | **UNCLASSIFIED / unsupported** |

**Group A: 12 tasks. Group B: 2 tasks. Unclassified: 1 (`mt2015_muxdff`,
unsupported for state-directed mechanism analysis regardless).**

`review2015_shiftcount` lands in Group A on the boundary of the rule (exactly 2
new states). The rule was fixed in advance and is applied as written.

### Consequence recorded in advance

The secondary saturated-vs-sparse analysis has **n = 2 in Group B**. It cannot
support an inferential claim and will be reported as descriptive only.

More importantly, this is a pre-hidden result in its own right: **the
state-directed mechanism reaches genuinely new checker states on only 2 of 14
supported tasks.** On the other 12 the original CorrectBench stimulus already
covers everything a 32-cycle directed search can reach. Pre-registered criterion
6 ("instrumentation demonstrates that amplification reaches genuinely new
checker states/transitions or boundary behaviours") is therefore already known
to be satisfied on only a small minority of tasks, before any hidden result is
seen. This is stated now so it cannot be re-framed after the fact.

Note on `m2014_q4k` and `review2015_count1k`: amplified state counts are *lower*
than original because the amplified suite is capped at 32 cycles while ORIGINAL
runs 56 and 3068 cycles respectively. Fewer states at a fraction of the cost is
not a defect; it is the budget doing its job. "New states" remains the correct
criterion because it measures what the original never reached.

## 2. RANDOM seed aggregation

RANDOM has three seeds (1000, 1001, 1002); directed arms are deterministic.

**The statistical unit is the task.** For every task x budget, the three RANDOM
seeds are averaged first to produce one task-level value, and that single value
is paired against the directed arm. Seeds are never treated as independent
tasks, and n is never inflated beyond the number of tasks.

RANDOM across-seed variance (standard deviation over the three seeds, averaged
over tasks) is reported separately at each budget, so seed sensitivity is
visible rather than hidden inside a mean.

## 3. ORIGINAL is a reference, not an equal-budget competitor

ORIGINAL runs at its true cost (mean 259.3 deployed cycles) and is **excluded**
from all equal-budget head-to-head comparisons.

The equal-budget comparison set is exactly:

```
TRUNCATION, RANDOM, GREEDY_VISIBLE, STATE_ONLY, STATE_PLUS_FAULT
```

ORIGINAL is reported separately as the full-suite reference, and may be used
only for an explicitly labelled **efficiency** statement of the form "arm X at
32 cycles retains Y% of ORIGINAL detection at Z% of its cycle cost". Such a
statement is never presented as an equal-budget win.

## 4. Unchanged

The pre-registered primary B=32 decision criteria in
`STEP_E_PREREGISTRATION.md` section 9 are not modified. The primary comparisons
remain STATE_PLUS_FAULT vs RANDOM and STATE_PLUS_FAULT vs GREEDY_VISIBLE at
B=32, with STATE_ONLY vs RANDOM and STATE_PLUS_FAULT vs STATE_ONLY as the
mechanism ablations.
