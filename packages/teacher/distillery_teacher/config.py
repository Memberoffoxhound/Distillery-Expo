"""Teacher settings from configs/default.yaml (+ env overrides)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CONFIG = _REPO_ROOT / "configs" / "default.yaml"

DEFAULT_TEACHER = "Cinque/supercombo"
DEFAULT_DEVICE_LABEL = "7090 XT"


@dataclass(frozen=True)
class TeacherConfig:
    name: str = DEFAULT_TEACHER
    device_label: str = DEFAULT_DEVICE_LABEL
    checkpoint: str | None = None
    output_dir: Path = field(
        default_factory=lambda: _REPO_ROOT / "artifacts" / "soft_labels"
    )
    force_fixture: bool = False
    repo_root: Path = field(default_factory=lambda: _REPO_ROOT)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def load_teacher_config(config_path: Path | str | None = None) -> TeacherConfig:
    path = Path(config_path) if config_path else _DEFAULT_CONFIG
    raw = _read_yaml(path)
    block = raw.get("teacher") or {}
    name = str(block.get("name") or DEFAULT_TEACHER)
    device = str(block.get("device") or DEFAULT_DEVICE_LABEL)
    ckpt = block.get("checkpoint")
    out = block.get("output_dir") or "artifacts/soft_labels"
    out_path = Path(out)
    if not out_path.is_absolute():
        out_path = _REPO_ROOT / out_path

    force = os.environ.get("DISTILLERY_TEACHER_FIXTURE", "").lower() in (
        "1",
        "true",
        "yes",
    )
    if block.get("force_fixture"):
        force = True
    if os.environ.get("DISTILLERY_INGEST_FIXTURE", "").lower() in ("1", "true", "yes"):
        force = True

    return TeacherConfig(
        name=name,
        device_label=device,
        checkpoint=str(ckpt) if ckpt else None,
        output_dir=out_path,
        force_fixture=force,
        repo_root=_REPO_ROOT,
    )
