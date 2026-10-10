# Resume on the 32 GB GPU Desktop

This handoff preserves the existing experiment; it does not restart training or change the model.

**Claude Code handoff:** read
[the conversation history and continuation context](CONVERSATION_HISTORY_AND_CLAUDE_HANDOFF.md)
before running anything. Root `CLAUDE.md` points Claude to that file automatically
when you work from the cloned repository directory.

**Snapshot, 10 October 2026:** 140/156 ConfiBench first task records saved, including failures; 16 tasks remain. All 138 original first records are preserved. The latest Kaggle CPU replay validated all 16 journals, with no fresh model calls. The last two attempted GPU jobs received CPU only and made no model progress.

## What to Download

The desktop repository is `Rifat-Hossain49/BIRDI_Project`. Source is at its root.
The user explicitly approved public publication of the full credential-free
handoff. An earlier private copy in `BIRDIResearchGrant/RTLCodeGen` is retained;
use this repository for the desktop continuation.

1. Authenticate GitHub on the desktop: `gh auth login`.
2. Download the repository and the release checkpoint:

```bash
gh repo clone Rifat-Hossain49/BIRDI_Project
cd BIRDI_Project
mkdir -p downloads desktop_work
gh release download desktop-handoff-20261010 --repo Rifat-Hossain49/BIRDI_Project \
  --pattern 'birdi-desktop-resume-20261010.zip' --dir downloads
```

The checkpoint archive contains the prepared, byte-preserved ConfiBench runtime, 140 first records, the older 138-record reference archive, all 16 latest response journals, and their checksums. It is sufficient for the remaining ConfiBench work. Do not use an older initial seed or regenerate saved task results.

Optional `birdi-research-history-*.zip` release assets preserve unique historical output archives, older trained JEPA artifacts, the upstream ConfiBench result archive and diagnostic results. `history_inventory.json` maps duplicate archives to their stored SHA256-identical copy and lists any credential-safety exclusions. Download/extract these only for historical analysis or replaying the earlier DRTB evaluation; they are not needed to start the 16 remaining tasks. Current DRTB source and research reports are in `new_implementation/`.

The release also has `birdi-source-20261010.zip` as a standalone source download
if Git cloning is inconvenient. Oversized historical text traces are stored
losslessly as `.gz` files; their original-content hashes and encoding are recorded
in `history_inventory.json`. Never extract old historical checkpoints over
`desktop_work`; that directory is reserved for newly resumed progress.

## GPU and Software

- NVIDIA GPU, 32 GB VRAM, recent NVIDIA driver, Docker with NVIDIA GPU support.
- The user's desktop is Windows with NVIDIA. Use WSL2 with Docker Desktop and NVIDIA GPU integration, and run the commands below in the WSL shell. Store the clone and `desktop_work` on the WSL Linux filesystem for better performance.
- Verify `nvidia-smi` on the host and verify GPU access from Docker before inference. Host GPU access alone does not imply container access.
- At least 60 GB free disk for the model, runtime, checkpoints and working files; optional historical assets need additional space.
- No Kaggle token is required. The Hugging Face model is downloaded when GPU continuation starts; an optional `HF_TOKEN` may be supplied as an environment variable, never committed.

The pinned backend is the same `llama.cpp b11399` CUDA 12.8 release. Driver/binary compatibility is checked at startup. No laptop GPU inference was performed while preparing this handoff; actual memory fit must be verified on the desktop.

### Windows Setup

Install a current NVIDIA Windows driver. In an administrator PowerShell window,
run `wsl --install -d Ubuntu` if WSL2 is not already installed, then restart when
requested. Install Docker Desktop, select the WSL2 engine and enable integration
for Ubuntu. Open Ubuntu and verify both commands:

```bash
nvidia-smi
docker run --rm --gpus all ubuntu:24.04 nvidia-smi
```

The second command must show the NVIDIA GPU inside the container. Do not proceed
with GPU inference if only the first works. Install Git and GitHub CLI in Ubuntu
or clone using your authenticated desktop tools, then continue from the clone
in the WSL shell. Keep at least 60 GB available to WSL/Docker as well as on the
Windows host. Do not execute `resume.py` directly in native PowerShell.

## Build and CPU Preflight

From the cloned `BIRDI_Project` directory:

```bash
docker build -f new_implementation/desktop/Dockerfile -t birdi-resume .
docker run --rm \
  -v "$PWD:/project:ro" \
  -v "$PWD/downloads:/downloads:ro" \
  -v "$PWD/desktop_work:/kaggle/working" \
  birdi-resume --cpu-only --hours 4
```

The `/kaggle/working` path is deliberate: saved Python tracebacks contain absolute Kaggle script paths, and exact journal replay must preserve those paths. The prepared ConfiBench source uses the original checkpoint profile; do not recompute the old Windows-generated profile on Linux or substitute an upstream checkout.

CPU preflight makes **zero new model calls**. It must either reach the next missing request or find an existing first record for every unfinished task. Any prompt/checksum/replay mismatch stops continuation. Read `desktop_work/desktop_cpu_audit.json` and the per-task logs if it fails. Do not bypass this gate.

## GPU Continuation

After successful desktop CPU preflight:

```bash
docker run --rm --gpus all \
  -v "$PWD:/project:ro" \
  -v "$PWD/downloads:/downloads:ro" \
  -v "$PWD/desktop_work:/kaggle/working" \
  birdi-resume --workers 2 --hours 24
```

Model: `unsloth/Qwen3.5-27B-GGUF`, file `Qwen3.5-27B-Q4_K_M.gguf`. Defaults: two workers, 65,536 aggregate context, 32,768 tokens per server slot. This is a conservative starting configuration for 32 GB, not a memory-fit or completion-time guarantee. If model startup reports OOM, rerun CPU preflight and use `--workers 1`; this preserves 32,768 tokens per slot. Do not change quantization, prompts or benchmark settings to get a faster score under the same baseline name.

The program checks actual GPU model allocation, records model-file SHA256 and backend provenance, and keeps the sampler unchanged: thinking off, default temperature 0.7, top_p 0.8, top_k 20, max output 8,192; upstream explicit stage temperatures are retained. ConfiBench remains population 20, debug limit 3, iteration limit 10, original confidence/discriminator/ensemble/Eval1/Eval2 rules. Hardware and concurrency differ from Kaggle and must be disclosed; new stochastic outputs are not claimed bit-identical across hardware.

The worker budget is operator-selected, not Kaggle-limited. The final hour admits no new requests, allowing in-flight requests time to finish. Ctrl+C or a deadline stops workers and saves available progress; an interrupted in-flight response may need recomputation, but completed responses were committed atomically before use. Generated benchmark programs execute inside the container; do not expose personal data, credentials or the Docker socket to it.

## Restart and Final Collection

Keep the entire `desktop_work` directory. Run CPU preflight again before every GPU continuation. The original import archive is never reapplied over new desktop progress.

- `desktop_completion.json`: authoritative recorded/remaining task inventory, not a pass count.
- `desktop_saves.zip`: first task results.
- `desktop_runtime.zip`: immutable completed responses and iteration journals for unfinished tasks.
- `desktop_cpu_audit.json`: most recent CPU-only replay proof, consumed when GPU work starts.
- `desktop_engine.json`: actual model hash, CUDA allocation, backend and desktop hardware.
- `desktop_<timestamp>_<task>.log`: unique worker logs; historical failures are retained.

Only when all 156 tasks have a first record should the full equal-model comparison be assembled. Preserve failures and missing evaluation fields honestly; do not rerun scored failures or count a completed process as a successful benchmark task.

## Offline Tests

```bash
cd new_implementation
python -m unittest test_kaggle_accounts test_confibench_resume test_gpu_launch_hold \
  test_resume_collection test_resume_controller test_resume_completion desktop.test_resume
```

Credentials and transient model downloads are not part of the GitHub handoff. Historical extracted run directories are represented by their retained ZIP archives, not duplicated into Git.
