"""Ingest stage runner — emits DistilleryEvent shapes onto the existing bus."""

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
from distillery_ingest.config import IngestConfig, load_ingest_config
from distillery_ingest.models import RouteInfo
from distillery_ingest.resolve import SourcePreference, get_route, list_routes
from distillery_ingest.sources.fixture import cam_samples_for_route

EmitFn = Callable[[dict[str, Any]], Awaitable[None]]


async def _emit(emit: EmitFn, event) -> None:
    await emit(event.to_json_dict())


async def run_ingest_pipeline(
    job_id: str,
    emit: EmitFn,
    *,
    route_id: str | None = None,
    prefer: SourcePreference = "auto",
    cfg: IngestConfig | None = None,
    tick: float = 0.15,
) -> RouteInfo:
    """Thin vertical slice: resolve route → stage progress → ≥1 sample/cam."""
    cfg = cfg or load_ingest_config()
    stage = StageName.ingest

    async def log(msg: str, level: str = "info") -> None:
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.log,
                LogPayload(level=level, message=msg, source="ingest"),  # type: ignore[arg-type]
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

    await stage_status("running", f"Resolving mici routes for dongle {cfg.dongle_id}")
    await log(f"dongle_id={cfg.dongle_id} prefer={prefer}")
    await progress(0.05, "resolve source")
    await asyncio.sleep(tick)

    # Resolve listing first so decision has real source name
    listing = await asyncio.to_thread(list_routes, cfg, prefer=prefer, limit=10)
    source, routes = listing.source, listing.routes
    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.decision,
            DecisionPayload(
                title="Route source",
                rationale=(
                    "Prefer comma Connect for freshness; fall back to SSH realdata; "
                    "use labeled fixture when credentials are unavailable."
                ),
                options_considered=["comma Connect", "local SSH", "fixture (offline)"],
                chosen={
                    "connect": "comma Connect",
                    "ssh": "local SSH",
                    "fixture": "fixture (offline)",
                }.get(source.name, source.name),
                confidence=0.93 if source.name != "fixture" else 0.7,
            ),
            stage=stage,
        ),
    )
    await progress(0.2, f"source={source.name} routes={len(routes)}")
    await log(f"source={source.name} listed {len(routes)} route(s)")
    await asyncio.sleep(tick)

    if route_id:
        source, route = await asyncio.to_thread(get_route, route_id, cfg, prefer=prefer)
    elif routes:
        route = routes[0]
        # Ensure segments populated
        if not route.segments:
            source, route = await asyncio.to_thread(
                get_route, route.route_id, cfg, prefer=prefer
            )
    elif prefer == "fixture" or source.name == "fixture":
        source, route = await asyncio.to_thread(get_route, "fixture", cfg, prefer="fixture")
    else:
        # Live source listed 0 routes (or error) — do not silently ingest fixture.
        detail = getattr(listing, "message", None) or f"{source.name} returned 0 routes"
        raise RuntimeError(detail)

    if route is None:
        raise RuntimeError(
            f"route not found via {source.name}"
            + (f" (prefer={prefer})" if prefer else "")
        )

    await log(f"Selected route {route.route_id} ({route.display_name}) via {route.source}")
    await progress(0.4, f"route={route.route_id}")

    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.metric,
            MetricPayload(
                name="segments_found",
                value=float(route.segment_count or len(route.segments)),
                unit="segs",
            ),
            stage=stage,
        ),
    )
    if route.length_s is not None:
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.metric,
                MetricPayload(
                    name="route_hours",
                    value=round(route.length_s / 3600.0, 4),
                    unit="h",
                ),
                stage=stage,
            ),
        )

    samples = cam_samples_for_route(route, cfg.cams)
    n = max(len(samples), 1)
    for i, sample in enumerate(samples):
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
        await progress(0.45 + 0.45 * ((i + 1) / n), f"cam:{sample.cam}")
        await log(f"cam sample ready: {sample.cam} uri={sample.uri or 'n/a'}")
        await asyncio.sleep(tick * 0.5)

    await progress(1.0, "done")
    await log(
        f"Ingest complete — {route.segment_count or len(route.segments)} segments "
        f"via {route.source}"
        + (" [fixture]" if route.source == "fixture" else "")
    )
    await stage_status(
        "done",
        f"{route.route_id} · {route.source} · cams={[s.cam for s in samples]}",
    )
    return route
