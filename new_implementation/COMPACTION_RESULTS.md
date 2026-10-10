# Checker-Preserving Compaction: Pilot Results

> ## FROZEN
>
> These results are final and are not to be tuned or re-run with new selection
> heuristics. They stand as the permanent compaction baseline.
>
> Accepted conclusion:
>
> - smart selection gives a real low-budget gain at B=8 (greedy +0.1680,
>   95% CI [+0.0197, +0.3298]);
> - above roughly 16 cycles most useful behaviour in the original suite is
>   already retained;
> - at B=32 compaction does **not** beat chronological truncation;
> - therefore further improvement must come from generating NEW sequential
>   trajectories, not from selecting subsets of existing ones.
>
> Successor: `amp/sequence_search.py` and the Step E amplification experiment.

Step C/D of the ACTIVE-TB-AMP brief. 15 sequential pilot tasks, all STEP_MODEL
with a 100% replay-equivalence gate. **No LLM calls, no new test generation, no
simulator, no ACTIVE search, no BMC.**

Expected values come only from the frozen CorrectBench checker. Hypotheses guide
selection and never vote on truth.

## Setup

**Test unit.** A driver scenario, with its full event list.

**Cost.** One emitted driver event is one cycle. Every event counts, setup and
reset included, because a deployed testbench must execute them.

**Dependency preservation.** These drivers run scenarios back to back and state
carries across them, so a scenario cannot simply be dropped from the middle.
Each scenario is tested for *independent startability*: does the frozen checker
produce the same expectation sequence from that scenario onward when started
fresh there as it does in context? Only scenarios that pass may be reached
without replaying what precedes them; every other selection carries its full
prefix and is charged for it. Where the full-suffix test is unaffordable the
scenario is conservatively marked dependent, never optimistically independent.

Across the pilot, 79 of 113 scenarios are independently startable.

**Hypotheses.** Single-site AST mutations of the frozen checker's `GoldenDUT`
transition model, in five families: comparison swap, arithmetic/shift swap,
boundary off-by-one, branch negation, dropped state update. Each is split
family-stratified into a **search bank** (used for selection) and a **held-out
validation bank** (used only for scoring). Pilot totals: 175 detecting
hypotheses, 88 search, 92 held-out.

## Result: mean held-out detection

| Budget | truncation | random | greedy | family_greedy |
| --- | --- | --- | --- | --- |
| 8 | 0.6487 | 0.7180 | **0.8166** | 0.7611 |
| 16 | 0.9073 | 0.8725 | 0.9058 | **0.9179** |
| 32 | **0.9693** | 0.9533 | 0.9533 | 0.9600 |
| 64 | 0.9833 | 0.9820 | 0.9833 | 0.9833 |
| full suite | 1.0000 | | | |

## Paired per-task analysis against chronological truncation

Task-level paired bootstrap, 20 000 resamples, 15 tasks. Not marginal-interval
overlap: the paired difference is analysed directly.

| Budget | Arm | Mean delta | 95% CI | Wins | Ties | Losses |
| --- | --- | --- | --- | --- | --- | --- |
| 8 | random | +0.0693 | [-0.0740, +0.2263] | 6 | 4 | 5 |
| 8 | **greedy** | **+0.1680** | **[+0.0197, +0.3298]** | 6 | 8 | 1 |
| 8 | family_greedy | +0.1124 | [-0.0576, +0.2904] | 5 | 8 | 2 |
| 16 | random | -0.0349 | [-0.1127, +0.0350] | 3 | 8 | 4 |
| 16 | greedy | -0.0016 | [-0.0642, +0.0638] | 2 | 10 | 3 |
| 16 | family_greedy | +0.0105 | [-0.0467, +0.0720] | 2 | 11 | 2 |
| 32 | random | -0.0160 | [-0.0477, +0.0065] | 1 | 10 | 4 |
| 32 | greedy | -0.0159 | [-0.0567, +0.0156] | 1 | 12 | 2 |
| 32 | family_greedy | -0.0093 | [-0.0500, +0.0222] | 1 | 13 | 1 |
| 64 | all arms | ~0.0000 | - | 0 | 15 | 0 |

**Only one comparison is significant: greedy at budget 8, +16.8 points with a
confidence interval excluding zero.** At 16, 32 and 64 cycles no selection
strategy beats chronological truncation; the point estimates at 32 are slightly
negative.

## What this means for the AMP thesis

**The compaction axis alone does not deliver a win at the headline 32-cycle
budget.** Smart selection helps only when the budget is tight enough that
scenario ordering matters, and by 32 cycles simple truncation has already
captured almost everything.

Redundancy is real but smaller than a raw cost average suggests:

| Budget | Held-out detection | Fraction of full-suite cycles |
| --- | --- | --- |
| 8 | 0.6487 | 14.7% |
| 16 | 0.9073 | 29.5% |
| 32 | 0.9693 | 59.0% |
| 64 | 0.9833 | 86.0% |

At 59% of the original cycles, truncation retains 96.9% of held-out detection.
Worth reporting, but it is not the order-of-magnitude compression that the mean
suite length (259 cycles) hints at; that mean is inflated by a single 3068-event
driver, so the per-task ratio is the honest figure.

**Consequence:** the secondary target in the brief, "retain the baseline's
detection with materially fewer cycles", is weak at the budgets of interest.
Whatever advantage ACTIVE-TB-AMP can claim will have to come from
**amplification**, that is, adding tests the original suite never contained, not
from pruning what is already there. Step D's question was whether compression
offers genuine efficiency headroom, and on this evidence the answer is: only
below about 16 cycles.

## Threats to validity, stated plainly

1. **Hypotheses are checker mutations, not real RTL faults.** The held-out bank
   is a stratified split of mutations of the *same* checker, so search and
   held-out banks are correlated by construction. These numbers measure
   discrimination among behaviours near the checker's own model, and they are
   not the brief's `H(B)`, which requires golden-gated hidden RTL faults.
2. **No golden gating.** `e_t(B)` is not applied here: nothing in this
   experiment runs RTL, so a suite that would reject the golden design is not
   penalised. Every arm here preserves the frozen checker and a prefix-closed
   subset of its own stimulus, so Eval1 behaviour should be unchanged, but that
   is an argument, not a measurement.
3. **One fairness fix was needed mid-experiment.** The first greedy
   implementation stopped as soon as the search bank stopped improving, leaving
   most of the budget unspent, which made it an artificially weak baseline
   (0.8695 plateau at cost 9.2 regardless of budget). It now spends its budget.
   The table above is from the corrected version; the first run's numbers are
   superseded and should not be quoted.
4. **Independence is conservative, not exhaustive.** Scenarios whose full-suffix
   check is unaffordable are treated as dependent, so some legal compaction may
   be missed. That biases against the compaction arms, not for them.
5. **15 tasks.** Paired bootstrap on 15 tasks is a screening-grade instrument.

## Artefacts

| Path | Contents |
| --- | --- |
| `amp/frontend_adapter.py` | driver parser, frozen-checker executor, expectation recovery |
| `amp/vexpr.py`, `amp/vexpr_test.py` | RHS evaluator, 41 passing assertions |
| `amp/search_hypotheses.py` | AST mutation bank with family labels |
| `amp/compaction.py` | dependency analysis, detection matrix, four selection arms |
| `amp/compaction_results.csv` | 540 rows: task x arm x budget x seed |
| `amp/adapter_support_pilot.csv` | per-task support and gate outcome |

## Next decision

The brief's step E is state-directed and formal amplification through the same
adapter. This result argues for going there directly rather than investing
further in selection: pruning is close to exhausted above 16 cycles, and the
remaining headroom identified in `METRIC_RECONCILIATION.md` (45.8% of sequential
runs pass Eval1 yet miss a mutant verdict) is by definition about faults the
existing stimulus never exposes, which no subset of that stimulus can reach.
