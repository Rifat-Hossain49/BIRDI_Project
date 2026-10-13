# BIRDI Equal-Model ConfiBench Baseline: Desktop Completion Report

**Date:** 13 October 2026 · **Run window:** 10–11 October 2026 (times below are UTC; local time is UTC+6)

## 1. Summary

All 156 ConfiBench tasks now have a first task record. The 16 tasks left unfinished on Kaggle were completed on the desktop with the same frozen Qwen3.5-27B Q4_K_M model and baseline settings.

- **3 of the 16 desktop tasks pass** (Eval1 passes and Eval2 agreement is at least 0.8): `2014_q3fsm`, `vector100r` and `fsm_onehot`. The other 13 are recorded failures.
- **No earlier result changed.** All 140 pre-desktop first records, and the 138 original Kaggle records, are byte-identical after the run. No task has a duplicate record.
- **Across all 156 records**, a preliminary audit counts 154 Eval0 passes, 142 Eval1 passes and 110 loose Eval2 passes. 14 records lack Eval2 fields and 3 lack an Eval1 field.
- **About 2,140 new model responses** were generated on the desktop, over 4 GPU sessions totalling about 14.8 hours.
- **Three bugs in the desktop runner** were found and fixed during the run (Section 6). None changes prompts, sampling or scoring.

This is a record audit, not the final scored comparison. Official scoring (including the preserved `m2014_q3` exception), the 60/96 development/test split and the DRTB comparison are still to do (Section 10).

## 2. Protocol and environment

The frozen baseline protocol was not changed. Only the hardware, the host setup and the runner scheduling differ from the Kaggle runs.

| Setting | Value |
| --- | --- |
| Model | `unsloth/Qwen3.5-27B-GGUF`, file `Qwen3.5-27B-Q4_K_M.gguf` (logical ID `qwen3.5-27b`) |
| Model SHA256 | `84b5f7f112156d63836a01a69dc3f11a6ba63b10a23b8ca7a7efaf52d5a2d806` (same at every load) |
| Backend | Official `llama.cpp b11399` CUDA 12.8 Linux binaries (commit 2ca15f540), checksum-pinned, no source build |
| Sampling | Thinking off; temperature 0.7, top_p 0.8, top_k 20, max output 8,192 tokens; original per-stage temperatures kept |
| ConfiBench | RTL population 20, debug limit 3, iteration limit 10; confidence `e_rank_super` (threshold 0.15, K = 8); discriminator `col_70_wrong_row_25_correct`; ensemble minimum 2, ratio 0.8; first-result retention |
| Model server | 2 parallel slots, 32,768-token context per slot (65,536 total) |
| GPU | NVIDIA GeForce RTX 5090, 32,607 MiB, driver 610.88; 20.3–20.4 GB allocated by the model server |
| Host | Windows 11 Pro, Intel Core Ultra 9 285K, 128 GB RAM; WSL2 Ubuntu 24.04; Docker Desktop 4.94 (engine 29.8.2) |
| Container | `ubuntu:24.04` with Icarus Verilog and Python 3.12; working directory mounted at `/kaggle/working` so saved traceback paths stay identical |
| Throughput | About 54 tokens/s generation per slot; 5–6 ConfiBench iterations per hour with 2 workers |

Differences from Kaggle that must be disclosed with the baseline:

- **Hardware and concurrency:** one RTX 5090 serving 2 workers. New stochastic responses are not claimed to be bit-identical to what Kaggle hardware would have produced.
- **Runner amendments:** three fixes to the desktop runner (Section 6).
- **Time budget:** an operator-chosen 168-hour cap instead of Kaggle session limits. Every session ended because its work finished or crashed, never because of the cap.

## 3. Results for the 16 desktop tasks

3 tasks pass, 10 pass Eval1 but fall below the 0.8 Eval2 threshold, 2 fail Eval1 and 1 never produces a testbench that passes Eval0. "Pass" here means Eval1 passes and the Eval2 verdict agreement ratio is at least 0.8; strict Eval2 is the `Eval2_pass` field stored in each record.

| Task | Type | Eval0 | Eval1 | Eval2 ratio | Strict Eval2 | Pass (Eval1 and ratio ≥ 0.8) |
| --- | --- | --- | --- | --- | --- | --- |
| `2014_q3fsm` | SEQ | pass | pass | 10/10 | pass | **yes** |
| `vector100r` | CMB | pass | pass | 10/10 | pass | **yes** |
| `fsm_onehot` | CMB | pass | pass | 8/10 | fail | **yes** |
| `lemmings2` | SEQ | pass | pass | 7/10 | fail | no |
| `countbcd` | SEQ | pass | pass | 7/10 | fail | no |
| `lemmings4` | SEQ | pass | pass | 4/8 | fail | no |
| `fsm_serial` | SEQ | pass | pass | 3/10 | fail | no |
| `count_clock` | SEQ | pass | pass | 2/6 | fail | no |
| `2013_q2bfsm` | SEQ | pass | pass | 1/5 | fail | no |
| `gshare` | SEQ | pass | pass | 1/9 | fail | no |
| `review2015_fsm` | SEQ | pass | pass | 1/9 | fail | no |
| `fsm_hdlc` | SEQ | pass | pass | 1/10 | fail | no |
| `fsm_serialdata` | SEQ | pass | pass | 1/10 | fail | no |
| `lfsr5` | CMB | pass | fail | missing | missing | no |
| `circuit10` | SEQ | pass | fail | missing | missing | no |
| `review2015_fancytimer` | SEQ | fail | missing | missing | missing | no |

Types are the `circuit_type` field as stored in each record (CMB = combinational, SEQ = sequential); `lfsr5` is stored as CMB. Missing fields are reported as missing, not converted into passes or fails.

## 4. Record audit across all 156 tasks

The 156 records contain 110 loose Eval2 passes. Sequential tasks are much weaker than combinational ones, especially on strict Eval2 (14 of 74 versus 68 of 82).

| Group | Records | Eval0 pass | Eval1 pass | Strict Eval2 pass | Loose Eval2 pass |
| --- | --- | --- | --- | --- | --- |
| All tasks | 156 | 154 | 142 | 82 | 110 |
| Combinational (CMB) | 82 | 82 | 76 | 68 | 72 |
| Sequential (SEQ) | 74 | 72 | 66 | 14 | 38 |
| Recorded on the desktop | 16 | 15 | 13 | 2 | 3 |

Definitions: strict Eval2 is the stored `Eval2_pass` field. Loose Eval2 is Eval1 pass with an `Eval2_ratio` of at least 0.8 (ConfiBench's "loose Eval2 pass metric 0.8"). The loose count here **does not** apply the preserved `m2014_q3` exception, so it is not the official score.

Records with missing evaluation fields (kept as-is):

- **No Eval2 fields (14):** `always_case2`, `bugs_mux2`, `circuit10`, `circuit8`, `ece241_2013_q4`, `ece241_2014_q3`, `edgedetect2`, `lfsr32`, `lfsr5`, `m2014_q3`, `m2014_q6b`, `review2015_fancytimer`, `review2015_shiftcount`, `rule110`.
- **No Eval1 field (3):** `bugs_mux2`, `lfsr32`, `review2015_fancytimer`.
- 11 of the 14 were already missing before the desktop run, matching the handoff's count; the 3 new ones are `circuit10`, `lfsr5` and `review2015_fancytimer`.

## 5. Execution timeline and incidents

The run took 4 GPU sessions. Each one was preceded by the mandatory CPU-only replay, and three of them ended early because of runner bugs or a full disk.

| When (UTC) | Event |
| --- | --- |
| 10 Oct 09:16 | CPU replay 1: 16/16 tasks verified, 0 fresh calls, 0 mismatches (97 s) |
| 10 Oct 09:30 | GPU session 1: pinned backend installed (checksums verified), model downloaded (15.6 GB), server ready about 10:01 |
| 10 Oct 10:01 | **Incident A:** two workers started in the same second; `2014_q3fsm` crashed with `FileExistsError` before any model call |
| 10 Oct 10:05 | Session 1 stopped deliberately (SIGINT) to fix A; 1 fresh response committed, at most 2 in-flight responses lost |
| 10 Oct 10:05–10:06 | Fix A; CPU replay 2: 16/16; GPU session 2 starts |
| 10 Oct 10:21–13:51 | Records: `2014_q3fsm`, `2013_q2bfsm`, `circuit10`, `count_clock` (144/156) |
| 10 Oct ~14:10 | **Incident B:** drive E: filled; Ubuntu's disk file had grown from about 110 GB to 377 GB; filesystem went read-only and the runner exited |
| 11 Oct ~05:50 | Ubuntu moved from E: to G:; filesystem recovered cleanly; fix B written and tested |
| 11 Oct 06:02–06:03 | CPU replay 3: 12/12, nothing lost (`countbcd` kept all 579 saved responses); GPU session 3 starts |
| 11 Oct 07:37–11:21 | Records: `countbcd`, `fsm_onehot`, `fsm_hdlc`, `fsm_serial`, `fsm_serialdata`, `lemmings2` (150/156); 1 orphaned simulator killed |
| 11 Oct 11:22 | **Incident C:** checkpoint race on `lemmings4/next_request.json`; runner exited after writing its final checkpoint |
| 11 Oct 11:23 | Fix C; CPU replay 4: 6/6; GPU session 4 starts |
| 11 Oct 11:50–16:11 | Records: `gshare`, `lemmings4`, `review2015_fancytimer`, `review2015_fsm`, `vector100r`, `lfsr5`; 156/156, runner exit code 0 |

Incident B's root cause: ConfiBench's `subproc_call` runs simulations with `Popen(..., shell=True)` and, on timeout, kills only the process it started. A `vvp` simulator below it survived, and kept writing to a `TBout.txt` that ConfiBench had already deleted. That space was invisible to `du` until the drive filled. After recovery, the kernel reported "2 orphan inodes deleted" and usage returned to 123 GB.

## 6. Desktop runner amendments (must be disclosed)

All three changes are in `new_implementation/desktop/resume.py`, outside the frozen ConfiBench source, which is checksum-verified and was not modified. The offline suite grew from 42 to 46 tests, all passing.

| # | Problem | Fix | Effect on the experiment |
| --- | --- | --- | --- |
| A | All workers shared the save prefix `Desktop`, and ConfiBench names save folders `<prefix>_<second>`. Workers starting in the same second crashed (`FileExistsError`) or shared a folder | Per-task prefix `Desktop_<task>` via `worker_config()`, mirroring Kaggle's per-worker `S<shard>W<w>` prefixes | Only the name of new save folders changes. Resumed iterations keep their restored historical paths, and folder names already varied by timestamp |
| B | Orphaned `vvp` processes kept running after ConfiBench timeouts and filled the disk | `reap_orphans()` kills processes re-parented to the runner (never the workers or the model server) and logs each one to `desktop_reaped.log`. `check_disk()` stops the run cleanly if disk use grows by more than 80 GB in one session | Kills only simulations ConfiBench had already abandoned as timed out. One process was killed in total (`vvp run.vvp`) |
| C | `checkpoint()` listed journal files, then zipped them; a live worker deleted one in between | Skip a file that vanishes before it is zipped. All journal writes are atomic (`.tmp` then rename), so a partial file can never be skipped silently | Affects only the backup ZIP; the next snapshot, 60 s later, is complete |

## 7. Integrity evidence

- **CPU-only replay before every GPU session:** 16/16, 16/16, 12/12 and 6/6 unfinished tasks reached their next request with 0 fresh calls, 0 `ResumeMismatch` and matching request hashes.
- **First-record preservation:** checked by the runner at every 60-second checkpoint and again in the final audit: 140/140 pre-desktop records and 138/138 original records byte-identical.
- **Inventory:** 156/156 expected task IDs recorded; no duplicate, unexpected or unreadable records.
- **Model on GPU:** the same model SHA256 at every load, and the runner's allocation check (at least 75% of the model resident on the GPU) passed every time.
- **Results bundle:** 92 files with SHA256 checksums, verified after copying; checkpoint ZIPs byte-identical to the working copies; the saves archive holds all 156 `data.json` files.

## 8. Limitations and caveats

- **Not an official score.** The loose Eval2 count omits the `m2014_q3` exception. Official numbers must come from the frozen evaluator (`dirtb/evaluate.py` and ConfiBench's own analysis).
- **Coverage is not quality.** 156 records include failures and missing fields; this is not 156 passes, and it is not pass@1.
- **Regenerated in-flight work:** up to 2 in-flight responses were lost at each of the 3 interruptions and generated again, as the protocol allows. No completed response was regenerated and no scored failure was rerun.
- **Orphan cleanup may shift timing.** Kaggle runs kept abandoned simulators running, which used CPU. Removing them could change timing near the 40 s simulation timeout; the size of that effect was not measured.
- **Response count is derived.** "About 2,140" comes from journal sizes for the 16 tasks (986 at handoff, 3,126 at the end), not from a per-call log.
- **Not yet analysed:** no development/test split, no statistical analysis and no DRTB comparison has been done.

## 9. Results bundle and disk cleanup

The full results bundle is on the desktop at `C:\BIRDI_desktop_results` (87 MB, plus this report):

- `desktop_final_audit.json` and `desktop_task_results.csv`: the audit and per-task results for all 156 tasks
- `checkpoints/`: `desktop_saves.zip` (all first records), `desktop_runtime.zip` (all response journals), completion, engine and provenance JSON, `desktop_reaped.log`
- `logs/`: every worker log, the model server log, CPU replay logs and the container logs of all sessions
- `confibench_saves.tar.gz`: the complete ConfiBench save tree
- `runner_amendments.patch`: the Section 6 code changes
- `SHA256SUMS`

Disk space used by the testing was freed after the bundle was verified:

| Item | Freed |
| --- | --- |
| Ubuntu working copy (clone, 15.6 GB model, llama.cpp runtime, ConfiBench work files) | about 23 GB inside Ubuntu |
| Docker images (`birdi-resume`, `ubuntu:24.04`) and build cache | about 2 GB |
| Ubuntu disk file compacted (351.6 GB to 104.1 GB) | 247.5 GB on drive G: |
| Docker data disk compacted (3.5 GB to 1.8 GB) | 1.7 GB on drive C: |

Ubuntu is back to 103 GB used, the same as before testing. Docker Desktop and Git for Windows stay installed, and the Ubuntu distro now lives at `G:\wsl\ubuntu2404`.

## 10. Next steps

1. Score all 156 records with the frozen evaluator, including the `m2014_q3` exception, separately for the 60 development and 96 test tasks.
2. Run the frozen DRTB `unanimity` evaluation on the existing candidate pool, without regenerating candidates or retuning on held-out data.
3. Compare DRTB with this equal-model ConfiBench baseline: Eval1, Eval2, missed and falsely rejected mutants, abstention, compile failures, per task and by CMB/SEQ.
4. Compute paired wins, ties and losses with task-level uncertainty.
5. Commit the Section 6 runner amendments with this disclosure, and update the supervisor report with dated measurements.
