# Sequential ACTIVE-TB: Design and Experiment Plan

Status: **design for review. No implementation started, no GPU run launched.**

Research question:

> Can state-directed active verification plus bounded formal witness generation
> improve fault detection and verification efficiency on sequential RTL, where
> current SOTA testbench generators are weakest?

Predecessor: `IVRP_EXPERIMENT_RESULTS.md`. The generated-RTL consensus and
correction branch is terminated; its artefacts are preserved.

---

## 1. Sequential-only benchmark analysis

Produced by `analysis/sequential_gap_analysis.py` from the published AutoBench
and CorrectBench records plus the HDLBits task definitions. Full per-task table
in `analysis/sequential_gap.json`. Families are assigned from specification text
and interface by fixed ordered regex rules, never from ACTIVE-TB results.

**75 sequential tasks** (union of both baselines' records).

| Family | n | AB Eval1 | AB Eval2 | CB Eval1 | CB Eval2 | Never solved |
| --- | --- | --- | --- | --- | --- | --- |
| fsm | 31 | 0.323 | **0.094** | 0.690 | 0.252 | **19** |
| lfsr_shift | 12 | 0.358 | 0.167 | 0.700 | 0.350 | 7 |
| dff_register | 10 | 0.370 | 0.140 | 0.620 | 0.240 | 6 |
| counter | 9 | 0.356 | 0.167 | 0.867 | 0.378 | 5 |
| other_sequential | 13 | 0.508 | **0.031** | 0.769 | **0.154** | **11** |

**48 of 75 sequential tasks (64%) are never solved by either baseline in any
run.** FSMs dominate the absolute count (19); `other_sequential` has the worst
rate (11 of 13) and the lowest Eval2 for both baselines.

### Where the machinery is actually applicable

Judged from interface and specification only:

| Property | Count |
| --- | --- |
| Has a clock | 74 / 75 |
| **Has a reset port** | **29 / 75** |
| Output width <= 16 bits and clocked (BMC tractable) | **64 / 75** |

Excluded as wide or unclocked: `conwaylife`, `count_clock`, `countbcd`,
`edgecapture`, `fsm_ps2data`, `lfsr32`, `m2014_q4a`, `rotate100`, `rule110`,
`rule90`, `shift18`.

**The single most consequential fact for the contract design: 46 of 75
sequential tasks have no reset port.** Power-up state is unconstrained, which is
precisely the class A failure mode measured earlier. `reset_state` must be
UNKNOWN by default, not guessed.

### State of the existing formal path

Measured across all 156 tasks at seed 17, `typed_formal_active`:

| Metric | Value |
| --- | --- |
| BMC calls | 223 |
| SAT | 84 |
| UNSAT | 67 |
| TIMEOUT | 14 |
| UNSUPPORTED | 58 |
| REPLAY_REJECTED | 24 |
| **Witnesses actually accepted** | **13** |

BMC works, but **84 SAT results yielded only 13 accepted witnesses**. The
witness -> Scenario IR -> replay path is where the value is being lost, and it is
an engineering target rather than a research risk.

---

## 2. Sequential Verification Contract (SVC) schema

Deliberately narrow. This does **not** attempt general prose-to-semantics.
Every field is UNKNOWN unless the specification states it or a deterministic
check confirms it.

```
SequentialVerificationContract:
  module_name          : str
  ports                : [Port]                    # from the interface, exact
  clock                : str | UNKNOWN
  active_edge          : posedge | negedge | UNKNOWN
  reset_signal         : str | NONE | UNKNOWN
  reset_polarity       : active_high | active_low | UNKNOWN
  reset_kind           : synchronous | asynchronous | UNKNOWN
  reset_state          : {port: value} | UNKNOWN    # only if explicitly stated
  input_drive_phase    : edge opposite to active_edge   # DERIVED, never guessed
  observation_phase    : after active_edge + settle     # DERIVED, never guessed
  state_variables      : [{name, width, observable: bool}] | UNKNOWN
  transition_conditions: [{from, guard, to}] | UNKNOWN
  enable_conditions    : [{port, sense}] | UNKNOWN
  boundary_behavior    : {wrap_at, saturate_at, ...} | UNKNOWN
  latency_cycles       : int | UNKNOWN
  legal_input_constraints : [predicate] | UNKNOWN
  provenance           : {field: spec_quote | derived | llm_candidate}
```

Rules:

1. An LLM may **propose** field values; it never commits them.
2. Every proposal passes deterministic validation before acceptance:
   - `clock`, `reset_signal` must exist in the interface with width 1;
   - `reset_polarity` and `reset_kind` are accepted only with a supporting span
     in the specification text, recorded in `provenance`;
   - `latency_cycles` is accepted only if consistent across all candidate
     evidence, otherwise UNKNOWN;
   - `transition_conditions` must be deterministic and total over the stated
     guards, otherwise UNKNOWN.
3. Contradictions between proposals **reject to UNKNOWN**; they never majority
   vote. This is the direct lesson of the IVRP and same-pool arbitration results.
4. UNKNOWN is a first-class value that suppresses assertions rather than
   licensing a guess.

Assertion policy driven by the contract:

- `reset_state` UNKNOWN and no reset port -> **no absolute output assertion
  until the design has been driven through a state-establishing prefix**;
- `latency_cycles` UNKNOWN -> assert only relations invariant to a bounded
  phase shift, never absolute cycle-indexed values;
- the Class-A X/Z abstention fix is preserved and always on.

---

## 3. ACTIVE state and transition representation

The DUT's internal state is not observable in general, so the representation is
an **observable abstraction**, computed only from stimulus and outputs.

```
StateAbstraction(k, m):
  signature = ( last k output vectors , last m input vectors )
  abstract_state = hash(signature)
```

Defaults `k = 2`, `m = 1`, raised per task only when the abstraction proves too
coarse (measured by transition non-determinism, see below).

Evidence maintained per task:

| Structure | Contents |
| --- | --- |
| `visited_states` | set of abstract states reached |
| `visited_transitions` | set of `(abstract_state, input_vector) -> abstract_state` |
| `frontier` | visited states with untried legal input vectors |
| `boundary_values` | per output: min, max, all-zero, all-one, wrap events observed |
| `nondeterminism` | transitions observed with conflicting successors; signals the abstraction is too coarse |
| `disagreement_regions` | check points where reference candidates disagree |
| `live_visible_mutants` | visible mutants not yet killed |
| `fault_clusters` | visible mutants with identical kill-vectors so far (subsumption proxy) |

`nondeterminism` is the self-check that keeps the abstraction honest: if the
same `(state, input)` maps to two successors, `k` is increased for that task
rather than the evidence being trusted.

---

## 4. Sequence-search algorithm

Genuine feedback-driven search, not "sample a random pool and keep the best".

```
budget B cycles, suite S = [], evidence E = fresh
while cycles_used < B:
    frontier = E.frontier ordered by (untried inputs, boundary proximity,
                                      live mutants whose kill-vector is unresolved)
    for each of the top-w frontier targets:
        prefix  = shortest known trajectory reaching that abstract state   # BFS over visited_transitions
        suffix  = generated by one of the registered operators below
        candidate = prefix + suffix
    score(candidate) = ( new_transitions
                       + alpha * new_boundary_events
                       + beta  * newly_killed_visible_mutants
                       + gamma * disagreement_resolved ) / cycles(candidate)
    commit argmax score; simulate; update E
    if no candidate scores > 0 for r rounds: escalate to BMC (section 5)
```

Registered suffix operators, all deterministic given a seed:

1. boundary-reaching (drive a counter/register toward its wrap or saturate point)
2. reset/enable interaction (assert reset or enable in every phase relation)
3. wraparound continuation (cross the boundary and continue)
4. transition-targeting (an input vector untried from the current state)
5. pulse patterns (single-cycle asserts of each control input)
6. alternating/control patterns (period 2 and 4 toggles)
7. coverage-guided mutation of a previously high-scoring sequence

The scheduler chooses among operators by measured yield. `PortfolioScheduler`
already implements exactly this bandit and is reused unchanged.

`alpha`, `beta`, `gamma`, `w`, `r` are pre-registered before the pilot and fixed
across all arms.

---

## 5. BMC integration

Trigger: the active search stalls, or visible mutants remain live after the
budget's exploration phase.

```
for each live visible mutant, ordered by fault cluster size:
    for bound in [4, 8, 16, 32]:                       # progressive
        objective = exists input sequence within `bound` cycles, satisfying
                    legal_input_constraints, such that
                    outputs(reference) != outputs(mutant)
        result = YosysBMC.find_witness(objective, bound)
        if SAT:
            witness -> Scenario IR -> VIC compile -> simulate
            accept ONLY if replay reproduces the divergence
            break
        if UNSAT: continue to next bound        # NOT equivalence
    if all bounds UNSAT: record `unresolved_at_bound_32`, never `equivalent`
```

Hard rules:

- UNSAT at a bound is **not** an equivalence claim, and is reported as
  `unresolved`;
- a formal result **never** counts as a simulation kill; only a replayed,
  verified witness contributes to the kill count;
- `REPLAY_REJECTED` is counted and reported, since it is currently 24 of 84 SAT
  and is the main loss in the existing path.

Priority engineering target carried into implementation: raise accepted
witnesses from 13 toward the 84 SAT results, by fixing VCD-to-Scenario
extraction and the legal-input-constraint encoding.

---

## 6. Fair baselines

All operate on the same contract, harness, budget, and mutant sets.

| Arm | Description |
| --- | --- |
| `official_seed` | the benchmark's own seed testbench |
| `random_legal` | uniform random legal sequences |
| `greedy_visible` | greedy visible-mutant targeting, no state model |
| `llm_scenarios` | LLM proposes scenarios, deterministic harness compiles them |
| `bmc_only` | BMC witnesses only, no active search |
| `active_no_bmc` | state-directed search, no formal |
| `active_plus_bmc` | the proposed method |
| `AutoBench` | published records |
| `CorrectBench` | published records |

AutoBench and CorrectBench are compared **only** under their published metric
definitions. The project's agreement-based Eval2 is never compared against their
mutation Eval2; `analysis/score_vs_sota.py` already computes the
publication-compatible form and is reused.

---

## 7. Budget protocol

Cycle budgets **8, 16, 32, 64**, identical for every internal arm
(`random_legal`, `greedy_visible`, `llm_scenarios`, `bmc_only`,
`active_no_bmc`, `active_plus_bmc`).

A cycle is one active clock edge applied to the DUT. Reset cycles count.
BMC-derived sequences consume budget at their replayed length, so formal work is
not free.

---

## 8. Sequential pilot: selection rule and task IDs

**Rule, fixed before any result is examined:** among the 75 sequential tasks,
keep those that are BMC-tractable (clocked, output width <= 16); within each of
the five families, sort task IDs lexicographically and take the first three.
Nothing about ACTIVE-TB performance enters the rule.

**15 pilot tasks:**

| Family | Task IDs |
| --- | --- |
| counter | `count10`, `count15`, `count1to10` |
| dff_register | `alwaysblock2`, `circuit10`, `dff` |
| fsm | `2012_q2fsm`, `2013_q2afsm`, `2013_q2bfsm` |
| lfsr_shift | `2014_q4a`, `ece241_2013_q12`, `history_shift` |
| stateful/other | `circuit7`, `circuit8`, `circuit9` |

Bias check, reported because the previous pilot was optimistically biased:

| | Pilot | All sequential |
| --- | --- | --- |
| Never solved by either baseline | 11 / 15 (73%) | 48 / 75 (64%) |
| Mean CorrectBench Eval2 | **0.200** | 0.264 |
| Has a reset port | 4 / 15 | 29 / 75 |

**The pilot is harder than the sequential average on both measures**, so it
cannot flatter the method the way the 20-task pilot did.

---

## 9. Metrics

**Primary:** hidden-mutant kills per 100 cycles, and the Pareto frontier of
fault detection against verification cost. The claim is about efficiency, not
raw mutation score.

**Secondary:** Eval1; publication-compatible Eval2; Eval2 given Eval1; hidden
mutant kill rate; wall time; BMC calls, time, SAT/UNSAT/TIMEOUT/REPLAY_REJECTED;
LLM calls and tokens; state and transition coverage proxy; false alarms;
unsupported tasks.

Every number is reported per budget, so a method that wins only by spending more
is visible as such.

---

## 10. Ablations

| Arm | Content |
| --- | --- |
| A | seed only |
| B | random legal |
| C | active visible-fault targeting |
| D | state/coverage-directed only |
| E | state-directed + visible faults |
| F | BMC only |
| G | state-directed + BMC |
| H | full method with selective LLM semantic fallback |

The comparisons that carry the claim are **D vs B** (does the state model help
beyond random), **G vs E** (do formal witnesses add anything beyond active
search), and **G vs F** (is the combination better than formal alone).

---

## 11. Success and failure criteria, pre-registered

**Success**

1. `active_plus_bmc` beats `random_legal` and `greedy_visible` on hidden kills
   per 100 cycles at **every** budget, with non-overlapping bootstrap intervals
   at 32 and 64 cycles.
2. `G` beats `E` on hidden kill rate, showing formal witnesses contribute.
3. `D` beats `B`, showing the state model contributes.
4. Eval1 is not degraded relative to the deterministic-harness baseline.
5. Accepted BMC witnesses materially exceed the current 13 of 84 SAT.

**Failure**

1. `active_plus_bmc` is within noise of `random_legal` at 32 and 64 cycles.
2. The gain disappears once budgets are equalised, that is, the method only wins
   by spending more cycles.
3. BMC contributes no accepted witnesses beyond the current rate.
4. Improvement appears only after post-hoc tuning of `alpha`, `beta`, `gamma`.

On failure, the honest conclusion is that budgeted adaptive selection does not
help on this benchmark, and the ACTIVE premise itself is falsified. That result
would be reported, not rescued.

---

## 12. Reuse audit

Verified by reading the modules, not assumed.

| Module | Lines | Disposition |
| --- | --- | --- |
| `active_tb/types.py` | 153 | **Reuse unchanged.** `Contract`, `Scenario`, `Cycle`, `Mutant` already carry what the SVC needs; SVC extends rather than replaces. |
| `active_tb/ir.py` | 71 | **Reuse unchanged.** Scenario validation and normalisation. |
| `active_tb/tb.py` | 172 | **Reuse, one extension.** Already owns clock, reset, drive and sample mechanics deterministically. Needs the state-establishing prefix and phase-invariant assertion modes. |
| `active_tb/sim.py` | 111 | **Reuse unchanged.** |
| `active_tb/formal.py` | 342 | **Reuse core, repair witness path.** `YosysBMC.find_witness` and VCD parsing work; the replay-rejection rate is the target. |
| `active_tb/mutation.py` | 134 | **Reuse unchanged**, with visible and hidden operator families kept disjoint. |
| `active_tb/coverage.py` | 325 | **Reuse as a feature source** for the scoring function. |
| `active_tb/scheduler.py` | 105 | **Reuse unchanged.** The bandit is exactly the operator-selection mechanism section 4 needs. |
| `active_tb/real_coverage.py` | 392 | **Reuse if Verilator is available**, otherwise the abstraction of section 3 stands alone. |
| `active_tb/spec_only.py` | 660 | **Retire.** This is the generated-RTL consensus branch being terminated. Kept on disk, not called. |
| `active_tb/temporal.py` | 337 | **Retire as an oracle**; salvage its per-family behavioural patterns as SVC extraction hints only, never as expectations. |
| `active_tb/engine.py` | 1561 | **Refactor.** Contains the active loop but is entangled with the retired oracle path. |
| `analysis/score_vs_sota.py` | - | **Reuse unchanged** for publication-compatible scoring. |
| Class-A X/Z abstention fix | - | **Preserved and always on.** |

Retired code is not deleted, so the negative results stay reproducible.

---

## Hidden-fault discipline

Visible mutants may guide search. Hidden mutants must never influence state
selection, sequence generation, stopping criteria, BMC targets, or thresholds.
The suite is frozen and hashed before hidden evaluation, using the same
freeze-and-hash discipline that the IVRP experiment demonstrated. Hidden
operator families are chosen disjoint from the visible ones wherever the
mutation engine supports it.

---

## What I need before implementing

Review of: the SVC schema (section 2), the state abstraction and its `k`/`m`
defaults (section 3), the scoring function and operator set (section 4), the
pilot selection rule and its 15 tasks (section 8), and the success/failure
criteria (section 11). No GPU run will be launched until this design is
reviewed.
