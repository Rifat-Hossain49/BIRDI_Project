# Cross-family judge — results

Pre-registration: `XJUDGE_PREREGISTRATION.md` (with Amendment 1). Scorer:
`analysis/xjudge_score.py`. Every number comes from ConfiBench's own released logs
plus judge simulations run through ConfiBench's own drivers and checkers.

---

## J0 — weak cross-family pool (pre-registered baseline)

Qwen2.5-Coder-7B, Llama-3.1-8B and CodeGemma-7B (all 4-bit): 254 RTLs over the 60
tasks where a mask decision can change a verdict. Simulations: 1844 ran, 17
checker errors, 7 compile errors, 2 timeouts.

| | ConfiBench-4o | ConfiBench-4o-mini (held-out) |
|---|---:|---:|
| **diagnostic AUC of p(s)** | **0.661** | **0.683** |
| ConfiBench's own confidence (4o) | 0.614 | — |
| same-family item discrimination (4o) | 0.577 | — |
| Eval1 | 0.8974 → 0.8568 (Δ −0.0406) | 0.8825 → 0.8269 (Δ −0.0556) |
| **Eval2** | 0.7222 → 0.7073, **Δ −0.0150**, CI [−0.0363, +0.0064] | 0.5556 → 0.5406, **Δ −0.0150** |
| scenarios unmasked | 237 of 1386 | 129 of 1565 |
| missed detections recovered | 59 | 83 |
| false rejections introduced | 34 | 17 |
| records whose Eval1 an unmask broke | 19 | 26 |

**Verdict: FAIL** on the pre-registered criterion (4o lower bound −0.0363). This
was the expected outcome for the weak-judge baseline.

**What it establishes.** Even weak models from other families separate
ConfiBench's wrongly masked scenarios from its rightly masked ones **better than
ConfiBench's own confidence** (0.661 against 0.614 on 4o) and much better than
same-family item discrimination (0.577). The correlated-error diagnosis in
`MISKEY_RESULTS.md` is supported: independence carries real signal.

**Why it still fails.** Separation is not precision. The rule's cost is
asymmetric: one wrong unmask on a scenario Golden fails breaks that record's
Eval1 and with it all of its Eval2, while one correct unmask recovers a single
mutant, which matters only if it pushes the record across the 0.8 line. At J0's
accuracy the wrong unmasks (19 records' worth on 4o) outweigh the recovered
detections. A more accurate judge fails a genuinely wrong scenario more reliably,
which is exactly the precision J0 lacks — the premise J1 tests.

## J1 — Qwen3.5-27B, zero-shot

First attempt (vLLM, GPTQ-Int4) produced nothing: CUDA out of memory inside
vLLM's profiling pass on 2x T4. Rerun as J1b under Amendment 1 (llama.cpp,
Q4_K_M) with the same model, prompt, sampling and extraction.

### Coverage: PARTIAL. These are diagnostics, not the pre-registered endpoint.

llama.cpp reached only ~22 tokens/s for a dense 27B on 2x T4, so one 8.6 h
session produced **87 of 300 samples — 17 of 60 tasks**. Scenario coverage is
245/1386 (4o) and 162/1565 (4o-mini), i.e. 18% and 10%. The primary Eval2
endpoint therefore has **not** been validly tested, and the numbers below must
not be read as the pre-registered result. A resumed session is running.

### The judge itself

| | passes the official testbench |
|---|---:|
| combinational | 24/26 = **92.3%** |
| **sequential** | 22/40 = **55.0%** |

Of 87 samples, 21 hit the token limit still reasoning and produced no module.

### Separation (diagnostic AUC), against ConfiBench's own 0.614

| | 4o | 4o-mini |
|---|---:|---:|
| all masked scenarios | **0.860** | **0.976** |
| combinational only | **1.000** | **1.000** |
| **sequential only** | **0.617** | 0.841 |
| tasks where the judge is majority-correct (§6 gate) | **0.858** | **0.974** |
| tasks where it is not | 0.667 | 0.700 |

### Eval2 as measured on this partial coverage — still not a pass

| | ConfiBench | with judge | Δ | 95% CI |
|---|---:|---:|---:|---|
| 4o | 0.7222 | 0.7244 | +0.0021 | [+0.0000, +0.0064] |
| 4o-mini | 0.5556 | 0.5513 | −0.0043 | [−0.0107, +0.0000] |

4o's lower bound is exactly 0.0000 and 4o-mini is negative, so §5 is not met even
on the covered subset. Precision did improve sharply with judge strength: Eval1
was broken by an unmask on 4 records here against 19 for J0 and 42 for the
same-family rule.

### What §6 decides

The §6 gate was fixed in advance: restrict the AUC to tasks where the judge's own
majority RTL passes the official testbench, and fine-tuning is justified only if
that exceeds 0.70. It is **0.858** on 4o and **0.974** on 4o-mini. **The gate
passes: the limitation is judge accuracy, not the idea.**

The split makes the target concrete. Where the judge is accurate (combinational,
92%), separation is perfect (AUC 1.000). Where it is not (sequential, 55%),
separation collapses to 0.617 — and sequential is exactly where ConfiBench is
weak (Eval2 0.576 against 0.857). Caveat: the combinational 1.000 rests on 139
over-masked against only 8 rightly-masked scenarios, so it is not robust.

**Still required before any claim:** full coverage, then the §5 endpoint.

---

## Headroom: is the limit judge quality, or coverage?

The same rule scored three ways. The oracle arms consult Golden, so they are
upper bounds and never results.

| | ConfiBench-4o | ConfiBench-4o-mini |
|---|---:|---:|
| J1 as measured (18% / 10% coverage) | +0.0021 | −0.0043 |
| perfect judge, **same** coverage | +0.0064 | +0.0021 |
| perfect judge, **full** coverage (ceiling) | **+0.0513** [+0.0278, +0.0791] | **+0.0256** [+0.0107, +0.0427] |

Two things follow, and they set the order of work.

**The prize is real.** A perfect judge at full coverage takes ConfiBench-4o from
0.7222 to **0.7735**, with a CI excluding zero — past ConfiBench's own published
figure and past CorrectBench's 0.7013. That would be a genuine SOTA improvement
on the strongest published method, not an inherited score.

**Coverage, not judge quality, is the binding constraint right now.** At today's
coverage even a *perfect* judge could only gain +0.0064; the remaining +0.0449 is
locked behind scenarios the judge has not yet been run on. Finishing coverage is
pure GPU time and needs no training. Judge quality is the second lever: at
current coverage J1 realises about a third of what a perfect judge would
(+0.0021 of +0.0064) on 4o, and less than nothing on 4o-mini.

**So the order is: finish coverage first, then improve the judge.** Extrapolating
J1's current realisation rate to full coverage gives roughly +0.017 on 4o and
about zero on 4o-mini — better, but still short of the §5 criterion. Closing the
rest depends on the judge becoming as accurate on sequential circuits as it
already is on combinational ones (55% against 92%), which is exactly what
fine-tuning would target.

---

## Session 2 (33/60 tasks) — two corrections to the analysis above

Coverage roughly doubled (4o: 442 scenarios with >=3 votes, up from 245). Judge
accuracy drifted down as more tasks were reached: combinational 84.4%, sequential
48.8% (from 92.3% / 55.0% on the first 17 tasks).

| rule (development set, 4o) | Eval1 | Eval2 |
|---|---|---|
| Qwen alone (pre-registered) | 0.8782 (−0.0192, CI excludes 0; 9 records broken) | 0.7244 (+0.0021) |
| two-family gate (Qwen AND 7-8B pool) | 0.8953 (−0.0021; 1 record broken) | 0.7222 (+0.0000; 2 detections recovered) |

Pre-registered criterion: **FAIL** again (4o lower bound +0.0000, 4o-mini −0.0064).

**Correction 1 — coverage was not the binding constraint.** The headroom section
extrapolated linearly from coverage. Doubling coverage moved Eval2 by exactly
zero. The extrapolation ignored a nonlinearity: a record counts for Eval2 only if
its mutant agreement crosses 0.8. The oracle arm crosses because it unmasks every
recoverable scenario in a record at once; a real judge unmasks some and usually
leaves the record short. The unmask direction therefore needs near-complete
recall and precision simultaneously, which diagnostic AUC does not reveal. The
two-family gate delivers the precision (Eval1 protected) and loses the recall.

**Correction 2 — the Eval1-repair ceiling of +0.0825 was far too high.** It assumed
every failing record could be repaired by masking. Measured on the golden logs:

| | 4o | 4o-mini |
|---|---:|---:|
| Eval1 failures maskable in principle | 44/48 | 52/55 |
| median share of live scenarios that must be masked | **65%** | **62%** |
| records whose repair would mask > 50% of the testbench | **22** | **29** |
| records needing <= 25% masked (genuinely repairable) | 13 | 11 |

Most Eval1 failures are not a few wrong scenarios: the checker is broadly wrong.
Masking cannot repair that without gutting the testbench's detection power. The
realistic masking ceiling is about 13 records on 4o, roughly +0.03 Eval1 and +0.02
Eval2 even with perfect decisions.

**Consequence.** Re-deciding masks over ConfiBench's existing scenarios cannot
beat ConfiBench convincingly on all metrics. Its two largest losses — systemic
checker errors (22-29 records) and the 320 missed detections its stimulus never
exposes — both require generating testbench *content*: corrected expected values
and new stimulus. The cross-family mechanism survives (two-family agreement:
precision 1.000 on 48 decisions); its role has to change from mask voter to
reference model.
