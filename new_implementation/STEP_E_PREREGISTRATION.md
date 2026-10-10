# Step E Pre-Registration: Checker-State-Directed Sequential Amplification

Status: **frozen before any Golden or hidden-fault contact.**

Question this experiment answers, and nothing else:

> At an equal 32-cycle deployment budget, does checker-state-directed sequential
> amplification generate novel trajectories that improve Golden-gated detection
> of independent RTL faults over random and greedy visible-fault baselines?

No BMC in this run.

---

## 1. Frozen configuration

| Item | Value |
| --- | --- |
| Pilot | the 15 sequential tasks in `amp/pilot_tasks.json` (hash-selected, frozen) |
| STEP_MODEL tasks | 14 |
| Unsupported for state-directed search | `mt2015_muxdff` (direct-drive disagrees with `check_dut` at 35/62 positions) |
| State canonicalisation | deterministic JSON of `GoldenDUT.__dict__`, excluding private, callable and unserialisable members |
| Consistency gate | direct-drive expectations must equal `check_dut`-recovered expectations at every comparable position |
| Determinism gate | same canonical state + same input must give same successor and same expected output, over the original trace plus 3 random legal sequences (seed 17) |
| Input enumeration | exhaustive when the legal input space is <= 64 vectors; otherwise structured candidates (all-zero, all-one, one-hot, one-cold, previous, previous +/-1 per field, single-bit pulse) plus 8 fixed-seed random vectors |
| LONG_HORIZON_CONTINUATION | hold the current control vector for +1, +2, +4, +8, +16 cycles, budget permitting |
| Exploration cap | 200 retained states per task |
| Visible hypothesis bank | single-site AST mutations of `GoldenDUT` in 5 families: comparison, arithmetic, boundary, condition, hold. Max 6 per family, 40 total |
| Scoring weights | b1 = 1.0 (fault families), b2 = 1.0 (new states), b3 = 0.5 (new transitions), b4 = 0.5 (new boundary events) |
| Denominator | full replay cost: init + concrete prefix + suffix + observation cycles |
| Random seeds | exploration 17; RANDOM arm 1000+s for s in 0..2 (3 seeds) |
| Budgets | 8, 16, 32, 64 deployed cycles |
| Headline budget | **32** |

Weights, seeds, caps and gates are fixed now and may not change after hidden
results exist.

## 2. The six arms

| Arm | Definition |
| --- | --- |
| `ORIGINAL` | the untouched CorrectBench stimulus, reported at its true cost |
| `TRUNCATION` | chronological prefix of the original at exactly the budget |
| `RANDOM` | newly generated legal sequential trajectories, same deployed budget |
| `GREEDY_VISIBLE` | visible checker-fault discrimination per full replay cost, **no state term** (b2 = b3 = b4 = 0) |
| `STATE_ONLY` | state / transition / boundary directed, **no fault guidance** (b1 = 0) |
| `STATE_PLUS_FAULT` | state exploration plus family-balanced visible-fault discrimination. The proposed method. |

A suite is a single continuous input sequence built by greedy marginal-gain
append, so dependency is preserved by construction: expectations are always
recomputed over the whole emitted sequence, never spliced.

## 3. Unsupported-task handling

**Analysis A, supported mechanism comparison.** The 14 STEP_MODEL tasks, arms
RANDOM / GREEDY_VISIBLE / STATE_ONLY / STATE_PLUS_FAULT. This is the clean
algorithmic comparison.

**Analysis B, deployable 15-task system.** `mt2015_muxdff` uses a frozen
fallback declared now: `ORIGINAL` if it fits the budget, otherwise chronological
`TRUNCATION`. The fallback is never chosen using hidden performance. Fallback
rate is reported.

## 4. Freeze order

Suites for every task x arm x budget x seed are emitted as executable Verilog,
serialised deterministically, and SHA-256 hashed into a manifest **before** the
sealed evaluator may load Golden RTL or hidden faults. No suite is regenerated
after evaluation starts.

## 5. Search cost is recorded, not hidden

Per suite: deployed cycles, checker transitions simulated during search,
candidate sequences evaluated, states explored, transitions explored, visible
mutations evaluated, search CPU seconds, peak retained states, and whether the
200-state cap was hit.

## 6. Hidden Bank A

`HDLBits_data_mutants.jsonl`, labelled **Hidden Bank A - existing benchmark RTL
mutant bank**. Not described as an untouched final generalisation bank: earlier
ACTIVE-TB work has used this resource. Step-E search does not read it; it is
evaluation-only. Its RTL-level mutation operators are independent of the
checker-AST families used for search, which is the separation that matters here.

## 7. Primary metric

For budget B,

```
H_A(B) = mean over tasks [ GoldenPass(task, arm, B)
                           * hidden_killed(task, arm, B)
                           / eligible_hidden(task) ]
```

A task whose suite rejects Golden contributes zero. Raw mutant rejection is
never reported as the primary number.

Also reported: Golden acceptance / Eval1; hidden kill rate conditional on Golden
pass; Golden-gated hidden kills per 100 deployed cycles; publication-compatible
Eval2 where computable; strict verdict agreement; compile and unsupported rates.

## 8. Primary comparisons at B = 32

Paired per-task differences, with mean, median, win/tie/loss, and paired
bootstrap 95% CI:

- `STATE_PLUS_FAULT` vs `RANDOM`
- `STATE_PLUS_FAULT` vs `GREEDY_VISIBLE`
- `STATE_ONLY` vs `RANDOM` - does state exploration itself contribute?
- `STATE_PLUS_FAULT` vs `STATE_ONLY` - does fault guidance add beyond coverage?

## 9. Screening decision, fixed now

**PASS / promising** requires all of, at B = 32:

1. positive mean paired delta of STATE_PLUS_FAULT over RANDOM;
2. positive mean paired delta of STATE_PLUS_FAULT over GREEDY_VISIBLE;
3. Golden acceptance not materially degraded;
4. the gain is not caused by a single task;
5. STATE_ONLY at least directionally better than RANDOM;
6. instrumentation shows amplification reaching genuinely new checker states,
   transitions or boundary behaviour;
7. at least some hidden RTL kills attributable to newly generated trajectories
   absent from the original suite.

Statistical significance at 15 tasks is desirable but not required, provided the
mechanism signal is clear and broadly distributed.

**FAIL** if any of: STATE_PLUS_FAULT within noise of RANDOM/GREEDY_VISIBLE at
B = 32; advantage disappears under exact budget accounting; gains come from one
outlier task; new state coverage does not translate into hidden kills; Golden
acceptance materially regresses.

BMC will not be added to rescue a failed state-directed result.

## 10. Secondary analysis, groups defined before hidden contact

Tasks are split using **pre-hidden exploration statistics only**:

- **Group A, state-saturated**: new states reachable within budget <= 2.
- **Group B, state-rich**: new states reachable within budget > 2.

From the local instrumentation already run, `count15` and `countslow` are
saturated, `dff8ar` is state-rich, `lemmings3` is borderline. The final
assignment is computed from the frozen exploration output, never from hidden
results.

Hypothesis under test: ACTIVE amplification helps primarily where the original
stimulus leaves meaningful sequential state space unexplored.

## 11. Not in this run

No BMC. No LLM calls. No new oracle population. No compaction retuning. If Step
E passes, BMC becomes the next ablation, after its witness-replay pipeline is
repaired and unit-tested separately.
