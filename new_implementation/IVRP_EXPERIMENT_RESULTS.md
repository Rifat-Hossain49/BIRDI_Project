# IVRP Stage 1: Results

> ## Recorded outcome
>
> **Experiment FAIL / hypothesis unresolved due to validator compilation yield.**
>
> H0 was **not** proved. The 0.48 and 0.44 compile rates mean this experiment
> cannot establish that independent LLM populations contain no semantic signal.
>
> **Architectural decision (taken separately from the hypothesis):** the
> generated-RTL consensus and correction branch of ACTIVE-TB is **terminated**,
> for these reasons:
>
> - same-pool arbitration was already net negative;
> - IVRP Rule E achieved only 0.50 correction precision;
> - conservative Eval1 delta was -0.0364;
> - two previously passing testbenches were broken;
> - no correlated failure was recovered under the frozen rule;
> - four suggestive inconclusive cases do not justify another
>   model, prompt, or population search;
> - even an optimistic repair path remains far from the CorrectBench Eval1 gap.
>
> IVRP is **not** re-run with different models. All artefacts below are
> preserved as a negative/inconclusive experiment and are not to be deleted or
> rewritten. Successor work is `SEQUENTIAL_ACTIVE_TB_DESIGN.md`.

Run once, exactly as frozen in `IVRP_EXPERIMENT_PREREGISTRATION.md`.
Kernel `tishaferdous/active-tb-s-ivrp-stage1` version 1, COMPLETE.

Decision-file integrity, verified before golden was read:

```
sha256 recorded on Kaggle : bfd6623225b335d76ec77b088112749072af66ab2ad4eb1923f77c429313e597
sha256 recomputed locally : bfd6623225b335d76ec77b088112749072af66ab2ad4eb1923f77c429313e597
                            MATCH
```

Ordering held: population B was generated from specification and interface only,
simulated, evidence built, frozen rules applied, decisions written and hashed,
and only then was golden read. `ivrp_manifest.json` records
`golden_artifacts_seen: false`.

**Stage 2 was not launched.** It is gated on Stage 1 passing, and Stage 1 did
not pass.

---

## Headline: the instrument failed a pre-registered precondition

Amendment A3 required that compile and elaboration yield be reported separately
by family, and stated that a family which mostly fails to compile makes the
result *partly inconclusive about semantic independence rather than evidence for
H0*. That is what happened, to both families.

| Family | Model | Candidates | Compiled | Interface OK | Compile rate |
| --- | --- | --- | --- | --- | --- |
| mistral | mistral-7b-instruct-v0.3 | 100 | 48 | 73 | **0.48** |
| phi35 | Phi-3.5-mini-instruct | 100 | 44 | 83 | **0.44** |

Population A, for comparison, compiled at 0.846 (Qwen2.5-Coder-7B) and 0.660
(Llama-3.1-8B) on the full task set. Both IVRP families are far weaker.

The consequence is structural. Rule E requires at least 6 concrete values out of
T = 10. Across the 2248 check points:

| Concrete IVRP values at a check point | Points | Share |
| --- | --- | --- |
| 0 | 82 | 3.6% |
| 1 | 254 | 11.3% |
| 2 | 258 | 11.5% |
| 3 | 480 | 21.4% |
| 4 | 609 | 27.1% |
| 5 | 169 | 7.5% |
| **6 or more (Rule E can fire)** | **396** | **17.6%** |

**Rule E was structurally blocked on 82.4% of check points by compile failure,
not by agreement with population A.** The experiment therefore did not put H1
and H0 to a fair test.

---

## Pre-registered metrics, reported as specified

Assertion level. The starred rule is PRIMARY and is the registered basis for the
decision.

| N | Rule | Attempted | TP | FP | Precision | 95% CI | Recall | FCR | Broken TBs | Abstain |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 3 | D | 26 | 7 | 19 | 0.269 | [0.137, 0.461] | 0.091 | 0.0185 | 2 | 0.000 |
| 3 | **E \*** | 12 | 7 | 5 | **0.583** | [0.320, 0.807] | 0.091 | 0.0049 | 2 | 0.000 |
| 3 | F | 3 | 0 | 3 | 0.000 | [0.000, 0.562] | 0.000 | 0.0029 | 2 | 0.000 |
| 3 | G | 12 | 7 | 5 | 0.583 | [0.320, 0.807] | 0.091 | 0.0049 | 2 | 0.935 |
| 5 | D | 36 | 11 | 25 | 0.306 | [0.180, 0.469] | 0.182 | 0.0244 | 5 | 0.000 |
| 5 | **E \*** | 14 | 7 | 7 | **0.500** | [0.268, 0.732] | 0.091 | 0.0068 | 2 | 0.000 |
| 5 | F | 4 | 0 | 4 | 0.000 | [0.000, 0.490] | 0.000 | 0.0039 | 2 | 0.000 |
| 5 | G | 14 | 7 | 7 | 0.500 | [0.268, 0.732] | 0.091 | 0.0068 | 2 | 0.917 |

Baselines for reference: same-population recall 0.124, false-correction 0.0125.

Testbench level, PRIMARY rule E at N = 5. Conservative counts only
single-failure testbenches as recoverable, because the diagnostic recorded just
the first failing check.

| Rule | Eval1 now | Conservative | Delta | Optimistic | Recovered (conservative) | Broken | Net |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **E** | 0.6000 | **0.5636** | **-0.0364** | 0.6000 | 0 | 2 | **-2** |
| D | 0.6000 | 0.5091 | -0.0909 | 0.5818 | 0 | 5 | -5 |

Circuit-class split, rule E at N = 5: CMB 3 false corrections, 2 unscoreable, no
true corrections. SEQ 7 true corrections, 4 false corrections, 14 unscoreable.
Every correct repair was on a sequential task.

### Stage-1 advancement criteria (A8), PRIMARY rule E, N = 5

| # | Criterion | Value | Verdict |
| --- | --- | --- | --- |
| 1 | Precision >= 0.90 | 0.500 | **FAIL** |
| 2 | Recall > 0.124 | 0.091 | **FAIL** |
| 3 | False-correction rate < 0.0125 | 0.0068 | PASS |
| 4 | Conservative Eval1 delta positive | -0.0364 | **FAIL** |
| 5 | Negligible regression on passing TBs | 2 broken | **FAIL** |
| 6 | Some recovery in the correlated subset | 0 of 11 | **FAIL** |

Five of six fail. On the letter of A8, H0 becomes the practical architectural
decision.

---

## The central independence test, case by case

The 11 correlated cases, where population A confidently agrees with the wrong
expectation. This is the subset the whole experiment exists to probe.

| Task | Method | Concrete | TB expected | IVRP vote | Golden | Category |
| --- | --- | --- | --- | --- | --- | --- |
| countbcd | diverse_ensemble | 4 | 011 | **000** | **000** | inconclusive, evidence below floor |
| countbcd | single_oracle | 4 | 011 | **000** | **000** | inconclusive, evidence below floor |
| fsm1 | diverse_ensemble | 5 | 0 | **1** | **1** | inconclusive, evidence below floor |
| fsm1 | single_oracle | 5 | 0 | **1** | **1** | inconclusive, evidence below floor |
| gshare | single_oracle | 0 | 0 | - | x | inconclusive, no evidence |
| gshare | typed_formal_active | 0 | 0 | - | x | inconclusive, no evidence |
| kmap3 | single_oracle | 1 | 0 | 0 | 1 | inconclusive, evidence below floor |
| kmap3 | typed_formal_active | 1 | 0 | 0 | 1 | inconclusive, evidence below floor |
| rule90 | diverse_ensemble | 4 | 0...0 | (differs) | 1000...01 | inconclusive, evidence below floor |
| m2014_q6b | diverse_ensemble | 6 | 0 | 0 | x | **IVRP repeats the same wrong value** |
| m2014_q6b | single_oracle | 6 | 0 | 0 | x | **IVRP repeats the same wrong value** |

Summary: **9 inconclusive through insufficient compiling evidence, 2 where IVRP
repeated population A's wrong value.** Rule E recovered 0 of 11, but it was
permitted to fire on only 2 of them.

The finding that matters most for interpretation: **in 4 of the 9 inconclusive
cases the IVRP plurality pointed at the correct golden value and Rule E refused
to fire purely because 4 or 5 candidates compiled where 6 were required**
(countbcd twice, fsm1 twice). That is not evidence for H0. It is evidence that
independent signal may exist and that this instrument could not read it.

Where both populations did vote, they agreed at 1277 points and disagreed at
680, so population B is not merely a copy of population A.

The 2 genuine repeats are both `m2014_q6b`, where golden is X - a class A
indeterminate point, the failure mode the already-implemented X/Z abstention fix
addresses and which was deliberately not exercised in this read-only experiment.

---

## Terminal outcome

The pre-registration allows exactly three outcomes and forbids inventing a
fourth. Two of its provisions point in different directions here, and both were
written before the data existed:

- **A8** says that if the six criteria are not met, H0 is the practical
  architectural decision and the branch stops. Five of six failed.
- **A3** says that a family which mostly fails to compile makes the result
  *partly inconclusive about semantic independence rather than evidence for H0*.
  Both families compiled below 50%, and Rule E was blocked on 82.4% of points.

A3 is the more specific provision and it describes exactly what occurred. The
honest classification is therefore:

> **FAIL as an experiment, not a STRONG NEGATIVE about the hypothesis.**
> Rule E does not clear the Stage-1 gate, so Stage 2 is not authorised and was
> not run. But the gate was not failed by population B agreeing with population
> A's errors; it was failed by population B mostly not compiling. H0 is not
> established, and neither is H1.

Calling this a STRONG NEGATIVE would overclaim: 4 of 11 correlated cases had the
correct answer sitting in an evidence-starved plurality. Calling it PROMISING
BUT UNDERPOWERED would also be wrong: the primary rule produced a negative
conservative Eval1 delta and broke two passing testbenches.

Per A11, the response to a failure is explicitly **not** to change models and
rerun, raise N, or search prompts, and none of those has been done. What the
decision now requires is a judgement that belongs to you, not to me:

1. **Treat this as the terminal negative** for generated-RTL consensus as
   semantic ground truth, and pivot to Direction A (specification-derived
   executable semantics) or Direction B (narrow to sequential verification).
   Defensible: even the optimistic reading of this branch never approached the
   36-point Eval1 gap to CorrectBench.
2. **Re-run Stage 1 once with compile-capable models**, declared as a *separate
   exploratory experiment* under a new pre-registration, on the grounds that A3
   anticipated exactly this and the instrument, not the hypothesis, failed. This
   is a model-capability repair, not prompt or threshold tuning, and the same
   frozen rules and thresholds would apply unchanged.

I am not choosing between these unilaterally, because option 2 is close enough
to "change models and rerun" that it needs your explicit call rather than my
inference.

---

## Cost actually incurred

200 generation calls, 3.46 GPU-hours (mistral 1.49, phi35 1.97), one Kaggle
session, ~2.3 MB of results. Within the pre-registered estimate.
