"""Student distill settings from configs/default.yaml (+ env overrides)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CONFIG = _REPO_ROOT / "configs" / "default.yaml"

DEFAULT_STUDENT = "stock-modelV2-I/O"
DEFAULT_TARGET = "mici/QCOM"


@dataclass(frozen=True)
class StudentConfig:
    name: str = DEFAULT_STUDENT
    target: str = DEFAULT_TARGET
    io_compatible: bool = True
    steps: int = 12
    lr: float = 3e-4
    soft_labels_dir: Path = field(
        default_factory=lambda: _REPO_ROOT / "artifacts" / "soft_labels"
    )
    output_dir: Path = field(
        default_factory=lambda: _REPO_ROOT / "artifacts" / "student"
    )
    force_fixture: bool = False
    repo_root: Path = field(default_factory=lambda: _REPO_ROOT)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def load_student_config(config_path: Path | str | None = None) -> StudentConfig:
    path = Path(config_path) if config_path else _DEFAULT_CONFIG
    raw = _read_yaml(path)
    block = raw.get("student") or {}
    name = str(block.get("name") or DEFAULT_STUDENT)
    target = str(block.get("target") or DEFAULT_TARGET)
    io_ok = bool(block.get("io_compatible", True))
    steps = int(block.get("steps") or 12)
    lr = float(block.get("lr") or 3e-4)
    soft = block.get("soft_labels_dir") or "artifacts/soft_labels"
    soft_path = Path(soft)
    if not soft_path.is_absolute():
        soft_path = _REPO_ROOT / soft_path
    out = block.get("output_dir") or "artifacts/student"
    out_path = Path(out)
    if not out_path.is_absolute():
        out_path = _REPO_ROOT / out_path

    force = os.environ.get("DISTILLERY_STUDENT_FIXTURE", "").lower() in (
        "1",
        "true",
        "yes",
    )
    if os.environ.get("DISTILLERY_INGEST_FIXTURE", "").lower() in ("1", "true", "yes"):
        force = True

    return StudentConfig(
        name=name,
        target=target,
        io_compatible=io_ok,
        steps=steps,
        lr=lr,
        soft_labels_dir=soft_path,
        output_dir=out_path,
        force_fixture=force,
        repo_root=_REPO_ROOT,
    )
