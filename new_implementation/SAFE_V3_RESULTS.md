# ACTIVE-TB-SAFE v3 — results

Run: Kaggle `tishaferdous/active-tb-safe-v3` v2, 156 tasks, two frontends, four
arms each, shared execution path, nothing filtered.

**Headline: the v3 method changes did not work. No Channel 2 arm beats doing
nothing, the new gate is worse than the one it replaced, and baseline-aware
ordering actively hurt.** The run also exposed a defect in the *original*
architecture that is more consequential than anything v3 changed.

---

## 1. The most important finding is a bug in the original architecture

`literal` (the frontend's own driver bytes) and `primary` (ACTIVE-TB-SAFE
Channel 1) are supposed to be the same bytes, so they must score identically.
They did not.

| | CorrectBench | AutoBench |
|---|---:|---:|
| literal-vs-primary divergences | **6** | **21** |
| of which `primary = MISSING_ARTIFACT` | 6 | 21 |
| tasks where literal PASSED and primary shipped nothing | 5 | 10 |

Every divergence is the same thing: **Channel 1 was never emitted.**
`run_safe.py` aborts on `parse.supported == False` *before* writing Channel 1 —
but Channel 1 does not need the parse. It is the frontend's bytes, passed
through; the parse exists only to describe the interface to Channel 2.

So on 27 tasks across the two frontends, ACTIVE-TB-SAFE shipped **no testbench at
all** where the frontend had a working one. That is a direct violation of the
architecture's central claim — "whatever the generator scored, it still scores" —
and it is worth more than every v3 change combined:

| | Eval1 literal | Eval1 primary | recoverable |
|---|---:|---:|---:|
| CorrectBench | 0.7756 | 0.7436 | +0.0320 |
| AutoBench | 0.4936 | 0.4295 | +0.0641 |

Fix: emit Channel 1 before the parse and checker gates. One block move.

This bug predates v3 and was invisible until `reconcile_eval` put the two arms on
one execution path — which is precisely why that reconciliation was worth
building.

---

## 2. Publication-compatible metric, paired, N = 156 (`available`)

Δ is against `primary`, because `primary` **is** the frontend's testbench and
matching it is inheritance, not a win.

### CorrectBench

| arm | Eval1 | Eval2 | ΔEval2 vs primary | 95% CI |
|---|---:|---:|---:|---|
| published (frontend's own report) | 0.7821 | 0.7051 | +0.0513 | [+0.0192, +0.0897] |
| literal | 0.7756 | 0.6538 | +0.0000 | — |
| **primary** (Channel 1) | 0.7436 | 0.6538 | — | reference |
| control (Case-A gate) | 0.7436 | 0.6538 | +0.0000 | [−0.0192, +0.0192] |
| fixedorder | 0.7308 | 0.6474 | −0.0064 | [−0.0256, +0.0128] |
| **improved** | 0.7308 | 0.6410 | **−0.0128** | [−0.0321, +0.0000] |
| random stimulus | 0.7244 | 0.6346 | −0.0192 | [−0.0449, +0.0000] |

### AutoBench

| arm | Eval1 | Eval2 | ΔEval2 vs primary | 95% CI |
|---|---:|---:|---:|---|
| published | 0.4936 | 0.4487 | +0.0705 | [+0.0321, +0.1154] |
| literal | 0.4936 | 0.3782 | +0.0000 | — |
| **primary** | 0.4295 | 0.3782 | — | reference |
| control | 0.4295 | 0.3718 | −0.0064 | [−0.0192, +0.0000] |
| fixedorder / improved / random | 0.4295 | 0.3782 | +0.0000 | [+0.0000, +0.0000] |

Read plainly: **every Channel 2 arm is at or below the baseline it wraps.** No
CI excludes zero on the positive side. The channel currently costs more than it
adds.

---

## 3. The gate split increased false alarms — the risk I flagged, realised

| arm | tasks shipping C2 | **false alarms on Golden** | alarms on accepted mutants |
|---|---:|---:|---:|
| control (Case A) | 17 | **0** | 2 |
| improved (translation) | 9 | **4** | 3 |
| fixedorder | 11 | 4 | 3 |
| random | 9 | 5 | 3 |

I said before the run that splitting the gate might raise detection or might
raise false rejections, and that only the combined verdict would say. It raised
false alarms: 0 → 4 on Golden, while shipping **half as many suites**.

Case A was over-restrictive for the reason I identified — it discarded the
channel's own product — but it was also, empirically, the thing keeping false
alarms at zero. Removing it without replacing its filtering power was a net loss.

### Why the new gate ships fewer suites

CorrectBench stage 14, control vs improved:

| rejection reason | control | improved |
|---|---:|---:|
| A. no candidate passed Channel 1 | 25 | — (rule removed) |
| B. shadow suite did not simulate | 12 | 22 |
| C. discarded detection | 6 | — (rule removed) |
| **G. checker raised / sweep unusable** | — | **18** |
| F. nothing left after repair | — | 3 |
| **shipped** | **17** | **9** |

The dominant new rejection is **G, 18 tasks**: `translation_audit` calls
`accepted_values` at every step, which re-sweeps the output space, and that sweep
returns `None` on wide outputs (>4096 combinations) or when the checker raises.
The old gate never needed the sweep — it just ran candidates.

That is an implementation limit, not a conceptual one: where the sweep is
unusable the audit could fall back to the expectation adjudication already
produced instead of rejecting. Untested, so listed as a hypothesis rather than a
fix.

---

## 4. Baseline-aware ordering hurt, and the mechanism is clear

CorrectBench stage 10, "BMC returned SAT":

| arm | pairs submitted | SAT | lost |
|---|---:|---:|---:|
| control (fixed order) | 124 | **61** | 63 |
| improved (baseline-aware) | 124 | **53** | 71 |

Prioritising pairs Channel 1 cannot separate **reduced** the witness yield by 8
tasks. In hindsight the mechanism is obvious and I should have predicted it:
candidate pairs the frozen suite cannot tell apart are pairs that behave
similarly, and behaviourally similar designs are exactly the ones for which BMC
finds no disagreement within the bound. The ordering optimised for a property
anti-correlated with solvability.

---

## 5. The formal search is not earning its cost

On AutoBench, `random` scores **identically** to `improved` (Eval2 0.3782, Δ
exactly 0.0000). On CorrectBench random is marginally worse (0.6346 vs 0.6410) —
a one-task difference, well inside the CI.

Matched test-for-test and cycle-for-cycle, uniformly random stimulus adjudicated
by the frozen checker does about as well as differential BMC. On this benchmark,
at this budget, the formal machinery is not distinguishable from random search.

---

## 6. The adapter fixes worked at the funnel, and did not reach the metric

CorrectBench, stage 8 (state model validated): **108 (v2) → 124 (v3)**.
AutoBench local validation: **52 → 114**.

Those are real and large. They did not move Eval2, because the funnel's binding
constraint is downstream: stage 10 loses 63–71 of 124 tasks to "BMC found no
disagreement", and the gate then loses most of the rest. Widening the top of a
funnel whose narrowest point is further down buys nothing.

---

## 7. A harness gap that is not the method's fault, but is real

> **Corrected in §11.2.** Most of this gap was an artefact of the §1 bug leaking into the reconciler. The real gap is 2–3 tasks per frontend.

`published` exceeds `literal` by +0.0513 (CorrectBench) and +0.0705 (AutoBench)
on Eval2, both CIs excluding zero — while Eval1 reproduces closely (0.7756 vs
0.7821; 0.4936 vs 0.4936).

So our harness reproduces the frontends' **Eval1** almost exactly but scores
their **Eval2 agreement** lower than they reported. Since Eval2 depends on the
official testbench's verdict per mutant, the gap is most likely in the mutant set
or the official-verdict path, not in the testbenches. It is quantified here
rather than hidden, and it applies equally to every arm, so it does not affect
any Δ.

---

## 8. What the architecture actually ships, versus what was stress-tested

A distinction the tables above blur, and it matters for what may be claimed.

**ACTIVE-TB-SAFE as specified** says Channel 1 is authoritative and Channel 2
emits *warnings only, never a verdict*. Under that specification the pipeline's
score is exactly `primary` — and once the §1 emission bug is fixed, `primary` is
byte-identical to `literal`, so the shipped pipeline scores **exactly what the
frontend scores, guaranteed by construction rather than by measurement.**

The `combined` verdict `V_aug = V₁ ∧ ¬ShadowAlarm` is a **stress test**, not the
shipped behaviour: it was constructed to make false alarms cost something, so
that the channel could not look free. It is the strictest honest reading, and the
channel fails it.

So there are two separate questions, with two different answers:

| question | answer |
|---|---|
| Does the wrapper regress the frontend? | **No** — exact parity by construction, after the §1 fix. |
| Does Channel 2 add detection worth its false alarms? | **No** — not in either gate configuration. |

On the second: `control` (Case-A gate) shipped 17 suites with **0** Golden false
alarms but gained **0** tasks of Eval2 — safe and useless. `improved`
(translation gate) shipped 9 with **4** Golden false alarms — less safe and still
useless. Neither configuration earns its place as a scored channel. As a
*warning* channel, `control` is at least trustworthy enough not to cry wolf,
while `improved` at 4 false alarms in 9 suites is not.

---

## 9. Honest conclusion

- The **v3 method changes are a negative result.** The gate split, the
  baseline-aware ordering and assertion-level repair together made the pipeline
  slightly worse, and the ablations show the formal search is not separable from
  random stimulus at this budget.
- The **bug fixes are a positive result** at the funnel level and a **large
  positive** in the case of Channel 1 emission — which is not a v3 feature but a
  restoration of what the architecture always claimed.
- **Channel 2, as it stands, should not be shipped as a scored channel.** It does
  not beat doing nothing on either frontend, and after the gate split it raises
  false alarms on Golden.

The defensible claim from this work is *not* "ACTIVE-TB-SAFE beats SOTA". It is
narrower, and it is genuinely supported:

> A frozen testbench generator can be wrapped so that its verdict is preserved
> exactly, by construction rather than by measurement, once Channel 1 is emitted
> unconditionally. A formal shadow channel built on differential BMC over
> spec-only candidates does **not**, at this budget and on this benchmark, find
> faults the frontend misses often enough to pay for its false alarms — and a
> matched random-stimulus ablation is indistinguishable from it.

The negative half of that is worth as much as the positive half, because it is
measured rather than asserted: the ablations were built to be able to show this,
and they did.

---

## 10. Provenance

- Method frozen at `METHOD_FREEZE_v3.json`, combined SHA-256
  `8cc045e0386fd0cd94032f4a7413a5880f53d9f80fce8d2e26f7207a042ca08b`, recorded
  **before** any v3 result was inspected.
- The ConfiBench transfer (`tishaferdous/active-tb-safe-cbx`) was pushed with
  that frozen method, also before inspecting these results, so it is a genuine
  out-of-sample run.
- The Channel 1 emission fix in §1 was identified **after** seeing these results.
  It is therefore reported separately and must not be folded into the frozen
  transfer's numbers. Post-fix runs will be labelled as such.
- v2 artefacts remain untouched in `kaggle_runs/safe_full_v2/`.


---

## 11. Addendum — post-fix confirmation (v3b) and the ConfiBench transfer

### 11.1 The Channel 1 fix recovered exactly what it predicted

Run `tishaferdous/active-tb-safe-v3b`: identical to v3 except Channel 1 is
emitted before the parse and checker gates.

| | CorrectBench | AutoBench |
|---|---:|---:|
| literal-vs-primary divergences | 6 → **0** | 21 → **0** |
| `primary` Eval1 | 0.7436 → **0.7756** (+0.0320) | 0.4295 → **0.4936** (+0.0641) |
| predicted recovery | +0.0320 | +0.0641 |

Predicted to the digit, and `primary` is now byte-identical to `literal` on every
task. The non-regression claim now holds by construction.

### 11.2 Correction to §7: most of the "harness gap" was my own coupling

§7 reported `published` beating `literal` on Eval2 by +0.0513 and +0.0705 and
called it a harness gap. **That was largely wrong.** `reconcile_eval` scores a
mutant only if *both* reference arms return a verdict, so when `primary` was
`MISSING_ARTIFACT`, every mutant on that task became unscoreable and `literal`
lost its Eval2 there too. The bug in §1 was silently depressing `literal`.

With the fix:

| Eval2 | published | literal (v3) | literal (v3b) | remaining gap |
|---|---:|---:|---:|---:|
| CorrectBench | 0.7051 | 0.6538 | **0.6859** | 0.0192 |
| AutoBench | 0.4487 | 0.3782 | **0.4359** | 0.0128 |

The real harness gap is 2–3 tasks per frontend, not 8–11. The coupling itself is
a design flaw in the reconciler: the reference arms should be scored
independently, so one arm's missing artefact cannot erase another's result.

### 11.3 Channel 2 after the fix — conclusion unchanged

| ΔEval2 vs primary | CorrectBench | AutoBench |
|---|---:|---:|
| control | 0.0000 | −0.0064 |
| improved | −0.0128 | 0.0000 |
| random | −0.0128 | 0.0000 |

Still no arm above `primary`.

### 11.4 ConfiBench transfer — the method result replicates

Run `tishaferdous/active-tb-safe-cbx`, method frozen at
`8cc045e0…a042ca08b` **before** any v3 result was inspected. It therefore still
carries the §1 bug, as a frozen-method run must.

| arm | Eval1 | Eval2 | ΔEval2 vs primary | 95% CI | Golden false alarms |
|---|---:|---:|---:|---|---:|
| primary | 0.7500 | 0.6474 | — | reference | — |
| control | 0.7500 | 0.6474 | +0.0000 | [−0.0192, +0.0192] | **0** |
| fixedorder | 0.7500 | 0.6474 | +0.0000 | [−0.0192, +0.0192] | 2 |
| improved | 0.7500 | 0.6410 | −0.0064 | [−0.0192, +0.0000] | 2 |
| random | 0.7436 | 0.6346 | −0.0128 | [−0.0321, +0.0000] | 3 |

On a third frontend, with the method frozen in advance, the pattern is the same
as on the first two: no Channel 2 arm beats doing nothing; the Case-A gate is the
only one with zero false alarms; random stimulus is no worse than formal search.
**The negative result for Channel 2 transfers.**

### 11.5 ConfiBench absolute numbers are NOT yet trustworthy — my extraction

`published` Eval1 is **0.9103**; our `literal` Eval1 is **0.7885**. On
CorrectBench the same comparison agrees to within one task. So on ConfiBench, 21
tasks pass Golden with the testbench ConfiBench evaluated but fail (19) or fail
to compile (2) with the one I extracted.

This is my selection rule, not ConfiBench. The 21 mismatches are concentrated on
the tasks with the most iterations — median **26** candidate testbench
directories against **4** overall — which is exactly where "take the last one" is
most likely to be wrong. ConfiBench selects among several generated testbenches
by confidence (`multibench_iter_ids`, `multibench_valid_ratios` in each task's
`run_info.json`); the archive records that decision, and the correct extraction
reads it rather than inferring recency.

What this does and does not affect:

- It does **not** affect §11.4. Every arm shares the same Channel 1 bytes, so the
  arm comparison is paired on whatever testbench was extracted.
- It **does** mean the absolute ConfiBench Eval1/Eval2 above understate ConfiBench
  by roughly 21 tasks and must not be quoted as ConfiBench's performance.

The extractor's docstring said the rule was inferred and would be checked by
exactly this literal-versus-published comparison. It was, and it failed on
ConfiBench. Fixing the extraction is data preparation, not a method change, so it
does not touch the freeze.
