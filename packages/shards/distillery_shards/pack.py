"""Pack route segments into training shard descriptors (frame windows)."""

from __future__ import annotations

import json
from pathlib import Path

from distillery_ingest.models import RouteInfo, SegmentInfo
from distillery_shards.config import ShardConfig
from distillery_shards.models import ShardDescriptor, ShardSample

_BYTES_PER_FRAME_EST = 48_000


def _segment_frame_count(duration_s: float | None, fps: int) -> int:
    if duration_s is None or duration_s <= 0:
        return fps * 60
    return max(int(round(duration_s * fps)), fps)


def _label_placeholders(cams: tuple[str, ...], frame_start: int, frame_end: int) -> dict:
    return {
        "kind": "placeholder",
        "frame_range": [frame_start, frame_end],
        "cams": list(cams),
        "desire": None,
        "pose": None,
        "note": "labels filled by later teach/train milestones",
    }


def _soft_target_placeholders(frame_count: int) -> dict:
    return {
        "kind": "placeholder",
        "teacher": "Cinque/supercombo",
        "device": "7090 XT",
        "slots": frame_count,
        "note": "soft-targets written by teach stage (not M2)",
    }


def pack_route_to_shards(
    route: RouteInfo,
    cfg: ShardConfig,
    *,
    write_files: bool = True,
) -> list[ShardDescriptor]:
    """Slice route segments into window_frames shards with soft-target placeholders."""
    shards: list[ShardDescriptor] = []
    window = max(1, cfg.window_frames)
    cams = list(cfg.cams)
    fixture = bool(route.meta.get("fixture")) or route.source == "fixture"

    segments = list(route.segments or [])
    if not segments:
        segments = [
            SegmentInfo(
                segment_id=f"{route.route_id}/0",
                index=0,
                duration_s=route.length_s or 60.0,
                cams={},
                meta={"synthetic": True},
            )
        ]

    shard_idx = 0
    for seg in segments:
        n_frames = _segment_frame_count(seg.duration_s, cfg.fps)
        start = 0
        while start < n_frames:
            end = min(start + window, n_frames)
            count = end - start
            shard_id = f"shard_{shard_idx:03d}"
            size_bytes = count * len(cams) * _BYTES_PER_FRAME_EST
            meta = {
                "fixture": fixture,
                "label": "fixture" if fixture else route.source,
                "source": route.source,
                "dongle_id": route.dongle_id,
                "window_frames": window,
                "fps": cfg.fps,
                "segment_index": seg.index,
            }
            if fixture:
                meta["reason"] = "offline fixture — no real ingest artifacts"

            shards.append(
                ShardDescriptor(
                    shard_id=shard_id,
                    route_id=route.route_id,
                    segment_id=seg.segment_id,
                    frame_start=start,
                    frame_end=end - 1,
                    frame_count=count,
                    fps=cfg.fps,
                    cams=cams,
                    labels=_label_placeholders(cfg.cams, start, end - 1),
                    teacher_soft_targets=_soft_target_placeholders(count),
                    size_bytes=size_bytes,
                    status="ready",
                    meta=meta,
                )
            )
            shard_idx += 1
            start = end

    if write_files and shards:
        _write_shard_artifacts(shards, cfg.output_dir, route.route_id)
    return shards


def _safe_route_dir(route_id: str) -> str:
    return route_id.replace("|", "__").replace("/", "_")


def _write_shard_artifacts(
    shards: list[ShardDescriptor],
    output_dir: Path,
    route_id: str,
) -> Path:
    dest = output_dir / _safe_route_dir(route_id)
    dest.mkdir(parents=True, exist_ok=True)
    manifest = []
    for s in shards:
        (dest / f"{s.shard_id}.json").write_text(
            json.dumps(s.model_dump(mode="json"), indent=2) + "\n"
        )
        manifest.append(s.summary_dict())
    (dest / "manifest.json").write_text(
        json.dumps({"route_id": route_id, "shards": manifest}, indent=2) + "\n"
    )
    return dest


def shard_to_sample(desc: ShardDescriptor, *, uri: str | None = None) -> ShardSample:
    """Build SamplePayload-shaped event meta for Jony / Expo binding."""
    return ShardSample(
        cam="other",
        label=f"{desc.shard_id} · {desc.frame_count}f",
        placeholder=True,
        uri=uri,
        meta={
            "shard_id": desc.shard_id,
            "route_id": desc.route_id,
            "segment_id": desc.segment_id,
            "frame_count": desc.frame_count,
            "frame_start": desc.frame_start,
            "frame_end": desc.frame_end,
            "size_bytes": desc.size_bytes,
            "status": desc.status,
            "fixture": bool(desc.meta.get("fixture")),
            "label": desc.meta.get("label"),
            "source": desc.meta.get("source"),
            "dongle_id": desc.meta.get("dongle_id"),
            "fps": desc.fps,
            "cams": desc.cams,
        },
    )
