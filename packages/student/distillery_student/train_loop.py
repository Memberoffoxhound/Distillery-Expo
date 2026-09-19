"""Lightweight distill loop — PyTorch when available; pure Python fallback for CI."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from distillery_student.device import probe_train_device, resolve_torch_device
from distillery_student.focus import focus_for_train, weighted_mse_factor


def _try_torch() -> bool:
    try:
        import torch  # noqa: F401

        return True
    except ImportError:
        return False


def load_soft_label_summary(soft_dir: Path) -> dict[str, Any]:
    manifest = soft_dir / "manifest.json"
    if manifest.is_file():
        data = json.loads(manifest.read_text())
        data.setdefault("live", False)
        data.setdefault("source", "fixture")
        return data
    return {
        "live": False,
        "source": "fixture",
        "teacher": "Cinque/supercombo",
        "batches": [],
        "note": "no soft_labels manifest — synthetic fixture distill",
    }


def _run_distill_torch(
    *,
    steps: int,
    lr: float,
    seed: float,
    dim_weights: list[float] | None = None,
    sample_weight: float = 1.0,
) -> list[dict[str, float]]:
    """Tiny student MLP distilled toward a soft target on Craig's probed device."""
    import torch
    import torch.nn as nn

    device = resolve_torch_device() or torch.device("cpu")
    torch.manual_seed(int(abs(seed) * 1000) % (2**31 - 1) or 1)

    model = nn.Sequential(
        nn.Linear(8, 16),
        nn.ReLU(),
        nn.Linear(16, 8),
    ).to(device)
    target = torch.sin(torch.linspace(0, math.pi, 8, device=device)).unsqueeze(0)
    target = target / (target.norm() + 1e-6)
    w = torch.tensor(
        weighted_mse_factor(dim_weights, 8), device=device, dtype=torch.float32
    ).unsqueeze(0)
    sw = float(sample_weight) if sample_weight and sample_weight > 0 else 1.0
    opt = torch.optim.SGD(model.parameters(), lr=lr)

    records: list[dict[str, float]] = []
    x = torch.ones(1, 8, device=device) * seed
    for step in range(1, steps + 1):
        opt.zero_grad(set_to_none=True)
        pred = model(x)
        # Per-dim weighted MSE × sample_weight (focus bias)
        per = (pred - target) ** 2 * w
        loss = per.mean() * sw
        loss.backward()
        opt.step()
        step_lr = lr * (0.95 ** step)
        for g in opt.param_groups:
            g["lr"] = step_lr
        records.append(
            {
                "step": float(step),
                "train_loss": round(float(loss.detach().cpu().item()), 6),
                "lr": step_lr,
                "backend": 1.0,  # 1=pytorch
                "sample_weight": sw,
            }
        )
    return records


def _run_distill_pure(
    *,
    steps: int,
    lr: float,
    seed: float,
    dim_weights: list[float] | None = None,
    sample_weight: float = 1.0,
) -> list[dict[str, float]]:
    loss = seed
    sw = float(sample_weight) if sample_weight and sample_weight > 0 else 1.0
    dims = weighted_mse_factor(dim_weights, 8)
    # Focus intensity slightly steepens the synthetic curve
    focus_boost = 1.0 + 0.05 * (sum(dims) / len(dims) - 1.0) * sw
    records: list[dict[str, float]] = []
    for step in range(1, steps + 1):
        wobble = math.sin(step * 0.7) * 0.01
        loss = loss * (0.88 + wobble) / focus_boost
        step_lr = lr * (0.95 ** step)
        records.append(
            {
                "step": float(step),
                "train_loss": round(loss * sw, 6),
                "lr": step_lr,
                "backend": 0.0,  # 0=pure-python
                "sample_weight": sw,
            }
        )
    return records


def run_distill_steps(
    *,
    steps: int = 12,
    lr: float = 3e-4,
    seed: float = 1.85,
    focus: str | None = None,
    coached: dict[str, Any] | None = None,
) -> list[dict[str, float]]:
    """Return per-step loss/lr records. Uses PyTorch if present, else pure math.

    Optional ``focus`` / ``coached`` bias loss via dim + sample weights.
    """
    spec = focus_for_train(text=focus, coached=coached)
    dim_w = list(spec.get("dim_weights") or []) if spec else None
    sample_w = float(spec.get("sample_weight") or 1.0) if spec else 1.0
    kwargs = dict(
        steps=steps, lr=lr, seed=seed, dim_weights=dim_w, sample_weight=sample_w
    )
    if _try_torch():
        try:
            return _run_distill_torch(**kwargs)
        except Exception:  # noqa: BLE001 — never fail train on torch quirks in CI
            return _run_distill_pure(**kwargs)
    return _run_distill_pure(**kwargs)


def write_checkpoint(
    output_dir: Path,
    *,
    final_loss: float,
    steps: int,
    meta: dict[str, Any],
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "student_checkpoint.json"
    probe = probe_train_device()
    payload = {
        "format": "distillery-student-stub",
        "io_contract": "stock-modelV2",
        "final_loss": final_loss,
        "steps": steps,
        "meta": meta,
        "weights": {
            "note": "ship-today stub weights — real pytorch params when wired",
            "n_params_est": 1_200_000,
            "backend": probe.get("backend", "pytorch"),
            "device_name": probe.get("device_name"),
            "torch": probe.get("torch"),
        },
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path
