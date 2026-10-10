# ConfiBench Completion Handoff: 7 October 2026

This is the latest operational status. Earlier dated notes describe earlier states.

## Result Inventory

- 140/156 first task records saved; 16 tasks unresolved. A saved record is not necessarily a pass.
- All 138 original records remain byte-identical in the canonical archive.
- Both CPU replay runs finished. The corrected second run verified the exact next missing model request for all 16 tasks, with zero fresh task responses.
- No new final task record was added today. No remote model job or local controller is running.
- Checkpoint/contract hashes, frozen prompts, sampling settings and first-record scoring rules are unchanged.

## Execution Performed

1. Private CPU replay: `tishaferdous/confibench-qwen-cbq-cpu-frontier-oct7`.
2. It found a `circuit10` replay conflict caused solely by a timestamped absolute filename in a Python traceback. Fifteen tasks reached their next missing model request.
3. The runtime now restores the recorded working directory for the affected iteration. It does not normalize prompts, alter their hashes or regenerate saved responses.
4. Corrected private CPU replay: `tishaferdous/confibench-qwen-cbq-cpu-frontier-v2-oct7`. All 16 frontiers passed the strict audit. Historical conflict evidence remains saved.
5. Two disjoint GPU continuations were accepted on the newly authorized account:
   - `sahanzparvintopy/confibench-qwen-cbq-resume-r5a7s1-oct7`: `vector100r`, `fsm_serial`, `fsm_serialdata`, `lemmings4`.
   - `sahanzparvintopy/confibench-qwen-cbq-resume-r5a7s2-oct7`: `fsm_onehot`, `review2015_fsm`, `2014_q3fsm`, `circuit10`.
6. Both ended ERROR in their first cell: `nvidia-smi` was absent. Papermill stopped before installation, model download, server startup or inference.
7. A separate hardware-only probe explicitly requested `NvidiaTeslaT4`, with a 180-second cap and no model/data download: `sahanzparvintopy/confibench-hardware-probe-oct7`. It also received CPU only: `gpu_count=0`.
8. GPU launching was disabled on this account. No blind model retries or automatic controller were started. The quota API still reports 30.00/30.00 GPU hours remaining, with 0.00 hours used.

The metadata requested GPU correctly. The reason Kaggle did not allocate it is not established. Phone verification/account eligibility or a platform allocation issue needs checking; neither is asserted as the proven cause.

## Current Resources

| Account | GPU-session hours available | Current scheduling decision |
|---|---:|---|
| tishaferdous | 1.16 | Below safe launch minimum |
| naimahjyoti | 0.65 | Below safe launch minimum |
| rifathosain | 3.77 | Prior missing-artifact startup failures; still quarantined |
| arafhossainazim | 1.01 | Below safe launch minimum |
| adibhossain701 | 0.65 | Below safe launch minimum |
| sahanzparvintopy | 30.00 | GPU allocation unverified; hardware hold |

The API reports refresh on 10 October at 00:00 UTC / 06:00 Bangladesh. The unquarantined older accounts cannot pool their fractional quota into one GPU session. The existing minimum retains 0.75 hours for setup/shutdown and at least 0.75 hours of worker time.

## Resume Requirements

1. On `sahanzparvintopy`, inspect Settings > Accelerator and any phone-verification/account-eligibility requirement. If T4 x2 is selectable, run the hardware-only probe with that accelerator and confirm two actual GPUs in its output. Available quota and `enable_gpu=true` alone are insufficient proof.
2. Review the saved startup failures and verified hardware output before releasing account 7's explicit scheduling hold. Preserve the original error logs and immutable input archives.
3. Resume only from `cbq-cpu-frontier-v2-oct7_collected/cbq_runtime.zip` or a newer audited checkpoint; never from the old initial seed.
4. The prepared runtime supports two disjoint sessions per account, four task workers per session, a four-hour worker cap, 48 fresh responses per task and a final one-hour window that admits no new requests. These are execution bounds, not changes to ConfiBench's population, iterations or output-token limit.
5. Collect and audit every wave, replay the latest journals on CPU, then schedule only the still-unfinished tasks. Retain the first task result even if it fails.
6. Any local controller must have an explicit bounded window; the previous controller's deadline has expired. No controller was left running by this continuation.

Thirty fresh GPU hours may advance the remaining baseline substantially, but do not guarantee full completion. The previous measured planning estimate was 60-90 additional GPU-session hours; no new inference throughput was measured during today's CPU-only allocations.

## Verification and Evidence

- 38 offline regression tests passed, covering exact journal replay, immutable responses, working-directory restoration, current CPU frontiers, launch approval, quota reservation, archive handling and first-record preservation.
- The scheduler now resolves workspace-relative review evidence independently of its current working directory. This fixes the earlier false audit stop without relaxing integrity checks.
- Future GPU pushes send an explicit accelerator argument; CPU replay pushes never request one. The hardware probe showed that the explicit argument alone did not resolve this account's allocation issue.
- `completion_audit.json`: authoritative completed/missing task inventory and original-record preservation.
- `launch_manifest.json`: accepted jobs, preserved errors, reviewed CPU recovery and disabled accounts `[3, 7]`.
- `hardware_failure_review_20261007.json`: strict first-cell failure review and hardware probe evidence.
- `quota_verified_20261007.json`: live quota observations, without credentials.
- `canonical_latest.zip`: saved first records. Runtime journals are separate and are not counted as completed results.

Credentials remain only in the local ignored `.env`; they are not embedded in notebooks, datasets or reports.
