"""Shard stage runner — emits DistilleryEvent shapes onto the existing bus."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Literal

from distillery_events import (
    DecisionPayload,
    EventKind,
    LogPayload,
    MetricPayload,
    ProgressPayload,
    SamplePayload,
    StageName,
    StagePayload,
    make_event,
)
from distillery_shards.config import ShardConfig, load_shard_config
from distillery_shards.fixture import resolve_route_for_pack
from distillery_shards.models import ShardDescriptor
from distillery_shards.pack import pack_route_to_shards, shard_to_sample

EmitFn = Callable[[dict[str, Any]], Awaitable[None]]
SourcePreference = Literal["auto", "connect", "ssh", "fixture"]


async def _emit(emit: EmitFn, event) -> None:
    await emit(event.to_json_dict())


async def run_shard_pipeline(
    job_id: str,
    emit: EmitFn,
    *,
    route_id: str | None = None,
    prefer: SourcePreference = "auto",
    cfg: ShardConfig | None = None,
    tick: float = 0.12,
    write_files: bool = True,
) -> list[ShardDescriptor]:
    """Pack route into training shards; emit stage=shard progress/samples/metrics."""
    cfg = cfg or load_shard_config()
    stage = StageName.shard

    async def log(msg: str, level: str = "info") -> None:
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.log,
                LogPayload(level=level, message=msg, source="shard"),  # type: ignore[arg-type]
                stage=stage,
            ),
        )

    async def stage_status(status: str, detail: str | None = None) -> None:
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.stage,
                StagePayload(name=stage, status=status, detail=detail),  # type: ignore[arg-type]
                stage=stage,
            ),
        )

    async def progress(frac: float, detail: str | None = None) -> None:
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.progress,
                ProgressPayload(fraction=min(1.0, max(0.0, frac)), detail=detail),
                stage=stage,
            ),
        )

    await stage_status("running", "Packing training shards")
    await log(
        f"window_frames={cfg.window_frames} prefer={prefer} route_id={route_id or 'auto'}"
    )
    await progress(0.05, "resolve route")
    await asyncio.sleep(tick)

    route, used_fixture = resolve_route_for_pack(
        route_id,
        prefer=prefer,
        force_fixture=cfg.force_fixture,
    )

    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.decision,
            DecisionPayload(
                title="Shard window",
                rationale=(
                    f"{cfg.window_frames}-frame windows balance teacher soft-label memory "
                    "vs batch diversity on 7090 XT."
                ),
                options_considered=["60-frame", "120-frame", "240-frame"],
                chosen=f"{cfg.window_frames}-frame",
                confidence=0.84,
            ),
            stage=stage,
        ),
    )
    await progress(0.15, f"route={route.route_id}")
    await log(
        f"Packing route {route.route_id} via {route.source}"
        + (" [fixture]" if used_fixture else "")
    )
    await asyncio.sleep(tick)

    shards = await asyncio.to_thread(
        pack_route_to_shards,
        route,
        cfg,
        write_files=write_files,
    )
    n = max(len(shards), 1)
    total_bytes = 0

    for i, desc in enumerate(shards):
        sample = shard_to_sample(desc)
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.sample,
                SamplePayload(
                    cam=sample.cam,
                    label=sample.label,
                    placeholder=sample.placeholder,
                    uri=sample.uri,
                    meta=sample.meta,
                ),
                stage=stage,
            ),
        )
        total_bytes += desc.size_bytes
        # Name matches demo runner so Jony's Shard pane already binds
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.metric,
                MetricPayload(
                    name="shards_written",
                    value=float(i + 1),
                    unit="shards",
                    series="shards",
                ),
                stage=stage,
            ),
        )
        await progress((i + 1) / n * 0.85 + 0.15, f"shard {i + 1}/{n}")
        await log(
            f"Wrote {desc.shard_id} frames={desc.frame_count} "
            f"size≈{desc.size_bytes // (1024 * 1024)} MB"
            + (" [fixture]" if desc.meta.get("fixture") else "")
        )
        await asyncio.sleep(tick * 0.5)

    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.metric,
            MetricPayload(name="shard_count", value=float(len(shards)), unit="shards"),
            stage=stage,
        ),
    )
    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.metric,
            MetricPayload(name="shard_bytes", value=float(total_bytes), unit="bytes"),
            stage=stage,
        ),
    )

    await progress(1.0, "done")
    detail = (
        f"{len(shards)} shards · {route.route_id}"
        + (" · fixture" if used_fixture else "")
    )
    await log(f"Shard pack complete — {detail}")
    await stage_status("done", detail)
    return shards
