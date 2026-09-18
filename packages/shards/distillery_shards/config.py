"""Shard packing settings from configs/default.yaml (+ env overrides)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CONFIG = _REPO_ROOT / "configs" / "default.yaml"

DEFAULT_WINDOW_FRAMES = 120
DEFAULT_FPS = 20
DEFAULT_CAMS = ("road", "wide", "driver")


@dataclass(frozen=True)
class ShardConfig:
    window_frames: int = DEFAULT_WINDOW_FRAMES
    fps: int = DEFAULT_FPS
    cams: tuple[str, ...] = DEFAULT_CAMS
    output_dir: Path = field(default_factory=lambda: _REPO_ROOT / "artifacts" / "shards")
    force_fixture: bool = False
    repo_root: Path = field(default_factory=lambda: _REPO_ROOT)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def load_shard_config(config_path: Path | str | None = None) -> ShardConfig:
    path = Path(config_path) if config_path else _DEFAULT_CONFIG
    raw = _read_yaml(path)
    hardware = raw.get("hardware") or {}
    mici = hardware.get("mici") or {}
    cams_raw = mici.get("cams") or list(DEFAULT_CAMS)
    cams = tuple(str(c) for c in cams_raw)

    shards_block = raw.get("shards") or {}
    window = int(shards_block.get("window_frames") or DEFAULT_WINDOW_FRAMES)
    fps = int(shards_block.get("fps") or DEFAULT_FPS)
    out = shards_block.get("output_dir") or "artifacts/shards"
    out_path = Path(out)
    if not out_path.is_absolute():
        out_path = _REPO_ROOT / out_path

    force = os.environ.get("DISTILLERY_SHARD_FIXTURE", "").lower() in ("1", "true", "yes")
    if isinstance(shards_block, dict) and shards_block.get("force_fixture"):
        force = True
    if os.environ.get("DISTILLERY_INGEST_FIXTURE", "").lower() in ("1", "true", "yes"):
        force = True

    return ShardConfig(
        window_frames=window,
        fps=fps,
        cams=cams or DEFAULT_CAMS,
        output_dir=out_path,
        force_fixture=force,
        repo_root=_REPO_ROOT,
    )
