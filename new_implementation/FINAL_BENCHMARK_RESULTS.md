# ACTIVE-TB-D Final Benchmark

Pipeline finalised, implemented, and benchmarked once against CorrectBench and
equal-budget baselines on Golden-gated hidden RTL fault detection.

| | |
| --- | --- |
| Distillation manifest | `918a6234628fea50d9a44c5dd5cce95c0e0e845cc60e923e5288ce717e28328d` |
| Suites | 120, all hashes verified before Golden was loaded |
| Kernel | `tishaferdous/active-tb-distill-sealed` v1, COMPLETE, CPU |
| Baselines | reused from the Step-E sealed run, manifest `99d6b241...` |
| Metric | `H(B) = mean[GoldenPass x killed/eligible]`, Hidden Bank A |

## VERDICT: the method does not beat chronological truncation

ACTIVE-TB-D is statistically indistinguishable from truncation at every budget,
and slightly behind it at the headline B = 32. The dependency-preserving
machinery does not earn its complexity.

---

## H(B), Golden-gated hidden RTL fault detection

| Arm | B8 | B16 | **B32** | B64 |
| --- | --- | --- | --- | --- |
| *ORIGINAL (CorrectBench, 259 cyc)* | *0.3719* | *0.3719* | *0.3719* | *0.3719* |
| TRUNCATION | 0.2356 | 0.2919 | **0.3385** | 0.3452 |
| DISTILL_GREEDY | 0.2252 | 0.3119 | 0.3252 | 0.3385 |
| DISTILL_FAMILY | 0.2252 | 0.2985 | 0.2985 | 0.3385 |
| RANDOM | 0.2341 | 0.2477 | 0.2499 | 0.2790 |

Mean deployed cycles:

| Arm | B8 | B16 | B32 | B64 |
| --- | --- | --- | --- | --- |
| ORIGINAL | 259.3 | 259.3 | 259.3 | 259.3 |
| TRUNCATION | 8.0 | 16.0 | 32.0 | 51.4 |
| DISTILL_GREEDY | 6.6 | 13.6 | 27.4 | 45.3 |
| DISTILL_FAMILY | 6.4 | 13.6 | 26.7 | 45.3 |

## Paired comparison, DISTILL_GREEDY vs TRUNCATION

| B | mean dH | 95% CI | W/T/L | cycles |
| --- | --- | --- | --- | --- |
| 8 | -0.0104 | [-0.0800, +0.0689] | 1/12/2 | 6.6 vs 8.0 |
| 16 | +0.0200 | [-0.1000, +0.1733] | 2/10/3 | 13.6 vs 16.0 |
| **32** | **-0.0133** | [-0.0333, +0.0000] | **0/13/2** | 27.4 vs 32.0 |
| 64 | -0.0067 | [-0.0200, +0.0000] | 0/14/1 | 45.3 vs 51.4 |

**At the headline budget the method wins on zero tasks.** No interval excludes
zero at any budget.

At B = 16 the *mean* is higher at lower cost, which looks like Pareto dominance,
but the paired data shows 2 wins against 3 losses. That is a mean artefact
driven by a few tasks, not a robust improvement, and it is not claimed as one.

Family balancing actively hurts: DISTILL_FAMILY vs DISTILL_GREEDY is -0.0267 at
B = 32, 0 wins / 13 ties / 2 losses.

## Efficiency against CorrectBench (not equal-budget)

| Arm | Retains of CorrectBench detection | At fraction of its cycles |
| --- | --- | --- |
| TRUNCATION | **91.9%** | 55.7% |
| DISTILL_GREEDY | 87.7% | 50.9% |
| DISTILL_FAMILY | 81.0% | 49.7% |
| RANDOM | 62.2% | 55.7% |

The genuine efficiency finding belongs to **truncation**, not to the proposed
method. CorrectBench's sequential testbenches are roughly half redundant, and
the trivial baseline exploits that better than the engineered one.

## Per-task H(32)

| Task | ORIGINAL | TRUNCATION | RANDOM | DISTILL_G | DISTILL_F |
| --- | --- | --- | --- | --- | --- |
| 2014_q4a | 0.900 | 0.900 | 0.900 | 0.900 | 0.900 |
| circuit8 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| circuit9 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| circuit10 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| count15 | 0.000 | 0.000 | 0.370 | 0.000 | 0.000 |
| countslow | 0.900 | 0.900 | 0.200 | 0.900 | 0.600 |
| dff8ar | 0.778 | 0.778 | 0.778 | 0.778 | 0.778 |
| dualedge | 0.200 | 0.200 | 0.200 | 0.200 | 0.200 |
| ece241_2013_q4 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| ece241_2014_q5b | 0.700 | 0.700 | 0.700 | 0.700 | 0.700 |
| lemmings3 | 0.500 | 0.400 | 0.000 | 0.300 | 0.200 |
| m2014_q4k | 0.700 | 0.700 | 0.267 | 0.600 | 0.600 |
| mt2015_muxdff | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| review2015_count1k | 0.900 | 0.500 | 0.333 | 0.500 | 0.500 |
| review2015_shiftcount | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |

Six of fifteen tasks score zero for every arm including CorrectBench's own
suite: its testbench rejects the Golden design there, so no checker-preserving
backend can help. Eight of the remaining nine are ties across all arms. The
whole comparison rests on `lemmings3`, `m2014_q4k`, `countslow` and
`review2015_count1k`, which is why nothing reaches significance.

## Threat to validity that limits the CorrectBench comparison

The `ORIGINAL` arm is **not** the literal CorrectBench testbench. It is the
original stimulus re-emitted through our driver emitter. Its measured Golden
acceptance on this sequential pilot is 0.533, whereas CorrectBench's published
sequential Eval1 is 0.7173. Some of that gap is the pilot being a hard
15-task subset, but re-emission loss cannot be excluded.

Consequence: **absolute comparisons against CorrectBench's published numbers are
not trustworthy from this run.** The equal-budget paired comparisons between our
arms remain valid, because every arm passes through the same emitter and is
affected identically. That is the part of this result that should be believed.

## What was actually established

Across the whole programme, measured and reproducible:

1. CorrectBench's published sequential figures are Eval1 0.7173, Eval2 0.5493,
   reproduced exactly from its own analyser (`METRIC_RECONCILIATION.md`).
2. In 45.8% of sequential runs the checker passes Eval1 but the stimulus misses
   at least one mutant verdict, so stimulus-side headroom exists.
3. That headroom is **not** reachable by: oracle-population consensus (IVRP,
   inconclusive), checker-state-directed amplification (Step E, FAIL), or
   dependency-preserving distillation (this run, no improvement over truncation).
4. The suites are roughly half redundant: ~92% of hidden-fault detection is
   retained at ~56% of deployed cycles by chronological truncation.

Finding 4 is the only positive result, and it is a property of the benchmark
rather than a contribution of any method built here.

## Honest position on novelty and SOTA

There is no defensible novelty claim from this pipeline. Dependency-preserving
distillation was implemented as specified, benchmarked once, and did not beat a
one-line baseline. Reporting it as a contribution would not survive review.

The remaining honest options are to publish finding 4 as a benchmark-analysis
result about redundancy and Eval1 fragility in LLM-generated sequential
testbenches, or to change the information setting (reference-assisted, per
`ACTIVE_TB_FWD_DESIGN.md`) and accept that it is no longer a spec-only
comparison with CorrectBench.
