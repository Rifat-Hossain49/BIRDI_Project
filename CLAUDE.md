# BIRDI Continuation Instructions

Start by reading `new_implementation/desktop/CONVERSATION_HISTORY_AND_CLAUDE_HANDOFF.md`
and `new_implementation/desktop/README.md`. The former is a reconstructed research
and conversation history, not a complete verbatim chat export.

This project is at the root of `Rifat-Hossain49/BIRDI_Project`. The user explicitly
approved publishing the credential-free full handoff publicly on 10 October 2026.
Work from that repository root. An earlier private copy also exists under
`BIRDI/` in `BIRDIResearchGrant/RTLCodeGen`; that is not the desktop target.

The user is moving to Windows with an NVIDIA GPU with 32 GB VRAM. Use WSL2 and
the documented Linux Docker container; do not run the checkpointed ConfiBench
workers natively on Windows. Existing journals require `/kaggle/working` paths.

As of 10 October 2026, the equal-model ConfiBench baseline has 140/156 first task
records and 16 unresolved tasks. These counts include failures, not just passes.
The DRTB candidate pool has already been generated; do not regenerate it or
restart the old JEPA training pipeline to finish this experiment.

Download the checkpoint release, run mandatory CPU-only replay, then continue
the same Qwen3.5-27B Q4_K_M model with the frozen baseline settings. Never bypass
request hashes, profile checks, compiler-order replay or the first-record rule.
Preserve every completed response and iteration boundary. Never rerun a scored
failure to improve the reported baseline. Do not reset `desktop_work`.

Generation cannot read golden RTL, official testbenches, hidden mutants or their
verdicts. Those are evaluation-only inputs. Do not tune the frozen method on the
held-out split. Report missing evaluation fields and failures explicitly.

No credentials are distributed here. Do not commit credentials, personal files,
model downloads or raw desktop working directories. Do not request historical
Kaggle tokens: desktop continuation does not need them.

The desktop runner has offline tests, but Docker/GPU execution has not been
validated on the new desktop. Check NVIDIA access, driver compatibility, CPU
replay and actual VRAM allocation before making fresh model calls. Claim neither
guaranteed completion time nor SOTA superiority without measured evidence.
