# Pre-registration — pilot 2: diverse reading paths for shared misreadings

Written **before** any checklist-path design was generated.

---

## 1. The bottleneck (measured, ConfiBench-4o dev set)

20.9% of sequential scenarios are **shared misreadings**: all five Qwen3.5-27B
samples agree and all are wrong, so sampling more of the same never exposes the
error, and localized resolution (pilot 1) cannot act because there is no
disagreement to localize. 81% of these start at rows 0–2 — initial/reset state or
the first transition — and they concentrate in six tasks (two hold 88%).

## 2. Hypothesis

Making the model answer explicit questions about the specification's semantic
axes **before** implementing — storage elements, initial state, clock edge and
latches, reset, output timing, and a row-by-row reading of any waveform — changes
how it reads the spec enough to correct misreadings that plain prompting repeats.

## 3. Materials (frozen)

- Prompt: `analysis/dlr2_prompt.txt` (generic; nothing task-specific).
- **Targets** (tasks with shared misreadings): `ece241_2014_q4`, `circuit8`,
  `ece241_2013_q4`, `edgecapture`, `fsm_ps2`, `counter_2bc`.
- **Controls** (no shared misreading): `2013_q2afsm`, `fsm2`, `ece241_2014_q5b`,
  `fsm_serial`, `circuit9`, `countbcd`.
- Stimulus: the same 208 ConfiBench-4o sub-testbenches used for the direct path.

## 4. Procedure (frozen)

Same model, quantisation, engine, sampling (T 0.6, top_p 0.95, top_k 20), thinking
on, token limit and strict answer extraction as J1b. 5 samples per task. Every
design and golden are simulated on the 208 sub-testbenches; rows are compared as
in the reference pilot. A path's scenario verdict is its **majority** trace over
the designs that ran (at least 3; otherwise the scenario counts as not fixed).

## 5. Criterion (frozen)

**Primary — fixes misreadings.** For each target task, Fix = share of its
shared-misreading scenarios where the checklist-path majority trace equals
golden. A task is *fixed* if Fix ≥ 0.5. Pass if **at least 3 of the 6** target
tasks are fixed.

**Guard — does no harm.** Pooled over the control tasks' scenarios, checklist-path
majority accuracy must be **no more than 5 points below** the direct path's.

**GO** requires both. Otherwise NO-GO, with no prompt revision on these tasks.

**Secondary (reported, not decisive):** exposure (a mixed pool of direct and
checklist designs contains a trace other than the shared wrong one, which gives
localized resolution something to act on); mixed-pool majority accuracy;
checklist designs' pass rate on the official testbench.

## 6. Limitations stated in advance

Development tasks only. Six targets is very few, and two of them contribute 88% of
the misread scenarios, so per-task and per-scenario views are both reported.
