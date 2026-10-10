# Adapter Support Report

Step B of the ACTIVE-TB-AMP brief, after exactly one bounded hardening pass.
No LLM calls, no new test generation, no GPU.

## Result

| Class | Tasks | Sequential |
| --- | --- | --- |
| **STEP_MODEL** | **15 / 15 (100%)** | 15 |
| TRACE_ONLY | 0 | 0 |
| UNSUPPORTED | 0 | 0 |

**Replay-equivalence gate: 15 of 15 adapted tasks pass (100%).** The gate was
not weakened as support increased; it is the same two-part test throughout.

Blocker accounting, as requested: **unique unsupported tasks 0, blocker
instances 0, tasks with more than one blocker 0.** The earlier report's
mismatch (9 tasks against 10 blocker instances) came from listing
`mt2015_muxdff` under both "gate failure" and the equivalence tally; the
report now records blockers as an explicit per-task list so the two counts can
never drift apart again.

| Task | Class | Events | Checks | Replay cost | Clean | Perturbed |
| --- | --- | --- | --- | --- | --- | --- |
| 2014_q4a | STEP_MODEL | 41 | 20 | 41 | pass | pass |
| circuit8 | STEP_MODEL | 45 | 23 | 45 | pass | pass |
| circuit9 | STEP_MODEL | 40 | 26 | 40 | pass | pass |
| circuit10 | STEP_MODEL | 37 | 23 | 37 | pass | pass |
| count15 | STEP_MODEL | 120 | 75 | 120 | pass | pass |
| countslow | STEP_MODEL | 91 | 76 | 91 | pass | pass |
| dff8ar | STEP_MODEL | 32 | 16 | 32 | pass | pass |
| dualedge | STEP_MODEL | 66 | 37 | 66 | pass | pass |
| ece241_2013_q4 | STEP_MODEL | 56 | 31 | 56 | pass | pass |
| ece241_2014_q5b | STEP_MODEL | 41 | 27 | 41 | pass | pass |
| lemmings3 | STEP_MODEL | 67 | 51 | 67 | pass | pass |
| m2014_q4k | STEP_MODEL | 51 | 25 | 51 | pass | pass |
| mt2015_muxdff | STEP_MODEL | 90 | 62 | 90 | pass | pass |
| review2015_count1k | STEP_MODEL | 3068 | 3060 | 3068 | pass | pass |
| review2015_shiftcount | STEP_MODEL | 39 | 23 | 39 | pass | pass |

"Checks" counts positions where the frozen checker has a recoverable opinion;
the remaining events are setup positions the checker does not evaluate. Replay
cost counts **every** emitted event, setup included, because a deployed
testbench must execute them.

## What the equivalence gate tests

For each task, two probes through the **frozen checker's own**
`SignalTxt_to_dictlist` and `check_dut`, executed verbatim:

1. **clean** - feed back the recovered expectations; the checker must report
   zero failures. This is the strong test: it fails if recovery is wrong
   anywhere the checker has an opinion.
2. **perturbed** - corrupt three recovered positions; the checker must report
   failures. This catches an adapter that trivially passes by never being
   checked.

## Fixes made, all general

The hardening pass changed no checker semantics and added no task-specific
accommodation. Every fix was driven by a diagnosed general cause.

### 1. Deterministic RHS evaluator (`amp/vexpr.py`)

Replaced the four-pattern regex matcher with a recursive-descent parser (no
Python `eval`) covering unary `!` `~` `-`, arithmetic including `%`, comparison,
equality, logical and bitwise operators, shifts, parentheses and ternary
`cond ? a : b`. Unsupported input is **refused**, not guessed; division and
modulo by zero raise rather than returning a silent zero.

`amp/vexpr_test.py`: **41 assertions, all passing**, including the three
constructs that blocked pilot tasks - `!d`, `scenario % 2`,
`(data == 1) ? 0 : 1`.

A second, subtler defect surfaced here: `scenario` was tracked as a parser
local but never placed in the evaluator environment, so a driver referencing its
own scenario counter (`d = scenario % 2`) failed to resolve it. Exposing
`scenario` in the environment is what took the pilot from 14/15 to 15/15.

### 2. Event-count limitation removed

`review2015_count1k` emits **3068 events**. Nothing is truncated: the cap is now
a pathological-input guard set far above any real driver, and the full replay
prefix cost stays available for the compaction budget.

Removing the cap exposed an O(n^2) cost in the original recovery, which replayed
a prefix per event. `recover_expectations` now applies each candidate output
assignment to the whole sequence in a single `check_dut` run, giving O(candidates)
checker invocations instead of O(events x candidates). Measured effect on
`count10`: identical 71 expectations, runtime from seconds to 0.1 s.

That single-pass method relies on one property, which is **verified rather than
assumed**: positions are identified by rendering the scenario field as the event
index, and the routine first confirms that relabelling does not change the
checker's verdict. If it does, recovery refuses.

### 3. Multi-output and non-point checkers

Four tasks reported "no recoverable expectations" purely because the probe only
handled a single output. `circuit8` and `circuit10` have two outputs;
`ece241_2013_q4` and `lemmings3` have four. Recovery now sweeps the Cartesian
product of outputs under a work budget. All four are now STEP_MODEL with the
gate passing.

No checker is forced to answer arbitrary new sequences. Recovery reports a point
expectation only where the frozen checker actually accepts exactly one value; a
position where it accepts several, or none, is left with no expectation.

### 4. `mt2015_muxdff` diagnosed, fixed generally

The checker rejected the adapter's own recovered expectation, so recovery was
semantically wrong. The general cause: **a checker's expectation domain can
exceed the driver's declared port width.** `mt2015_muxdff` declares `wire Q` as
one bit while its `GoldenDUT` holds a three-bit value masked to `0x7`, so a
sweep bounded by the declared width never reached the accepted value.

The fix is general: when some position rejects every candidate in the declared
range, the sweep widens and is kept only if it resolves strictly more positions.
No exception for this task exists anywhere in the code.

The same class of defect explained `review2015_count1k`, whose `q` is ten bits
wide and whose checker counts modulo 1000, while the probe was capped at eight
bits. The arbitrary bit cap was replaced by an explicit **work budget**
(`combos x events`), so declared widths are honoured whenever affordable.

## Known limitation carried forward

`SignalTxt_to_dictlist` maps X and Z to 0 in the frozen checkers, so a mutant
leaving an output undefined is read as 0 and can pass. This is the published
frontend's behaviour and is **preserved**, not repaired: changing it would alter
the semantics whose paired comparison the experiment depends on. It is recorded
here and remains a candidate for a clearly separate ablation.

## Status against the stop rule

Support is 15/15 with a 100% equivalence gate, above the 10-12 threshold, so the
next step is checker-preserving compaction run as the **real pilot** rather than
a narrow feasibility experiment. The hardening pass is closed; no further
parser or checker accommodations will be added to raise coverage.
