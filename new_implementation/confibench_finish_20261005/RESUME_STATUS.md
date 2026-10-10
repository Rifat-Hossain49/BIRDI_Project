# ConfiBench-Qwen Completion: October 5

## Latest Continuation: 7 October, 15:16 Bangladesh

**140/156 first records; 16 unresolved.** All 16 latest checkpoints passed strict
CPU replay with zero fresh model responses. The `circuit10` traceback-directory
conflict was corrected by restoring its recorded execution path, not by changing
prompts or regenerated responses. All 138 original records remain byte-identical.

Two GPU continuations were accepted on account 7, `sahanzparvintopy`, but both
failed in their first cell because Kaggle allocated CPU only (`nvidia-smi` absent).
A hardware-only probe with an explicit T4 request also received zero GPUs.
No model was downloaded or started; the account still reports **30.00 GPU hours
available, 0.00 used**. Account 7 is now on a hardware-allocation hold, alongside
the existing account-3 quarantine. Other authorized accounts remain below the
safe launch budget. No remote model job or local controller is running.

**38 regression tests passed.** Logs, quotas, strict CPU recovery proof and
unchanged input checkpoints are saved. GPU availability must be verified in the
new account's notebook settings before continuation. The platform/account cause
is not established; phone verification is a possible requirement to check, not a
proven diagnosis. See [CONTINUATION_HANDOFF_20261007.md](CONTINUATION_HANDOFF_20261007.md)
for the authoritative current handoff and exact resume requirements. Sections
below are retained historical observations, not current execution status.

## Extra GPU Account: 7 October

Registered account 7, `sahanzparvintopy`, after verifying its token identity and
**30.00 GPU-hours** through Kaggle's API. Twenty-six offline tests passed.
No new GPU job has launched: latest-checkpoint CPU replay is staged and still
awaits explicit approval for the private export. Coverage remains 140/156 records,
with 16 unresolved. The account-3 quarantine and first-record policy are unchanged.

## Deadline Safety Audit: 7 October

Coverage remains 140/156 first task records, with 16 unresolved. No GPU job was
launched. Latest-checkpoint CPU replay is staged with zero fresh model calls,
but its private upload was blocked pending approval for this exact bundle.
Twenty-two regression tests passed. Live remaining quota is 7.24 GPU-session
hours in total, including 3.77 on the quarantined account; none of the other
accounts meets the current safe launch minimum. GPU continuation remains off.
See `NO_WASTE_RESUME_PLAN_20261007.md` for the verified resource inventory,
replay safeguards and execution plan. The staged notebook has not run yet.

## Latest Inspection: 7 October, 12:08 Bangladesh

The three round-4 Kaggle notebooks are COMPLETE. Their outputs have been
downloaded and audited, with no new checkpoint-integrity conflicts. They saved
64 fresh task responses and one first final record, `ece241_2013_q4`.
Canonical coverage is now **140/156 first task records; 16 remain unresolved**.
Task-record coverage includes failures and is not a pass count. All 138 original
records remain byte-identical. Runtime journals for unfinished tasks are retained.

There are **no active jobs** in this completion run. The local controller PID
38332 is absent; its last recorded poll was 6 October at 09:28 UTC. The exact
termination time/cause is unknown. Its original 6 October 18:33 UTC deadline has
elapsed. Controller and automatic-launch metadata have been reconciled to
stopped/off; no window extension or new GPU launch occurred during inspection.
Older sections below are dated history, not current live status.

## Current Resume Safeguards: 6 October

Four round-3 jobs are RUNNING on accounts 1, 2, 4 and 5, covering eight unfinished
tasks. Account 3's submission and its single capped retry both ended ERROR with
empty `[]` kernel logs, no execution archives, and no API failure explanation.
The cause is unknown; the absence of artifacts is not proof of zero model calls.
Both failures remain in the launch manifest with their original audit errors.

Account 3 is disabled for new submissions pending investigation. Its two assigned
tasks remain unresolved, using their prior audited checkpoints; they are not
marked completed or failed benchmark outcomes. Operator-reviewed quarantine is
limited to terminal missing-artifact jobs with verified empty-log and unchanged
runtime hashes. It never bypasses a request/checksum conflict or accepts a scored
result. The other four accounts can continue normally after collection/audit.

The local controller was restored without extending its 6 October 18:33 UTC
deadline (7 October 00:33 Bangladesh) or resetting its launched-wave count.
Current PID: 38332; logs: `controller.oct6.resume2.stdout.log` and corresponding
stderr log. The computer must remain awake and connected for continuation.

The completion audit `completion_audit.json` now checks expected IDs, duplicates,
archive integrity and byte-identical preservation of all 138 original records.
Current coverage remains 139/156; 17 task records are missing. It also lists raw
error flags and unavailable evaluation fields. The upstream normal multibench
path does not clear `incomplete_running`; thus an `ERROR(incomplete)` flag alone
is not evidence that Eval1/Eval2 failed. Ten saved records lack one or both Boolean
evaluation outcomes; these are reported explicitly, not silently made successes
or rerun to improve the first-result baseline. No full benchmark claim is made.

Nineteen offline tests passed, including missing-artifact quarantine guards and
completion-identity/original-record checks. Failed-startup evidence, frozen model
settings, response caps and the first-record policy remain intact.

## Authorized Resume: 6 October

The user requested "okay then resume" after the prior bounded window expired.
The previous controller state was archived as `controller_history_*.json` before
opening a new window. Authorization and quota observations are recorded in
`resume_authorization_20261006.json`. No finished task record was reset.

Live quota checks found 3.26, 3.80, 3.77, 3.81 and 3.77 GPU-session hours on
accounts 1-5, respectively: **18.41 hours combined**, before the new submissions.
All 17 unresolved tasks had eligible audited runtime archives with no blocked
checkpoint. The resumed controller started at 06:33 UTC / 12:33 Bangladesh,
PID 9500, with a fresh user-authorized **12-hour / four-wave upper bound**.
It still checks actual quota before every launch and may stop earlier.

Jobs keep the existing two-task/two-worker, two-hour maximum worker budget and
16-fresh-response-per-task cap. Model, prompts, confidence rules, scoring and
checkpoint integrity checks are unchanged. One startup health request per job
is additional to the task-response cap. New tags start at round 3, so prior
datasets, kernels, logs and first records are not overwritten.

The controller collects and audits a wave before launching another. Its logs
are `controller.oct6.stdout.log` and `controller.oct6.stderr.log`; current progress
is in the JSON state files. This computer must stay awake and connected for
automatic collection and subsequent waves. Existing Kaggle jobs run remotely.
The remaining quota is not a guarantee that all 17 tasks will finish.

## Latest Inspection: 6 October, 12:29 Bangladesh

All ten submitted jobs across the two GPU waves are COMPLETE, and all their
output archives have now been downloaded and audited. No replay-integrity audit
errors were recorded. There are **no active Kaggle jobs** in this completion run.

Overall task coverage remains **139/156 first records, 17 unresolved**. Neither
wave added final task records; together they committed **228 fresh task responses**
for future resume (excluding the pilot and startup health requests). Workers
reached the configured execution/call bounds before finishing their tasks.
Partial response journals and iteration checkpoints are preserved, not counted
as completed benchmark results. Latest examples: `ece241_2013_q4` has eight
completed iteration boundaries, `review2015_fancytimer` seven, and `fsm_serial`,
`fsm_serialdata` and `vector100r` six.

The local controller process is no longer running. Its last saved poll was
5 October at 10:14 UTC; the reason its process disappeared is not established.
Its original 5 October 23:37 UTC deadline has elapsed. State has been reconciled
to `stopped` with a stop-observation timestamp, not an invented exact stop time.
Automatic-launch flags are off. No deadline, quota or wave budget was silently
extended, and no new run was launched during this status inspection.

The next execution must resume from the newly audited runtime archives. It
must not restart the tasks from scratch or treat notebook COMPLETE as a full
benchmark result. Older sections below are retained as dated audit history.

## Update: 07:32 UTC / 13:32 Bangladesh

The GPU pilot finished and passed its checkpoint audit: five fresh task responses
were durably saved, prior journals remained intact, and `ece241_2014_q4` produced
its first final task record. Canonical coverage is now **139/156 records**, with
**17 unresolved**. This is task completion, not an assertion of golden acceptance.

Five disjoint jobs in wave 1 are RUNNING across the five configured accounts,
covering ten unresolved tasks; seven other tasks await a subsequent audited wave.
The local controller stopped at 07:06 UTC after a Kaggle status-query timeout
during a DNS outage. The remote jobs were unaffected. It was restored at 07:31
UTC with its original 23:37 UTC deadline and one already-launched wave retained;
no task or GPU budget was reset and no duplicate job was submitted.

Transient status/download network failures now retry at the next poll rather
than terminating continuation or being classified as checkpoint corruption.
Fifteen offline tests passed, including restart-budget preservation. Current
controller PID: 55824; restart logs: `controller.resume1.stdout.log` and
`controller.resume1.stderr.log`. Older snapshot sections below remain as audit
history. Read the JSON state files for current status.

## Durable Status

The authoritative archive is `canonical_latest.zip` in this directory. At the
last inspected status (05:31 UTC / 11:31 Bangladesh), it contains **138 of 156
first task records**, with **18 unresolved tasks**. Records include failures;
this is not a pass count. The latest GPU pilot is still running and has not yet
produced downloadable evidence of fresh generation or a completed task.

Live local state is recorded in `monitor_state.json`, `launch_manifest.json`
and, when the controller is started, `controller_state.json`. Machine timestamps
are UTC. This document is a snapshot, not a live completion assertion.

## Recovery Evidence

- Two October 4 CPU-only forced-interruption pilots verified byte-identical
  response replay and restoration of nine completed iterations on
  `ece241_2014_q4`. They made no fresh model calls.
- The first October 5 CPU preflight attempted all other 17 tasks and replayed
  247 saved responses without downloading a model or enabling GPUs.
- Four raw historical response candidates did not match their new requests.
  They are retained but treated as cache misses, never replayed for a different
  prompt. Committed journals remain strictly request-checked and fail closed.
- Two committed-request conflicts were traced to `os.walk` file ordering:
  identical malformed Verilog produced different compiler error messages when
  compilation input ordering differed. Saved request reconstruction verified
  the old hashes; the prompt differences were compiler diagnostics, not RTL.
- Actual compiler file ordering from the first replay was recovered for 153
  directories across 11 tasks. New compiler ordering is journalled before use.
  A changed file set fails closed rather than guessing an order.
- The final CPU preflight, `cbq-replay-remaining-v3-oct5`, attempted all 17 tasks
  with zero fresh responses and **no remaining replay conflicts**. It produced
  no new final task records.

## Startup Failures and Fixes

1. `cbq-resume-gpu-oct5` stopped after its source-build deadline, approximately
   21 notebook minutes. No model download or task generation was reached.
2. Source compilation was replaced by checksum-verified official llama.cpp
   CUDA binaries, pinned to release `b11399`, commit `2ca15f540`. A CPU-only ABI
   probe verified the executable and libraries before another GPU submission.
3. `cbq-resume-gpu2-oct5` downloaded the model and started the server in about
   four minutes, but a guard incorrectly required an old offload-log string.
   It stopped before task generation. Its startup logs are retained.
4. `cbq-resume-gpu3-oct5` checks enumerated CUDA devices and measured VRAM
   allocation on both GPUs instead of relying on that log string. Its durable
   fresh-generation gate remains pending until collection and audit.

The runtime release is an execution amendment, not a scoring-method change.
Model, prompts, sampling, 20-RTL population, 10-iteration limit, confidence
threshold, multibench rules and first-record retention remain unchanged. The
release/backend difference must be disclosed in the final comparison.

## Bounded Continuation

The tested controller `../continue_resumed_finish.py` can collect and audit
finished jobs, then submit disjoint unresolved tasks using verified runtime ZIPs.
It does not bypass the fresh-generation pilot gate.

- Pilot: one task, at most eight fresh task responses, 90-minute worker budget.
- Subsequent jobs: at most two tasks/two workers per account, at most 16 fresh
  responses per task, at most two hours of worker execution.
- Each notebook additionally performs one startup JSON health-probe request.
  Future bundles cap that probe at three minutes and startup at 30 minutes.
- One kernel per configured account per wave; five accounts currently usable.
- Response journals are committed before returning results to the pipeline;
  runtime and final-record ZIPs are published atomically every minute.
- Every wave is collected before the next is scheduled. Latest audited runtime
  archives, not final-record archives alone, are attached for resume.
- Priority is fewest GPU-wave attempts, then highest completed-iteration cursor.
  No priority or retry is based on golden pass/fail scores.
- Stop conditions include checkpoint conflicts, failed/unconfirmed submission,
  a GPU job with no durable model progress, insufficient verified quota, six
  controller waves or an 18-hour controller deadline.
- A stopped controller leaves all saved checkpoints intact. Remote jobs already
  running are not cancelled automatically. Output collection remains available.

The original GPU launch hold stays present. Only exact notebook/dataset hashes
for the approved account can pass it. The old monitor delegates to the new
collector; it cannot start old non-resumable retry waves.

The controller runs on this Windows machine, which must remain awake and
connected for automatic collection and further launches. Existing remote
Kaggle jobs continue independently if the controller stops.

It was started at 05:37 UTC (11:37 Bangladesh), PID 31252, with a six-wave /
18-hour limit and five-minute polling. Its first check confirmed that the pilot
was still RUNNING, so it waited without submitting an overlapping job. Logs are
`controller.stdout.log` and `controller.stderr.log`; the latter was empty at
startup verification. Use `controller_state.json` to check its current status.

## Verification and Limits

Fourteen offline tests passed: journal replay, hard interruption, iteration
restore, request integrity, candidate-cache misses, compiler-order restoration,
exact launch approval, worker queue coverage, collector integrity and controller
stop conditions. Checkpoint compaction tests passed separately. The latest
prebuilt one-task bundle was staged locally; all notebook code cells compile.

At the initial quota inspection, the five accounts had about 39.7 combined
GPU-session hours. Quotas are queried again before each launch; they do not prove
the 18 tasks will finish within that budget. Saved partial calls are progress,
but only audited `data.json` files count toward 156 task records. Historical
token usage is unknown, not zero. No final full-benchmark or SOTA claim is made.
