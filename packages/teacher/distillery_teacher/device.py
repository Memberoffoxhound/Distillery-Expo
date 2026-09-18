"""Detect AMD / ROCm / 7090 XT teacher GPU — never claim live if absent."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TeacherDeviceInfo:
    available: bool
    live: bool
    backend: str  # "rocm" | "amdgpu" | "fixture" | "none"
    device: str
    detail: str
    meta: dict[str, Any]


def _rocm_smi_present() -> bool:
    return shutil.which("rocm-smi") is not None


def _read_amdgpu_names() -> list[str]:
    names: list[str] = []
    drm = "/sys/class/drm"
    if not os.path.isdir(drm):
        return names
    try:
        for entry in sorted(os.listdir(drm)):
            if not entry.startswith("card") or "-" in entry:
                continue
            for rel in (
                f"{entry}/device/product_name",
                f"{entry}/device/label",
                f"{entry}/device/uevent",
            ):
                path = os.path.join(drm, rel)
                if not os.path.isfile(path):
                    continue
                try:
                    text = open(path, encoding="utf-8", errors="ignore").read().strip()
                except OSError:
                    continue
                if "product_name" in rel or "label" in rel:
                    if text:
                        names.append(text)
                elif "PCI_ID=1002:" in text or "DRIVER=amdgpu" in text:
                    names.append("amdgpu")
    except OSError:
        pass
    return names


def _looks_like_7090(names: list[str]) -> bool:
    blob = " ".join(names).lower()
    return "7090" in blob or "rx 7090" in blob


def detect_teacher_device(*, force_fixture: bool = False) -> TeacherDeviceInfo:
    """Probe for AMD/ROCm teacher GPU. Fixture path is explicitly non-live."""
    if force_fixture or os.environ.get("DISTILLERY_TEACHER_FIXTURE", "").lower() in (
        "1",
        "true",
        "yes",
    ):
        return TeacherDeviceInfo(
            available=False,
            live=False,
            backend="fixture",
            device="fixture",
            detail="force_fixture — soft labels from fixture (live=false)",
            meta={"live": False, "source": "fixture", "teacher": "Cinque/supercombo"},
        )

    names = _read_amdgpu_names()
    has_rocm = _rocm_smi_present()
    rocm_out = ""
    if has_rocm:
        try:
            proc = subprocess.run(
                ["rocm-smi", "--showproductname"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            rocm_out = (proc.stdout or "") + (proc.stderr or "")
        except (OSError, subprocess.TimeoutExpired):
            rocm_out = ""

    combined = names + ([rocm_out] if rocm_out else [])
    is_7090 = _looks_like_7090(combined)
    has_amd = bool(names) or has_rocm or "amdgpu" in " ".join(combined).lower()

    if is_7090 and has_amd:
        return TeacherDeviceInfo(
            available=True,
            live=True,
            backend="rocm" if has_rocm else "amdgpu",
            device="7090 XT",
            detail="AMD Radeon RX 7090 XT detected — live Cinque/supercombo path",
            meta={
                "live": True,
                "source": "device",
                "teacher": "Cinque/supercombo",
                "device": "7090 XT",
                "backend": "rocm" if has_rocm else "amdgpu",
            },
        )

    if has_amd:
        return TeacherDeviceInfo(
            available=False,
            live=False,
            backend="fixture",
            device="fixture",
            detail=(
                "AMD GPU seen but not confirmed 7090 XT / no live Cinque weights — "
                "using fixture soft labels (live=false)"
            ),
            meta={
                "live": False,
                "source": "fixture",
                "teacher": "Cinque/supercombo",
                "amd_names": names[:5],
                "rocm_smi": has_rocm,
            },
        )

    return TeacherDeviceInfo(
        available=False,
        live=False,
        backend="fixture",
        device="fixture",
        detail="No AMD/ROCm/7090 XT detected — fixture soft labels (live=false)",
        meta={
            "live": False,
            "source": "fixture",
            "teacher": "Cinque/supercombo",
            "device": "fixture",
        },
    )
