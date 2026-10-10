# METRIC_RECONCILIATION

Step A of the ACTIVE-TB-AMP brief. Evaluator reconciled and baseline artifacts
inventoried. No GPU run, no LLM call, no new generation.

---
++ 
## 1. The correction, confirmed from source

My earlier reporting of CorrectBench Eval2 as 0.5231 overall and ~0.2640
sequential was **wrong**, and the brief's correction is right. The cause is
identified exactly.

Published Eval2 is **not** the stored `Eval2_pass` boolean and **not** raw
mutant detection. From `baselines/ConfiBench/analyze.py` and
`baselines/CorrectBench/analyze.py`, both pinned at `LOOSE_FACTOR = 0.8`:

```python
def loose_Eval2_pass(self, data):
    if data.get("Eval2_pass", False):
        return True
    numerator, denominator = data["Eval2_ratio"].split("/")
    return float(numerator) / float(denominator) >= self.loose_factor

def Eval2_pass(self, data):
    if data["task_id"] == "m2014_q3":
        if data.get("Eval2_failed_mutant_idxes", []) == [3,4,7,8,9,10] \
           or self.loose_Eval2_pass(data):
            return True
        return False
    return self.loose_Eval2_pass(data)
```

`Eval2_ratio` counts **agreement with the golden testbench's verdicts** over the
mutant set, so accepting a mutant the official testbench also accepts *earns*
agreement, and rejecting it *loses* agreement. I had been reading the strict
all-verdicts-agree flag, which is a different and stricter measurement.

The task-specific exception for `m2014_q3` is real and is reproduced verbatim.

## 2. Exact reproduction

`analysis/metric_reconciliation.py` ports the analyzer and reproduces the paper.

| Source | Runs | Tasks | Eval1 | **published_eval2** | gated on Eval0+Eval1 | strict_all_verdicts_agree |
| --- | --- | --- | --- | --- | --- | --- |
| AutoBench | 1560 | 156 | 0.5147 | 0.4481 | 0.4455 | 0.3462 |
| AutoBench-direct | 1560 | 156 | 0.5615 | 0.3385 | 0.0000 | 0.2571 |
| **CorrectBench** | 780 | 156 | 0.7949 | **0.7013** | 0.7000 | 0.5231 |

Sequential only:

| Source | Runs | Eval1 | **published_eval2** | strict |
| --- | --- | --- | --- | --- |
| AutoBench | 750 | 0.3707 | 0.2600 | 0.1093 |
| **CorrectBench** | 375 | 0.7173 | **0.5493** | 0.2640 |

**CorrectBench paper: 70.13% overall, 54.93% sequential. Reproduced: 0.7013 and
0.5493.** Exact to four decimal places, on all three CorrectBench record files
(`run_info.jsonl`, `run_info_and_codes.jsonl`, `run_info_and_codes_new.jsonl`,
identical scores).

### Where my earlier numbers came from

| My earlier figure | What it actually is | Published figure |
| --- | --- | --- |
| 0.5231 overall | `strict_all_verdicts_agree` | 0.7013 |
| ~0.2640 sequential | `strict_all_verdicts_agree`, sequential | 0.5493 |

Neither is a different run collection or evaluator commit. It is one substituted
predicate. Both quantities are now computed and reported under distinct names so
the confusion cannot recur.

`AutoBench-direct` gated at 0.0000 is not a bug: no run in that file has both
`Eval0_iv_pass` and `Eval0_py_pass` recorded true, so the gate is empty. Its
ungated 0.3385 is the comparable figure. Flagged rather than smoothed over.

pass@1 versus best-of-k, CorrectBench: per-run mean 0.7013, any-run 0.7949. The
published figure is the per-run mean, which is what we must compare against.

## 3. Required scoring names, as implemented

| Name | Definition | Status |
| --- | --- | --- |
| `published_eval1` | `Eval1_pass` | implemented |
| `published_eval2` | verbatim port including the `m2014_q3` exception | implemented, reproduces the paper |
| `strict_all_verdicts_agree` | stored `Eval2_pass` boolean | implemented, reported separately |
| `raw_mutant_detection` | fraction of mutants the TB rejected | **not derivable** from these records; they store agreement plus failing indices, not rejection counts. Returns `None` rather than a guess. |
| `official_tb_disagreement_on_accepted_cases` | our TB rejects where golden accepts | derivable only with re-simulation, deferred to the sealed evaluator |
| `independently_confirmed_false_rejection` | established independently | requires an independent fault source; not claimed from these records |

A mutant that survives the official testbench is **not** recorded as "clean" or
"equivalent" anywhere in this analysis.

## 4. Regression tests

`analysis/metric_regression_test.py`, **26 assertions, all passing**. Covers
every case the brief names: 8/10 passes (exactly at threshold), 7/10 fails,
4/5 passes, compile failure via the Eval0 gate, golden rejection via the Eval1
gate, the `m2014_q3` exception including its negative cases, a
known-equivalent alternative where over-rejection *costs* agreement, and a real
surviving bug where 8/10 still passes published Eval2.

That last test pins the most important property for this project: **published
Eval2 tolerates real escapes.** A testbench missing two genuine bugs out of ten
still passes. This is precisely why the brief's `H(B)` is the primary outcome
and published Eval2 is secondary.

## 5. Baseline artifact inventory

The actual checker and driver bytes were located, not just summary JSON.

| Frontend | Artifacts | Rows | Checker field | Driver field | Status |
| --- | --- | --- | --- | --- | --- |
| AutoBench | `data/AutoBenchResults/run_info_and_codes.jsonl` | 1560 | `tb_py_checker` | `tb_v_driver` | **available** |
| CorrectBench | `data/CorrectBenchResults/run_info_and_codes.jsonl` | 780 | `tb_py_checker` | `tb_v_driver` | **available** |
| CorrectBench | `run_info.jsonl` | 780 | absent | absent | scores only |
| **ConfiBench** | `saves_inEDA/Y25_0224~0302/NO1_ConfiBench_4omini_20250226_104808` | - | - | - | **ABSENT** |

`baselines/ConfiBench/` contains ConfiBench's *code* and its *copies of*
AutoBench and CorrectBench results. Its own generated run artifacts are not on
disk; `analyze.py` references `saves_inEDA/...`, which does not exist here.

**Consequence for the brief's requirement to include ConfiBench as a direct
comparison:** it cannot be run as a frozen frontend from local data. Obtaining
it requires executing the ConfiBench frontend, which is a metered LLM
generation cost and is not covered by "reuse saved artifacts". This is reported
rather than worked around, and no substitute is invented. The CorrectBench
frontend is sufficient to begin steps B through D.

## 6. Checker structure: the adapter is feasible

All 780 CorrectBench checkers share one shape: `class GoldenDUT` with
`__init__`, `load`, `check`, plus module-level `check_dut` and
`SignalTxt_to_dictlist`.

`load` is a genuine input-driven transition function, which is the brief's
STEP_MODEL interface. From `count10`:

```python
class GoldenDUT:
    def __init__(self):
        self.q_reg = 0
    def load(self, signal_vector):
        if signal_vector['reset'] == 1: self.q_reg = 0
        else: self.q_reg = (self.q_reg + 1) % 10
    def check(self, signal_vector):
        if signal_vector['check_en']:
            if self.q_reg != signal_vector['q']: return False
        return True
```

Two semantics that the adapter must preserve exactly, both discovered by
reading rather than assumed:

1. **`check_dut` calls `check` BEFORE `load` for each vector.** The expected
   value compared at a vector is the state *before* that vector's update. This
   phase convention belongs to the checker and must not be re-derived.
2. **`SignalTxt_to_dictlist` maps X and Z to 0** (`signal[key] = 0 # used to be
   "x"`). A mutant leaving an output at X is read as 0 and can therefore pass.
   This is a real weakness in the published harness. Checker-preserving means we
   keep this behaviour in the main track and **document** it, not that we
   silently repair it; any change would alter the frontend's semantics and
   invalidate the paired comparison. It is recorded here as a known limitation
   of the baseline and a candidate for a clearly separate ablation.

Classification of these 780 as STEP_MODEL versus TRACE_ONLY is step B and is not
claimed here. Uniform structure makes the adapter feasible; it does not prove
every `load` is safe on arbitrary new sequences. Checkers containing hard-coded
per-scenario answers must land in TRACE_ONLY, and that determination requires
execution, not pattern matching.

## 7. The measured case for the AMP direction

Computed from the CorrectBench records under the reconciled metric:

| Outcome | All (n=780) | **Sequential (n=371)** |
| --- | --- | --- |
| Eval1 fails: checker or driver rejects the golden design | 160 (20.5%) | 104 (28.0%) |
| Eval1 passes, perfect verdict agreement | 408 (52.3%) | 97 (26.1%) |
| **Eval1 passes, but at least one mutant verdict missed** | **212 (27.2%)** | **170 (45.8%)** |

**In 45.8% of sequential runs the checker is good enough to accept the golden
design, yet the stimulus fails to expose at least one fault.** That population is
the target of amplification, and it is where a backend can win without touching
expected-value logic.

`count10` is a concrete instance: its checker models the mod-10 wrap correctly,
and it still scores 8/10. The checker is right; the stimulus is weak.

The remaining 28.0% of sequential runs fail Eval1, where the checker itself is
wrong. A checker-preserving backend **cannot** fix those, and that limit stays
visible in Eval1 exactly as the brief requires.

## 8. Next step

Step B: implement the lossless checker and driver adapter, replay the original
testbenches through it, and produce the adapter support report with the
TRACE_ONLY versus STEP_MODEL split. No new generation is required for that step.
