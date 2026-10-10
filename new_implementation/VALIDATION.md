# ACTIVE-TB+ validation performed in this build environment

Passed locally:

- `python -m compileall` for all project Python modules and scripts.
- Syntax validation of every code cell in `ACTIVE_TB_PLUS_Budgeted_Adaptive_Kaggle.ipynb`.
- `smoke_test.py` — contract/seed/mutation/TB static smoke.
- `checkpoint_smoke_test.py` — method-level checkpoint, skip-on-resume, and snapshot behavior.
- `adaptive_smoke_test.py` — new `active_adaptive` method with a deterministic fake simulator and a hard cycle-budget assertion.
- `budget_method_smoke_test.py` — exact method labels such as `b008__random_s03` and `b008__active_adaptive`, budget override, and trial metadata.
- `budget_report_smoke_test.py` — budget curves, AUKC, and paired-bootstrap report generation.
- `import_task_contract_cache` against the supplied completed ACTIVE-TB checkpoint; 154 supported-task contracts were imported successfully without copying old results or suites.
- ZIP integrity test for the packaged codebase.

Not reproduced locally:

- A physical Qwen3.5-27B load on two Tesla T4 GPUs. The Kaggle notebook retains the previously successful isolated-venv and dual-T4 preflight/load checks and will fail before a long experiment if placement is invalid.
- A real Icarus/Yosys end-to-end run in this container. The local container initially lacked the EDA binaries; an installation attempt exceeded the tool timeout. The Kaggle notebook installs/checks Icarus, Yosys, `yosys-smtbmc`, and Z3 before any benchmark job.

For the paper experiment, treat the 3-task no-LLM smoke and 2-task LLM smoke in the Kaggle notebook as mandatory before enabling the full 156-task exact-budget sweep.
