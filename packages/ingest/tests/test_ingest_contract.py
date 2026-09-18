"""Smoke tests — ingest event contract matches DistilleryEvent / SamplePayload."""

from __future__ import annotations

import asyncio
import os

import pytest

from distillery_events import DistilleryEvent, EventKind, SamplePayload, StageName
from distillery_ingest import load_ingest_config, run_ingest_pipeline
from distillery_ingest.resolve import list_routes, resolve_source
from distillery_ingest.sources.fixture import FIXTURE_ROUTE_ID, cam_samples_for_route


@pytest.fixture(autouse=True)
def _force_fixture(monkeypatch):
    monkeypatch.setenv("DISTILLERY_INGEST_FIXTURE", "1")
    monkeypatch.delenv("COMMA_JWT", raising=False)
    monkeypatch.delenv("CONNECT_JWT", raising=False)
    monkeypatch.delenv("MICI_SSH_HOST", raising=False)


def test_config_resolves_dongle():
    cfg = load_ingest_config()
    assert cfg.dongle_id == "3e2de7ed673817c2"
    assert set(cfg.cams) >= {"road", "wide", "driver"}


def test_resolve_falls_back_to_fixture():
    src = resolve_source(prefer="auto")
    assert src.name == "fixture"
    routes = src.list_routes()
    assert len(routes) >= 1
    assert routes[0].meta.get("fixture") is True or routes[0].meta.get("label") == "fixture"
    assert routes[0].dongle_id == "3e2de7ed673817c2"


def test_fixture_has_three_cams_metadata():
    src = resolve_source(prefer="fixture")
    route = src.get_route(FIXTURE_ROUTE_ID) or src.list_routes()[0]
    assert route.segment_count >= 1
    assert route.segments
    seg = route.segments[0]
    for cam in ("road", "wide", "driver"):
        assert cam in seg.cams
        assert seg.cams[cam].get("fps") == 20
        assert seg.cams[cam].get("filename")
    samples = cam_samples_for_route(route, ("road", "wide", "driver"))
    assert {s.cam for s in samples} == {"road", "wide", "driver"}
    for s in samples:
        assert s.meta.get("label") == "fixture"
        assert s.placeholder is True


def test_ingest_pipeline_emits_stage_progress_and_samples():
    events: list[dict] = []

    async def emit(ev: dict) -> None:
        events.append(ev)

    async def _run() -> None:
        await run_ingest_pipeline(
            "test-job",
            emit,
            prefer="fixture",
            tick=0.0,
        )

    asyncio.run(_run())

    # Validate DistilleryEvent shape
    parsed = [DistilleryEvent.model_validate(e) for e in events]
    kinds = {e.kind for e in parsed}
    assert EventKind.stage in kinds
    assert EventKind.progress in kinds
    assert EventKind.sample in kinds

    stages = [e for e in parsed if e.kind == EventKind.stage]
    assert any(e.payload.get("status") == "running" for e in stages)
    assert any(e.payload.get("status") == "done" for e in stages)
    assert all(e.stage == StageName.ingest for e in stages)

    samples = [e for e in parsed if e.kind == EventKind.sample]
    cams = {e.payload["cam"] for e in samples}
    assert cams >= {"road", "wide", "driver"}
    for e in samples:
        SamplePayload.model_validate(e.payload)
        assert e.payload.get("placeholder") is True
        assert e.payload.get("meta", {}).get("route_id")
        assert e.payload.get("meta", {}).get("dongle_id") == "3e2de7ed673817c2"


def test_list_routes_api_shape():
    src, routes = list_routes(prefer="fixture", limit=5)
    assert src.name == "fixture"
    summary = routes[0].summary_dict()
    for key in ("route_id", "dongle_id", "display_name", "source", "segment_count", "meta"):
        assert key in summary
