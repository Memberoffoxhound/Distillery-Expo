"""PyTorch train-device probe for /health, /ready, and status chips.

Craig (and /health) imports ``probe_train_device`` for a sync status dict.
Reports whatever torch can use (CUDA / ROCm / MPS / CPU). Not 7090-locked.

``force_fixture`` only marks the *data/teacher* path as fixture (live=false) —
it does **not** mean the train device is unavailable. CPU is a valid device.

Graig owns the train/teach PyTorch swap in the loop; this module is the
health / readiness chip only — do not treat tinygrad as the train backend here.
"""

from __future__ import annotations

import os
from typing import Any


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes")


def _cuda_index() -> int:
    try:
        import torch

        return int(torch.cuda.current_device())
    except Exception:  # noqa: BLE001
        return 0


def _probe_torch_device() -> tuple[str, str, str]:
    """Return (torch_status, device_name, device_kind).

    ``device_name`` is a truthful torch device string:
      cuda | cuda:N | rocm | rocm:N | mps | cpu
    """
    try:
        import torch
    except ImportError:
        return "missing", "none", "unknown"

    # ROCm builds expose HIP via torch.version.hip while still using torch.cuda.*
    hip = getattr(getattr(torch, "version", None), "hip", None)
    try:
        cuda_ok = bool(torch.cuda.is_available())
    except Exception:  # noqa: BLE001
        cuda_ok = False

    if cuda_ok:
        idx = _cuda_index()
        if hip:
            name = "rocm" if idx == 0 else f"rocm:{idx}"
            return "ok", name, "gpu"
        name = "cuda" if idx == 0 else f"cuda:{idx}"
        return "ok", name, "gpu"

    try:
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and bool(mps.is_available()):
            return "ok", "mps", "gpu"
    except Exception:  # noqa: BLE001
        pass

    return "ok", "cpu", "cpu"


def _leftover_tinygrad_note() -> dict[str, Any] | None:
    """Optional leftover tinygrad import note — not the train backend."""
    try:
        import tinygrad  # noqa: F401
    except ImportError:
        return None
    try:
        from tinygrad import Device

        backend = str(getattr(Device, "DEFAULT", None) or "CPU")
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "ok",
            "label": "leftover (not train backend)",
            "detail": f"tinygrad importable; Device probe failed: {exc}"[:200],
        }
    return {
        "status": "ok",
        "label": "leftover (not train backend)",
        "detail": (
            f"tinygrad present Device.DEFAULT={backend} — "
            "train device chip uses torch"
        ),
    }


def probe_train_device(*, force_fixture: bool = False) -> dict[str, Any]:
    """Sync train-device probe for health / Craig /ready.

    Keys: device_found, device_ready, device_kind, device_name, torch
    ``torch`` ∈ {ok, missing}; ``device_kind`` ∈ {gpu, cpu, unknown}.
    ``device_name`` ∈ cuda | cuda:N | rocm | rocm:N | mps | cpu | none.

    ``force_fixture`` does not invent a dead device — it only tags
    ``data_source=fixture`` / ``live=false`` for the soft-label path.
    """
    fixture = force_fixture or _env_truthy("DISTILLERY_STUDENT_FIXTURE")
    torch_status, device_name, device_kind = _probe_torch_device()

    leftover = _leftover_tinygrad_note()

    if torch_status == "missing":
        out: dict[str, Any] = {
            "device_found": False,
            "device_ready": False,
            "device_kind": "unknown",
            "device_name": "none",
            "torch": "missing",
            "live": False,
            "source": "probe",
            "data_source": "fixture" if fixture else "live",
            "detail": (
                "torch: missing — install optional dep "
                "(pip install 'distillery-expo[torch]')"
            ),
        }
        if leftover is not None:
            out["tinygrad_note"] = leftover
        return out

    found = device_kind in ("gpu", "cpu") and bool(device_name) and device_name != "none"
    ready = found and torch_status == "ok"
    detail = f"torch device={device_name} kind={device_kind}"
    if fixture:
        detail += "; data path fixture / not licensed"

    out = {
        "device_found": found,
        "device_ready": ready,
        "device_kind": device_kind if found else "unknown",
        "device_name": device_name,
        "torch": "ok",
        "live": False,  # ship-today: never claim licensed/live GPU teach
        "source": "torch",
        "data_source": "fixture" if fixture else "live",
        "detail": detail,
    }
    if leftover is not None:
        out["tinygrad_note"] = leftover
    return out
