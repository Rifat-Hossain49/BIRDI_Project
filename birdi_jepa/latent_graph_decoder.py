"""Decode a graph embedding into a state/data-flow graph with a Qwen latent decoder.

This is the 'embedding -> graph' stage. A Qwen causal LM is conditioned ONLY on
the predicted graph embedding ``z`` via a trained soft prefix: the latent vector
is projected into a few virtual tokens that are prepended to the decoder, and the
model autoregressively generates the canonical graph JSON. No problem text is
ever fed in, so the generated graph is a pure function of the embedding.

Pipeline position:
    problem -> encoder -> JEPA predictor -> z   (graph embedding)
    z -> THIS MODULE (Qwen + trained soft prefix) -> graph JSON
    graph JSON -> codegen.py (Qwen, graph only) -> solution code
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .embedding import _disable_optional_vision_imports


DEFAULT_LATENT_DECODER_MODEL = "Qwen/Qwen2.5-Coder-0.5B"


@dataclass
class LatentDecoderArtifacts:
    model: Any
    tokenizer: Any
    history: pd.DataFrame
    num_prefix_tokens: int


def _require_torch() -> tuple[Any, Any, tuple[Any, Any, Any, Any]]:
    _disable_optional_vision_imports()
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, Dataset
    from transformers import AutoModelForCausalLM, AutoTokenizer

    return torch, nn, (DataLoader, Dataset, AutoModelForCausalLM, AutoTokenizer)


def build_latent_prefix_causal_lm(
    checkpoint: str,
    latent_dim: int,
    num_prefix_tokens: int = 16,
    freeze_base: bool = False,
    dtype: Any = None,
) -> Any:
    """A Qwen causal LM whose only conditioning is a soft prefix from the latent."""

    torch, nn, deps = _require_torch()
    _, _, AutoModelForCausalLM, _ = deps

    class LatentPrefixCausalLM(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.base = AutoModelForCausalLM.from_pretrained(checkpoint, torch_dtype=dtype)
            hidden = self.base.config.hidden_size
            self.num_prefix_tokens = num_prefix_tokens
            self.hidden = hidden
            # Qwen ships sampling defaults (temperature/top_p/top_k) that warn under greedy
            # decoding; clear them so generation is clean and deterministic.
            gen_cfg = self.base.generation_config
            gen_cfg.do_sample = False
            gen_cfg.temperature = None
            gen_cfg.top_p = None
            gen_cfg.top_k = None
            # Project the graph embedding into `num_prefix_tokens` virtual tokens.
            self.prefix_projector = nn.Sequential(
                nn.LayerNorm(latent_dim),
                nn.Linear(latent_dim, hidden),
                nn.GELU(),
                nn.Linear(hidden, hidden * num_prefix_tokens),
            )
            if freeze_base:
                for param in self.base.parameters():
                    param.requires_grad = False

        def _prefix(self, latent: Any) -> Any:
            batch = latent.shape[0]
            proj = self.prefix_projector(latent)
            return proj.view(batch, self.num_prefix_tokens, self.hidden)

        def forward(self, latent: Any, input_ids: Any, attention_mask: Any, labels: Any) -> Any:
            token_embeds = self.base.get_input_embeddings()(input_ids)
            prefix = self._prefix(latent).to(token_embeds.dtype)
            inputs_embeds = torch.cat([prefix, token_embeds], dim=1)

            prefix_mask = torch.ones(
                latent.shape[0], self.num_prefix_tokens,
                dtype=attention_mask.dtype, device=attention_mask.device,
            )
            full_mask = torch.cat([prefix_mask, attention_mask], dim=1)

            prefix_labels = torch.full(
                (latent.shape[0], self.num_prefix_tokens), -100,
                dtype=labels.dtype, device=labels.device,
            )
            full_labels = torch.cat([prefix_labels, labels], dim=1)
            return self.base(inputs_embeds=inputs_embeds, attention_mask=full_mask, labels=full_labels)

        @torch.no_grad()
        def generate(self, latent: Any, max_new_tokens: int = 384, **kwargs: Any) -> Any:
            prefix = self._prefix(latent).to(self.base.dtype)
            attn = torch.ones(
                latent.shape[0], self.num_prefix_tokens,
                dtype=torch.long, device=prefix.device,
            )
            return self.base.generate(
                inputs_embeds=prefix, attention_mask=attn, max_new_tokens=max_new_tokens, **kwargs
            )

    return LatentPrefixCausalLM()


def train_latent_graph_decoder(
    latents: np.ndarray,
    graph_texts: Sequence[str],
    train_idx: np.ndarray,
    val_idx: np.ndarray,
    checkpoint: str = DEFAULT_LATENT_DECODER_MODEL,
    num_prefix_tokens: int = 32,
    epochs: int = 6,
    batch_size: int = 1,
    grad_accum: int = 8,
    lr: float = 1e-4,
    base_lr_scale: float = 0.1,
    freeze_base: bool = False,
    max_graph_length: int = 512,
    seed: int = 42,
    device: str | None = None,
) -> LatentDecoderArtifacts:
    """Train the Qwen latent->graph decoder. `latents` should match inference (z_pred).

    The prefix projector is trained at ``lr``; when the base is trainable it uses a
    much smaller ``lr * base_lr_scale`` so the base cannot wash out the prefix by
    collapsing to a generic (latent-ignoring) output.
    """

    torch, _, deps = _require_torch()
    DataLoader, Dataset, _, AutoTokenizer = deps
    torch.manual_seed(seed)

    tokenizer = AutoTokenizer.from_pretrained(checkpoint)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    device_obj = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    model = build_latent_prefix_causal_lm(
        checkpoint=checkpoint,
        latent_dim=int(np.asarray(latents).shape[1]),
        num_prefix_tokens=num_prefix_tokens,
        freeze_base=freeze_base,
        dtype=torch.float32,
    )
    model.to(device_obj)
    model.base.config.use_cache = False
    try:
        model.base.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    except TypeError:
        model.base.gradient_checkpointing_enable()

    latents = np.asarray(latents, dtype="float32")

    class GraphDataset(Dataset):
        def __init__(self, indices: np.ndarray) -> None:
            self.indices = indices

        def __len__(self) -> int:
            return len(self.indices)

        def __getitem__(self, item: int) -> dict[str, Any]:
            idx = int(self.indices[item])
            # Append EOS so the model learns to STOP after the graph. Without this the
            # target is only graph tokens followed by masked padding, so the model never
            # sees a stop signal and loops endlessly at generation ("]}]}]}...").
            text = graph_texts[idx]
            if tokenizer.eos_token and not text.endswith(tokenizer.eos_token):
                text = text + tokenizer.eos_token
            encoded = tokenizer(
                text,
                max_length=max_graph_length,
                truncation=True,
                padding="max_length",
                return_tensors="pt",
            )
            input_ids = encoded["input_ids"].squeeze(0)
            attention_mask = encoded["attention_mask"].squeeze(0)
            labels = input_ids.clone()
            labels[attention_mask == 0] = -100
            return {
                "latent": torch.tensor(latents[idx], dtype=torch.float32),
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "labels": labels,
            }

    train_loader = DataLoader(GraphDataset(train_idx), batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(GraphDataset(val_idx), batch_size=batch_size, shuffle=False)
    prefix_params = [p for n, p in model.named_parameters() if "prefix_projector" in n and p.requires_grad]
    base_params = [p for n, p in model.named_parameters() if "prefix_projector" not in n and p.requires_grad]
    param_groups = [{"params": prefix_params, "lr": lr}]
    if base_params:
        param_groups.append({"params": base_params, "lr": lr * base_lr_scale})
    optimizer = torch.optim.AdamW(param_groups)
    use_amp = device_obj.type == "cuda"
    scaler = torch.cuda.amp.GradScaler(enabled=use_amp)

    history: list[dict[str, float]] = []
    for epoch in range(1, epochs + 1):
        model.train()
        train_losses: list[float] = []
        optimizer.zero_grad(set_to_none=True)
        for step, batch in enumerate(train_loader):
            batch = {key: value.to(device_obj) for key, value in batch.items()}
            with torch.cuda.amp.autocast(enabled=use_amp):
                outputs = model(**batch)
                loss = outputs.loss / grad_accum
            scaler.scale(loss).backward()
            if (step + 1) % grad_accum == 0:
                scaler.step(optimizer)
                scaler.update()
                optimizer.zero_grad(set_to_none=True)
            train_losses.append(outputs.loss.item())

        model.eval()
        val_losses: list[float] = []
        with torch.no_grad():
            for batch in val_loader:
                batch = {key: value.to(device_obj) for key, value in batch.items()}
                with torch.cuda.amp.autocast(enabled=use_amp):
                    outputs = model(**batch)
                val_losses.append(outputs.loss.item())

        row = {
            "epoch": float(epoch),
            "decoder_train_loss": float(np.mean(train_losses)),
            "decoder_val_loss": float(np.mean(val_losses)),
        }
        history.append(row)
        print(f"latent-decoder epoch {epoch:02d} | train {row['decoder_train_loss']:.4f} | val {row['decoder_val_loss']:.4f}")

    model.base.config.use_cache = True
    return LatentDecoderArtifacts(
        model=model, tokenizer=tokenizer, history=pd.DataFrame(history), num_prefix_tokens=num_prefix_tokens
    )


def extract_first_json(text: str) -> str:
    """Return the first balanced ``{...}`` object, ignoring any trailing junk."""
    start = text.find("{")
    if start == -1:
        return text.strip()
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        char = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        else:
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return text[start:].strip()


def generate_graphs_from_latents(
    artifacts: LatentDecoderArtifacts,
    latents: np.ndarray,
    indices: Sequence[int],
    max_new_tokens: int = 384,
    repetition_penalty: float = 1.3,
    device: str | None = None,
) -> list[str]:
    """Generate graph JSON strings from latent vectors (embedding -> graph)."""

    torch, _, _ = _require_torch()
    device_obj = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    model = artifacts.model.to(device_obj)
    model.eval()
    model.base.config.use_cache = True
    tokenizer = artifacts.tokenizer
    latents = np.asarray(latents, dtype="float32")

    outputs: list[str] = []
    with torch.no_grad():
        for idx in indices:
            latent = torch.tensor(latents[int(idx)], dtype=torch.float32).unsqueeze(0).to(device_obj)
            generated = model.generate(
                latent,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                num_beams=1,
                repetition_penalty=repetition_penalty,
                no_repeat_ngram_size=0,
                eos_token_id=tokenizer.eos_token_id,
                pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
            )
            decoded = tokenizer.decode(generated[0], skip_special_tokens=True)
            outputs.append(extract_first_json(decoded))
    return outputs
