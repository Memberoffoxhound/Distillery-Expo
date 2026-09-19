"""Teacher soft-label compute — PyTorch when available; pure-python fallback.

Uses Craig's ``probe_train_device`` labels (cuda/rocm/mps/cpu). Does not claim
live GPU teach. Soft targets stay labeled fixture unless the pipeline opts into
live via DISTILLERY_TEACHER_LIVE + checkpoint. tinygrad is not required.
"""

from __future__ import annotations

import math
from typing import Any

from distillery_student.device import probe_train_device, resolve_torch_device


def probe_teach_device(*, force_fixture: bool = False) -> dict[str, Any]:
    """Re-export Craig train probe for teach ML path (same torch contract)."""
    return probe_train_device(force_fixture=force_fixture)


def _pseudo_logits_pure(n: int, dims: int = 8, seed: int = 0) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(n):
        row = []
        for d in range(dims):
            v = math.sin((seed + 1) * 0.17 + i * 0.31 + d * 0.47) * 0.5 + 0.5
            row.append(round(v, 5))
        out.append(row)
    return out


def _pseudo_logits_torch(n: int, dims: int = 8, seed: int = 0) -> list[list[float]]:
    import torch

    device = resolve_torch_device() or torch.device("cpu")
    torch.manual_seed((seed + 1) * 17)
    idx = torch.arange(n, device=device, dtype=torch.float32).unsqueeze(1)
    dims_t = torch.arange(dims, device=device, dtype=torch.float32).unsqueeze(0)
    base = torch.sin((seed + 1) * 0.17 + idx * 0.31 + dims_t * 0.47) * 0.5 + 0.5
    weight = torch.ones(dims, dims, device=device) / dims
    out = torch.sigmoid(base @ weight)
    return [[round(float(v), 5) for v in row] for row in out.detach().cpu().tolist()]


def generate_soft_targets(
    *,
    n_samples: int,
    seed: int = 0,
) -> tuple[dict[str, Any], str]:
    """Return (soft_targets dict, backend_name).

    backend_name ∈ {\"pytorch\", \"pure-python\"}.
    """
    probe = probe_train_device()
    if probe.get("torch") == "ok":
        try:
            desire = _pseudo_logits_torch(n_samples, 8, seed=seed)
            plan_lat = _pseudo_logits_torch(n_samples, 4, seed=seed + 10)
            plan_long = _pseudo_logits_torch(n_samples, 4, seed=seed + 20)
            return (
                {
                    "kind": "pytorch",
                    "desire_logits": desire,
                    "plan_lat": plan_lat,
                    "plan_long": plan_long,
                    "device_kind": probe.get("device_kind"),
                    "device_name": probe.get("device_name"),
                },
                "pytorch",
            )
        except Exception:  # noqa: BLE001
            pass
    return (
        {
            "kind": "fixture",
            "desire_logits": _pseudo_logits_pure(n_samples, 8, seed=seed),
            "plan_lat": _pseudo_logits_pure(n_samples, 4, seed=seed + 10),
            "plan_long": _pseudo_logits_pure(n_samples, 4, seed=seed + 20),
        },
        "pure-python",
    )
