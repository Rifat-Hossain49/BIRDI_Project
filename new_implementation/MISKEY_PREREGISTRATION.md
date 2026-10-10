# Pre-registration — Mis-keyed Scenario Detection for testbench confidence

Written **before** any result of the proposed rule was computed. At the time of
writing, the only numbers seen are ConfiBench's own released results and the
oracle audit in `analysis/confibench_mask_audit.py`, neither of which depends on
the rule below.

---

## 1. The measured weakness this targets

From ConfiBench's own released archive (GPT-4o, 3 runs × 156 tasks), with the
reconstruction verified against ConfiBench's recorded per-mutant failures on
**414 of 420** Eval1-passing records:

- **98%** of ConfiBench's Eval2 disagreements are *missed detections* (its
  testbench accepts a mutant the official testbench rejects), not false
  rejections (587 vs 12). ConfiBench's testbenches are too weak, not too strict.
- **45.5%** of those missed detections (267 / 587) were **caught** by
  ConfiBench's own stimulus and checker, and then **discarded by its scenario
  mask**.
- Of the discarded catches, **59%** came from scenarios that **Golden passes** —
  the checker's expectation was correct and the suspicion that masked it was
  false.

## 2. Why the weakness exists

ConfiBench's confidence in scenario `s` depends only on the fraction of its 20
LLM-generated RTLs that fail `s`:

    confidence(s) = clip(1 − (e^{fail_frac(s)} − 1) + 0.1·ln(1 + full_pass_frac), 0, 1)

That count cannot separate two situations:

- the **checker is wrong** at `s`, so correct and incorrect RTLs alike fail it;
- `s` is a **hard corner case**, so buggy RTLs fail it and good ones pass.

In the second case many RTLs fail `s` *because* it exposes bugs — so
consensus-based confidence is biased towards masking precisely the scenarios
with the most detection power.

## 3. The proposed rule

Psychometrics separates a **difficult** test item (weak examinees fail, strong
ones pass) from a **mis-keyed** one (the answer key is wrong, so strength does not
help) with *item discrimination*: the correlation between passing the item and
the examinee's score on the rest of the test. The mapping is exact:

| psychometrics | testbench confidence |
|---|---|
| examinee | LLM-generated RTL |
| item | scenario |
| answer key | the Python checker's expected value |
| mis-keyed item | a scenario whose expected value is wrong |

For each sub-testbench, scenario `s`, and the RS matrix rows not entirely `-1`:

- `x_r = 1` if RTL `r` passes `s`, else `0`;
- `rest_r` = RTL `r`'s pass fraction over every scenario **except** `s`;
- `disc(s) = Pearson(x, rest)` — the point-biserial item–rest correlation.

**Decision.** Keep ConfiBench's mask everywhere, with one exception: a scenario
ConfiBench masks is **unmasked** iff `disc(s) > 0`. If `disc(s)` is undefined
(zero variance in `x` or `rest`), ConfiBench's decision stands.

**The single parameter is τ = 0**, fixed here, a priori, as the conventional
psychometric boundary between an item that functions and one that does not. It
will not be tuned.

The rule never *adds* a mask. So Eval1 can only fall (if a truly mis-keyed
scenario is unmasked) and raw detection can only rise. The net effect on
published Eval2 — which requires Eval1 — is what is being measured.

## 4. Scope, stated as a limitation

Only the **final masking decision** changes. ConfiBench's generation, its
correction and reboot loop, its testbench selection and its multibench
composition are all held fixed at what it actually produced. The evaluation
therefore answers: *given ConfiBench's own testbenches, does this rule decide the
masks better?* It does not capture how a different confidence signal would have
changed ConfiBench's generation trajectory, which would require re-running
ConfiBench with GPT-4o.

## 5. Validity gates — checked before any result is read

1. The reproduced ConfiBench mask (from the stored RS matrix, `e_rank_super`,
   threshold 0.15, K = 8) must match the recorded `scen_mask` on **≥ 95%** of
   sub-testbenches.
2. Re-scoring with the **recorded** masks must reproduce ConfiBench's recorded
   per-mutant verdicts at the rate already established (414 / 420).

If either fails, the reproduction is fixed first and no rule result is reported.

## 6. Endpoints

**Primary.** Published Eval2 (Eval1-gated, loose factor 0.8, `m2014_q3`
exception) on **ConfiBench-4o**, per task averaged over its 3 runs, compared
against ConfiBench's recorded masks by **paired task-level bootstrap**
(10,000 resamples, 95% percentile CI).

**Held-out.** The same rule, unchanged, on **ConfiBench-4o-mini** — a different
generator with different RS matrices, never used while designing the rule.

**Secondary.** Eval1 change; number of scenarios unmasked; of those, how many
the oracle audit classes as over-masked versus rightly masked.

## 7. Decision criterion

- **Success:** 4o CI lower bound **> 0**, **and** 4o-mini point estimate **> 0**.
- **Otherwise the result is negative**, reported as such, and this direction is
  stopped. No second rule is tried on the same data to rescue it.
