# Deadline-Safe ConfiBench Continuation

**Superseded operational status:** the user approved private execution and CPU
replay has now finished. All 16 frontiers passed; two accepted GPU jobs and an
explicit hardware probe received CPU only. No fresh model work started and all
30 GPU hours remain. See [CONTINUATION_HANDOFF_20261007.md](CONTINUATION_HANDOFF_20261007.md)
and the top section of `RESUME_STATUS.md` for current evidence and the hardware
hold. The staged/pending-approval statements below describe the earlier audit.

## Verified State

- 140/156 first task records are saved; 16 tasks remain unresolved.
- Task-record coverage includes failures; it is not a pass count.
- All 138 original records are preserved byte-for-byte.
- No GPU job or controller is currently running in this completion campaign.
- No additional GPU job was launched during this audit.

## Resource Constraint

The first live Kaggle quota query on 7 October, before adding the extra account,
returned:

| Account | Remaining GPU-session hours | Scheduling status |
|---|---:|---|
| tishaferdous | 1.16 | Below existing safe launch minimum |
| naimahjyoti | 0.65 | Below existing safe launch minimum |
| rifathosain | 3.77 | Quarantined after two missing-artifact startup failures |
| arafhossainazim | 1.01 | Below existing safe launch minimum |
| adibhossain701 | 0.65 | Below existing safe launch minimum |

Total reported quota: **7.24 hours**. Quota on non-quarantined accounts:
**3.47 hours**. The current launcher retains 0.75 hours for setup/shutdown and
requires at least 0.75 hours of worker time; none of those accounts qualifies.
The API reports the next refresh at 10 October 00:00 UTC / 06:00 Bangladesh.

The previous checkpoint/throughput-based completion estimate was 60-90 additional
GPU-session hours, not a guarantee. Finishing the unchanged full baseline cannot
be promised from the quota currently available. A CPU preflight saves avoidable
work; it cannot eliminate model generation that the benchmark still requires.

## Changes Implemented

1. At a fresh-call budget stop, the journal records the exact next request,
   request hash, stage, call index, task contract and replay count. No provider
   call occurs when the CPU fresh-call allowance is zero.
2. The collector requires a verified cache miss or an actual task record for
   each CPU worker. Crashes, killed workers, stale requests and incompatible
   journals cannot be treated as successful preflight.
3. The GPU scheduling gate can require the latest audited CPU frontier and
   exact runtime archive checksum for every selected task.
4. Staging alone is no longer interpreted as an accepted remote submission.
5. The completion manifest must agree with the actual downloaded task records.

Twenty-two offline regression tests passed. The staged notebook's two code cells
compile. All 1,227 dataset ZIP members were checked: no account tokens or `.env`
files were found, and archive paths are portable.

## Next Execution

The private CPU-only bundle is `kaggle_upload_cbq-cpu-frontier-oct7`:

- 16 latest audited task checkpoints, not the old initial seed.
- No GPU, model download, model server or fresh model generation.
- Four CPU workers; existing two-hour worker budget remains bounded.
- Saved model responses are reused only for matching request hashes.
- Any final records are collected using the existing first-record policy.

The proposed upload to `tishaferdous` was blocked by the execution approval
checker pending explicit approval for this exact bundle. **It has not launched.**
The bundle includes private benchmark prompts, model responses and checkpoints;
it does not include account credentials. Approval was requested for private
publication and CPU-only execution. GPU continuation remains off.

After CPU replay finishes: download and audit the outputs; retain original
response bytes; identify each exact next missing call; update the remaining-task
inventory. Only then consider a bounded GPU allocation with adequate quota.

## Scientific Boundaries

Do not shrink the RTL population, iterations, prompts or output-token allowance
to manufacture a faster result under the frozen baseline's name. Do not retry
saved failures, use golden answers during generation, or count checkpoints as
completed evaluations. If a deadline prevents full completion, report the
unresolved tasks explicitly instead of inventing final scores.

The compiler diagnostics explain real repeated work: for example, generated
`countbcd` candidates procedurally assign the wire output `ena`, causing Icarus
elaboration failures. ConfiBench refills its unusable candidate population, which
can require many additional model calls inside one outer iteration. Preserved
responses from these refills are useful progress, even when the iteration cursor
does not advance. The plain-Verilog extraction path was checked; it correctly
returns unfenced code and is not the cause of those observed failures.

## Extra Account Added: 7 October

The user supplied an extra Kaggle credential for GPU continuation. Kaggle token
introspection verified the username `sahanzparvintopy`; the live quota API returned
**30.00 GPU-session hours**, refreshing on 10 October at 00:00 UTC. It is registered
as scheduler account 7 using the `GPU_KAGGLE_API_TOKEN` alias (or the existing
numbered convention `KAGGLE_API_TOKEN_7`). The email is not used as a username.

The credential is stored only in the local `.env`, which is now ignored by Git.
It is not embedded in notebooks, datasets, reports or the account-name registry.
Twenty-six regression tests passed, including new alias and environment-priority
tests. Existing checkpoints, account quarantine and launch gates are unchanged.

The extra account was authenticated and registered, **not launched**. The CPU
replay export approval remains pending. It does not authorize bypassing the
latest-checkpoint replay gate or replaying already saved results. Thirty extra
hours improves the available budget but does not guarantee finishing the
previously estimated 60-90 hours of remaining frozen-baseline work.
