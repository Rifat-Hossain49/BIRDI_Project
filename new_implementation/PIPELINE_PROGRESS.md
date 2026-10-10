# Divergence-Resolved Testbench generation (<=30B) — progress log

Goal: reach ConfiBench-level Eval1/Eval2 with open models of at most 30B, and beat
ConfiBench's own method run with the same model. Every stage has a pass/fail
criterion written before it runs; results are checkpointed here as each run lands.

## Latest Operational Status: 5 October 2026

The equal-model baseline has **138/156 first task records**, not 138 passes;
18 tasks remain unresolved. All 17 non-pilot task checkpoints pass CPU replay.
The single capped GPU resume pilot is running. A tested, bounded local controller
is monitoring it and will schedule disjoint resumed jobs only after its durable
fresh-generation audit passes. No new completion count is claimed before collection.

Authoritative state: `confibench_finish_20261005/monitor_state.json` and
`controller_state.json`. Recovery evidence, startup failures, backend amendment,
controller limits and quota uncertainty are documented in
[RESUME_STATUS.md](confibench_finish_20261005/RESUME_STATUS.md).
Older sections below are dated experiment snapshots.

## Order of work

| # | stage | pre-registration | status |
|---|---|---|---|
| 1 | Pilot 1 — localized resolution | `DLR_PREREGISTRATION.md` | running |
| 2 | Pilot 2 — diverse reading paths | `DLR2_PREREGISTRATION.md` | pending |
| 3 | Assemble pipeline, freeze on 33 dev tasks, run once on all 156 | — | pending |
| 4 | Equal-model ConfiBench baseline + mutation-adequate stimulus | — | pending |

## Checkpoints

### Checkpoint — pilots launched
- Pilot 1 (localized resolution): Kaggle `dlr-pilot-one`, 151 questions, running.
- Pilot 2 (diverse reading paths): Kaggle `dlr-pilot-two`, 6 target + 6 control tasks, running.
- Both pre-registered before generation; scorers self-tested.

### Checkpoint — evaluator validated, stimulus ceiling measured (local, dev tasks)

**Gate:** local official verdicts reproduce ConfiBench's recorded verdicts on
**520/520** mutants (100%). Our Eval1/Eval2 are on ConfiBench's exact scale (same
mutants on all 156 tasks, all mutants used, same rules).

**Calibration — golden as a perfect reference, our deterministic stimulus:**

| | Eval1 | Eval2 |
|---|---:|---:|
| combinational (20) | 1.000 | 1.000 |
| sequential (40) | 1.000 | 0.875 |
| **all (60)** | **1.000** | **0.917** |

Stimulus is **not** the main bottleneck: with correct expected values the pipeline's
ceiling (0.917) is far above ConfiBench's 0.722. Reference accuracy decides the result.

Remaining stimulus gaps (all sequential): `count_clock`, `countbcd`, `lemmings4`,
`timer` miss 2-6 mutants each (deep counters and long timers the 40-cycle random
scenarios never reach) — the target for stage 5, mutation-adequate stimulus;
`m2014_q4d` rejects 6 mutants the official testbench accepts (to investigate).

Bug found and fixed during calibration: testbench-internal identifiers (`f`, `scen`,
`step`) could collide with a design's own port names (`2013_q2bfsm` has a port `f`).
Renamed to `tb_fd_`, `tb_scen_`, `tb_step_`; the task now passes.

`m2014_q4d` resolved: not a pipeline bug. The official testbench **accepts
functionally different mutants** (mutant 7 is `out <= in`, mutant 2 is
`out <= in ^ !out`), and the 520/520 gate confirms ConfiBench saw the same verdicts.
A correct, stronger testbench disagrees with a weak official one and loses Eval2
agreement on that task. This penalises every method equally; the testbench will not
be weakened to imitate it.

### Checkpoint — stimulus frozen (dev tasks, golden as perfect reference)

| stimulus | Eval1 | Eval2 | missed | false rejects |
|---|---:|---:|---:|---:|
| random scenarios (8 x 40 cycles) | 1.000 | 0.917 | 19 | 7 |
| **+ long constant-input runs, cost-budgeted** | **1.000** | **0.967** | **6** | **7** |

Long runs fixed `count_clock`, `countbcd`, `timer` (and `fsm_serial`'s one miss) with
no regressions. The only remaining failures are `lemmings4` (2 missed) and
`m2014_q4d` (weak official testbench). A first attempt without a cost budget made
`conwaylife` (256-bit grid) exceed the evaluator timeout, producing a spurious Eval1
failure; the generic budget (total observed bits across long runs capped at 4M)
removed it while leaving narrow designs at full length.

**Frozen:** `build_driver(..., marathons=True)` with the cost budget; evaluator
simulation timeout 300 s. Stimulus is no longer the bottleneck — the pipeline ceiling
with a perfect reference is 0.967 against ConfiBench's 0.722.

### Checkpoint — first end-to-end pipeline run (dev, 33 tasks with Qwen designs)

Qwen3.5-27B designs from the (incomplete) J1b sampling, frozen stimulus, plain
plurality resolution, ConfiBench-exact scoring. No localized questions, no checklist.

| | pipeline Eval1 | pipeline Eval2 | ConfiBench-4o Eval1 | ConfiBench-4o Eval2 |
|---|---:|---:|---:|---:|
| CMB (10) | 0.800 | 0.800 | 0.867 | 0.800 |
| SEQ (23) | 0.478 | 0.435 | 0.884 | 0.435 |
| **ALL (33)** | **0.576** | **0.545** | **0.879** | **0.545** |

**Eval2 ties ConfiBench-4o with a 27B open model; Eval1 is far behind.** When the
reference is right, Eval2 almost always follows (18 of 19), because the stimulus is
strong. The gap is reference accuracy, and the pool is thin: J1b never finished, so 3
tasks had no compiling design and many had only 1-2.

Caveats: these 33 tasks were selected as ConfiBench's weak spots (it scores 0.545 here
against 0.722 overall), so this is not representative; only the frozen run on all 156
counts. Slow tasks (`ece241_2014_q5a` 424 s, `ece241_2013_q2` 284 s, `circuit2` 217 s)
are candidates that hang until the 300 s timeout — a cost issue to fix before the
Kaggle-scale run.

### Checkpoint — full generation launched across three accounts

Frozen generation config (direct path, 5 designs per task, thinking on, budget forcing
at 8000 reasoning + 3000 answer tokens), sharded 52/52/52 over all 156 tasks.

| shard | account | status |
|---|---|---|
| 0 | tishaferdous | queued — auto-launches when a pilot frees a GPU slot (2-session cap per account) |
| 1 | shellshocker | running |
| 2 | rifathosain | running |

Tooling fix: the account-rotation push reported success when Kaggle had refused the
job ("Maximum batch GPU session count of 2 reached"); it now fails loudly unless
Kaggle confirms the push.

### Checkpoint — pilots scored (2026-09-14)

**Pilot 2 (diverse reading paths, checklist prompt): NO-GO** under the frozen rule.

| target | shared-misreading scenarios | fixed by checklist | exposed by mixed pool |
|---|---:|---:|---:|
| ece241_2014_q4 | 186 | 130 (70%) FIXED | 179 (96%) |
| circuit8 | 180 | 0 (0%) | 0 (0%) |
| ece241_2013_q4 | 34 | 29 (85%) FIXED | 34 (100%) |
| edgecapture | 7 | 0 | 0 |
| fsm_ps2 | 6 | 2 (33%) | 6 (100%) |
| counter_2bc | 1 | 0 | 0 |

2/6 targets fixed (needed 3); control accuracy 0.890 -> 0.866 (-2.4 pts, within guard).
Secondary: mixed-pool majority 0.573 vs direct 0.603 on all 12 tasks. The checklist path
is **not** added to the pipeline. Exploratory note only (does not decide): where it
helps, the mixed pool turns a unanimous misreading into a disagreement on 96-100% of
scenarios, which is exactly what localized resolution needs; circuit8 (waveform reading)
is untouched by any prompt change.

**Pilot 1 (localized resolution): INCOMPLETE, no valid decision.** The thinking pass
answered 120/151 within the 10.5 h session; 98 of those 120 hit the 8000-token cap before
writing an answer, and the 256-token direct pass never answered. Pipeline accuracy on the
answered 120: 0.758 vs majority 0.733 (CI [-0.035, +0.099]); select-recoverable bucket
0.457 vs 0.314. Fix registered before rerun as **DLR Amendment 1**: budget forcing at the
same 8000-token cap, same prompt/sampling/criterion, all 151 re-asked, split across two
sessions. Verified locally against a mock server (natural / forced / continued paths,
resume, scorer format).

### Checkpoint — jobs running (2026-09-14)

| job | account | notes |
|---|---|---|
| gen shard 0 (52 tasks) | tishaferdous | first session |
| gen shard 1 resume | shellshocker | 159/260 samples carried forward |
| gen shard 2 resume | rifathosain | 224/260 samples carried forward |
| DLR forced shard 0 (75 q) | rifathosain | circuit4, circuit9, countbcd, ece241_2014_q3, fsm_serial |
| DLR forced shard 1 (76 q) | shellshocker | circuit7, ece241_2013_q4, ece241_2014_q5b, fsm2, fsm_ps2, gatesv100 |

Quota note: tishaferdous already ran both pilots (~22 GPU-h) this week before shard 0.

### Checkpoint — interim end-to-end, partial Stage 3 candidates (dev, 33 tasks)

Budget-forced Qwen3.5-27B designs from shards 1-2 first sessions (5 per task), frozen
stimulus, plain plurality, ConfiBench-exact scoring. Interim only: generation is not
finished and the frozen run on all 156 is the one that counts.

| | pipeline Eval1 | pipeline Eval2 | ConfiBench-4o Eval1 | ConfiBench-4o Eval2 |
|---|---:|---:|---:|---:|
| CMB (11) | 0.818 | 0.818 | 0.818 | 0.636 |
| SEQ (22) | 0.364 | 0.318 | 0.894 | 0.455 |
| **ALL (33)** | **0.515** | **0.485** | **0.869** | **0.515** |

CMB already beats ConfiBench-4o on Eval2 (0.818 vs 0.636). SEQ Eval1 is the whole gap.
Oracle-ceiling diagnostic (resolution-limited vs generation-limited) running next.

### Checkpoint — oracle ceiling on the interim candidates (dev, 33 tasks)

Same 33 tasks, candidates, driver and units as the interim run; golden used only as a
diagnostic on dev (`dirtb/oracle_ceiling.py`, `dirtb/oracle_s3partial_dev.json`).

| | plurality | perfect resolver over the 5 candidates | best single candidate | ConfiBench-4o Eval1 |
|---|---:|---:|---:|---:|
| CMB (11) | 0.818 | 0.818 | 0.818 | 0.818 |
| SEQ (22) | 0.364 | **0.500** | 0.500 | 0.894 |
| ALL (33) | 0.515 | 0.606 | 0.606 | 0.869 |

Units: unanimous-right 97, plurality-right 57, select-recoverable 15, **none-right 60**.

**Finding: resolution is not the binding constraint; candidate correctness is.** A perfect
resolver adds only 3 tasks (edgecapture, lemmings3, review2015_shiftcount). 11/22 SEQ tasks
have at least one unit where no candidate is right (fsm_ps2, fsm_ps2data, fsm_serialdata,
gshare, 2014_q3fsm, count_clock, circuit8, circuit9, rule110, lemmings4, 2013_q2bfsm).
ConfiBench-4o reaches 0.894 SEQ Eval1 not by being right but by masking uncertain scenarios
(at an Eval2 cost: 0.455). Next: evaluate *disagreement-scoped abstention* on dev -- mark
outputs don't-care only where the candidate pool disagrees, keep every agreed observation
as a check -- against plurality, with ConfiBench-exact Eval1/Eval2.

### Checkpoint — equal-model ConfiBench baseline prepared (not yet launched)

`BASELINE_CONFIBENCH_QWEN.md` freezes the settings; `prepare_confibench_qwen.py` builds two
78-task bundles (`kaggle_upload_cbq{0,1}of2`, 5.4 MB each). Smoke-tested locally against a
mock server. Launches as soon as two GPU slots free up (all accounts currently busy).

### Checkpoint — consensus-scoped abstention (dev, 33 tasks, interim candidates)

`dirtb/abstain_policies.py` -> `dirtb/abstain_s3partial_dev.json`. Same candidates, driver
and scoring as the interim run. Policy **unanimity** (`vote@1.0`, identical to `classX@1.0`
on every task): an output bit is checked only where every simulated candidate agrees;
elsewhere it is don't-care. No golden, mutant or official information enters the reference.

| policy | CMB Eval1 / Eval2 | SEQ Eval1 / Eval2 | ALL Eval1 / Eval2 | bits don't-care | missed | false-reject |
|---|---|---|---|---:|---:|---:|
| plurality | 0.818 / 0.818 | 0.364 / 0.318 | 0.515 / 0.485 | 0.0% | 11 | 27 |
| vote@0.6 | 0.909 / 0.909 | 0.409 / 0.364 | 0.576 / 0.545 | 4.0% | 11 | 23 |
| vote@0.8 | 0.909 / 0.909 | 0.500 / 0.455 | 0.636 / 0.606 | 7.2% | 13 | 23 |
| **unanimity** | **0.909 / 0.909** | **0.591 / 0.545** | **0.697 / 0.667** | 10.4% | 13 | 22 |
| tail@1.0 | 0.909 / 0.818 | 0.636 / 0.364 | 0.727 / 0.515 | 40.8% | 47 | 21 |
| *ConfiBench-4o* | *0.818 / 0.636* | *0.894 / 0.455* | *0.869 / 0.515* | | | |

- Unanimity vs plurality, per task: **+6 / -0 on Eval1 and on Eval2** (one-sided sign test
  p = 0.016): 2013_q2bfsm, count_clock, ece241_2013_q2, edgecapture, lemmings3,
  review2015_shiftcount.
- Unanimity vs ConfiBench-4o (3-run average) on these 33 tasks: **Eval2 +0.152** (higher on 8
  tasks, lower on 4); Eval1 -0.172 (higher on 5, lower on 10).
- Row-scoped abstention is the right granularity: abstaining from the first divergence to the
  end of the unit (tail) passes more goldens but misses 47 mutants -- the same trade ConfiBench's
  scenario masks make.
- Remaining Eval1 losses are **unanimous misreadings** (all candidates agree and are wrong):
  fsm_ps2, fsm_ps2data, fsm_serialdata, gshare, rule110, lemmings4, circuit8, 2014_q3fsm,
  ece241_2014_q3, circuit9. Abstention cannot see these; only disagreement can expose them.
- ece241_2014_q4 is 100% don't-care under every policy: no reset, so X propagates in golden and
  in every candidate; Eval1 passes vacuously and Eval2 fails. Not tuned for.

Caveats: interim candidates, 33 of 60 dev tasks (ConfiBench's weak spots), policy chosen on
dev with golden. Only the frozen run on all 156, reported dev and held-out test separately,
counts.

### Checkpoint — does a larger candidate pool help abstention? (dev, 23 tasks)

The 23 dev tasks that have both interim Stage 3 designs and J1b designs (same model, same
prompt; J1b without budget forcing). Unanimity policy, ConfiBench-exact scoring.

| candidates (per task) | ALL Eval1 / Eval2 | SEQ (16) Eval1 / Eval2 | bits don't-care | missed |
|---|---|---|---:|---:|
| Stage 3 only (<=5) | 0.652 / 0.609 | 0.562 / 0.500 | 11.3% | 11 |
| J1b only (<=5) | 0.565 / 0.522 | 0.500 / 0.438 | 18.5% | 9 |
| **pooled (<=10)** | **0.739 / 0.652** | **0.688 / 0.562** | 13.1% | 15 |
| *ConfiBench-4o* | *0.884 / 0.507* | *0.917 / 0.417* | | |

Pooled vs Stage 3 only: Eval1 +2 / -0 (circuit9, fsm_ps2 -- both unanimous misreadings at
5 designs that a 6th-10th design contradicts); Eval2 +2 / -1 (fsm_hdlc: 2 designs that
disagree hide a check that 1 design kept).

**Decision (dev-only evidence, before any test-split run): freeze N = 10 designs per task.**
More designs turn unanimous misreadings into disagreements, which abstention then removes;
the don't-care fraction rises only 11% -> 13%. Cost: a second Stage 3 round of 5 designs
per task on all 156 tasks (same frozen generator, sample indices 5-9), ~35 GPU-h.

### Checkpoint — generation shard 2 complete (round 1, N = 5)

`kaggle_runs/s3gen2b/gen_samples.jsonl`: 260/260 samples, 257 with a module, 52/52 tasks
(natural 213, forced 44, continued 3), no duplicate keys. Round 2 (sample indices 5-9) for
these tasks launched as 6-way shards 2 and 5; shard 2of6 on rifathosain with generation capped
at 4.5 h to stay inside the account's weekly GPU quota (resumable).

### Checkpoint — frozen-run tooling verified

- `dirtb/run_pipeline.py --policy unanimity` reproduces `abstain_policies.py` vote@1.0 exactly on
  the 33 interim dev tasks (0 per-task differences; ALL Eval1 0.697 / Eval2 0.667).
- Fixed a latent bug in `run_pipeline.py`: the reference template was the first simulated
  candidate even when its row count differed from the grouped majority; it is now a trace with
  the grouped row count.
- `dirtb/merge_samples.py` merges every session and round keyed by (task, path, sample index),
  preferring rows with a module, and reports per-task coverage. On the finished files: 643 rows
  -> 419 unique samples (shard 2 complete 260 + shard 1 first session 159), consistent with the
  sessions still running.

### Checkpoint - completed jobs fetched and preregistered DLR scored (2026-09-15)

- Round-one generation: shard 1 and shard 2 are complete; shard 0 preserved 219/260 rows.
  The deduplicated first-round pool has 739/780 samples, 731 with RTL, across 147/156 complete
  tasks. The 41 missing rows all belong to shard 0 and will be filled by the N=10 continuation.
- The first N=10 continuation contributed 79 new unique designs. The current merged pool has
  818/1560 samples and 808 extracted RTL modules.
- DLR forced rerun: 151/151 questions answered, 34 abstentions. Pipeline accuracy 0.6623 versus
  majority 0.7815; delta -0.1192 with task-clustered 95% CI [-0.2727, +0.0286]. This is a
  preregistered **NO-GO**. DLR is excluded from the frozen winning path.
- `prepare_stage3_gen.py` now filters resume rows to each shard and rejects duplicate
  `(task_id, path, sample_idx)` keys before publishing a shard payload.
- Remaining N=10 work by six-way shard: 0=150, 1=130, 2=51, 3=151, 4=130, 5=130 samples.
  Accounts 1 and 3 have reached their current weekly GPU quota. Shards 3 and 4 are running in
  parallel on account 2; shards 0, 1, 2, and 5 are staged locally for the next free/reset slots.

### Checkpoint - N=10 generation resumed after quota reset (2026-09-19)

- Shards 3 and 4 completed on account 2 with 260/260 rows each, no duplicate keys, and 259
  extracted RTL modules each.
- The merged N=10 pool now contains 1099/1560 unique samples and 1089 RTL modules. Exactly
  67/156 tasks have all ten samples. Remaining work: shard 0=150, shard 1=130, shard 2=51,
  shard 5=130 samples.
- All remaining work is now running: shard 0 and shard 5 on account 1, shard 2 on account 2,
  and shard 1 on account 3.
- The equal-model ConfiBench baseline bundle was rebuilt after excluding a stale read-only
  `.git` directory; its archive contains no API key or repository metadata. Baseline shard 0/2
  is running in account 3's second GPU slot.
- `dirtb/kaggle_rotate.py` now permits ephemeral process-environment credentials to override
  the file while still keeping secrets out of logs and generated artifacts.

### Scheduling change - account 2 retired (2026-09-19)

Per user instruction, account 2 is disabled for every future dataset/kernel push. The helper
enforces this with `DISABLED_PUSH_ACCOUNTS = {2}`. Its already-running short shard 2 cannot be
cancelled through the installed Kaggle API, so status/fetch remain permitted only to recover
that final checkpoint. All subsequent generation and baseline work will use accounts 1 and 3.

### Checkpoint - account 2 run manually canceled (2026-09-19)

- The user manually stopped `shellshocker/stage3-gen-shard-2-of-6-n10` and account 2 is no
  longer available to the local scheduler. No new work will be submitted there.
- Its final log reached 40/51 newly generated rows, but cancellation happened before
  `stage3_gen_results.zip` was written. The output API exposed only the log, so those 40
  unarchived rows are not treated as recovered data.
- The latest durable shard-2 checkpoint remains 209/260 rows in
  `kaggle_runs/s3gen2_round2_complete/extracted/gen_samples.jsonl`; all 51 missing rows will
  be rescheduled on account 1 or 3 after a slot becomes free.
- Surviving status check: generation shards 0 and 5 are running on account 1; generation
  shard 1 and equal-model ConfiBench shard 0 are running on account 3.

### Checkpoint - accounts 1 and 3 completed; final work relaunched (2026-09-19)

- Generation shards 0, 1, and 5 completed and their archives were downloaded and validated.
  Merging them with the prior durable pool produced 1509/1560 unique samples, 1495 with
  extracted RTL, 145/156 tasks complete at N=10, and no task without an RTL module.
- Equal-model ConfiBench shard 0 completed all 78/78 assigned tasks; `cbq_saves.zip` was
  downloaded and extracted locally.
- The old ConfiBench shard-1 payload was rejected during preflight because it contained a
  stale `.git` tree. It was rebuilt with the hardened packager and re-audited: zero Git
  metadata, zero credential-bearing files, empty API configuration, and all cells compile.
- The remaining 51 generation samples from shard 2 were rebuilt from the 1509-row merged
  checkpoint and launched on account 1. Equal-model ConfiBench shard 1 was launched on
  account 3. Current states: generation recovery `RUNNING`, ConfiBench shard 1 `QUEUED`.
- Account 2 remains disabled and was not used for either launch.

### Checkpoint - equal-model baseline adapter failure found and corrected (2026-09-19)

- Inspection of completed ConfiBench shard 0 found 78/78 `data.json` files but zero tasks
  reaching Eval1/Eval2. Every task failed at ConfiBench's first JSON stage with llama.cpp
  HTTP 400 `Failed to initialize samplers: std::exception`; therefore the apparent zero
  score is an invalid integration run and must not be reported as a method result.
- Root cause: the Qwen adapter requested llama.cpp grammar-constrained JSON. The adapter now
  preserves ConfiBench's JSON semantics using an explicit JSON-only prompt constraint, matching
  the repository's non-OpenAI fallback style, without the incompatible server grammar.
- Added a live JSON request/parse smoke test before task execution and compilation of every
  copied Python source during bundle construction. This also caught and fixed an escaped-newline
  syntax error before upload.
- Both corrected bundles passed preflight: generated sources compile, no `.git` metadata, and
  no credential-bearing files. Corrected shard 1 is running on account 1; corrected shard 0 is
  running on account 3. The older account-3 shard-1 run uses the broken adapter and is excluded.
- The final 51-sample candidate-generation recovery remains running on account 1. Account 2
  remains disabled.

### Checkpoint - N=10 generation complete; baseline preflight corrected (2026-09-20)

- The final generation recovery completed and was downloaded. The frozen candidate pool now
  contains exactly 1560/1560 unique samples (10 per task for all 156 tasks), 1545 with an
  extracted RTL module, and zero tasks without a usable RTL candidate.
- The first prompt-JSON baseline replacements stopped before task execution because the new
  smoke test imported ConfiBench from `/kaggle/working`; its import-time manager resolves the
  empty `config/key_API.json` relative to the ConfiBench directory. No baseline task output
  from these failed versions is used.
- The smoke test now temporarily changes to the ConfiBench project directory, performs the
  live JSON request and parse, and restores the original directory. Bundle construction also
  compiles every copied Python source.
- Corrected ConfiBench shard 1 version 2 is running on account 1 and corrected shard 0 version
  3 is running on account 3. Account 2 remains disabled.

### Checkpoint - corrected baseline sessions preserved and repartitioned (2026-09-20)

- Both corrected two-way sessions completed with `JSON_MODE_SMOKE_OK`. Their resumable
  archives preserve 14 unique task artifacts (4 from old shard 0 and 10 from old shard 1).
  Thirteen have `Eval1_pass` and twelve pass loose Eval2, but every artifact retains
  ConfiBench's incomplete flag, so these are progress diagnostics rather than final scores.
- ConfiBench-Qwen is substantially slower than candidate generation: a 10.5-hour session
  advanced only 4 or 10 tasks. To reduce restart loss and stragglers, the remaining work was
  repartitioned into four 39-task resume shards. This is scheduling-only: model, prompts,
  ten-iteration limit, RTL population, testbench selection, and scoring remain frozen.
- Restored eight llama-server slots at 131k aggregate context (16k per independent stage call)
  to improve task throughput on T4 x2. All four resume bundles compile, contain their prior
  checkpoint, and have clean archive paths.
- Account 1 is running resume shards 0/4 and 1/4. Account 3 rejected shards 2/4 and 3/4 after
  reaching its 30-hour weekly GPU quota; both are staged locally for the next eligible slot.
  Account 2 remains disabled.

### Scheduling update - replacement account 2 activated (2026-09-20)

- The user supplied a new second-account credential. Kaggle token introspection verified its
  owner as `naimahjyoti`; the retired `shellshocker` mapping was replaced without persisting
  or logging the token in any artifact.
- Account 3 (`rifathosain`) remains exhausted for this round. Resume shards 2/4 and 3/4 were
  launched on `naimahjyoti`; shards 0/4 and 1/4 continue on `tishaferdous`.
- All four repartitioned ConfiBench-Qwen resume shards are currently `RUNNING`.

### Checkpoint - disk/context hardening and four-shard relaunch (2026-09-21)

- Wave-1 shards 0/4 and 1/4 completed on account 1 and each preserved nine
  `data.json` task checkpoints. Account 1 then reached its weekly GPU quota.
- Wave-1 shard 2/4 stopped after its eight-server layout exhausted disk and one
  request exceeded the 16,384-token per-slot context. Nine completed task
  checkpoints were recovered before relaunch.
- Wave-1 shard 3/4 was canceled, but eleven completed task checkpoints were
  recovered and validated before relaunch.
- The resume runner now uses four server slots at the 131,072 aggregate context
  tier (32k context per slot), removes llama.cpp build artifacts after startup,
  and periodically compacts completed task directories while retaining scoring
  and diagnostic files.
- A verified backup account (`arafhossainazim`) was registered as scheduler
  account 4. No credential value is stored in generated bundles or logs.
- Current live state: optimized resume shards 0/4 and 1/4 are `RUNNING` on
  account 4; optimized shards 2/4 and 3/4 are `RUNNING` on account 2. The frozen
  156-task candidate pool remains complete at 1,560/1,560 samples.

### Checkpoint - completed wave audited; resume defect fixed (2026-09-22)

- All four 10.5-hour notebooks completed cleanly, with no disk or context
  failure. Their new archives contain 11, 17, 8, and 15 task records.
- Audit exposed a resume defect: ConfiBench ships an empty `saves/` directory,
  while setup extracted `prev_saves.zip` only when that directory did not exist.
  Logs therefore reported `39 tasks in shard, 39 to run`; the checkpoint was
  packaged but silently not restored.
- The packager now always extracts a supplied checkpoint and supports repeated
  `--prev` arguments. It creates a canonical merged archive, retaining the
  earlier preregistered result for accidental duplicate tasks rather than
  choosing by score.
- Merging the old and new runs preserves 13, 17, 10, and 16 unique tasks by
  shard: **56/156 total**, with **100 remaining**. Rebuilt notebooks compile,
  contain canonical forward-slash paths, and contain no credentials.
- Correct true-resume runs for shards 0/4 and 1/4 are running on account 4 with
  26 and 22 tasks remaining. Shards 2/4 and 3/4 are staged with 29 and 23 tasks
  remaining, but account 2 rejected them after reaching weekly GPU quota.
- Accounts 1 and 3 have zero GPU quota until 2026-09-26. At launch, account 4
  had 8.02 GPU-hours remaining, so the active pair is expected to checkpoint
  again before completing. No result from the completed wave was discarded.

### Scheduling update - second backup account activated (2026-09-22)

- A newly supplied credential was authenticated as Kaggle user
  `adibhossain701` and registered as scheduler account 5. It had the full 30
  weekly GPU-hours available at launch.
- Correct true-resume shards 2/4 and 3/4 are now `RUNNING` on account 5 from
  their canonical 10-task and 16-task checkpoints. Shards 0/4 and 1/4 remain
  `RUNNING` on account 4.
- All four baseline shards are therefore active in parallel. Generated bundles
  and logs contain no API credential values.

### Checkpoint - Kaggle nested-archive behavior fixed (2026-09-22)

- Account-4 shards 0/4 and 1/4 completed, while account-5 shards 2/4 and 3/4
  remained running. Validation showed the completed notebooks again started all
  39 shard tasks and did not print the checkpoint-restoration sentinel.
- Root cause: Kaggle automatically expanded the nested `prev_saves.zip` during
  dataset ingestion, exposing `prev_saves/saves/...` as ordinary files. The
  runtime therefore could not find the expected ZIP even though the records
  were present in the mounted dataset.
- Checkpoints are now published directly under `resume_saves/`. Runtime reads an
  expected count from `XJ_BOUNDARY.json`, copies those records into ConfiBench,
  and hard-fails unless the exact count is restored before model setup.
- A local simulation of Kaggle's outer-ZIP extraction restored exactly 15, 17,
  10, and 16 task records for shards 0--3. Current durable union is **58/156**;
  true remaining counts are 24, 22, 29, and 23 (**98 total**).
- The rebuilt inputs contain no credentials and compile successfully. Shards
  0/4 and 1/4 are staged for the next available quota. The currently running
  account-5 shards may still contribute new non-overlapping tasks; their output
  will be merged before their next validated resume.

### Checkpoint - direct-file resumes launched with remote verification (2026-09-23)

- The pre-fix account-5 runs completed. Merging their outputs added three new
  non-overlapping tasks, bringing the durable union to **61/156**. Per-shard
  checkpoint counts are 15, 17, 10, and 19; **95 tasks remain**.
- The scheduler now waits until Kaggle's remote dataset file listing exposes the
  exact `resume_saves/**/data.json` count recorded in `XJ_BOUNDARY.json` before
  launching a notebook. This prevents a newly pushed kernel from mounting the
  previous dataset version.
- Account 5 had 7.97 GPU-hours remaining. Validated direct-file resumes for
  shards 2/4 and 3/4 are `RUNNING`; the remote preflight observed exactly 10 and
  19 checkpoints respectively. Runtime will hard-fail if those counts differ.
- Shards 0/4 and 1/4 remain staged with 24 and 22 tasks left until quota resets
  or another account becomes available.

### Checkpoint - direct-file resume verified end-to-end (2026-09-24)

- Both account-5 direct-file resume sessions completed successfully. Kaggle reports
  `COMPLETE` for `confibench-qwen-shard-2-of-4` and
  `confibench-qwen-shard-3-of-4`.
- The shard-2 runtime restored exactly 10 checkpoint tasks before processing 29
  remaining tasks; its final archive contains 18/39 unique task records.
- The shard-3 runtime restored exactly 19 checkpoint tasks before processing 20
  remaining tasks; its final archive contains 28/39 unique task records.
- This is the first remote end-to-end confirmation that the direct
  `resume_saves/**/data.json` layout, boundary count, runtime assertion, and
  scheduler-side remote listing check all work together.
- The durable equal-model baseline now contains **78/156** tasks. Per-shard counts
  are 15, 17, 18, and 28; remaining counts are 24, 22, 21, and 11
  (**78 total remaining**).
- The latest pair of runs is finished, but the full equal-model baseline and the
  final frozen 156-task pipeline evaluation are not yet finished. No final
  same-model comparison or SOTA claim is made at this checkpoint.

### Scheduling update - all-account ten-way finish launched (2026-09-26)

- Weekly GPU quota reset was verified through Kaggle's quota API: all five
  configured accounts had 30.00 GPU-hours available before launch.
- The validated 78-task checkpoint union was repartitioned into ten shards. The
  bundles collectively contain all 156 benchmark tasks, exactly 78 restored
  task records, and exactly 78 unfinished tasks; no task is omitted.
- Unfinished counts by shard 0--9 are 7, 6, 10, 7, 10, 7, 10, 8, 8, and 5.
  Each bundle compiled and passed a credential-leak scan before publication.
- Two private GPU kernels were launched per account: shards 0/1 on account 1,
  2/3 on account 2, 4/5 on account 3, 6/7 on account 4, and 8/9 on account 5.
- Kaggle accepted every dataset and kernel, each remote checkpoint preflight
  succeeded, and a post-launch query reported all ten kernels `RUNNING`.
- This is scheduling-only. Model weights, prompts, sampling, ConfiBench code,
  iteration limits, RTL population, and Eval1/Eval2 remain frozen.

### Checkpoint - ten-way recovery exhausted current quota (2026-09-27)

- All six follow-up Kaggle kernels reached `COMPLETE`, and their outputs were
  downloaded and audited locally. Kaggle completion indicated a clean notebook
  exit at the configured time budget; it did not imply that every assigned
  ConfiBench task produced a final `data.json` checkpoint.
- The follow-up runs added four previously unfinished tasks. The canonical
  equal-model checkpoint is now **122/156**, leaving **34 tasks**.
- The five accounts have only 0.00--1.34 GPU hours remaining and report their
  next quota refresh at **2026-10-03 00:00**. No short run was launched because
  it could not complete model setup plus a useful task attempt.
- The 34 remaining tasks are staged as ten disjoint finish bundles named
  `cbqfinal2a` through `cbqfinal2j`. Four bundles contain four tasks/four
  workers; six contain three tasks/three workers. Each task therefore receives
  a dedicated worker and a 10-hour work budget.
- The staged task union is exactly 34/34 unique, all notebook cells compile,
  and a credential scan found no token material. This changes scheduling only;
  the frozen Qwen model, prompts, generation method, and Eval1/Eval2 scoring
  remain unchanged.

### Scheduling update - low-quota finish launch (2026-09-27)

- At the user's direction, the ten staged finish kernels were submitted despite
  the small quota balances shown by Kaggle.
- Accounts 1, 3, 4, and 5 each accepted two kernels. All eight accepted kernels
  were subsequently confirmed `RUNNING`; together they cover 26 of the 34
  remaining tasks.
- Account 2 rejected both `cbqfinal2c` and `cbqfinal2d` with Kaggle's explicit
  `Maximum weekly GPU quota of 30.00 hours reached` response. Those two bundles
  remain staged and cover the other eight tasks.
- No task assignment was duplicated or dropped. Kernel acceptance and benchmark
  completion remain distinct: results will be counted only after downloaded
  `data.json` checkpoints are audited.

### Scheduling update - sixth account completes launch coverage (2026-09-27)

- A new credential was authenticated as Kaggle user `shellshocker`; Kaggle
  reported 28.20 of 30.00 GPU hours remaining before launch. It was registered
  as scheduler account 6 without placing its credential in generated artifacts.
- The two previously rejected bundles, `cbqfinal2c` and `cbqfinal2d`, were
  launched on account 6 and both were confirmed `RUNNING`.
- All ten finish kernels are now running and collectively cover all 34 tasks
  missing from the canonical 122/156 checkpoint. No task remains unassigned.

### Checkpoint - finish wave audited and prioritized retries launched (2026-09-28)

- All ten finish kernels completed and their outputs were downloaded. One
  unusually large archive required a selective retry; the final archive set is
  readable and complete.
- Thirteen of the 34 attempted tasks produced new `data.json` checkpoints. The
  canonical equal-model checkpoint is now **135/156**, with **21 tasks** still
  unresolved.
- Accounts 1--5 report zero remaining GPU quota. Account 6 (`shellshocker`)
  reported 6.70 hours remaining after the finish wave.
- Worker logs were inspected to distinguish tasks that reached simulation or
  discriminator stages from tasks dominated by slow RTL generation. Eight
  higher-probability retries were placed into `cbqretry3a` and `cbqretry3b`,
  with four dedicated workers and a 10-hour work budget per kernel.
- Both retry kernels were accepted by Kaggle and confirmed `RUNNING`. The other
  13 unresolved tasks remain recorded locally for the 2026-10-03 quota reset.

### Checkpoint - prioritized retry wave audited (2026-09-29)

- `cbqretry3a` completed and its archive was downloaded successfully. It added
  one new checkpoint, `ece241_2013_q2`.
- Kaggle marked `cbqretry3b` as `CANCEL_ACKNOWLEDGED`. Its kernel output listing
  is empty, so no partial task checkpoint is recoverable from that run.
- The canonical equal-model checkpoint is now **136/156**, leaving **20 tasks**.
  No retry kernel remains active; unresolved tasks are retained for the next
  quota window.

### Scheduling Update - Quota Reset Finish Wave (2026-10-03)

- The five currently configured credentials report 30.00 GPU hours each. The
  canonical archived/recovered task union was audited again: 136 of 156 task
  records are retained with source paths and SHA-256 hashes; 20 remain unresolved.
- Ten private kernels, `cbqoct300` through `cbqoct309`, were accepted and each
  independently confirmed `RUNNING`. Two kernels run per account and two workers
  run per kernel, covering exactly the 20 unresolved tasks without overlap.
- Execution now atomically archives recorded tasks every minute, reports missing
  tasks in `cbq_completion.json`, bounds the session before Kaggle's hard cutoff,
  and preserves unfinished diagnostics separately. Local checkpoint tests passed
  for malformed JSON, retained failed results, and atomic archive replacement.
- A parser execution defect was found: the upstream 30-second timeout left its
  parser thread alive. The copied baseline now runs these pure helper calls in
  killable child processes at the same timeout. A Kaggle startup smoke test checks
  results, exception propagation, large responses, and cleanup after timeout.
  This execution amendment is documented in `BASELINE_CONFIBENCH_QWEN.md`.
- A hidden local monitor runs `monitor_finish_20261003.py`; it collects audited
  output archives, retains the first recorded result, and automatically submits
  remaining tasks while enough GPU quota is available. Its state, logs, and process
  information live in `confibench_finish_20261003/`. The local machine must stay
  on for collection and subsequent launches; submitted Kaggle jobs run remotely.
- All twenty tasks are in progress. Full benchmark completion is not yet claimed.

### 2026-10-04: Recovery Audit and GPU Launch Hold

- The ten October 3 kernels ended after about 110.22 total notebook-session hours.
  Only two new final records were recovered: canonical coverage is 138/156,
  with 18 unresolved tasks. The prior in-progress statement is now historical.
- All ten partial archives and logs are downloaded and verified. Recovery banks
  contain 1,005 candidate saved responses and 15 first-saved RTL populations.
  These are not new task completions or proven functional successes.
- Per-call journals and iteration-boundary JSON checkpoints are implemented in
  copied baseline code. Six CPU-only unit tests pass, plus final-archive tests.
  Seventy-two actual upstream prompt-stage requests replayed with zero fresh
  model calls. At this point, actual Linux simulation recovery was unverified.
- ConfiBench GPU launching is explicitly held in both the collector and shared
  push command. The earlier automatic-retry behavior is disabled by this hold.
- A bounded, zero-fresh-call CPU-only Kaggle interruption/resume pilot is staged.
  Initial publication was blocked by the permissions reviewer due to its private
  recovered-response payload; this was resolved by subsequent explicit approval.
- See `confibench_finish_20261003/RECOVERY_AND_RESUME_AUDIT.md` for limitations,
  artifacts, tests, and the recorded private-publication approval.

### 2026-10-04: Actual Kaggle CPU Resume Validation Passed

- After explicit user approval, two private CPU-only notebook versions completed
  on `ece241_2014_q4`. Neither downloaded a model nor made fresh model calls.
- Version 1 replayed 108 saved responses after a forced interruption and saved
  nine completed iteration boundaries through the actual upstream Linux pipeline.
- Version 2 restored `next_iteration=9` in both phases, skipping those nine
  iterations. Only four unfinished-prefix responses were replayed per phase;
  committed response files remained byte-identical across restart.
- Both runs intentionally stopped at the first missing response under the
  zero-fresh-call cap. They are validation evidence, not final benchmark records.
- Coverage remains **138/156**, with **18 unresolved tasks**. GPU launches remain
  held pending a single capped fresh-generation pilot; throughput is not yet
  validated. Reports and runtime archives are saved in
  `kaggle_runs/cbq_cpu_resume_oct4/` and `kaggle_runs/cbq_cpu_resume_oct4_v2/`.
