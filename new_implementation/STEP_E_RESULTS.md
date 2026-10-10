# Step E Results: Checker-State-Directed Sequential Amplification

> ## FROZEN NEGATIVE RESULT
>
> This branch is closed. Its state score, fault weight, state abstraction and
> candidate operators are not to be tuned, and BMC is not to be added to it.
>
> Successor work is a **separate research track with a different information
> setting**: `ACTIVE_TB_FWD_DESIGN.md`, reference-assisted, where trusted Golden
> RTL is available during synthesis. That track is not a continuation or rescue
> of Step E and its results must never be pooled with the spec-only
> CorrectBench comparison.

Sealed evaluation run once under the frozen protocol. Reported exactly as
produced.

| | |
| --- | --- |
| Suite manifest | `99d6b241afb147ee6b18801314eec7857a7ec34b2ef0e6a4929380c6a7660daa` |
| Suites | 468, all hashes verified by the evaluator before Golden was loaded |
| Kernel | `tishaferdous/active-tb-step-e-sealed` v1, COMPLETE, CPU only |
| Hidden bank | Hidden Bank A, 15 tasks x 10 RTL mutants, 4232 eligible instances |
| Search code in evaluation dataset | none |

## VERDICT: **FAIL**

The pre-registered PASS criteria are not met. The state-directed mechanism is
worse than both baselines it was meant to beat, and it materially degrades
Golden acceptance.

---

## Golden acceptance

| Arm | B8 | B16 | B32 | B64 |
| --- | --- | --- | --- | --- |
| ORIGINAL (15 tasks) | 0.533 | 0.533 | 0.533 | 0.533 |
| TRUNCATION (15) | 0.533 | 0.533 | 0.533 | 0.533 |
| RANDOM (15) | 0.489 | 0.467 | 0.444 | 0.444 |
| GREEDY_VISIBLE (14) | 0.571 | 0.571 | 0.571 | 0.571 |
| **STATE_ONLY (14)** | **0.286** | **0.286** | **0.286** | **0.286** |
| **STATE_PLUS_FAULT (14)** | **0.286** | **0.286** | **0.286** | **0.286** |

**The state-directed arms reject the Golden design on 71% of tasks.** Against
TRUNCATION's 0.533 on the same budget this is a severe Eval1 regression, and it
alone fails pre-registered criterion 3.

Note the arm counts differ: GREEDY_VISIBLE, STATE_ONLY and STATE_PLUS_FAULT
cover 14 tasks (`mt2015_muxdff` has no state model), so their rates are not
directly comparable to the 15-task rows without that caveat.

## H_A(B): Golden-gated hidden RTL fault detection

| Arm | B8 | B16 | B32 | B64 |
| --- | --- | --- | --- | --- |
| TRUNCATION | 0.2356 | 0.2919 | **0.3385** | 0.3452 |
| RANDOM | 0.2341 | 0.2477 | 0.2499 | 0.2790 |
| STATE_ONLY | 0.1317 | 0.1532 | 0.1532 | 0.1532 |
| STATE_PLUS_FAULT | 0.1317 | 0.1532 | 0.1532 | 0.1532 |
| GREEDY_VISIBLE | 0.0365 | 0.0365 | 0.0365 | 0.0365 |
| *ORIGINAL (reference, ~259 cycles)* | *0.3719* | *0.3719* | *0.3719* | *0.3719* |

At every budget the ordering is TRUNCATION > RANDOM > STATE arms >
GREEDY_VISIBLE. The proposed method is **third of five**.

## Primary paired comparisons at B = 32

Task-level units, RANDOM seeds averaged before pairing, `mt2015_muxdff`
excluded, paired bootstrap 20 000 resamples.

| Comparison | Mean | Median | 95% CI | W/T/L |
| --- | --- | --- | --- | --- |
| STATE_PLUS_FAULT vs RANDOM | **-0.1146** | 0.0000 | [-0.2476, +0.0069] | 1/8/5 |
| STATE_PLUS_FAULT vs GREEDY_VISIBLE | +0.1167 | 0.0000 | [-0.0071, +0.2762] | 4/8/2 |
| STATE_ONLY vs RANDOM | **-0.1146** | 0.0000 | [-0.2476, +0.0069] | 1/8/5 |
| STATE_PLUS_FAULT vs STATE_ONLY | **0.0000** | 0.0000 | [+0.0000, +0.0000] | 0/14/0 |
| STATE_PLUS_FAULT vs TRUNCATION | **-0.2095** | 0.0000 | [-0.3738, **-0.0714**] | 0/8/6 |

The only interval excluding zero is **STATE_PLUS_FAULT losing to TRUNCATION**.

**STATE_PLUS_FAULT and STATE_ONLY are identical on all 14 tasks.** The
family-balanced visible-fault term never changed a single selection decision:
with b2 = 1.0 per new state against b1 = 1.0 per new fault family, the state
term dominated the argmax at every step. Visible-fault guidance contributed
exactly nothing.

RANDOM across-seed variability, reported separately as frozen: mean per-task SD
0.065 / 0.071 / 0.068 / 0.057 at B = 8/16/32/64, max 0.29. The
STATE_PLUS_FAULT deficit against RANDOM (-0.1146) is larger than the mean seed
SD, so it is not an artefact of which random seeds were drawn.

## Per-task H_A(32)

| Task | Grp | TRUNC | RANDOM | GREEDY_V | STATE_ONLY | STATE+F | ORIGINAL |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2014_q4a | A | 0.900 | 0.900 | 0.000 | 0.900 | 0.900 | 0.900 |
| circuit10 | A | 0.000 | 0.000 | 0.100 | 0.000 | 0.000 | 0.000 |
| circuit8 | A | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| circuit9 | A | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| count15 | A | 0.000 | 0.370 | 0.000 | 0.000 | 0.000 | 0.000 |
| countslow | A | 0.900 | 0.200 | 0.100 | 0.000 | 0.000 | 0.900 |
| dff8ar | **B** | 0.778 | 0.778 | 0.111 | 0.444 | 0.444 | 0.778 |
| dualedge | A | 0.200 | 0.200 | 0.100 | 0.200 | 0.200 | 0.200 |
| ece241_2013_q4 | **B** | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| ece241_2014_q5b | A | 0.700 | 0.700 | 0.000 | 0.000 | 0.000 | 0.700 |
| lemmings3 | A | 0.400 | 0.000 | 0.000 | 0.000 | 0.000 | 0.500 |
| m2014_q4k | A | 0.700 | 0.267 | 0.100 | 0.600 | 0.600 | 0.700 |
| mt2015_muxdff | UNCL | 0.000 | 0.000 | - | - | - | 0.000 |
| review2015_count1k | A | 0.500 | 0.333 | 0.000 | 0.000 | 0.000 | 0.900 |
| review2015_shiftcount | A | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |

Four tasks detect nothing under any arm including ORIGINAL (`circuit8`,
`circuit9`, `ece241_2013_q4`, `review2015_shiftcount`); their checkers already
fail Eval1 or their mutants are all accepted, so no backend can help them.

## Group analysis, descriptive only

| Group | n | STATE_PLUS_FAULT - RANDOM at B=32 |
| --- | --- | --- |
| A, state-saturated | 12 | -0.1059 |
| B, state-rich | 2 | -0.1667 |

The pre-registered hypothesis was that amplification helps where the original
stimulus leaves state space unexplored. **It is not supported: the deficit is
larger in Group B**, the two tasks with genuine new-state headroom. With n = 2
this is descriptive, but it points the opposite way from the hypothesis.

## Efficiency framing against ORIGINAL

Explicitly not an equal-budget comparison. ORIGINAL costs ~259 cycles.

- TRUNCATION at 32 cycles retains **91.9%** of ORIGINAL's detection.
- STATE_PLUS_FAULT at 32 cycles retains **42.9%**.

The useful efficiency result belongs to plain chronological truncation, not to
the proposed method.

## Verdict against the pre-registered criteria

| # | Criterion | Result |
| --- | --- | --- |
| 1 | positive mean paired delta over RANDOM | **FAIL** (-0.1146) |
| 2 | positive mean paired delta over GREEDY_VISIBLE | pass (+0.1167, CI spans zero) |
| 3 | Golden acceptance not materially degraded | **FAIL** (0.286 vs 0.533) |
| 4 | gain not driven by a single task | n/a, there is no gain |
| 5 | STATE_ONLY at least directionally better than RANDOM | **FAIL** (-0.1146) |
| 6 | amplification reaches genuinely new states | **FAIL** (2 of 14 tasks, recorded pre-hidden) |
| 7 | hidden kills attributable to new trajectories | **FAIL** (state arms kill strictly fewer everywhere) |

Five of seven fail. The pre-registered FAIL conditions are met on several counts
independently: STATE_PLUS_FAULT is not within noise of the baselines, it is
clearly below them; Golden acceptance materially regresses; and new state
coverage did not translate into hidden kills.

## Why it failed, as far as the evidence supports

1. **Reaching new checker states is not the same as exercising the DUT
   correctly.** The directed search optimised a coverage signal computed
   entirely inside the frozen checker's own state abstraction. Sequences that
   maximise that signal drove the DUT into conditions where the checker rejects
   even correct RTL, which is why Golden acceptance collapsed to 0.286. The
   objective and the goal came apart.

2. **The original stimulus was already near-saturated.** Recorded before any
   hidden contact: only 2 of 14 tasks had more than 2 new reachable states
   within budget. On the other 12 there was nothing for state-direction to find,
   so it could only redistribute cycles away from stimulus that was already
   working.

3. **The fault term was inert.** STATE_PLUS_FAULT never differed from
   STATE_ONLY on any task. With the frozen weights the state term always
   dominated the argmax, so the family-balanced fault contribution was never
   decisive. Whether a different weighting would help is untested and, under the
   pre-registration, not something to explore by tuning after seeing this.

4. **Random legal stimulus is a strong baseline here.** RANDOM beat both
   directed arms, and simple truncation of the original beat everything except
   the full suite.

## Consequences, per the frozen protocol

BMC is **not** added to rescue this. The pre-registration states plainly that
BMC becomes the next ablation only if Step E shows useful signal, and it does
not.

What this experiment does establish, negatively but cleanly: on this benchmark,
at these budgets, checker-state-directed amplification does **not** generate
novel trajectories that improve Golden-gated detection of independent RTL
faults over random or greedy visible-fault baselines. The answer to the question
Step E was built to settle is no.

The one durable positive from the whole AMP line remains the frozen compaction
result: greedy selection gives a real gain at B = 8, and chronological
truncation retains 91.9% of full-suite detection at roughly 12% of its cycles.

## Artefacts

| Path | Contents |
| --- | --- |
| `STEP_E_PREREGISTRATION.md` | frozen configuration, weights, seeds, criteria |
| `STEP_E_ANALYSIS_FREEZE.md` | grouping, seed aggregation, ORIGINAL handling, frozen before inspection |
| `amp/suite_manifest.json`, `.sha256` | 468 suites with per-suite hashes |
| `amp/suites/` | frozen executable stimulus |
| `amp/sealed_evaluator.py` | sealed evaluator, imports no search code |
| `kaggle_runs/step_e_sealed_v1/step_e_results/sealed_records.csv` | raw simulation records |
| `amp/step_e_metrics.csv` | per-task metric values with group labels |
| `analysis/step_e_scoring.py` | scoring under the frozen definitions |
