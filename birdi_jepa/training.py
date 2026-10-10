"""JEPA latent predictor training utilities."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .algorithm_ir import ir_from_code
from .state_graph import build_problem_text, graph_from_code


@dataclass
class PreparedData:
    frame: pd.DataFrame
    problem_texts: list[str]
    graph_texts: list[str]
    ir_texts: list[str]


def prepare_dataframe(
    csv_path: str | Path,
    max_rows: int | None = None,
    seed: int = 42,
    min_confidence: float = 0.0,
    always_include_keywords: Sequence[str] | None = None,
) -> PreparedData:
    """Load the CSV and add problem text plus pseudo-label graph JSON/IR."""

    df = pd.read_csv(csv_path)
    required = {"Instruction", "Input", "Output"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"CSV is missing required columns: {sorted(missing)}")

    df = df.dropna(subset=["Instruction", "Output"]).copy()
    if max_rows is not None and max_rows < len(df):
        keyword_mask = _keyword_mask(df, always_include_keywords)
        focused = df[keyword_mask]
        pool = df[~keyword_mask]
        if len(focused) >= max_rows:
            df = focused.sample(n=max_rows, random_state=seed).reset_index(drop=True)
        else:
            fill_count = max_rows - len(focused)
            if fill_count < len(pool):
                pool = pool.sample(n=fill_count, random_state=seed)
            df = pd.concat([focused, pool], ignore_index=True).sample(frac=1.0, random_state=seed).reset_index(drop=True)
    else:
        df = df.reset_index(drop=True)

    problem_texts: list[str] = []
    graph_texts: list[str] = []
    ir_texts: list[str] = []
    confidences: list[float] = []
    ir_confidences: list[float] = []
    parse_ok: list[bool] = []
    ir_parse_ok: list[bool] = []
    node_counts: list[int] = []
    edge_counts: list[int] = []

    for row in df.itertuples(index=False):
        graph = graph_from_code(row.Instruction, row.Input, row.Output)
        ir = ir_from_code(row.Instruction, row.Input, row.Output)
        problem_texts.append(build_problem_text(row.Instruction, row.Input))
        graph_texts.append(graph.to_canonical_json())
        ir_texts.append(ir.to_text())
        confidences.append(graph.confidence)
        ir_confidences.append(ir.confidence)
        parse_ok.append(bool(graph.metadata.get("parse_ok")))
        ir_parse_ok.append(bool(ir.metadata.get("parse_ok")))
        node_counts.append(len(graph.nodes))
        edge_counts.append(len(graph.edges))

    df["problem_text"] = problem_texts
    df["state_graph_text"] = graph_texts
    df["algorithm_ir_text"] = ir_texts
    df["pseudo_label_confidence"] = confidences
    df["algorithm_ir_confidence"] = ir_confidences
    df["pseudo_label_parse_ok"] = parse_ok
    df["algorithm_ir_parse_ok"] = ir_parse_ok
    df["state_graph_nodes"] = node_counts
    df["state_graph_edges"] = edge_counts

    if min_confidence > 0:
        df = df[df["pseudo_label_confidence"] >= min_confidence].reset_index(drop=True)
        problem_texts = df["problem_text"].tolist()
        graph_texts = df["state_graph_text"].tolist()
        ir_texts = df["algorithm_ir_text"].tolist()

    return PreparedData(frame=df, problem_texts=problem_texts, graph_texts=graph_texts, ir_texts=ir_texts)


def nearest_indices(
    query_embeddings: np.ndarray,
    target_embeddings: np.ndarray,
    top_k: int = 5,
    exclude_self: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """Return nearest target indices and cosine scores for each query embedding."""

    query = np.asarray(query_embeddings, dtype="float32")
    target = np.asarray(target_embeddings, dtype="float32")
    if query.ndim == 1:
        query = query[None, :]
    query = query / np.maximum(np.linalg.norm(query, axis=1, keepdims=True), 1e-12)
    target = target / np.maximum(np.linalg.norm(target, axis=1, keepdims=True), 1e-12)
    sims = query @ target.T
    if exclude_self:
        if sims.shape[0] != sims.shape[1]:
            raise ValueError("exclude_self=True requires query and target to have the same length.")
        np.fill_diagonal(sims, -np.inf)
    k = max(1, min(int(top_k), sims.shape[1]))
    idx = np.argpartition(-sims, kth=k - 1, axis=1)[:, :k]
    row = np.arange(sims.shape[0])[:, None]
    order = np.argsort(-sims[row, idx], axis=1)
    idx = idx[row, order]
    scores = sims[row, idx]
    return idx.astype(np.int64), scores.astype("float32")


def _keyword_mask(df: pd.DataFrame, keywords: Sequence[str] | None) -> pd.Series:
    if not keywords:
        return pd.Series(False, index=df.index)
    pattern = "|".join(re.escape(str(keyword).strip()) for keyword in keywords if str(keyword).strip())
    if not pattern:
        return pd.Series(False, index=df.index)
    haystack = (
        df["Instruction"].fillna("").astype(str)
        + " "
        + df.get("Input", pd.Series("", index=df.index)).fillna("").astype(str)
    )
    return haystack.str.contains(pattern, case=False, regex=True, na=False)


def train_val_split(n_items: int, val_fraction: float = 0.1, seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    indices = list(range(n_items))
    random.Random(seed).shuffle(indices)
    val_size = max(1, int(n_items * val_fraction))
    val_idx = np.array(indices[:val_size], dtype=np.int64)
    train_idx = np.array(indices[val_size:], dtype=np.int64)
    return train_idx, val_idx


def require_torch() -> Any:
    try:
        import torch
    except ImportError as exc:
        raise ImportError("PyTorch is required for JEPA training.") from exc
    return torch


def require_torch_modules() -> tuple[Any, Any, Any]:
    torch = require_torch()
    import torch.nn as nn
    import torch.nn.functional as F

    return torch, nn, F


def make_predictor(input_dim: int, target_dim: int, hidden_dim: int = 1024, dropout: float = 0.1) -> Any:
    torch, nn, F = require_torch_modules()

    class ResidualMLPPredictor(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.input_projection = nn.Linear(input_dim, target_dim) if input_dim != target_dim else nn.Identity()
            self.net = nn.Sequential(
                nn.LayerNorm(input_dim),
                nn.Linear(input_dim, hidden_dim),
                nn.GELU(),
                nn.Dropout(dropout),
                nn.Linear(hidden_dim, target_dim),
            )
            self.output_norm = nn.LayerNorm(target_dim)

        def forward(self, x: Any) -> Any:
            residual = self.input_projection(x)
            z = residual + self.net(x)
            return F.normalize(self.output_norm(z), p=2, dim=-1)

    return ResidualMLPPredictor()


def jepa_mse_loss(pred: Any, target: Any) -> Any:
    _, _, F = require_torch_modules()
    pred = F.normalize(pred, p=2, dim=-1)
    target = F.normalize(target.detach(), p=2, dim=-1)
    return ((pred - target) ** 2).sum(dim=-1).mean()


def contrastive_loss(pred: Any, target: Any, temperature: float = 0.05) -> Any:
    torch, _, F = require_torch_modules()
    pred = F.normalize(pred, p=2, dim=-1)
    target = F.normalize(target.detach(), p=2, dim=-1)
    logits = pred @ target.T / temperature
    labels = torch.arange(pred.shape[0], device=pred.device)
    return 0.5 * (F.cross_entropy(logits, labels) + F.cross_entropy(logits.T, labels))


def vicreg_variance_covariance_loss(pred: Any, variance_target: float = 0.02) -> tuple[Any, Any]:
    """Small anti-collapse regularizer for normalized predicted latents.

    Predicted latents are L2-normalized, so their healthy per-dimension standard
    deviation is around ``1 / sqrt(dim)``. A target near 0.02 is intentionally
    gentle for 1024-d embeddings: it discourages identical predictions without
    overpowering the frozen target-graph alignment objective.
    """

    torch, _, _ = require_torch_modules()
    if pred.shape[0] <= 1:
        zero = pred.sum() * 0.0
        return zero, zero
    centered = pred - pred.mean(dim=0, keepdim=True)
    std = torch.sqrt(centered.var(dim=0, unbiased=False) + 1e-4)
    variance = torch.relu(float(variance_target) - std).mean()
    cov = centered.T @ centered / max(1, pred.shape[0] - 1)
    off_diag = cov - torch.diag(torch.diag(cov))
    covariance = off_diag.pow(2).sum() / pred.shape[1]
    return variance, covariance


def latent_collapse_metrics(pred: Any) -> dict[str, float]:
    """Return lightweight diagnostics for representational collapse."""

    torch, _, F = require_torch_modules()
    pred = F.normalize(pred, p=2, dim=-1)
    dim_std = pred.std(dim=0, unbiased=False)
    if pred.shape[0] > 1:
        sim = pred @ pred.T
        mask = ~torch.eye(pred.shape[0], dtype=torch.bool, device=pred.device)
        offdiag = sim[mask]
        offdiag_mean = offdiag.mean().item()
        offdiag_p95 = torch.quantile(offdiag, 0.95).item()
    else:
        offdiag_mean = 1.0
        offdiag_p95 = 1.0
    return {
        "pred_dim_std_mean": dim_std.mean().item(),
        "pred_dim_std_min": dim_std.min().item(),
        "pred_offdiag_cos_mean": float(offdiag_mean),
        "pred_offdiag_cos_p95": float(offdiag_p95),
    }


def retrieval_metrics(pred: Any, target: Any, ks: tuple[int, ...] = (1, 5, 10)) -> dict[str, float]:
    torch = require_torch()
    import torch.nn.functional as F

    pred = F.normalize(pred, p=2, dim=-1)
    target = F.normalize(target, p=2, dim=-1)
    sim = pred @ target.T
    ranks = torch.argsort(sim, dim=1, descending=True)
    labels = torch.arange(sim.shape[0], device=sim.device).unsqueeze(1)
    correct_positions = (ranks == labels).nonzero(as_tuple=False)[:, 1] + 1
    metrics = {
        "mean_cosine": sim.diag().mean().item(),
        "mrr": (1.0 / correct_positions.float()).mean().item(),
    }
    for k in ks:
        metrics[f"retrieval_at_{k}"] = (correct_positions <= k).float().mean().item()
    return metrics


def embedding_diagnostics(embeddings: np.ndarray, sample_size: int = 512, seed: int = 42) -> dict[str, float]:
    """Summarize whether an embedding set has collapsed.

    A mean off-diagonal cosine near 1.0 means most vectors point in the same
    direction. That is exactly the failure mode where every downstream decoded
    graph/code sample becomes the same high-frequency solution.
    """

    arr = np.asarray(embeddings, dtype="float32")
    if len(arr) == 0:
        raise ValueError("Cannot diagnose an empty embedding array.")
    rng = np.random.default_rng(seed)
    if len(arr) > sample_size:
        idx = rng.choice(len(arr), size=sample_size, replace=False)
        arr = arr[idx]
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    normed = arr / np.maximum(norms, 1e-12)
    sim = normed @ normed.T
    mask = ~np.eye(sim.shape[0], dtype=bool)
    off_diag = sim[mask]
    centered = normed - normed.mean(axis=0, keepdims=True)
    dim_std = centered.std(axis=0)
    try:
        singular_values = np.linalg.svd(centered, compute_uv=False)
        probs = singular_values / max(float(singular_values.sum()), 1e-12)
        effective_rank = float(np.exp(-(probs * np.log(np.maximum(probs, 1e-12))).sum()))
    except np.linalg.LinAlgError:
        effective_rank = 0.0
    return {
        "n": float(len(arr)),
        "dim": float(arr.shape[1]),
        "norm_mean": float(norms.mean()),
        "norm_std": float(norms.std()),
        "dim_std_mean": float(dim_std.mean()),
        "dim_std_min": float(dim_std.min()),
        "effective_rank": effective_rank,
        "offdiag_cos_mean": float(off_diag.mean()) if len(off_diag) else 1.0,
        "offdiag_cos_std": float(off_diag.std()) if len(off_diag) else 0.0,
        "offdiag_cos_p95": float(np.quantile(off_diag, 0.95)) if len(off_diag) else 1.0,
    }


def train_jepa_predictor(
    problem_embeddings: np.ndarray,
    target_embeddings: np.ndarray,
    epochs: int = 12,
    batch_size: int = 64,
    lr: float = 1e-3,
    weight_decay: float = 1e-4,
    contrastive_weight: float = 0.2,
    temperature: float = 0.05,
    variance_weight: float = 0.0,
    covariance_weight: float = 0.0,
    variance_target: float = 0.02,
    hidden_dim: int = 1024,
    val_fraction: float = 0.1,
    seed: int = 42,
    device: str | None = None,
) -> tuple[Any, pd.DataFrame, dict[str, np.ndarray]]:
    """Train the problem embedding -> state graph embedding predictor."""

    torch, _, _ = require_torch_modules()
    from torch.utils.data import DataLoader, TensorDataset

    torch.manual_seed(seed)
    np.random.seed(seed)
    random.seed(seed)

    problem_embeddings = np.asarray(problem_embeddings, dtype="float32")
    target_embeddings = np.asarray(target_embeddings, dtype="float32")
    if len(problem_embeddings) != len(target_embeddings):
        raise ValueError("problem_embeddings and target_embeddings must have the same length.")

    train_idx, val_idx = train_val_split(len(problem_embeddings), val_fraction=val_fraction, seed=seed)
    train_ds = TensorDataset(
        torch.tensor(problem_embeddings[train_idx]),
        torch.tensor(target_embeddings[train_idx]),
    )
    val_problem = torch.tensor(problem_embeddings[val_idx])
    val_target = torch.tensor(target_embeddings[val_idx])

    device_obj = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    model = make_predictor(problem_embeddings.shape[1], target_embeddings.shape[1], hidden_dim=hidden_dim).to(device_obj)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True, drop_last=len(train_ds) > batch_size)

    history: list[dict[str, float]] = []
    for epoch in range(1, epochs + 1):
        model.train()
        train_losses: list[float] = []
        train_jepa: list[float] = []
        train_contrastive: list[float] = []
        train_variance: list[float] = []
        train_covariance: list[float] = []
        for xb, yb in loader:
            xb = xb.to(device_obj)
            yb = yb.to(device_obj)
            optimizer.zero_grad(set_to_none=True)
            pred = model(xb)
            loss_jepa = jepa_mse_loss(pred, yb)
            loss_contrastive = contrastive_loss(pred, yb, temperature=temperature)
            loss_variance, loss_covariance = vicreg_variance_covariance_loss(pred, variance_target=variance_target)
            loss = (
                loss_jepa
                + contrastive_weight * loss_contrastive
                + variance_weight * loss_variance
                + covariance_weight * loss_covariance
            )
            loss.backward()
            optimizer.step()
            train_losses.append(loss.item())
            train_jepa.append(loss_jepa.item())
            train_contrastive.append(loss_contrastive.item())
            train_variance.append(loss_variance.item())
            train_covariance.append(loss_covariance.item())

        model.eval()
        with torch.no_grad():
            val_pred = model(val_problem.to(device_obj))
            val_target_device = val_target.to(device_obj)
            val_jepa = jepa_mse_loss(val_pred, val_target_device).item()
            val_contrastive = contrastive_loss(val_pred, val_target_device, temperature=temperature).item()
            val_variance, val_covariance = vicreg_variance_covariance_loss(
                val_pred,
                variance_target=variance_target,
            )
            val_loss = (
                val_jepa
                + contrastive_weight * val_contrastive
                + variance_weight * val_variance.item()
                + covariance_weight * val_covariance.item()
            )
            metrics = retrieval_metrics(val_pred, val_target_device)
            collapse = latent_collapse_metrics(val_pred)

        row = {
            "epoch": float(epoch),
            "train_loss": float(np.mean(train_losses)),
            "train_jepa": float(np.mean(train_jepa)),
            "train_contrastive": float(np.mean(train_contrastive)),
            "train_variance": float(np.mean(train_variance)),
            "train_covariance": float(np.mean(train_covariance)),
            "val_loss": float(val_loss),
            "val_jepa": float(val_jepa),
            "val_contrastive": float(val_contrastive),
            "val_variance": float(val_variance.item()),
            "val_covariance": float(val_covariance.item()),
            **metrics,
            **collapse,
        }
        history.append(row)
        print(
            f"epoch {epoch:02d} | train {row['train_loss']:.4f} | "
            f"val {row['val_loss']:.4f} | cos {row['mean_cosine']:.4f} | "
            f"R@1 {row['retrieval_at_1']:.3f} | R@5 {row['retrieval_at_5']:.3f} | "
            f"std {row['pred_dim_std_mean']:.4f} | offdiag {row['pred_offdiag_cos_mean']:.4f}"
        )

    return model, pd.DataFrame(history), {"train_idx": train_idx, "val_idx": val_idx}


def predict_embeddings(model: Any, embeddings: np.ndarray, batch_size: int = 256, device: str | None = None) -> np.ndarray:
    torch = require_torch()
    from torch.utils.data import DataLoader, TensorDataset

    device_obj = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    model = model.to(device_obj)
    model.eval()
    loader = DataLoader(TensorDataset(torch.tensor(embeddings.astype("float32"))), batch_size=batch_size)
    preds: list[np.ndarray] = []
    with torch.no_grad():
        for (xb,) in loader:
            preds.append(model(xb.to(device_obj)).cpu().numpy())
    return np.concatenate(preds, axis=0).astype("float32")
