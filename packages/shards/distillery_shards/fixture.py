"""Offline fixture path — pack when no real ingest artifacts (mirrors ingest)."""

from __future__ import annotations

import json
from pathlib import Path

from distillery_ingest.config import IngestConfig, load_ingest_config
from distillery_ingest.models import RouteInfo
from distillery_ingest.sources.fixture import FIXTURE_ROUTE_ID, build_fixture_route
from distillery_shards.config import ShardConfig


def _fixture_manifest_path() -> Path:
    return Path(__file__).resolve().parents[1] / "fixtures" / "sample_shards.json"


def load_fixture_route(cfg: ShardConfig | None = None) -> RouteInfo:
    """Return Connect-shaped fixture route labeled for offline shard packing."""
    ingest_cfg: IngestConfig = load_ingest_config()
    route = build_fixture_route(ingest_cfg)
    meta = dict(route.meta)
    meta["fixture"] = True
    meta["label"] = "fixture"
    meta.setdefault("reason", "no real ingest artifacts — shard fixture path")
    return route.model_copy(update={"meta": meta, "source": "fixture"})


def resolve_route_for_pack(
    route_id: str | None,
    *,
    prefer: str = "auto",
    force_fixture: bool = False,
) -> tuple[RouteInfo, bool]:
    """Resolve a route for packing; fall back to labeled fixture when needed."""
    from distillery_ingest.resolve import get_route, list_routes

    ingest_cfg = load_ingest_config()
    if force_fixture or prefer == "fixture" or ingest_cfg.force_fixture:
        route = load_fixture_route()
        if route_id and route_id not in (route.route_id, FIXTURE_ROUTE_ID, "fixture"):
            route = route.model_copy(
                update={"meta": {**route.meta, "requested_route_id": route_id}}
            )
        return route, True

    try:
        if route_id:
            _src, route = get_route(route_id, ingest_cfg, prefer=prefer)  # type: ignore[arg-type]
        else:
            _src, routes = list_routes(ingest_cfg, prefer=prefer, limit=5)  # type: ignore[arg-type]
            if not routes:
                return load_fixture_route(), True
            route = routes[0]
            if not route.segments:
                _src, route = get_route(route.route_id, ingest_cfg, prefer=prefer)  # type: ignore[arg-type]
        if route.source == "fixture" or route.meta.get("fixture"):
            return route, True
        return route, False
    except Exception:  # noqa: BLE001
        return load_fixture_route(), True


def fixture_manifest_summary() -> dict:
    path = _fixture_manifest_path()
    if path.is_file():
        return json.loads(path.read_text())
    return {
        "label": "fixture",
        "fixture": True,
        "route_id": FIXTURE_ROUTE_ID,
        "window_frames": 120,
        "note": "generated at pack time when sample_shards.json absent",
    }
