"""Smoke tests — shard event contract matches DistilleryEvent / SamplePayload."""

from __future__ import annotations

import asyncio

import pytest

from distillery_events import DistilleryEvent, EventKind, SamplePayload, StageName
from distillery_shards import load_shard_config, run_shard_pipeline
from distillery_shards.fixture import load_fixture_route, resolve_route_for_pack
from distillery_shards.pack import pack_route_to_shards, shard_to_sample


@pytest.fixture(autouse=True)
def _force_fixture(monkeypatch):
    monkeypatch.setenv("DISTILLERY_INGEST_FIXTURE", "1")
    monkeypatch.setenv("DISTILLERY_SHARD_FIXTURE", "1")
    monkeypatch.delenv("COMMA_JWT", raising=False)
    monkeypatch.delenv("CONNECT_JWT", raising=False)
    monkeypatch.delenv("MICI_SSH_HOST", raising=False)


def test_config_window_default():
    cfg = load_shard_config()
    assert cfg.window_frames == 120
    assert set(cfg.cams) >= {"road", "wide", "driver"}


def test_fixture_route_labeled():
    route = load_fixture_route()
    assert route.meta.get("fixture") is True
    assert route.meta.get("label") == "fixture"
    assert route.source == "fixture"
    assert route.segment_count >= 1


def test_pack_produces_descriptors_with_placeholders():
    cfg = load_shard_config()
    route = load_fixture_route()
    shards = pack_route_to_shards(route, cfg, write_files=False)
    assert len(shards) >= 1
    for s in shards:
        assert s.shard_id.startswith("shard_")
        assert s.route_id == route.route_id
        assert s.frame_count > 0
        assert s.size_bytes > 0
        assert s.status == "ready"
        assert s.labels.get("kind") == "placeholder"
        assert s.teacher_soft_targets.get("kind") == "placeholder"
        assert s.meta.get("fixture") is True
        sample = shard_to_sample(s)
        for key in ("shard_id", "route_id", "frame_count", "size_bytes", "status"):
            assert key in sample.meta


def test_resolve_falls_back_to_fixture():
    route, used = resolve_route_for_pack(None, prefer="auto", force_fixture=True)
    assert used is True
    assert route.meta.get("fixture") is True


def test_shard_pipeline_emits_stage_progress_samples():
    events: list[dict] = []

    async def emit(ev: dict) -> None:
        events.append(ev)

    async def _run() -> None:
        await run_shard_pipeline(
            "test-shard-job",
            emit,
            prefer="fixture",
            tick=0.0,
            write_files=False,
        )

    asyncio.run(_run())

    parsed = [DistilleryEvent.model_validate(e) for e in events]
    kinds = {e.kind for e in parsed}
    assert EventKind.stage in kinds
    assert EventKind.progress in kinds
    assert EventKind.sample in kinds
    assert EventKind.metric in kinds
    assert EventKind.decision in kinds
    assert EventKind.log in kinds

    stages = [e for e in parsed if e.kind == EventKind.stage]
    assert any(e.payload.get("status") == "running" for e in stages)
    assert any(e.payload.get("status") == "done" for e in stages)
    assert all(e.stage == StageName.shard for e in stages)

    samples = [e for e in parsed if e.kind == EventKind.sample]
    assert len(samples) >= 1
    for e in samples:
        SamplePayload.model_validate(e.payload)
        meta = e.payload.get("meta") or {}
        assert meta.get("shard_id")
        assert meta.get("route_id")
        assert meta.get("frame_count")
        assert meta.get("size_bytes") is not None
        assert meta.get("status")
        assert meta.get("fixture") is True

    names = {e.payload.get("name") for e in parsed if e.kind == EventKind.metric}
    assert "shards_written" in names
