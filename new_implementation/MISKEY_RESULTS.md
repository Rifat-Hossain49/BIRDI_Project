# Mis-keyed Scenario Detection — results

Pre-registration: `MISKEY_PREREGISTRATION.md`, written before any result of the
rule was computed. Evaluator: `analysis/miskey_eval.py`. Everything is recovered
from ConfiBench's own released logs; nothing is re-simulated.

**Result: NEGATIVE on both generators, by the pre-registered criterion.** The
direction is stopped, as the pre-registration requires.

---

## 1. Validity — the numbers can be trusted

| gate | ConfiBench-4o | ConfiBench-4o-mini | required |
|---|---:|---:|---:|
| reproduced ConfiBench mask = recorded mask | **97.7%** (1505/1540) | **99.0%** (1739/1756) | ≥ 95% |
| recorded-mask verdicts = recorded verdicts | **99.7%** (4011/4023) | **99.2%** (3931/3961) | — |

ConfiBench's masking rule and its per-mutant verdicts are reproduced almost
exactly from its own data, so the comparison below is between ConfiBench and the
rule on identical testbenches, differing only in the masking decision.

## 2. Primary and held-out endpoints

Paired task-level bootstrap, N = 156 tasks, 3 runs averaged per task.

| | ConfiBench | with rule | Δ | 95% CI |
|---|---:|---:|---:|---|
| **4o — Eval2** (primary) | 0.7222 | 0.7179 | **−0.0043** | [−0.0278, +0.0171] |
| 4o — Eval1 | 0.8974 | 0.8077 | −0.0897 | [−0.1303, −0.0534] |
| **4o-mini — Eval2** (held-out) | 0.5556 | 0.5598 | **+0.0043** | [−0.0064, +0.0150] |
| 4o-mini — Eval1 | 0.8825 | 0.8376 | −0.0449 | [−0.0705, −0.0235] |

Criterion: 4o CI lower bound > 0 **and** 4o-mini point estimate > 0.
The 4o lower bound is −0.0278. **FAIL.**

## 3. What happened

| | 4o | 4o-mini |
|---|---:|---:|
| scenarios ConfiBench masked | 1386 | 1565 |
| scenarios the rule unmasked | 839 | 376 |
| missed detections recovered | **232** | 136 |
| false rejections introduced | 55 | 20 |
| records whose Eval1 an unmask broke | **42** | 21 |

The rule did what it was designed to do on one side: it recovered **232 of the
267** detections ConfiBench had caught and then masked away (87%). But it could
not tell those scenarios from ones whose expected value is genuinely wrong, so it
unmasked those too — breaking Eval1 on 42 records and, through the Eval1 gate,
cancelling the gain.

## 4. Why — the signal does not exist (exploratory, labelled as such)

`analysis/miskey_diagnostic.py`, on 4o only. Among masked scenarios, can item
discrimination tell apart the ones Golden passes (over-masked) from the ones
Golden fails (rightly masked)?

| | AUC |
|---|---:|
| item discrimination (proposed) | **0.577** |
| ConfiBench's own confidence | **0.614** |

| | share with disc(s) > 0 | median disc(s) |
|---|---:|---:|
| over-masked (correct to unmask) | 87.2% | +0.551 |
| rightly masked (wrong to unmask) | 84.8% | +0.392 |

The proposed signal is barely above chance and **worse than the one ConfiBench
already uses**. No threshold fixes that, which is why a second threshold is not
being tried.

The mechanism is the reason the psychometric analogy fails. Item discrimination
detects a mis-keyed item because in a real exam the **answer key is independent
of the examinees**. Here it is not: GPT-4o wrote the checker *and* the 20 RTLs,
from the same specification. When the checker misreads the spec, the RTLs that
share that misreading are precisely the ones that score well on the rest of the
test — so a genuinely wrong scenario still shows positive discrimination (84.8%
of them do). A mis-keyed scenario looks exactly like a good one.

## 5. What this adds to the project's record

This is the same wall, reached from a new direction. Every method in this project
that used LLM-generated artefacts to judge other LLM-generated artefacts written
from the same specification has failed for the same reason — correlated errors:

| method | judge | judged | outcome |
|---|---|---|---|
| oracle consensus | LLM candidates | expected values | FAIL |
| IVRP | LLM validators | candidate RTL | FAIL |
| ACTIVE-TB-SAFE Channel 2 | LLM candidate pairs (BMC) | stimulus | no gain over random |
| **mis-key detection** | **LLM RTL population** | **checker** | **FAIL, AUC 0.577** |

What *is* established, and is worth reporting in its own right, is the failure
analysis of ConfiBench itself (`analysis/confibench_weakness.py`,
`analysis/confibench_mask_audit.py`):

- 98% of ConfiBench's Eval2 losses are **missed detections**, 2% false rejections.
- **45.5%** of those misses were caught by its own testbench and discarded by its
  mask; **59%** of the discarded catches came from scenarios Golden passes.
- An oracle that unmasked only those would lift Eval2 by up to **+0.056** without
  touching Eval1. That ceiling is real; the problem is reaching it golden-free.
- ConfiBench's weakness is **sequential circuits**: Eval2 0.576 (SEQ) against
  0.857 (CMB), with Eval1 essentially equal.

## 6. The one principled lead that remains — not pursued here

The failure is correlation between judge and judged. The only way through it is a
judge whose errors are **independent** of GPT-4o's. The project already holds one
candidate: the spec-only RTL pool from a *different model family*
(Qwen, Llama, CodeGemma). Cross-family errors should be less correlated than
within-family ones.

It is a genuine hypothesis, not a promise. Those models are weaker than GPT-4o,
testing it requires simulating ConfiBench's scenarios on that pool (Kaggle), and
it would need its own pre-registration with ConfiBench-4o-mini held out as the
confirmatory set. Realistic odds are low to moderate.
