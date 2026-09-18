"""Tinygrad-compatible train device probe — not locked to any single GPU SKU.

Craig (and /health) can import ``probe_train_device`` for a sync status dict.
Reports whatever tinygrad can use (GPU if present, else CPU/other).

``force_fixture`` only marks the *data/teacher* path as fixture (live=false) —
it does **not** mean the train device is unavailable. CPU is a valid device.
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
    if not upper or upper in ("NONE", "UNKNOWN"):
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
    ``tinygrad`` ∈ {ok, missing}; ``device_kind`` ∈ {gpu, cpu, unknown}.

    ``force_fixture`` does not invent a dead device — it only tags
    ``data_source=fixture`` / ``live=false`` for the soft-label path.
    """
    fixture = force_fixture or _env_truthy("DISTILLERY_STUDENT_FIXTURE")
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
            "data_source": "fixture" if fixture else "live",
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
        "live": False,  # ship-today: never claim licensed/live GPU teach
        "source": "tinygrad",
        "data_source": "fixture" if fixture else "live",
        "detail": (
            f"tinygrad Device.DEFAULT={device_name} kind={device_kind}"
            + ("; data path fixture / not licensed" if fixture else "")
        ),
    }
