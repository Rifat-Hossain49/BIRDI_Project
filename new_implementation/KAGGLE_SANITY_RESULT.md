# ACTIVE-TB+ Kaggle Sanity Result

Run date: 2026-08-25

Private kernel:
https://www.kaggle.com/code/tishaferdous/active-tb-plus-budgeted-adaptive-sanity-v2

Post-run-hardened private dataset:
https://www.kaggle.com/datasets/tishaferdous/active-tb-plus-budgeted-adaptive-v3

Successful version: 2

## Review fixes applied before launch

- Fixed `active_adaptive` so visible-mutant saturation enters bounded
  coverage/diversity exploration instead of terminating immediately.
- Added a regression test for saturation with remaining cycle budget.
- Strengthened model identity in experiment fingerprints by recording the full
  normalized model mount path.
- Added portable ZIP discovery/extraction and notebook post-run invariants.

## Kaggle environment

- Accelerator: Tesla T4 x2
- Model: Qwen3.5-27B, NF4 4-bit
- Placement: 16 modules on `cuda:0`, 52 modules on `cuda:1`
- CPU/disk offload: none
- EDA preflight: Icarus Verilog, Yosys, `yosys-smtbmc`, and Z3 passed
- Total successful notebook runtime: approximately 25.7 minutes

## Integration results

- No-LLM exact-budget smoke: 42/42 jobs supported, 0 budget violations.
- LLM smoke: 4/4 jobs supported, 0 budget violations.
- Both checkpoint run states are `complete` with 0 remaining jobs.
- Explicit notebook markers:
  - `MODEL_DUAL_T4_LOAD_PASS`
  - `ACTIVE_TB_PLUS_SMOKE_PASS`
  - `SANITY_VALIDATION_PASS` for both integrations

At budget 16 on the three-task no-LLM smoke, `active_adaptive` and
`active_no_llm` both obtained a 0.90 pooled hidden-mutant kill rate, versus
0.50 for the two-trial Random baseline. This is a smoke sample, not a
statistically meaningful performance claim.

On the two-task LLM smoke, `active_adaptive` and `active_full` both killed 6/7
hidden mutants. Adaptive used 30 total cycles and 6 scenario-LLM calls, while
active-full used 22 cycles and 2 calls. For `gatesv`, six adaptive LLM calls
produced zero accepted LLM additions. The full experiment should therefore
measure call efficiency carefully, and a same-frontier failed-call cooldown is
a reasonable next ablation before claiming the adaptive policy is better.

## Local artifacts

- Final notebook: `ACTIVE_TB_PLUS_Budgeted_Adaptive_Kaggle.ipynb`
- Final portable package: `active_tb_plus_budgeted_adaptive_v3.zip`
- Package SHA256:
  `0BD4AE9540D7555ACD64A58CE99D4205C099A0F4EA0D3C5385C8BFA5FF8EB889`
- Downloaded run artifacts: `kaggle_runs/sanity_v2_version2/`

The local v3 notebook additionally requires every sanity job to be supported
and removes the disposable venv/copied source before successful Kaggle output
persistence. These two post-run hardenings do not alter the benchmark methods.
