"""Graph autoencoder: learn a DECODABLE latent for state/data-flow graphs.

Earlier the pipeline used a frozen retrieval embedding (Qwen3-Embedding) as the
target latent. Retrieval embeddings place similar graphs nearby but are NOT
invertible -- the encoder was never trained so the graph can be reconstructed
from the vector, so a decoder cannot reliably recover it.

Here we instead fine-tune a pretrained encoder-decoder (CodeT5+) JOINTLY as a
bottleneck autoencoder: graph -> encoder -> z (pooled, fixed-size) -> decoder ->
graph. Because the same training optimises reconstruction *through* z, the latent
is decodable by construction. The JEPA predictor then learns problem -> z, and at
inference the same decoder turns the predicted latent back into a graph.

A small amount of noise is added to z during training (denoising AE) so the
decoder tolerates the gap between the true z and the JEPA-predicted z_pred.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .embedding import _disable_optional_vision_imports


DEFAULT_AUTOENCODER_MODEL = "Salesforce/codet5p-220m"


@dataclass
class AutoencoderArtifacts:
    model: Any
    tokenizer: Any
    history: pd.DataFrame
    latent_dim: int


def _require() -> tuple[Any, Any, tuple]:
    _disable_optional_vision_imports()
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, Dataset
    from transformers import AutoTokenizer, T5ForConditionalGeneration
    from transformers.modeling_outputs import BaseModelOutput

    return torch, nn, (DataLoader, Dataset, AutoTokenizer, T5ForConditionalGeneration, BaseModelOutput)


def build_graph_autoencoder(checkpoint: str, num_memory_tokens: int = 16, latent_dim: int = 256) -> Any:
    torch, nn, deps = _require()
    _, _, _, T5ForConditionalGeneration, BaseModelOutput = deps

    class GraphAutoencoder(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.t5 = T5ForConditionalGeneration.from_pretrained(checkpoint)
            d_model = self.t5.config.d_model
            self.d_model = d_model
            self.latent_dim = latent_dim
            self.num_memory_tokens = num_memory_tokens
            # graph -> pooled encoder state -> latent bottleneck
            self.to_latent = nn.Sequential(nn.LayerNorm(d_model), nn.Linear(d_model, latent_dim))
            # latent -> decoder cross-attention memory
            self.from_latent = nn.Sequential(
                nn.Linear(latent_dim, d_model * num_memory_tokens), nn.GELU()
            )

        def encode(self, input_ids: Any, attention_mask: Any, normalize: bool = True) -> Any:
            encoder = self.t5.get_encoder()
            hidden = encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
            mask = attention_mask.unsqueeze(-1).to(hidden.dtype)
            pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-6)
            z = self.to_latent(pooled)
            if normalize:
                z = torch.nn.functional.normalize(z, p=2, dim=-1)
            return z

        def _memory(self, z: Any) -> Any:
            mem = self.from_latent(z).view(z.shape[0], self.num_memory_tokens, self.d_model)
            return mem

        def forward(self, input_ids: Any, attention_mask: Any, labels: Any, latent_noise: float = 0.0) -> Any:
            z = self.encode(input_ids, attention_mask, normalize=True)
            if latent_noise > 0:
                z = torch.nn.functional.normalize(z + latent_noise * torch.randn_like(z), p=2, dim=-1)
            mem = self._memory(z)
            mem_mask = torch.ones(
                z.shape[0], self.num_memory_tokens, dtype=attention_mask.dtype, device=z.device
            )
            return self.t5(
                encoder_outputs=BaseModelOutput(last_hidden_state=mem),
                attention_mask=mem_mask,
                labels=labels,
            )

        @torch.no_grad()
        def generate_from_latent(self, z: Any, max_new_tokens: int = 384, **kwargs: Any) -> Any:
            mem = self._memory(z)
            mem_mask = torch.ones(
                z.shape[0], self.num_memory_tokens, dtype=torch.long, device=z.device
            )
            return self.t5.generate(
                encoder_outputs=BaseModelOutput(last_hidden_state=mem),
                attention_mask=mem_mask,
                max_new_tokens=max_new_tokens,
                **kwargs,
            )

    return GraphAutoencoder()


def train_graph_autoencoder(
    graph_texts: Sequence[str],
    train_idx: np.ndarray,
    val_idx: np.ndarray,
    checkpoint: str = DEFAULT_AUTOENCODER_MODEL,
    num_memory_tokens: int = 16,
    latent_dim: int = 256,
    epochs: int = 8,
    batch_size: int = 8,
    lr: float = 3e-4,
    latent_noise: float = 0.1,
    max_graph_length: int = 512,
    seed: int = 42,
    device: str | None = None,
) -> AutoencoderArtifacts:
    """Fine-tune a CodeT5+ encoder-decoder jointly as a graph autoencoder."""

    torch, _, deps = _require()
    DataLoader, Dataset, AutoTokenizer, _, _ = deps
    torch.manual_seed(seed)

    tokenizer = AutoTokenizer.from_pretrained(checkpoint)
    device_obj = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    model = build_graph_autoencoder(checkpoint, num_memory_tokens=num_memory_tokens, latent_dim=latent_dim)
    model.to(device_obj)

    class GraphDataset(Dataset):
        def __init__(self, indices: np.ndarray) -> None:
            self.indices = indices

        def __len__(self) -> int:
            return len(self.indices)

        def __getitem__(self, item: int) -> dict[str, Any]:
            idx = int(self.indices[item])
            encoded = tokenizer(
                graph_texts[idx],
                max_length=max_graph_length,
                truncation=True,
                padding="max_length",
                return_tensors="pt",
            )
            input_ids = encoded["input_ids"].squeeze(0)
            attention_mask = encoded["attention_mask"].squeeze(0)
            labels = input_ids.clone()
            labels[attention_mask == 0] = -100
            return {"input_ids": input_ids, "attention_mask": attention_mask, "labels": labels}

    train_loader = DataLoader(GraphDataset(train_idx), batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(GraphDataset(val_idx), batch_size=batch_size, shuffle=False)
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=lr)
    use_amp = device_obj.type == "cuda"
    scaler = torch.cuda.amp.GradScaler(enabled=use_amp)

    history: list[dict[str, float]] = []
    for epoch in range(1, epochs + 1):
        model.train()
        train_losses: list[float] = []
        for batch in train_loader:
            batch = {key: value.to(device_obj) for key, value in batch.items()}
            optimizer.zero_grad(set_to_none=True)
            with torch.cuda.amp.autocast(enabled=use_amp):
                outputs = model(**batch, latent_noise=latent_noise)
                loss = outputs.loss
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
            train_losses.append(loss.item())

        model.eval()
        val_losses: list[float] = []
        with torch.no_grad():
            for batch in val_loader:
                batch = {key: value.to(device_obj) for key, value in batch.items()}
                with torch.cuda.amp.autocast(enabled=use_amp):
                    outputs = model(**batch, latent_noise=0.0)
                val_losses.append(outputs.loss.item())

        row = {
            "epoch": float(epoch),
            "ae_train_loss": float(np.mean(train_losses)),
            "ae_val_loss": float(np.mean(val_losses)),
        }
        history.append(row)
        print(f"graph-AE epoch {epoch:02d} | train {row['ae_train_loss']:.4f} | val {row['ae_val_loss']:.4f}")

    return AutoencoderArtifacts(
        model=model, tokenizer=tokenizer, history=pd.DataFrame(history), latent_dim=latent_dim
    )


def encode_graphs(
    artifacts: AutoencoderArtifacts,
    graph_texts: Sequence[str],
    indices: Sequence[int],
    batch_size: int = 16,
    max_graph_length: int = 512,
    device: str | None = None,
) -> np.ndarray:
    """Map graphs to their (normalized, decodable) autoencoder latents."""

    torch, _, _ = _require()
    device_obj = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    model = artifacts.model.to(device_obj)
    model.eval()
    tokenizer = artifacts.tokenizer
    indices = [int(i) for i in indices]

    chunks: list[np.ndarray] = []
    with torch.no_grad():
        for start in range(0, len(indices), batch_size):
            batch_idx = indices[start : start + batch_size]
            texts = [graph_texts[j] for j in batch_idx]
            encoded = tokenizer(
                texts, max_length=max_graph_length, truncation=True, padding=True, return_tensors="pt"
            ).to(device_obj)
            z = model.encode(encoded["input_ids"], encoded["attention_mask"], normalize=True)
            chunks.append(z.float().cpu().numpy())
    return np.concatenate(chunks, axis=0).astype("float32")


def decode_latents(
    artifacts: AutoencoderArtifacts,
    latents: np.ndarray,
    indices: Sequence[int],
    max_new_tokens: int = 384,
    num_beams: int = 4,
    device: str | None = None,
) -> list[str]:
    """Decode latent vectors back into graph JSON (latent -> graph)."""

    torch, _, _ = _require()
    device_obj = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    model = artifacts.model.to(device_obj)
    model.eval()
    tokenizer = artifacts.tokenizer
    latents = np.asarray(latents, dtype="float32")

    outputs: list[str] = []
    with torch.no_grad():
        for idx in indices:
            z = torch.tensor(latents[int(idx)], dtype=torch.float32).unsqueeze(0).to(device_obj)
            generated = model.generate_from_latent(z, max_new_tokens=max_new_tokens, num_beams=num_beams)
            outputs.append(tokenizer.decode(generated[0], skip_special_tokens=True))
    return outputs
