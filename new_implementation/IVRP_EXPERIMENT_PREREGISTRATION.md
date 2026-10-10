# IVRP Experiment: Pre-Registration

Status: **APPROVED WITH AMENDMENTS. Frozen. Stage 1 (Option 1, 20 tasks) runs
exactly once against this document.** See APPROVED AMENDMENTS at the end, which
supersede any conflicting text above.

Written before any IVRP candidate exists. Every threshold below is fixed at
the time of writing and may not be changed after results are seen.

---

## 1. Hypotheses

**Primary (H1).** A fresh RTL population generated independently after the
testbench is frozen will disagree correctly with shared oracle-pool mistakes
often enough to improve Eval1, with very high correction precision and
negligible regression on already-correct testbenches.

**Null (H0).** Fresh RTL candidates largely reproduce the same semantic
misunderstandings as the original oracle population, and therefore provide
insufficient independent correction signal.

**Decision this experiment makes.** Whether ACTIVE-TB continues to use
generated-RTL consensus as its source of semantic truth, or abandons that
branch.

---

## 2. The 20 pilot task IDs

Exactly the subset already used for the SOTA pilot. Not reselected, not
filtered by favourability.

```
7458, count10, countbcd, dff8ar, edgecapture, fadd, fsm1, fsm_serial,
gates100, gshare, kmap3, lfsr5, m2014_q6b, mux256to1, mux2to1v, popcount3,
review2015_fsmseq, ringer, rule90, vector4
```

Circuit class: 10 combinational, 10 sequential.

| Class | Tasks |
| --- | --- |
| CMB | 7458, fadd, gates100, kmap3, m2014_q6b, mux256to1, mux2to1v, popcount3, ringer, vector4 |
| SEQ | count10, countbcd, dff8ar, edgecapture, fsm1, fsm_serial, gshare, lfsr5, review2015_fsmseq, rule90 |

### Evidence available inside this subset

Measured from the existing seed 17 frozen bundle and the eval1 diagnostic:

| Quantity | Count |
| --- | --- |
| Frozen testbenches (5 methods x 20 tasks, non-empty) | 86 |
| Total assertions | 2248 |
| Distinct (task, check-point) identities | 582 |
| Testbenches passing Eval1 (known-correct expectations) | 33 |
| Testbenches failing Eval1 (known-wrong expectations) | 22 |
| **Correlated failures: population A vote agrees with the wrong expectation** | **11** |

**Statistical power warning, stated before running.** The central independence
test of Section 13 has n = 11, spanning 7 distinct tasks (countbcd, fsm1,
gshare, kmap3, m2014_q6b, rule90, and one more by method). The pre-registered
precision gate of 0.90 cannot be resolved at this sample size: if the rule
attempts 10 corrections and gets 9 right, the point estimate is 0.90 but the
95% Wilson interval is roughly [0.60, 0.98]. A single case moves the estimate
by about 9 points.

This is a property of the instructed subset, not a reason to change it. Two
options are offered in Section 12; the 20-task version is the default and will
be run as instructed unless you choose otherwise.

---

## 3. Ordering and separation

Strictly enforced, and already satisfied by construction because population A,
the testbenches, and the golden comparison all exist on disk and are read-only
in this experiment:

```
Specification
  -> oracle population A            (already frozen, unchanged)
  -> TB generation                  (already frozen, unchanged)
  -> testbench frozen               (already frozen: SHA-256 recorded per TB)
  -> IVRP population B generated    (this experiment, nothing before it changes)
  -> arbitration decisions frozen   (written to disk before golden is read)
  -> golden used only for scoring
```

Population B contributes to none of: expected values, consensus, testbench
construction, candidate ranking, scenario generation. It cannot, because those
artefacts are already written and hash-pinned.

The only change to the frozen system is the already-implemented Class-A X/Z
abstention fix, which is **not exercised here**: this experiment reads existing
frozen testbenches and does not re-run synthesis.

---

## 4. IVRP generation prompt

### Population A prompt, for contrast (unchanged, from `generate_spec_oracles.py`)

System:
```
You are an independent RTL behavioral-oracle engineer.
Implement the supplied specification as synthesizable SystemVerilog.
Return exactly one module named top_module with exactly the supplied interface.
Do not output a testbench, reference_module, prose, markdown, or multiple alternatives.
Do not weaken, omit, or invent behavior. Use deterministic reset/state semantics from the specification.
```
User:
```
Specification:
{description}

Required interface:
{header}

Independent derivation instruction: {one of 3 fixed perspectives}
```

### Population B (IVRP) prompt, new

System:
```
You are a digital design engineer writing production RTL.
Write one synthesizable SystemVerilog module named top_module matching the given interface exactly.
Output only code. No explanation, no testbench, no alternatives.
```
User:
```
Implement this RTL specification correctly.

{description}

Interface:
{header}

Before writing, restate the required behavior to yourself as a table of
input conditions to output values, including the behavior at reset and on
the first active clock edge. Then write the module.
```

The prompt asks only for a correct implementation. It never mentions a
testbench, an expected value, a disputed point, a failing assertion, or any
oracle output. No candidate sees golden RTL, the official testbench, the
ACTIVE-TB testbench, its expected values, existing oracle RTL, existing oracle
votes, or which assertion failed.

---

## 5. How population B is independent of population A

Recorded explicitly, because "different name" is not independence.

| Dimension | Population A | Population B (IVRP) |
| --- | --- | --- |
| Model families | Qwen2.5-Coder-7B, Llama-3.1-8B, plus CodeGemma-7B on 10 of the 20 tasks | **Mistral-7B-Instruct-v0.3, Phi-3.5-mini-instruct** |
| Family overlap with A | - | **none** |
| Generation call | original run | fresh calls, no cached reuse |
| System prompt | "independent RTL behavioral-oracle engineer" | "digital design engineer writing production RTL" |
| Reasoning framing | three fixed "perspective" suffixes | restate behavior as an input-condition to output table, including reset and first active edge |
| Prompt organisation | Specification, then interface, then perspective | instruction first, then specification, then interface, then reasoning directive |
| Sampling | temperature 0.20 | temperature 0.40, distinct per-candidate seeds |
| Repair loop | up to 1 compile repair | same, to keep compile yield comparable |

Gemma-2-9B was considered and **rejected**: it shares a base family with the
CodeGemma used in population A's repair stage on 10 of these 20 tasks.

Honest limit on the independence claim: all five models are instruction-tuned
LLMs trained on overlapping public code, and every HDLBits problem statement is
likely in all of their pretraining data. Family and prompt independence is real
but partial. If H0 holds, one plausible reading is that no LLM population is
independent enough on this benchmark, which is itself the architectural answer
being sought.

---

## 6. Population sizes

Pre-registered sweep: **N = 3 and N = 5 candidates per family**, two families,
so 6 and 10 IVRP candidates per task.

To avoid a second generation run, 5 candidates per family are generated once,
and **N = 3 is evaluated as candidate indices 0, 1, 2** - a fixed prefix
declared now, not a post-hoc reselection of the best three.

**N = 8 is not run in this screening experiment** (amendment 5). If N = 5 clears
the gate, the next expenditure is the held-out confirmatory task set, not
another population-size step. We are testing whether independent semantic signal
exists, not searching for the ensemble size that maximises a score.

---

## 7. Cost

| Item | Value |
| --- | --- |
| Generation calls | 20 tasks x 5 candidates x 2 families = **200** |
| Models | `unsloth/mistral-7b-instruct-v0.3-bnb-4bit`, `unsloth/Phi-3.5-mini-instruct-bnb-4bit` (both verified present and ungated on HF) |
| Expected generation time | ~30 s per call average, ~1.7 GPU-hours |
| Dependency install and model download | ~20 min (two 4-bit models) |
| Simulation | 200 candidates compiled and run over 1108 scenario instances, ~10 min |
| **Total wall clock** | **~2.5 to 3 hours** |
| Kaggle sessions | **1**, GPU, well inside the 12 h limit |
| Internet / model loading | **required** (HF download; hub retry/backoff already in `hf_backend.py`) |
| Storage | candidates ~250 KB, per-check-point CSV ~2 MB |

Checkpointing every 8 candidates, matching the existing generation stages, so a
timeout is resumable.

---

## 8. What is recorded per check point

Golden RTL is **not** an input at this stage. Alignment uses the stimulus-prefix
identity from `analysis/arbitration_prototype.py`, keyed on
`(reset_first, drive prefix up to the observed cycle, output port, index)` -
never scenario names.

For each (task, method, check-point identity):

`task_id`, `method`, `circuit_class`, `stimulus_prefix_hash`, `port`, `index`,
`tb_expected`, `populationA_vote`, `populationA_agrees_with_tb`,
`ivrp_values` (per candidate), `ivrp_concrete_count`, `ivrp_xz_count`,
`ivrp_vote`, `ivrp_vote_fraction`, `ivrp_entropy`, `cross_population_agreement`,
`rule_D_decision`, `rule_E_decision`, `rule_F_decision`, `rule_G_decision`.

Decisions are written to disk and hashed **before** any golden comparison runs.

---

## 9. Arbitration rules

Let `T` = total IVRP candidates (6 at N=3, 10 at N=5); `C` = concrete values;
`U` = X/Z count; `V` = most common concrete value; `p = count(V)/C`.

| Rule | Definition |
| --- | --- |
| **A. No correction** | Current behaviour. Baseline. |
| **B. Population-A majority** | Already measured: 12.4% recall, 1.25% false-correction, breaks 5.1% of passing TBs. |
| **C. Population-A family majority** | Already measured: 12.4% recall, 1.16% false-correction, breaks 4.6% of passing TBs. |
| **D. IVRP majority** | CORRECT to `V` if `C >= ceil(T/2)`, `p > 0.5`, `V != tb_expected`. Else KEEP. |
| **E. High-confidence IVRP** | CORRECT to `V` if `C >= max(3, ceil(0.6*T))`, `p >= 0.8`, `U <= 0.25*T`, `V != tb_expected`. Else KEEP. At N=3 (T=6) this requires `C>=4, p>=0.8, U<=1`. |
| **F. Cross-population disagreement** | CORRECT only if population A supports the current expectation **and** E's conditions hold with `V != tb_expected`. Targets the correlated subset directly. |
| **G. Selective with abstention** | CORRECT if E holds and `V != tb_expected`; KEEP if `p >= 0.8` and `V == tb_expected`; otherwise **ABSTAIN**. |

Ties in `V` force ABSTAIN under G and KEEP under D/E/F.

---

## 10. Pre-registered success criteria

Fixed now. Not to be revised after seeing results.

### Must-have (all required to integrate)

1. Correction precision **>= 0.90** (>= 0.95 preferred).
2. False-correction rate on known-correct expectations materially below
   population-A arbitration's 1.25%, and passing-TB regression **near zero**.
3. Clear improvement in recall over Baselines B and C (both at 12.4%).
4. **Positive conservative Eval1 delta** - the sound lower bound, not the
   optimistic bound.

### Strong evidence (desired, not required)

5. Meaningful recovery within the 11 correlated cases where population A is
   jointly wrong.
6. Improvement holds for both CMB and SEQ, or there is a clearly identifiable
   subset where it works reliably.

Optimistic projected Eval1 rising is explicitly **not** sufficient.

### Hard failure criteria (any one stops this direction)

- IVRP mostly reproduces population A's wrong expectation.
- Correction precision stays poor.
- Previously passing testbenches are materially damaged.
- IVRP majority is not meaningfully better than population-A family majority.
- Conservative projected Eval1 stays far below what would justify integration.
- Improvement appears only after post hoc prompt or threshold adjustment.

On failure the response is **not** to raise N, try more prompts, add voting
layers, stack an LLM judge, or run all 156 tasks. It is to record the negative
result and pivot per Section 18 of the brief (Direction A:
specification-derived executable semantics; Direction B: narrow to sequential
verification).

---

## 11. Metrics reported

**Assertion level:** correction precision, correction recall, false-correction
rate, abstention rate - each for rules D, E, F, G at N=3 and N=5, against
baselines A, B, C.

**Testbench level:** Eval1 before; failing TBs recovered; previously passing TBs
broken; **conservative Eval1 projection**; optimistic projection labelled as
such; Eval2 given Eval1 projection where valid; composite projection.

Uncertainty is stated explicitly: the diagnostic recorded only the **first**
failing check per testbench, so a testbench with multiple failing checks cannot
be shown to flip to PASS. Conservative projections count only single-failure
testbenches as recoverable. No optimistic bound is presented as achieved Eval1.

**Correlated-failure subset (n = 11), the central independence test:** number
where IVRP disagrees with the TB expectation; number where it disagrees
*correctly*; number where it repeats the same wrong value; number inconclusive;
precision within the subset. Reported with a Wilson interval, given n = 11.

**Split by circuit class:** CMB and SEQ separately, and where n permits, by
family (truth-table/waveform, counters, FSMs, shift/register, other sequential).

---

## 12. Two options for the task set

**Option 1 (default, as instructed).** The 20 pilot tasks. 200 generation calls,
~2.5-3 h, one Kaggle session. Central test has n = 11 and the precision gate is
not resolvable at that size; the experiment can still cleanly detect a *strong*
negative (IVRP reproducing A's errors), which is the more likely outcome and
the decision-relevant one.

**APPROVED: Option 1 is what runs.** Option 2 as originally written (all 91
eligible tasks) is **superseded** by amendment 2 below, because the 20 pilot
tasks will already have influenced the decision to continue and are therefore no
longer clean confirmatory data.

### Stage structure (approved)

```
Stage 1  20 frozen pilot tasks
         -> screening / architectural decision
Stage 2  ONLY if Stage 1 passes:
         the eligible tasks NOT in the pilot
         (91 tasks with >=1 recorded Eval1 failure at seed 17, minus the
          20 pilot tasks) -> held-out confirmatory test
```

The original 20 may later be pooled with Stage 2 only as a clearly labelled
secondary full-data analysis. This prevents confirming the hypothesis partly on
the same data that caused us to continue.

### Asymmetry of Stage 1 (approved, stated explicitly)

Stage 1 is a **screening experiment**. Its power is deliberately asymmetric:

- A **strong negative is sufficient** to terminate this architecture branch.
- A **positive result is NOT sufficient** to establish that IVRP works, because
  the central correlated-error subset has only n = 11.
- A promising positive **only authorises** the Stage 2 held-out confirmatory
  experiment. It authorises nothing else.

---

## 13. Expected output files

| Path | Contents |
| --- | --- |
| `kaggle_runs/ivrp_v1/ivrp_candidates.jsonl` | 200 IVRP candidates: task, family, index, seed, RTL, compile and interface status, timing |
| `kaggle_runs/ivrp_v1/ivrp_manifest.json` | models, prompts, temperature, seeds, `golden_artifacts_seen: false` |
| `kaggle_runs/ivrp_v1/ivrp_checkpoints.csv` | one row per (task, method, check point) with every field in Section 8 |
| `kaggle_runs/ivrp_v1/arbitration_decisions.csv` | frozen KEEP / CORRECT / ABSTAIN per rule per N, hashed before scoring |
| `analysis/ivrp_scoring.py` | applies golden, emits the tables below |
| `IVRP_EXPERIMENT_RESULTS.md` | Table 1 assertion metrics; Table 2 testbench projections; Table 3 correlated subset; Table 4 CMB/SEQ split; explicit gate verdict |

---

## 14. What I need from you

Approve, or amend:

1. Option 1 (20 tasks) or Option 2 (91 tasks).
2. The two IVRP model families (Mistral-7B-Instruct-v0.3, Phi-3.5-mini).
3. The IVRP prompt in Section 4.
4. The thresholds in Sections 9 and 10.

On approval I run it once, exactly as written above, and report against these
criteria whatever the outcome.

---

# APPROVED AMENDMENTS

Approved before any generation. These supersede anything above that conflicts.

## A1. Stage 1 is a screening experiment

Stated in Section 12. Strong negative terminates the branch; positive only
authorises Stage 2.

## A2. Stage 2 uses held-out tasks only

Stated in Section 12. Confirmatory set = the 91 eligible tasks minus the 20
pilot tasks. Pooling is permitted only as a labelled secondary analysis.

## A3. Models fixed; technical failure reported, not substituted

Mistral-7B-Instruct-v0.3 and Phi-3.5-mini. **Not replaced after seeing semantic
results.** Compile and elaboration success is recorded **separately by family**.

Non-compiling candidates, runtime failures, and X/Z or indeterminate outputs:

- do **not** count as votes,
- do **not** count as disagreement with the testbench expectation,
- contribute **only** to reduced concrete evidence, pushing rules toward
  abstention.

If a family is technically unusable because most of its RTL does not compile,
that is reported transparently and makes the result **partly inconclusive about
semantic independence** rather than evidence for H0.

## A4. Prompt frozen

Section 4 prompt unchanged. Population B sees specification and interface only:
no testbench, no disputed expected value, no golden behaviour, no existing
oracle candidates, no indication of which check point failed. No prompt
optimisation after observing the outcome.

## A5. N fixed at 3 and 5; no N=8 in Stage 1

Generate 5 per family once. N=3 is indices 0,1,2; N=5 is indices 0-4. Fixed.

## A6. Rule roles pre-registered

| Rule | Role | Binding |
| --- | --- | --- |
| **E** | **PRIMARY.** `C >= max(3, ceil(0.6T))`, `p >= 0.8`, `U <= 0.25T`, plurality differs from expectation -> CORRECT | **The go/no-go decision is based on E alone** |
| D | Liberal majority-vote baseline | **May not be reported as the headline even if it scores better** |
| F | Targeted diagnostic for the correlated-error subset: population A supports the current expectation AND E strongly supports another value | Answers whether IVRP breaks shared semantic errors |
| G | Three-way selective validator: E strongly supports a different value -> CORRECT; E strongly supports the current value -> KEEP; otherwise -> ABSTAIN | Reported, not the gate |

## A7. The n=11 subset is diagnostic, not the Stage-1 gate

Report exact counts and Wilson intervals. Do **not** claim reliable high
precision from n=11, and do **not** fail a promising result solely because the
interval is wide. The directional question for those 11 is: when population A
confidently repeats the wrong answer, does population B ever provide useful,
correct contradictory evidence? The go/no-go uses all assertion and testbench
evidence, not only these 11.

## A8. Stage-1 advancement criterion (PRIMARY Rule E) — all six required

1. Correction precision point estimate **>= 0.90**.
2. Correction recall **strictly better** than the same-population baselines'
   12.4%.
3. False-correction rate **below** the existing arbitration baseline of 1.25%.
4. **Conservative** projected Eval1 delta **positive**.
5. At most negligible regression among previously Eval1-passing testbenches.
6. At least some evidence that IVRP corrects cases where population A shares the
   wrong expectation.

Confidence intervals are reported, but the pilot interval is **not** required to
prove >= 0.90, because the pilot is knowingly underpowered. If these conditions
are not met, H0 is the practical architectural decision and the branch stops.
These conditions are not relaxed after viewing results.

## A9. Conservative Eval1 is the decision number

Both conservative and optimistic projections are reported; **only the
conservative one influences the Stage-1 decision.** Also reported explicitly:

```
net recovery = recovered passing TBs - previously passing TBs broken
```

## A10. Leakage protection and decision hash

Exact ordering, enforced in code:

```
generate population B
-> simulate B
-> construct all check-point evidence
-> apply frozen D/E/F/G rules
-> write arbitration_decisions.csv
-> hash and freeze decisions          <-- SHA-256 recorded in the results report
-> only then read golden outputs
-> score
```

Golden must not affect candidate inclusion, confidence thresholds, prompt,
population size, vote rule, or check-point selection.

## A11. Exactly three terminal outcomes

**FAIL** - independent population reproduces correlated semantic mistakes, or
correction is too unsafe. Action: stop generated-RTL ensemble correction
entirely. Do not increase N, search prompts, add another LLM judge, change
models and rerun, or proceed to 156 tasks. Pivot to specification-derived
semantics or narrower sequential verification.

**PROMISING BUT UNDERPOWERED** - Rule E clears A8 but the sample is too small
for a strong conclusion. Action: run exactly one held-out confirmatory
experiment on eligible non-pilot tasks. No architecture changes between stages.

**STRONG NEGATIVE** - population B overwhelmingly agrees with the same wrong
expectations, especially in the correlated subset. Conclude explicitly that
fresh LLM generation does not provide sufficient semantic independence for this
benchmark. That is a useful research result and ends the branch.

No fourth category. "Almost worked, try another prompt" is not an outcome.
