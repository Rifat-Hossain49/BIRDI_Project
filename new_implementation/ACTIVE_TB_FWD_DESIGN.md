# ACTIVE-TB-FWD: Budgeted Formal Witness Distillation

Status: **design for review. Nothing implemented, no benchmark launched.**

Information setting, stated once and enforced throughout: **trusted Golden RTL
is available during test synthesis.** This is a different regime from the
spec-only CorrectBench track and its results may never be pooled with it.

Research question:

> Given a trusted reference RTL and a limited deployed test budget, can formally
> synthesised fault-discriminating witnesses be selected into a compact suite
> that generalises to unseen RTL faults better than random, mutation-greedy,
> fuzzing and naive formal baselines?

## Phase 0 status

Frozen and unchanged: `IVRP_EXPERIMENT_RESULTS.md`, `COMPACTION_RESULTS.md`,
`STEP_E_PREREGISTRATION.md`, `STEP_E_ANALYSIS_FREEZE.md`, `STEP_E_RESULTS.md`,
the 468 Step-E suites and manifest `99d6b241...`. Step E carries an explicit
FROZEN NEGATIVE header. Hidden Bank A will not be used to tune anything in this
track.

---

## Blocking constraint, stated first

**No formal or simulation toolchain exists on this machine.** Verified:

| Tool | Status |
| --- | --- |
| yosys, yosys-smtbmc, z3 | not available |
| iverilog, vvp, verilator | not available |
| python `vcdvcd` | not installed |

Every phase below therefore runs on Kaggle CPU. This matters most for Phase 1:
repairing a witness pipeline that can only be exercised remotely is slow, so the
repair is designed as a **single self-contained regression kernel** that reports
a full funnel in one run rather than requiring interactive iteration.

---

## 1. Formal witness infrastructure repair plan

### What is known to be broken

From the Step-E-era audit of `active_tb/formal.py`, across 156 tasks:

| Outcome | Count |
| --- | --- |
| BMC calls | 223 |
| SAT | 84 |
| UNSAT | 67 |
| TIMEOUT | 14 |
| UNSUPPORTED | 58 |
| REPLAY_REJECTED | 24 |
| **Witnesses accepted** | **13** |

84 SAT yielding 13 accepted witnesses makes any formal result uninterpretable.
The 24 replay rejections are documented; the rest of the gap is not, and must
not be assumed recoverable.

### Suspected causes, to be distinguished by instrumentation not guesswork

1. **VCD extraction.** `_parse_vcd` uses `vcdvcd`, locates signals by suffix
   match, and reconstructs input vectors at rising clock edges. Suffix matching
   and edge reconstruction are both fragile.
2. **Initial-state legality.** A solver counterexample may depend on internal
   register values that a top-level testbench cannot force. Such a witness is
   not deployable and must be rejected, not repaired.
3. **Unsupported constructs.** 58 UNSUPPORTED suggests the miter or the
   `dffunmap`/`clk2fflogic` path fails on common designs.

### Repair actions

- Add **native Yosys witness export** (`--dump-yw`, `--dump-vlogtb`) alongside
  the VCD path, and compare the two on the same SAT instances. This localises
  whether extraction or the solver is at fault. Native `--dump-vlogtb` output is
  a **debugging instrument only**: it may initialise internal registers
  hierarchically, which a deployable harness may not do.
- Replace suffix matching with explicit hierarchical paths from the miter that
  we generate ourselves, so signal identity is never guessed.
- Require every witness to be **input-driven from a legitimate initial
  condition**: either a reset sequence the DUT interface supports, or a
  demonstrated state-establishing prefix. Internal-register forcing is grounds
  for rejection.
- Emit a **complete per-call funnel** with mutually exclusive outcomes:
  `SAT / UNSAT / TIMEOUT / UNSUPPORTED_CONSTRUCT / EXTRACTION_FAILED /
  INITIAL_STATE_ILLEGAL / REPLAY_NO_DIVERGENCE / DUPLICATE_WITNESS /
  NO_NEW_INFORMATION / OVER_BUDGET / ACCEPTED`. The existing report explains only
  24 of 71 lost SAT results; the funnel must account for all of them.
- **Witness minimisation**: after acceptance, shrink the witness by removing
  leading cycles and re-replaying, keeping the shortest sequence that still
  reproduces divergence.

### Synthetic regression suite, written before benchmark contact

Ten hand-written DUT/mutant pairs with known-correct answers:

| # | Case | Mutation |
| --- | --- | --- |
| 1 | combinational and/or | operator swap |
| 2 | free-running counter | increment to decrement |
| 3 | wraparound counter mod 10 | wrap constant 10 to 16 |
| 4 | enable-gated counter | enable ignored |
| 5 | active-high sync reset | reset polarity flipped |
| 6 | active-low async reset | async made synchronous |
| 7 | 4-state FSM | one transition destination changed |
| 8 | multibit input adder | operand width truncated |
| 9 | multibit output shifter | shift direction reversed |
| 10 | no-reset sequential | initial value assumption changed |

For each: build the Golden-vs-mutant miter, require SAT, extract, replay on both
Golden and mutant under Icarus, verify divergence, then minimise.

**Gate: >= 90% of supported synthetic SAT witnesses must replay successfully,
and the funnel must account for 100% of calls.** No benchmark runs until this
holds. If a case is genuinely unsupported by the toolchain it is reported as
such, not silently dropped.

---

## 2. Exact visible mutation families

Development bank, generated from **Golden RTL** (permitted in this track),
pre-registered here:

| Family | Operators |
| --- | --- |
| `arith` | `+`<->`-`, `*`<->`/` where present |
| `relational` | `<`<->`<=`, `>`<->`>=`, `==`<->`!=` |
| `logic` | `&`<->`|`, `^`<->`~^`, `&&`<->`||` |
| `constant` | integer literal +/-1; width constant altered |
| `assign` | blocking `=` <-> non-blocking `<=` |
| `condition` | `if` test negated; ternary branches swapped |
| `sensitivity` | `posedge`<->`negedge`; reset removed from sensitivity list |
| `bitselect` | index or range endpoint shifted by 1 |
| `reset` | reset polarity flipped; reset value altered |
| `state` | one FSM transition destination changed |

Caps: at most 6 per family per task, at most 48 total, to stop a prolific
operator dominating the objective.

Each mutant is compile-filtered, then classified by differential analysis:

| Class | Meaning |
| --- | --- |
| `STILLBORN` | does not compile or elaborates degenerately |
| `LIVE` | a differential input is known to exist, by simulation or SAT |
| `PROVEN_NOCHANGE` | equivalence **actually proved**, unbounded |
| `UNKNOWN` | bounded UNSAT, timeout, or unsupported |

Two rules with teeth: **a compile failure is never a kill**, and **bounded UNSAT
is never reported as equivalence** - it stays `UNKNOWN`.

---

## 3. Legal-input assumption policy

Witnesses are only useful if the deployed harness can produce them.

- Inputs are free within their declared widths unless the interface says
  otherwise.
- The clock is generated by the harness, never solver-controlled.
- Reset is driveable through its port when one exists.
- **Internal registers are never forced.** A witness requiring a specific
  power-up state is rejected as `INITIAL_STATE_ILLEGAL` unless a
  state-establishing input prefix is demonstrated.
- For designs with no reset port, a witness must either be insensitive to the
  power-up state or be prefixed by a sequence that establishes it; the prefix
  cost counts toward the deployed budget.
- Assumptions are declared per task in a machine-readable record and are
  identical across all arms, so no arm is given a legality advantage.

---

## 4. Candidate matrix representation

```
Candidate:
  witness_id
  input_sequence           concrete, replayable, from a legal initial condition
  replay_cost              init + prefix + witness + observation cycles
  origin                   BMC | FUZZ
  target_fault             the fault it was synthesised against
  killed                   set of visible fault ids it actually kills on replay
  families                 set of visible families covered
  bound_used, solver_seconds
```

Matrix: `witness x visible_fault`, entries populated **by simulation replay**,
never by solver claims. Faults with identical kill-vectors are clustered and
represented once for scoring, with cluster size recorded so a large cluster
cannot silently inflate coverage.

---

## 5. Exact optimisation formulation

For deployed budget `B`, over candidates `i` with cost `c_i`, visible fault
families `f`, and clusters `k`:

```
maximise    sum_f  w_f * y_f
subject to  sum_i c_i * x_i <= B
            y_f <= sum_{i kills a fault in family f} x_i
            x_i, y_f in {0,1}
```

`w_f` is family-balanced: each family contributes at most its weight once,
regardless of how many mutants it contains. Solved exactly by ILP where
tractable, and by greedy gain-per-cost otherwise; both are reported, and the
greedy result is the honest fallback rather than the headline when ILP succeeds.

Selection uses **visible** faults only. Offline solver and search time is
reported separately and never counted as deployed cycles.

---

## 6. Reference-assisted baselines

All arms receive the **same trusted Golden RTL**. This is the fairness condition
of this track.

| Arm | Definition |
| --- | --- |
| A `SEED` | deterministic seed stimulus |
| B `RANDOM` | legal random stimulus at the budget |
| C `FUZZ` | differential constrained-random search, fitness = Golden vs visible-mutant divergence |
| D `GREEDY_MUT` | greedy visible-mutant targeting by simulation, no formal |
| E `BMC_NAIVE` | one witness per targeted mutant, discovery order, no portfolio optimisation |
| F `BMC_GREEDY` | BMC witnesses plus greedy gain-per-cost distillation |
| G `FWD` | BMC + fuzz witness pool with budgeted family-balanced distillation. **The proposed method.** |

CorrectBench and AutoBench are **contextual references only** and are never
presented as a head-to-head comparison, because they do not receive Golden RTL.

---

## 7. Pilot task selection rule

The earlier "BMC-tractable if output width <= 16" heuristic is **withdrawn**: it
does not measure state bits, memories, cone structure or actual solver support.

New rule, in order:

1. Start from the 75 sequential HDLBits tasks.
2. Run a **Phase-1 tractability probe** on each: build the Golden-vs-trivial
   miter and attempt BMC at bound 8 with a 60 s cap. A task is `TRACTABLE` only
   if the probe returns SAT or UNSAT within the cap - actual solver support,
   measured, not inferred from port widths.
3. Among `TRACTABLE` tasks, sort by `sha256(task_id)` and take the first 3 per
   family (counter, dff_register, fsm, lfsr_shift, other_sequential).

Selection depends only on solver tractability and a fixed hash, never on
baseline performance or fault-detection outcomes. The resulting task list is
recorded before any fault bank is built. Expected size ~15; the actual number is
whatever the probe yields and is reported, including families that yield fewer
than 3.

---

## 8. Bank-B generation protocol

- **Bank A**: `HDLBits_data_mutants.jsonl`, existing benchmark RTL mutants.
  Continuity only, and already used by earlier work - never for tuning here.
- **Bank B**: fresh deterministic RTL fault bank, generated **only after** the
  algorithm, hyperparameters and final suites are frozen and hashed.
  - Operator families **disjoint** from the Phase-2 visible families wherever
    possible: multi-site faults, port swaps, off-by-N with N > 1, stuck-at on
    internal nets, pipeline-depth changes.
  - Deterministic from a recorded seed; compile-filtered; `STILLBORN` excluded
    from the eligible denominator.
  - Generation script committed and hashed **before** it is run.
- A third source of real bugs is preferred if a suitable one can be identified;
  none is assumed.

Ordering is enforced: freeze suites and hash -> generate Bank B -> evaluate.

---

## 9. Metrics

**Primary**

```
H(B) = mean over tasks [ GoldenPass * hidden_killed / eligible_hidden ]
```

reported at B = 8, 16, 32, 64, headline **B = 32**, on Bank A and Bank B
separately - never pooled.

**Secondary**: hidden kills per 100 deployed cycles; Golden pass rate; visible
mutation coverage; solver time; the full SAT/UNSAT/TIMEOUT/UNSUPPORTED funnel;
SAT-to-replay rate; witness length distribution; search CPU time; final suite
size and cycles.

---

## 10. Pre-registered PASS / FAIL

**Phase-1 gate (blocking).** >= 90% SAT-to-replay on supported synthetic cases,
and a funnel accounting for 100% of calls. Fail here and the benchmark does not
run; the result is reported as an infrastructure limitation, not a method
result.

**PASS at B = 32 on Bank B**, all required:

1. positive mean paired delta of `FWD` over `RANDOM`;
2. positive mean paired delta of `FWD` over `GREEDY_MUT`;
3. positive mean paired delta of `FWD` over `BMC_NAIVE` - this is the claim that
   *portfolio distillation*, not merely using BMC, is what helps;
4. Golden pass rate not materially below the `SEED` baseline;
5. gain not driven by a single task;
6. `FWD` >= `BMC_GREEDY`, or an explicit statement that exact optimisation adds
   nothing over greedy;
7. the advantage survives on Bank B, whose operators differ from the visible
   families used for synthesis.

**FAIL** if `FWD` is within noise of `RANDOM`/`GREEDY_MUT`; if the advantage
exists on Bank A but vanishes on Bank B (that is overfitting to the visible
operator families and must be reported as such); if Golden acceptance regresses;
or if gains require post-hoc weight tuning.

On FAIL: report it and stop. Do not add an LLM, do not widen the mutation bank
to recover a result, and do not re-tune `w_f` after seeing hidden scores.

---

## Novelty discipline

No novelty is claimed for mutation testing, formal equivalence checking, BMC, or
counterexample-based test generation. All are established.

The hypothesis under test is narrower: **whether a family-balanced, exact-budget
portfolio of formally generated differential witnesses generalises to unseen RTL
faults more efficiently than naive formal, random, fuzzing and greedy mutation
baselines.** Arm E (`BMC_NAIVE`) exists precisely so that "we used BMC" cannot be
mistaken for the contribution; the contribution, if any, is the distillation.

---

## Review requested

Before implementation: the Phase-1 repair plan and its gate, the mutation
families, the legal-input policy, the ILP formulation and family weighting, the
tractability-probe pilot rule, the Bank-B operator disjointness, and the
PASS/FAIL criteria. No benchmark will be launched until these are reviewed.
