# Pre-registration — Divergence-Localized Resolution (DLR), pilot 1

Written **before** any model answer was generated. Goal context: reach
ConfiBench-level testbench quality with open models of at most 30B parameters.

---

## 1. The bottleneck this targets (measured, ConfiBench-4o dev set)

With Qwen3.5-27B designs as a reference, sequential scenarios decompose as:

| bucket | share |
|---|---:|
| all samples agree, correct | 42.6% |
| samples disagree, majority correct | 16.4% |
| majority wrong, but some sample correct (**select-recoverable**) | 9.3% |
| all samples agree, all wrong (**shared misreading**) | 20.9% |
| samples disagree, none correct | 10.8% |

Errors are early and propagating: the first divergence from golden is ~16% into
the trace, and 58% of wrong scenarios have most later rows corrupted. One wrong
local decision drives a whole scenario.

## 2. Hypothesis

When the model's own candidate designs disagree, asking it **one pointed question
at the first point of divergence** — the agreed observed history, the inputs at
that step, and the two candidate outputs — resolves the disagreement **more
accurately than majority voting** over the candidates.

## 3. Materials (frozen)

- `analysis/dlr_questions.jsonl`: 151 questions over 11 tasks (CMB 43, SEQ 108;
  majority-correct 85, select-recoverable 36, none-correct 30), at most 20 per
  task, built reproducibly (seed 20260913), option order randomized.
- Majority-vote accuracy on these questions, computed before any answer: **0.781**
  (118/151).
- Only questions where golden matches one of the two options are included.

## 4. Procedure (frozen)

- Model: Qwen3.5-27B, `unsloth/Qwen3.5-27B-GGUF` Q4_K_M, llama.cpp, the same build
  that ran J1b. No fine-tuning.
- Two passes over all 151 questions:
  - **thinking** (primary): thinking on, T 0.6, top_p 0.95, top_k 20, max 8000 tokens;
  - **direct** (secondary): thinking off, same sampling, max 256 tokens.
- One sample per question per pass, fixed seed.
- The answer is the last `ANSWER: A` or `ANSWER: B` after the reasoning. Anything
  else is an **abstention**.

## 5. Scoring (frozen)

- **Pipeline accuracy**: an abstention falls back to the majority pick, which is
  what the pipeline would do.
- **Strict accuracy**: an abstention counts as wrong. Reported alongside, always.
- Comparison against majority vote is **paired per question**, with a
  **task-clustered bootstrap** (resample tasks, 10,000 draws), because 151
  questions come from only 11 tasks.

## 6. Decision criterion (thinking pass, pipeline accuracy)

- **GO**: CI lower bound of (DLR − majority) **> 0**, **and** DLR accuracy **≥ 0.85**.
- Otherwise **NO-GO** for localized resolution as specified; no re-prompting or
  threshold search on these questions to rescue it.

Secondary reporting only (does not decide): the direct pass; per-bucket accuracy,
especially select-recoverable, where the majority is structurally disadvantaged;
CMB versus SEQ.

## 7. Limitations stated in advance

- Development set only; a GO here must be confirmed on ConfiBench-4o-mini.
- Only 11 tasks, so the CI will be wide; a pass is evidence, not proof.
- Shared misreadings (20.9%) produce no disagreement and are out of scope for this
  mechanism by construction; they need a separate mechanism.

## Amendment 1 (2026-09-14, written before any rerun data exists)

**What happened.** The first run ended INCOMPLETE and cannot decide anything under §6.
The thinking pass answered 120/151 questions before the 10.5 h session budget ran out,
and 98 of those 120 hit the 8000-token cap mid-reasoning and never wrote an answer
line; the direct pass hit its 256-token cap on all 151. This is a token-budget failure
of the protocol, not evidence about the method.

**Already seen (disclosed).** 22 thinking answers finished naturally: 13 correct, 9
wrong. Pipeline accuracy on the 120 answered was 0.758 against majority 0.733.

**Change (budget forcing only).** Thinking pass, same sampling (T 0.6, top_p 0.95,
top_k 20), same prompt, same 8000 reasoning-token cap. If the reasoning has not
closed at the cap, it is closed for the model with a fixed sentence
("I have reasoned enough; I will now give the final answer.") and the model writes its
answer with up to 1024 more tokens. This is the same mechanism frozen for Stage 3
generation. The direct pass is dropped (it cannot answer in 256 tokens and is secondary).
All 151 questions are re-asked from scratch; the 22 earlier answers are not reused.
The run is split by task across two sessions to fit the session limit.

**Unchanged.** Questions, answer parsing, abstention fallback, scoring, bootstrap, and
the §6 criterion (CI lower bound of DLR minus majority > 0 AND accuracy >= 0.85, all
151 answered). No re-prompting or threshold search after this rerun; its decision is final.
