
"""Embedding helpers for frozen pretrained encoders."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np


DEFAULT_EMBED_MODEL = "Qwen/Qwen3-Embedding-0.6B"


def _disable_optional_vision_imports() -> None:
    """Stop transformers from importing timm/torchvision for text-only models.

    When ``AutoModel`` enumerates its config mapping it eagerly imports the
    optional ``timm_wrapper`` config, which imports ``timm`` and then
    ``torchvision``. On Kaggle, timm is installed while a matching torchvision
    often is not, so that optional import crashes an otherwise text-only run.
    Forcing the internal availability flags to False makes those optional config
    modules import cleanly without pulling in the vision stack.

    This is a real, version-independent guard. The ``TRANSFORMERS_NO_TORCHVISION``
    / ``USE_TIMM`` style environment variables used previously are NOT honoured by
    transformers and did nothing.
    """

    try:
        from transformers.utils import import_utils

        import_utils._timm_available = False
        import_utils._torchvision_available = False
    except Exception:
        pass


def encode_texts(
    texts: Sequence[str],
    model_name: str = DEFAULT_EMBED_MODEL,
    batch_size: int = 16,
    prompt: str | None = None,
    cache_path: str | Path | None = None,
    device: str | None = None,
) -> np.ndarray:
    """Encode texts with a SentenceTransformer-compatible model.

    The default is Qwen3-Embedding-0.6B because it is open, current, compact
    enough for Kaggle GPUs, and strong on text/code retrieval style tasks.
    """

    if cache_path is not None:
        cache = Path(cache_path)
        if cache.exists():
            return np.load(cache).astype("float32")
    else:
        cache = None

    texts = list(texts)

    embeddings = _encode_with_transformers(
        texts=texts,
        model_name=model_name,
        batch_size=batch_size,
        prompt=prompt,
        device=device,
    )

    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.save(cache, embeddings)

    return embeddings


def _encode_with_transformers(
    texts: Sequence[str],
    model_name: str,
    batch_size: int,
    prompt: str | None,
    device: str | None,
) -> np.ndarray:
    import torch
    import torch.nn.functional as F
    from tqdm.auto import tqdm

    _disable_optional_vision_imports()
    from transformers import AutoModel, AutoTokenizer

    input_texts = [f"{prompt}{text}" if prompt else str(text) for text in texts]
    device_obj = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    dtype = torch.float16 if device_obj.type == "cuda" else torch.float32

    tokenizer = AutoTokenizer.from_pretrained(model_name, padding_side="left")
    model = AutoModel.from_pretrained(model_name, torch_dtype=dtype).to(device_obj)
    model.eval()

    encoded_batches: list[np.ndarray] = []
    with torch.no_grad():
        for start in tqdm(range(0, len(input_texts), batch_size), desc=f"Encoding with {model_name}"):
            batch_texts = input_texts[start : start + batch_size]
            batch = tokenizer(
                batch_texts,
                padding=True,
                truncation=True,
                max_length=8192,
                return_tensors="pt",
            )
            batch = {key: value.to(device_obj) for key, value in batch.items()}
            outputs = model(**batch)
            embeddings = _last_token_pool(outputs.last_hidden_state, batch["attention_mask"])
            embeddings = F.normalize(embeddings, p=2, dim=1)
            encoded_batches.append(embeddings.float().cpu().numpy())

    return np.concatenate(encoded_batches, axis=0).astype("float32")


def _last_token_pool(last_hidden_states: "object", attention_mask: "object") -> "object":
    import torch

    left_padding = attention_mask[:, -1].sum() == attention_mask.shape[0]
    if left_padding:
        return last_hidden_states[:, -1]
    sequence_lengths = attention_mask.sum(dim=1) - 1
    batch_size = last_hidden_states.shape[0]
    return last_hidden_states[torch.arange(batch_size, device=last_hidden_states.device), sequence_lengths]
