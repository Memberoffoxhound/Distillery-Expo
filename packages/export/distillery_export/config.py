"""Export settings from configs/default.yaml (+ env overrides)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CONFIG = _REPO_ROOT / "configs" / "default.yaml"


@dataclass(frozen=True)
class ExportConfig:
    student_dir: Path = field(
        default_factory=lambda: _REPO_ROOT / "artifacts" / "student"
    )
    output_dir: Path = field(
        default_factory=lambda: _REPO_ROOT / "artifacts" / "export"
    )
    artifact_name: str = "student_modelV2_io.onnx"
    repo_root: Path = field(default_factory=lambda: _REPO_ROOT)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def load_export_config(config_path: Path | str | None = None) -> ExportConfig:
    path = Path(config_path) if config_path else _DEFAULT_CONFIG
    raw = _read_yaml(path)
    block = raw.get("export") or {}
    student = block.get("student_dir") or "artifacts/student"
    student_path = Path(student)
    if not student_path.is_absolute():
        student_path = _REPO_ROOT / student_path
    out = block.get("output_dir") or "artifacts/export"
    out_path = Path(out)
    if not out_path.is_absolute():
        out_path = _REPO_ROOT / out_path
    name = str(block.get("artifact_name") or "student_modelV2_io.onnx")
    return ExportConfig(
        student_dir=student_path,
        output_dir=out_path,
        artifact_name=name,
        repo_root=_REPO_ROOT,
    )
