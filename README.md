# BIRDI JEPA Typed-IR Experiment

## Current Research and Desktop Resume

The project has since evolved into RTL testbench generation with the DRTB
pipeline. The earlier JEPA/typed-IR experiment below is retained as research
history. The latest audited equal-model ConfiBench baseline has 140/156 first
task records, with 16 unresolved; this is task coverage, not a pass count.

For the 32 GB NVIDIA GPU desktop handoff, start with
[the desktop instructions](new_implementation/desktop/README.md).
They preserve the existing model, benchmark settings and response journals,
and require CPU replay before fresh GPU inference. Research reports and current
testbench source are under `new_implementation/`.

This repository now contains a first Kaggle-ready implementation of the idea in the pasted proposal:

```text
problem statement + input -> pretrained embedding encoder -> JEPA predictor -> predicted typed-IR latent
reference code -> typed algorithm IR + backup semantic graph -> pretrained embedding encoder -> target typed-IR latent
predicted typed-IR latent -> retrieve top-k typed IR prototypes from training index
problem text + retrieved typed IR + predicted typed-IR latent -> CodeT5+ IR repair decoder -> typed IR
decoded typed IR -> deterministic typed-IR compiler -> Python solution
```

The reference Python code is used only during training to build pseudo-label typed algorithm IR. In inference, the model only needs the problem statement and input.

The main target is now a typed algorithmic IR/DSL, not loose graph JSON. The extractor uses Python AST parsing only as a deterministic way to read reference code, then emits compact reusable operations such as:

```text
FUNC solution(nums)
FILTER negatives = nums AS x WHERE x < 0
RETURN MEAN(negatives)
```

The older state/data-flow graph extractor is still included as a diagnostic backup, but JEPA training, retrieval, decoder training, and final code compilation now use the typed IR.

## What Is Included

- `birdi_jepa/algorithm_ir.py` builds deterministic typed algorithm IR and compiles decoded IR directly into Python code.
- `birdi_jepa/state_graph.py` builds backup pseudo-label semantic state/data-flow graphs, using Python AST only as the parser and falling back to keyword graphs when parsing fails.
- `birdi_jepa/embedding.py` extracts frozen pretrained embeddings, defaulting to `Qwen/Qwen3-Embedding-0.6B`.
- `birdi_jepa/training.py` trains the JEPA predictor with latent MSE, InfoNCE-style contrastive loss, and small VICReg-style anti-collapse regularizers.
- `birdi_jepa/decoder.py` trains a CodeT5+ typed-IR repair decoder conditioned on problem text, retrieved IR prototypes, and the predicted IR latent.
- `birdi_jepa/codegen.py` keeps the older graph compiler and optional frozen-code-LLM helper only for debugging or upper-bound comparison.
- `notebooks/birdi_jepa_kaggle.ipynb` shows all intermediate outputs and plots for Kaggle GPU runs.
- `requirements-kaggle.txt` lists the packages to install in Kaggle.

The notebook also includes two practical safeguards for rare algorithms such as GCD:

- keyword-focused sampling, used only when `MAX_ROWS` is capped; with the current full-dataset config (`MAX_ROWS = None`) every valid row is used
- nearest-IR retrieval diagnostics, so you can see whether the JEPA latent found good typed algorithm prototypes before the repair decoder adapts them
- collapse diagnostics such as predicted-latent standard deviation, off-diagonal cosine, effective rank, and retrieval diversity

## Model Defaults

- Embedding encoder: `Qwen/Qwen3-Embedding-0.6B`
  - Apache 2.0, 0.6B parameters, 32k context, text/code retrieval capable.
  - Used for both problem embeddings and target typed-IR embeddings so both live in the same latent space.
- Typed-IR decoder: `Salesforce/codet5p-770m` in the full-dataset notebook configuration
  - BSD 3-Clause CodeT5+ encoder-decoder checkpoint.
  - Used as `problem text + top-k retrieved typed IR + z_pred -> repaired typed IR`.
  - The notebook sets `DECODER_BATCH_SIZE = 1`, `DECODER_GRADIENT_ACCUMULATION_STEPS = 4`, gradient checkpointing, Adafactor, `DECODER_LR = 3e-5`, and gradient clipping for Kaggle T4 memory.
  - The 3-4 hour Kaggle default keeps full-dataset JEPA/retrieval, then trains the expensive decoder on a focused 4,096-row train subset and 256-row validation subset.
  - The T4-safe default uses two compact retrieved typed-IR contexts with `GRAPH_MAX_SOURCE_LENGTH = 640`, `GRAPH_MAX_TARGET_LENGTH = 640`, and `GRAPH_MAX_NEW_TOKENS = 640`.
  - Decoder inputs include an explicit typed-IR instruction prefix, and training records skipped non-finite batches so failed decoder runs are visible instead of silently saving unusable weights.
  - If the 770M run still runs too long, first reduce `DECODER_MAX_TRAIN_ROWS` to `2048`; the core JEPA/retrieval pipeline remains full-dataset.
- IR-to-code: deterministic symbolic compiler
  - No Qwen/code LLM is used in the final notebook solution stage.
  - The emitted code is a direct function of the decoded typed IR, so wrong IR produces wrong code visibly instead of being silently repaired by a model.

The embedding and decoder model names are configurable in the notebook.

## Kaggle Run Steps

1. Create a Kaggle notebook and enable GPU.
2. Add the CSV as an input dataset. The notebook auto-searches for `Python Programming Questions Dataset.csv` under `/kaggle/input`.
3. Upload this repository folder as another Kaggle input, or copy the `birdi_jepa` folder, `requirements-kaggle.txt`, and notebook into the Kaggle working directory.
4. Run `notebooks/birdi_jepa_kaggle.ipynb` from top to bottom.
5. The current notebook is configured for a full-dataset run with `MAX_ROWS = None`, filters weak pseudo-labels with `MIN_CONFIDENCE = 0.75`, and trains the 770M typed-IR decoder as a core stage. On the included CSV this keeps about 12k parseable rows after confidence filtering.

The notebook prints and displays:

- dataset shape and examples
- pseudo-label parse confidence statistics
- a typed algorithm IR example plus backup state graph JSON
- embedding shapes and cache locations
- epoch-by-epoch JEPA loss, cosine similarity, MRR, retrieval@k, and anti-collapse diagnostics
- loss and metric curves
- nearest-neighbor sanity checks
- decoder train/validation loss curves and generated typed-IR examples
- generated typed-IR validity checks after decoder training
- four-problem inference probes, including cross-similarity, top-k retrieved typed IR, decoded IR, retrieved baseline code, final decoded-IR code, and execution probes
- diagnostics that compare decoded IR against retrieved baselines, without using retrieval to polish the final model output

## Local Smoke Check

The package can be syntax-checked locally without downloading models:

```powershell
python -m py_compile birdi_jepa\algorithm_ir.py birdi_jepa\state_graph.py birdi_jepa\embedding.py birdi_jepa\training.py birdi_jepa\decoder.py
```

The actual embedding and decoder runs should be done on Kaggle or another GPU machine because they download pretrained Hugging Face models.
