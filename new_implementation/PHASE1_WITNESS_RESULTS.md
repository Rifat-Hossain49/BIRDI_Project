# Phase 1: Formal Witness Pipeline Repair

Gate for ACTIVE-TB-SAFE Channel 2. Nothing downstream was built until this
passed, because a formal channel that loses most of its witnesses produces
warnings nobody can trust.

## Result: PASS at 90.0%

| | SAT-to-replay | Funnel accounted |
| --- | --- | --- |
| Predecessor (`active_tb/formal.py`, benchmark run) | 13/84 = **15.5%** | 24 of 71 losses explained |
| This pipeline, first run | 3/10 = 30.0% | **10/10** |
| After parser repair | 8/10 = 80.0% | 10/10 |
| **After replay repair** | **9/10 = 90.0%** | **10/10** |

Gate was pre-declared at >= 90% SAT-to-replay on supported cases with a funnel
accounting for 100% of calls. Both conditions are met.

## Final funnel

| Case | Family | Outcome | Bound | Witness len | Solver s |
| --- | --- | --- | --- | --- | --- |
| comb_operator | combinational | ACCEPTED | 4 | 1 | 0.20 |
| counter_free | counter | ACCEPTED | 4 | 1 | 0.19 |
| counter_wrap | counter | ACCEPTED | 32 | 10 | 0.20 |
| counter_enable | counter | ACCEPTED | 4 | 1 | 0.19 |
| reset_sync_high | reset | ACCEPTED | 8 | 1 | 0.19 |
| **reset_async_low** | reset | **REPLAY_NO_DIVERGENCE** | 8 | 8 | 0.21 |
| fsm_small | fsm | ACCEPTED | 16 | 3 | 0.23 |
| multibit_input | datapath | ACCEPTED | 4 | 1 | 0.18 |
| multibit_output | datapath | ACCEPTED | 4 | 4 | 0.19 |
| no_reset_seq | no_reset | ACCEPTED | 4 | 1 | 0.19 |

Witnesses are short after minimisation (1-10 cycles) and solver time is
negligible (0.18-0.23 s). BMC itself was never the bottleneck; extraction and
replay were.

## What was actually wrong

Three defects, each diagnosed from captured artefacts rather than inferred.

**1. Witness extraction read the wrong format.** The predecessor parsed a VCD and
matched signals by name suffix. The rewrite switched to Yosys's native
`--dump-vlogtb`, but the first parser still failed on 7 of 10 cases with
`no input steps parsed`. Dumping the raw output showed the real layout:

```
    UUT.d = 8'b00000001;        // initial value
    if (cycle == 0) begin
      UUT.d <= 8'b00000000;     // per-step, non-blocking, UUT. prefixed
    end
```

Signals carry a `UUT.` hierarchical prefix and per-step values use `<=`. Neither
was matched. Diagnostic detail: the 3 cases that "passed" at that point all had
**no free inputs** and were surviving on a fallback path, so zero witnesses were
genuinely parsed. 30% was really 0%.

**2. The initial value was being discarded.** The initial assignment is in force
at the *first* sampled edge; the cycle-0 block is a non-blocking update that
takes effect afterwards. Letting cycle 0 overwrite it dropped the first
stimulus, which is how `multibit_output` replayed as all-zeros and could not
possibly diverge (`0<<1 == 0>>1`). With the fix it recovers `d=1`, giving
`1<<1=2` against `1>>1=0`.

**3. The replay harness was less expressive than the miter.** The miter updates
reset on `f_half`, a half-cycle grid; the replay harness changed reset only on
whole-period boundaries. Any divergence requiring reset to move between clock
edges was therefore unreproducible by construction.

## Known limitation carried forward

`reset_async_low` still fails, and the half-cycle change did not fix it.
Asynchronous reset differs from synchronous reset only in a narrow timing
window, and the current replay harness does not reproduce that window faithfully
even on the half-cycle grid.

Consequences, recorded rather than smoothed over:

- The gate passes at **exactly** the 90% threshold, and it passes because
  `multibit_output` was repaired, **not** because asynchronous reset was. One
  known-broken class remains.
- **Designs with asynchronous reset must be flagged.** Channel 2 must not emit a
  warning derived from an async-reset witness without independent simulation
  confirmation, because such a witness may be a false alarm.
- Async reset is common in real RTL, so this is a real restriction on coverage,
  not a corner case.

The honest reading is that the formal path is now usable for the synchronous and
combinational majority, with an explicit exclusion for asynchronous reset.

## Artefacts

| Path | Contents |
| --- | --- |
| `safe/synthetic_cases.py` | 10 Golden/mutant pairs with documented distinguishing inputs |
| `safe/formal_witness.py` | miter, native witness extraction, 9-outcome funnel |
| `safe/witness_regression.py` | replay, divergence check, minimisation, gate |
| `kaggle_runs/witness_regression_v4/` | final funnel CSV |
| `kaggle_runs/witness_regression_v2/witness_out/vlogtb_samples/` | raw witness dumps used for diagnosis |

## Next

Channel 2 can now be built: differential BMC against candidate RTL, adjudication,
and shadow tests emitted as warnings only. Channel 1 continues to pass the frozen
generator's verdict through untouched, so non-regression remains a property of
the architecture rather than a measurement.
