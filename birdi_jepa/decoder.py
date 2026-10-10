"""Latent-conditioned target-text decoder built on an encoder-decoder LM.

The original notebook used this module for graph JSON. The same implementation
now also trains typed algorithm-IR repair decoders; the argument names remain
backward-compatible with the graph path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .embedding import _disable_optional_vision_imports


DEFAULT_DECODER_MODEL = "Salesforce/codet5p-770m"


@dataclass
class DecoderArtifacts:
    model: Any
    tokenizer: Any
    history: pd.DataFrame


def _format_decoder_source(problem_text: str, source_prefix: str = "") -> str:
    if not source_prefix:
        return problem_text
    return f"{source_prefix}{problem_text}"


def require_decoder_deps() -> tuple[Any, Any, Any, Any]:
    try:
        _disable_optional_vision_imports()
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader, Dataset
        from transformers import Adafactor, AutoTokenizer, T5ForConditionalGeneration
    except ImportError as exc:
        raise ImportError(
            "Decoder training requires torch and transformers. "
            "Install in Kaggle with: pip install -U transformers accelerate"
        ) from exc
    return torch, nn, Dataset, (DataLoader, AutoTokenizer, T5ForConditionalGeneration, Adafactor)


def build_latent_prefix_model(
    checkpoint: str,
    latent_dim: int,
    num_prefix_tokens: int = 8,
    freeze_base: bool = False,
    enable_gradient_checkpointing: bool = False,
) -> Any:
    torch, nn, _, deps = require_decoder_deps()
    _, _, T5ForConditionalGeneration, _ = deps

    class LatentPrefixT5(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.base = T5ForConditionalGeneration.from_pretrained(checkpoint)
            if enable_gradient_checkpointing and hasattr(self.base, "gradient_checkpointing_enable"):
                self.base.gradient_checkpointing_enable()
                self.base.config.use_cache = False
            d_model = self.base.config.d_model
            self.num_prefix_tokens = num_prefix_tokens
            self.prefix_projector = nn.Sequential(
                nn.LayerNorm(latent_dim),
                nn.Linear(latent_dim, d_model * num_prefix_tokens),
                nn.Tanh(),
            )
            if freeze_base:
                for param in self.base.parameters():
                    param.requires_grad = False

        def _inputs_with_prefix(self, input_ids: Any, attention_mask: Any, latent: Any) -> tuple[Any, Any]:
            token_embeddings = self.base.get_input_embeddings()(input_ids)
            prefix = self.prefix_projector(latent).view(latent.shape[0], self.num_prefix_tokens, -1)
            inputs_embeds = torch.cat([prefix, token_embeddings], dim=1)
            prefix_mask = torch.ones(
                latent.shape[0],
                self.num_prefix_tokens,
                dtype=attention_mask.dtype,
                device=attention_mask.device,
            )
            full_mask = torch.cat([prefix_mask, attention_mask], dim=1)
            return inputs_embeds, full_mask

        def forward(self, input_ids: Any, attention_mask: Any, latent: Any, labels: Any) -> Any:
            inputs_embeds, full_mask = self._inputs_with_prefix(input_ids, attention_mask, latent)
            return self.base(inputs_embeds=inputs_embeds, attention_mask=full_mask, labels=labels)

        def generate(self, input_ids: Any, attention_mask: Any, latent: Any, **kwargs: Any) -> Any:
            inputs_embeds, full_mask = self._inputs_with_prefix(input_ids, attention_mask, latent)
            return self.base.generate(inputs_embeds=inputs_embeds, attention_mask=full_mask, **kwargs)

    return LatentPrefixT5()


def train_latent_decoder(
    problem_texts: Sequence[str],
    graph_texts: Sequence[str],
    predicted_latents: np.ndarray,
    train_idx: np.ndarray,
    val_idx: np.ndarray,
    checkpoint: str = DEFAULT_DECODER_MODEL,
    epochs: int = 2,
    batch_size: int = 4,
    lr: float = 5e-5,
    weight_decay: float = 0.0,
    max_source_length: int = 256,
    max_target_length: int = 512,
    source_prefix: str = "",
    num_prefix_tokens: int = 8,
    freeze_base: bool = False,
    gradient_accumulation_steps: int = 1,
    enable_gradient_checkpointing: bool = False,
    optimizer_name: str = "adamw",
    max_grad_norm: float = 1.0,
    seed: int = 42,
    device: str | None = None,
) -> DecoderArtifacts:
    """Fine-tune a target-text decoder conditioned on predicted target latents."""

    torch, _, Dataset, deps = require_decoder_deps()
    DataLoader, AutoTokenizer, _, Adafactor = deps
    torch.manual_seed(seed)

    tokenizer = AutoTokenizer.from_pretrained(checkpoint)
    model = build_latent_prefix_model(
        checkpoint=checkpoint,
        latent_dim=int(predicted_latents.shape[1]),
        num_prefix_tokens=num_prefix_tokens,
        freeze_base=freeze_base,
        enable_gradient_checkpointing=enable_gradient_checkpointing,
    )
    device_obj = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    model.to(device_obj)

    class GraphDataset(Dataset):
        def __init__(self, indices: np.ndarray) -> None:
            self.indices = indices

        def __len__(self) -> int:
            return len(self.indices)

        def __getitem__(self, item: int) -> dict[str, Any]:
            idx = int(self.indices[item])
            source = tokenizer(
                _format_decoder_source(problem_texts[idx], source_prefix),
                max_length=max_source_length,
                truncation=True,
                padding="max_length",
                return_tensors="pt",
            )
            target = tokenizer(
                graph_texts[idx],
                max_length=max_target_length,
                truncation=True,
                padding="max_length",
                return_tensors="pt",
            )
            labels = target["input_ids"].squeeze(0)
            labels[labels == tokenizer.pad_token_id] = -100
            return {
                "input_ids": source["input_ids"].squeeze(0),
                "attention_mask": source["attention_mask"].squeeze(0),
                "labels": labels,
                "latent": torch.tensor(predicted_latents[idx], dtype=torch.float32),
            }

    train_loader = DataLoader(GraphDataset(train_idx), batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(GraphDataset(val_idx), batch_size=batch_size, shuffle=False)
    trainable_params = [p for p in model.parameters() if p.requires_grad]
    optimizer_key = optimizer_name.lower()
    if optimizer_key == "adafactor":
        optimizer = Adafactor(
            trainable_params,
            lr=lr,
            relative_step=False,
            scale_parameter=False,
            warmup_init=False,
            weight_decay=weight_decay,
        )
    elif optimizer_key == "adamw":
        optimizer = torch.optim.AdamW(trainable_params, lr=lr, weight_decay=weight_decay)
    else:
        raise ValueError("optimizer_name must be 'adafactor' or 'adamw'.")
    # Adafactor has its own internal RMS scaling; AMP GradScaler conflicts with it
    # and produces NaN gradients that get skipped, leaving the model untrained.
    use_amp = device_obj.type == "cuda" and optimizer_key != "adafactor"
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
    accumulation = max(1, int(gradient_accumulation_steps))
    grad_clip = float(max_grad_norm) if max_grad_norm and max_grad_norm > 0 else None

    history: list[dict[str, float]] = []
    for epoch in range(1, epochs + 1):
        model.train()
        train_losses: list[float] = []
        skipped_nonfinite = 0
        optimizer.zero_grad(set_to_none=True)
        for step, batch in enumerate(train_loader, start=1):
            batch = {key: value.to(device_obj) for key, value in batch.items()}
            with torch.amp.autocast("cuda", enabled=use_amp):
                outputs = model(**batch)
                loss = outputs.loss
                scaled_loss = loss / accumulation
            if not torch.isfinite(loss):
                skipped_nonfinite += 1
                optimizer.zero_grad(set_to_none=True)
                continue
            scaler.scale(scaled_loss).backward()
            if step % accumulation == 0 or step == len(train_loader):
                if grad_clip is not None:
                    scaler.unscale_(optimizer)
                    torch.nn.utils.clip_grad_norm_(trainable_params, grad_clip)
                scaler.step(optimizer)
                scaler.update()
                optimizer.zero_grad(set_to_none=True)
            train_losses.append(loss.item())

        model.eval()
        val_losses: list[float] = []
        val_nonfinite = 0
        with torch.no_grad():
            for batch in val_loader:
                batch = {key: value.to(device_obj) for key, value in batch.items()}
                outputs = model(**batch)
                if torch.isfinite(outputs.loss):
                    val_losses.append(outputs.loss.item())
                else:
                    val_nonfinite += 1

        row = {
            "epoch": float(epoch),
            "decoder_train_loss": float(np.mean(train_losses)) if train_losses else float("nan"),
            "decoder_val_loss": float(np.mean(val_losses)) if val_losses else float("nan"),
            "decoder_skipped_nonfinite_train_batches": float(skipped_nonfinite),
            "decoder_nonfinite_val_batches": float(val_nonfinite),
        }
        history.append(row)
        print(
            f"decoder epoch {epoch:02d} | train {row['decoder_train_loss']:.4f} "
            f"| val {row['decoder_val_loss']:.4f} | skipped non-finite train batches {skipped_nonfinite}"
        )

    return DecoderArtifacts(model=model, tokenizer=tokenizer, history=pd.DataFrame(history))


def generate_graph_json(
    artifacts: DecoderArtifacts,
    problem_texts: Sequence[str],
    predicted_latents: np.ndarray,
    indices: Sequence[int],
    max_source_length: int = 256,
    max_new_tokens: int = 256,
    source_prefix: str = "",
    device: str | None = None,
) -> list[str]:
    torch, _, _, _ = require_decoder_deps()
    device_obj = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    model = artifacts.model.to(device_obj)
    tokenizer = artifacts.tokenizer
    model.eval()
    outputs: list[str] = []
    with torch.no_grad():
        for idx in indices:
            encoded = tokenizer(
                _format_decoder_source(problem_texts[int(idx)], source_prefix),
                max_length=max_source_length,
                truncation=True,
                padding="max_length",
                return_tensors="pt",
            )
            latent = torch.tensor(predicted_latents[int(idx)], dtype=torch.float32).unsqueeze(0)
            generated = model.generate(
                input_ids=encoded["input_ids"].to(device_obj),
                attention_mask=encoded["attention_mask"].to(device_obj),
                latent=latent.to(device_obj),
                max_new_tokens=max_new_tokens,
                num_beams=2,
            )
            outputs.append(tokenizer.decode(generated[0], skip_special_tokens=True))
    return outputs
