# ConfiBench Recovery and Resume Audit

Date: 2026-10-04, Asia/Dhaka.

## Verified Outcome

- Ten October 3 notebooks ended; only two additional final task records appeared.
- Canonical audited task-record coverage remains 138/156. Eighteen tasks are unresolved.
- Kernel logs total approximately 110.22 notebook-session hours, including setup.
  This is not a billing statement or a count of individual GPU-device hours.
- All ten partial archives, completion manifests, and worker logs have been
  downloaded locally. ZIP CRCs and file SHA-256 hashes were checked.
- This audit and all local tests launched zero GPU jobs.

## Execution Failure

The previous launcher could skip completed tasks but could not restore execution
inside an unfinished task. A final `data.json` was required for task-level resume.
Repeated attempts therefore regenerated previous expensive model work. Periodic
compact archives and bounded partial diagnostics did not provide resumable state.
The ten-way wave was launched without a demonstrated interruption/resume pilot.

These are execution-design failures, not evidence that 18 benchmark tasks passed
or that ten successful notebook statuses imply complete benchmark coverage.

Example: `ece241_2014_q4` logged ten generation iterations and twenty correction
attempts. Recorded generation-stage durations total about 3.69 hours; correction
durations total about 6.40 hours. Stage timings exclude other work and unfinished
calls, so they must not be summed into a complete billing estimate.

## Recovered Material

`recovery_audit.json` records local paths, file hashes, completion manifests,
per-task iteration/correction counts, and last logged activity.

`legacy_runtime_v2.zip` contains replay banks for all 18 unfinished tasks:

- 1,005 candidate saved model responses, including generation, correction,
  simulation-debug, and reboot-stage conversations.
- Fifteen tasks have a frozen, first-saved 20-candidate RTL population.
- No golden evaluation score was used to choose a population or response.
- Truncated, empty, or ambiguous conversations are excluded and documented.
- Old iteration state is NOT guessed or reconstructed from text logs.
- Old token counts are unavailable in these transcripts. Replayed legacy entries
  carry `usage_unavailable: true`; their zero usage placeholders must not be
  reported as zero historical token consumption or used for fair cost comparisons.

Exact replay of four actual upstream prompt stages was validated for every task:
72 prompt-builder/adapter calls total, with zero fresh model calls. This validates
only those sampled stages, not all 1,005 candidates or whole-task simulation.
`circuit10` lacks a first-iteration stage0 transcript; its prompt validation used
the earliest saved iteration, iteration 2. The missing iteration is not skipped
in a benchmark run merely because its transcript is unavailable.

## New Resume Implementation

`confibench_resume.py` provides:

1. Per-task contract hashes binding checkpoints to the model/configuration and
   complete problem input.
2. Per-call response journals. A completed response is fsynced and atomically
   committed before being returned to downstream code.
3. Scope-specific ordered replay with exact request and response checksums.
4. JSON task-state checkpoints at completed iteration boundaries, preserving
   multibench entries, scenario matrices, masks, RTL population, next iteration,
   evaluation readiness, and required simulation metadata.
5. Fail-closed stopping on changed requests, corrupt records, incompatible
   contracts, or exhausted fresh-call budgets. Such failures bypass the
   upstream catch-and-reboot loop instead of silently spending more GPU time.

The bundle builder instruments a copy of the upstream task loop, not the original
baseline repository. Scoring criteria, population size, confidence threshold,
multibench acceptance rules, and iteration cap remain unchanged. The added
execution/recovery machinery must be disclosed with benchmark results.

`cbq_runtime.zip` is published atomically during the new launcher loop. New
bundles accept `--runtime-prev` and `--max-fresh-calls`. Final records and runtime
checkpoints are separate artifacts. No checkpoint of an in-flight HTTP request
is claimed: a response interrupted before commit can still be lost.

JSON snapshots avoid executable pickle deserialization. Raw saved-response
journals and iteration checkpoints are used instead of outcome-based reruns.

## Local Verification

Six CPU-only unit tests pass:

- Force-terminate a child process after response commit, then replay with no
  provider call.
- Interrupt the actual upstream loop mid-iteration, restore its prior boundary,
  and obtain the same final code/multibench state as an uninterrupted mock run.
- Restore an acceptance/break boundary directly at evaluation.
- Stop on changed profile/problem/request, tampered response, and fresh-call cap.
- Preserve NumPy matrix dtype and values across JSON serialization.
- Recover exact transcript whitespace and replay with a zero fresh-call budget.

The separate notebook-checkpoint publication test passes: malformed final records
are excluded, failed results retained, and compact archive replacement verified.
Notebook cells compile; dataset ZIP members use forward-slash paths.

These local tests use controlled model responses and simulation stubs. The
subsequent CPU pilots below also exercised the actual upstream pipeline on
Kaggle Linux. No GPU throughput improvement or successful completion of the
remaining 18 tasks is claimed.

## Bounded CPU-Only Pilot

Staged bundle: `new_implementation/kaggle_upload_cbq-replay-cpu-oct4`.

- Task: `ece241_2014_q4`, only one task.
- `enable_gpu: false`; no llama.cpp build or model download.
- `CBQ_MAX_FRESH_CALLS=0`, prohibiting fresh generation.
- First phase: replay saved responses, then terminate the worker process group.
- Second phase: restart against the same journals and verify saved responses
  remain unchanged. Simulation may rerun; model generation must not.
- Phases are bounded to 180 and 300 seconds, excluding bounded setup.
- Pilot artifacts are validation evidence, not scored benchmark submissions.

Initial publication was blocked by the permissions reviewer because the payload
includes private recovered model responses. The user subsequently gave explicit
approval; the private dataset and CPU-only notebook were then published and run.
The approval is recorded in `CPU_PILOT_APPROVAL.md`; results follow below.

## Launch Hold and Next Gate

`GPU_LAUNCH_HOLD` prevents automatic ConfiBench GPU retries and is checked by the
shared push command. Existing result collection remains allowed. No broad GPU
wave should resume before the CPU pilot has been inspected, missing replay scopes
understood, and a single capped fresh-generation pilot demonstrates durable resume.

Only then should unfinished tasks be assigned disjointly with verified runtime
archives attached. Do not repeat this experiment from the final-record archive
alone or represent the 1,005 recovered response candidates as finished tasks.

## Approved CPU Pilot: Version 1 Results

The user subsequently approved publication and execution. The private dataset
and CPU-only notebook were submitted successfully under `tishaferdous`. The
actual notebook slug is `confibench-cpu-only-interruption-replay-validation`.

Version 1 ended and its report, runtime ZIP, and two phase logs were downloaded:

- Phase 1 replayed four responses, then its worker process group was terminated.
- Phase 2 restarted and replayed 108 saved responses with zero fresh model calls.
- The already-committed response files remained byte-identical after restart.
- The actual upstream Linux pipeline completed nine iteration boundaries,
  saving eight multibench entries and valid-ratio sum 0.9761904761904762.
- It stopped intentionally at missing scope `9:TBgen:stage:stage_4:10_1_TBgen`,
  call 0. The worker exit code was 1 due to `BudgetStop`, not successful task
  completion. The enclosing notebook status was COMPLETE.
- No final `data.json` exists; canonical task coverage stays 138/156.
- No model was downloaded and no GPU job was launched.

Original version-1 artifacts remain in
`new_implementation/kaggle_runs/cbq_cpu_resume_oct4/`.

## Approved CPU Pilot: Version 2 Results

Version 2 also reached notebook status COMPLETE. Its downloaded report and both
worker logs confirm restoration from the version-1 iteration checkpoint:

- Both phases logged `next_iteration=9` (zero-based): nine completed iterations
  were skipped and execution resumed at iteration 10.
- Each phase replayed only four saved responses from the unfinished prefix.
- The restart preserved the committed response files byte-for-byte.
- The second worker stopped intentionally with `BudgetStop` at the first missing
  response, scope `9:TBgen:stage:stage_4:10_1_TBgen`, call 0.
- `iteration_boundary_restore_verified=true`; fresh model calls were zero,
  no model was downloaded, and GPU execution was disabled.
- `full_task_completed=false`. Worker exit code 1 is expected for the enforced
  zero-fresh-call cap; notebook COMPLETE is not benchmark task completion.

Evidence: `new_implementation/kaggle_runs/cbq_cpu_resume_oct4_v2/`, including
`cpu_resume_report.json`, `cpu_phase1.log`, `cpu_phase2.log`, and
`cpu_runtime.zip`. Canonical coverage remains 138/156 records, with 18 unresolved.
This validates recovery on one actual task, not all remaining tasks or GPU
generation throughput. The GPU launch hold remains in place; the next gate is
one explicitly capped fresh-generation pilot using the verified runtime archive.
