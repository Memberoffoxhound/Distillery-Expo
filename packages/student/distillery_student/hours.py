"""Driving-hours floor for train/eval — refuse toy sets unless explicitly allowed.

Default floor: 50 hours. Override for fixture CI via DISTILLERY_ALLOW_TOY_TRAIN=1
(or config allow_toy_train) — still labeled live=false / not licensed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_MIN_TRAIN_HOURS = 50.0
TOY_ALLOW_ENV = "DISTILLERY_ALLOW_TOY_TRAIN"


class InsufficientHoursError(RuntimeError):
    """Raised when train refuses below the hours floor without toy override."""

    def __init__(self, message: str, *, hours_info: dict[str, Any]):
        super().__init__(message)
        self.hours_info = hours_info


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes")


def toy_train_allowed(*, config_allow: bool | None = None) -> bool:
    """Explicit CI/fixture override — never implies licensed / live=true."""
    if config_allow is True:
        return True
    return _env_truthy(TOY_ALLOW_ENV)


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _hours_from_mapping(data: dict[str, Any]) -> float | None:
    for key in (
        "driving_hours",
        "route_hours",
        "total_hours",
        "hours",
        "hours_of_driving",
    ):
        if key in data and data[key] is not None:
            try:
                return float(data[key])
            except (TypeError, ValueError):
                continue
    for key in ("length_s", "duration_s", "total_duration_s"):
        if key in data and data[key] is not None:
            try:
                return float(data[key]) / 3600.0
            except (TypeError, ValueError):
                continue
    meta = data.get("meta")
    if isinstance(meta, dict):
        nested = _hours_from_mapping(meta)
        if nested is not None:
            return nested
    return None


def _hours_from_shards_dir(shards_dir: Path) -> tuple[float | None, dict[str, Any]]:
    """Sum frame_count/fps across shard manifests under shards_dir."""
    if not shards_dir.is_dir():
        return None, {"reason": "shards_dir_missing"}

    total_frames = 0
    fps_vals: list[float] = []
    routes = 0

    def _consume_manifest(manifest: dict[str, Any]) -> None:
        nonlocal total_frames
        for entry in manifest.get("shards") or []:
            if not isinstance(entry, dict):
                continue
            try:
                fc = int(entry.get("frame_count") or 0)
            except (TypeError, ValueError):
                fc = 0
            total_frames += max(fc, 0)
            meta = entry.get("meta") if isinstance(entry.get("meta"), dict) else {}
            fps = entry.get("fps") or meta.get("fps") or 20
            try:
                fps_vals.append(float(fps))
            except (TypeError, ValueError):
                fps_vals.append(20.0)

    for manifest_path in sorted(shards_dir.glob("*/manifest.json")):
        manifest = _load_json(manifest_path)
        if not manifest:
            continue
        routes += 1
        _consume_manifest(manifest)

    top = _load_json(shards_dir / "manifest.json")
    if top:
        _consume_manifest(top)
        routes = max(routes, 1)

    if total_frames <= 0:
        return None, {"reason": "no_shard_frames", "routes_scanned": routes}

    fps = sum(fps_vals) / len(fps_vals) if fps_vals else 20.0
    fps = fps if fps > 0 else 20.0
    hours = (total_frames / fps) / 3600.0
    return hours, {
        "total_frames": total_frames,
        "fps": fps,
        "routes_scanned": routes,
        "method": "shard_frames_over_fps",
    }


def estimate_driving_hours(
    *,
    soft_labels_dir: Path | None = None,
    shards_dir: Path | None = None,
    soft_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Estimate hours of driving data from soft-label / shard metadata.

    If unknown, ``known`` is False and ``hours`` is 0.0 (below the train floor).
    """
    soft_summary = dict(soft_summary or {})
    if soft_labels_dir is not None and not soft_summary:
        manifest = _load_json(Path(soft_labels_dir) / "manifest.json")
        if manifest:
            soft_summary = manifest

    live = bool(soft_summary.get("live"))
    source = str(soft_summary.get("source") or ("live" if live else "unknown"))
    meta = soft_summary.get("meta")
    fixture_meta = bool(meta.get("fixture")) if isinstance(meta, dict) else False
    fixture_like = (not live) or source == "fixture" or fixture_meta

    from_soft = _hours_from_mapping(soft_summary) if soft_summary else None
    if from_soft is not None:
        return {
            "hours": round(float(from_soft), 6),
            "known": True,
            "source": "soft_labels_meta",
            "live": live and not fixture_like,
            "fixture": fixture_like,
            "detail": "hours field (or length_s) on soft-label summary/manifest",
        }

    if shards_dir is not None:
        from_shards, shard_meta = _hours_from_shards_dir(Path(shards_dir))
        if from_shards is not None:
            return {
                "hours": round(float(from_shards), 6),
                "known": True,
                "source": "shards",
                "live": live and not fixture_like,
                "fixture": fixture_like,
                "detail": "estimated from shard frame_count/fps",
                "shard_meta": shard_meta,
            }

    return {
        "hours": 0.0,
        "known": False,
        "source": "unknown" if soft_summary else "missing",
        "live": False,
        "fixture": True,
        "detail": (
            "no hours metadata on soft labels/shards — treated as below floor "
            "(live=false / not licensed)"
        ),
    }


def hours_meet_floor(
    hours_info: dict[str, Any],
    *,
    min_hours: float = DEFAULT_MIN_TRAIN_HOURS,
    allow_toy: bool = False,
) -> dict[str, Any]:
    """Evaluate the ≥ min_hours gate."""
    hours = float(hours_info.get("hours") or 0.0)
    known = bool(hours_info.get("known"))
    below = (not known) or hours < float(min_hours)

    if not below:
        return {
            "ok": True,
            "reason": "hours_ok",
            "hours": hours,
            "min_hours": float(min_hours),
            "known": known,
            "allow_toy": allow_toy,
            "live": bool(hours_info.get("live")),
            "licensed": bool(hours_info.get("live")) and known and hours >= float(min_hours),
            "toy_override": False,
        }

    if allow_toy:
        return {
            "ok": True,
            "reason": "toy_override",
            "hours": hours,
            "min_hours": float(min_hours),
            "known": known,
            "allow_toy": True,
            "live": False,
            "licensed": False,
            "toy_override": True,
            "label": "live=false / not licensed (DISTILLERY_ALLOW_TOY_TRAIN)",
        }

    return {
        "ok": False,
        "reason": "insufficient_hours",
        "hours": hours,
        "min_hours": float(min_hours),
        "known": known,
        "allow_toy": False,
        "live": False,
        "licensed": False,
        "toy_override": False,
    }
