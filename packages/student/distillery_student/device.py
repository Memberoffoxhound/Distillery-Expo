"""Tinygrad-compatible train device probe — not locked to any single GPU SKU.

Craig (and /health) can import ``probe_train_device`` for a sync status dict.
Reports whatever tinygrad can use (GPU if present, else CPU/other).
"""

from __future__ import annotations

import os
from typing import Any

_GPU_HINTS = (
    "GPU",
    "CUDA",
    "NV",
    "HIP",
    "ROCM",
    "METAL",
    "CL",
    "OPENCL",
    "VULKAN",
    "WEBGPU",
    "QCOM",
    "AMD",
)


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes")


def _classify_kind(name: str) -> str:
    upper = (name or "").upper()
    if not upper or upper in ("NONE", "UNKNOWN", "FIXTURE"):
        return "unknown"
    if upper == "CPU" or upper.startswith("CPU"):
        return "cpu"
    for hint in _GPU_HINTS:
        if hint in upper:
            return "gpu"
    return "unknown"


def _probe_tinygrad_device() -> tuple[str, str, str]:
    """Return (tinygrad_status, device_name, device_kind)."""
    try:
        import tinygrad  # noqa: F401
    except ImportError:
        return "missing", "none", "unknown"

    name = "CPU"
    try:
        from tinygrad import Device

        raw = getattr(Device, "DEFAULT", None)
        if raw is not None:
            name = str(raw)
    except Exception:  # noqa: BLE001
        name = "CPU"
    return "ok", name, _classify_kind(name)


def probe_train_device(*, force_fixture: bool = False) -> dict[str, Any]:
    """Sync train-device probe for health / Craig.

    Keys: device_found, device_ready, device_kind, device_name, tinygrad
    ``tinygrad`` ∈ {ok, missing, fixture}; ``device_kind`` ∈ {gpu, cpu, unknown}.
    """
    if force_fixture or _env_truthy("DISTILLERY_STUDENT_FIXTURE"):
        return {
            "device_found": False,
            "device_ready": False,
            "device_kind": "unknown",
            "device_name": "fixture",
            "tinygrad": "fixture",
            "live": False,
            "source": "fixture",
            "detail": "force_fixture — train device probe labeled live=false / not licensed",
        }

    tg_status, device_name, device_kind = _probe_tinygrad_device()
    if tg_status == "missing":
        return {
            "device_found": False,
            "device_ready": False,
            "device_kind": "unknown",
            "device_name": "none",
            "tinygrad": "missing",
            "live": False,
            "source": "probe",
            "detail": "tinygrad not installed — cannot bind a train device",
        }

    found = device_kind != "unknown" or bool(device_name and device_name.lower() != "none")
    ready = found and tg_status == "ok"
    return {
        "device_found": found,
        "device_ready": ready,
        "device_kind": device_kind if found else "unknown",
        "device_name": device_name,
        "tinygrad": "ok",
        "live": False,
        "source": "tinygrad",
        "detail": f"tinygrad Device.DEFAULT={device_name} kind={device_kind}",
    }
