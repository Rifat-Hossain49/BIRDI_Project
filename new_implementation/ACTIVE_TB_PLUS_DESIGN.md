# ACTIVE-TB+ Design Notes

## Research question

Given a fixed verification-cycle budget and a set of plausible visible RTL fault hypotheses, what legal verification experiment should be executed next to maximize fault discrimination and generalization to unseen faults per unit cost?

## Main change from ACTIVE-TB

The old method stopped when it could no longer find a visible-mutant discriminator. ACTIVE-TB+ treats that event as **saturation**, not immediate termination.

At saturation it builds a legal exploration pool and scores candidates using:

```text
J(t) = [D(t) + lambda F(t) + gamma C(t) + eta N(t)] / cycle_cost(t)
       - mu R(t) - source_penalty(t)
```

where:

- `D(t)`: visible mutants newly discriminated by the scenario;
- `F(t)`: distinct visible fault families discriminated;
- `C(t)`: new coverage-proxy features;
- `N(t)`: normalized feature novelty;
- `R(t)`: redundancy;
- `source_penalty(t)`: small penalty for expensive BMC/LLM-origin candidates.

A scenario with no visible kill may still be admitted **only in exploration mode** when it adds new legal coverage features. This is the mechanism intended to improve generalization to hidden faults without ever consulting hidden-fault outcomes.

## Selective LLM gate

Qwen is no longer called merely because one formal attempt failed. It is eligible only when:

1. active deterministic/formal discrimination found no new candidate;
2. exploration also found no visible discriminator;
3. the unresolved visible-fault frontier remains non-empty;
4. stagnation has persisted for the configured number of rounds;
5. the per-task LLM call budget has not been exhausted.

The LLM still emits typed scenario intent, not raw timing-sensitive testbench code. The scenario is deterministically validated and replayed in simulation before admission.

## Exact equal-budget evaluation

`run_budget_sweep.py` reruns each logical method independently at each hard total-cycle budget. It does not truncate a 64-cycle result and call that an 8-cycle run. This avoids a subtle evaluation error because a budget-specific method may select a different shorter candidate when a long candidate no longer fits.

Random receives multiple seeds. The new reporting layer computes:

- hidden/visible kill rate at each budget;
- hidden kills per 100 cycles;
- mean generation time;
- AUKC (area under the kill-budget curve);
- paired task-level bootstrap confidence intervals;
- wins/ties/losses against Random, old ACTIVE-TB, and the no-LLM ablation.

## Blindness guarantee

The hidden mutant list is used only by `score_method` after suite generation. Candidate selection, coverage scoring, active clustering, BMC targets, exploration, and LLM prompts see only the golden RTL, contract, visible mutants, and already-generated scenarios.
