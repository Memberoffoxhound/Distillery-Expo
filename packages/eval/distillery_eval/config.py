"""Eval scorecard settings from configs/default.yaml (+ env overrides)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from distillery_student.hours import DEFAULT_MIN_TRAIN_HOURS, toy_train_allowed

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CONFIG = _REPO_ROOT / "configs" / "default.yaml"

# Flash gate thresholds — must be met on REAL measured numbers (no greenwash).
DEFAULT_MIN_TEACHER_AGREEMENT = 0.92
DEFAULT_MAX_LATERAL_MAE = 0.08
DEFAULT_MAX_LONGITUDINAL_MAE = 0.10
DEFAULT_MIN_DESIRE_TOP1 = 0.90
DEFAULT_MIN_ROUTE_REPLAY = 0.90


@dataclass(frozen=True)
class EvalConfig:
    soft_labels_dir: Path = field(
        default_factory=lambda: _REPO_ROOT / "artifacts" / "soft_labels"
    )
    student_dir: Path = field(
        default_factory=lambda: _REPO_ROOT / "artifacts" / "student"
    )
    export_dir: Path = field(
        default_factory=lambda: _REPO_ROOT / "artifacts" / "export"
    )
    output_dir: Path = field(
        default_factory=lambda: _REPO_ROOT / "artifacts" / "eval"
    )
    min_teacher_agreement: float = DEFAULT_MIN_TEACHER_AGREEMENT
    max_lateral_mae: float = DEFAULT_MAX_LATERAL_MAE
    max_longitudinal_mae: float = DEFAULT_MAX_LONGITUDINAL_MAE
    min_desire_top1: float = DEFAULT_MIN_DESIRE_TOP1
    min_route_replay: float = DEFAULT_MIN_ROUTE_REPLAY
    # If True, force fixture scoring path (still real numbers; still may fail gate)
    force_fixture: bool = False
    min_train_hours: float = DEFAULT_MIN_TRAIN_HOURS
    allow_toy_train: bool = False
    shards_dir: Path = field(
        default_factory=lambda: _REPO_ROOT / "artifacts" / "shards"
    )
    repo_root: Path = field(default_factory=lambda: _REPO_ROOT)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def load_eval_config(config_path: Path | str | None = None) -> EvalConfig:
    path = Path(config_path) if config_path else _DEFAULT_CONFIG
    raw = _read_yaml(path)
    block = raw.get("eval") or {}

    def _path(key: str, default: str) -> Path:
        v = block.get(key) or default
        p = Path(v)
        return p if p.is_absolute() else _REPO_ROOT / p

    force = os.environ.get("DISTILLERY_EVAL_FIXTURE", "").lower() in (
        "1",
        "true",
        "yes",
    )
    if os.environ.get("DISTILLERY_INGEST_FIXTURE", "").lower() in ("1", "true", "yes"):
        force = True
    if block.get("force_fixture"):
        force = True

    return EvalConfig(
        soft_labels_dir=_path("soft_labels_dir", "artifacts/soft_labels"),
        student_dir=_path("student_dir", "artifacts/student"),
        export_dir=_path("export_dir", "artifacts/export"),
        output_dir=_path("output_dir", "artifacts/eval"),
        min_teacher_agreement=float(
            block.get("min_teacher_agreement") or DEFAULT_MIN_TEACHER_AGREEMENT
        ),
        max_lateral_mae=float(block.get("max_lateral_mae") or DEFAULT_MAX_LATERAL_MAE),
        max_longitudinal_mae=float(
            block.get("max_longitudinal_mae") or DEFAULT_MAX_LONGITUDINAL_MAE
        ),
        min_desire_top1=float(block.get("min_desire_top1") or DEFAULT_MIN_DESIRE_TOP1),
        min_route_replay=float(block.get("min_route_replay") or DEFAULT_MIN_ROUTE_REPLAY),
        force_fixture=force,
        min_train_hours=float(
            block.get("min_train_hours")
            or os.environ.get("DISTILLERY_MIN_TRAIN_HOURS")
            or DEFAULT_MIN_TRAIN_HOURS
        ),
        allow_toy_train=bool(block.get("allow_toy_train")) or toy_train_allowed(),
        shards_dir=_path("shards_dir", "artifacts/shards"),
        repo_root=_REPO_ROOT,
    )
