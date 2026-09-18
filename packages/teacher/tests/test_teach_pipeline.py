"""Teach pipeline — fixture soft labels are honestly non-live."""

from __future__ import annotations

import asyncio

import pytest

from distillery_events import DistilleryEvent, EventKind, StageName
from distillery_teacher import detect_teacher_device, load_teacher_config, run_teach_pipeline
from distillery_teacher.fixture import build_fixture_batches


@pytest.fixture(autouse=True)
def _force_fixture(monkeypatch):
    monkeypatch.setenv("DISTILLERY_TEACHER_FIXTURE", "1")
    monkeypatch.delenv("DISTILLERY_TEACHER_LIVE", raising=False)


def test_config_loads():
    cfg = load_teacher_config()
    assert "Cinque" in cfg.name or "supercombo" in cfg.name.lower()
    assert cfg.force_fixture is True


def test_detect_force_fixture_is_not_live():
    info = detect_teacher_device(force_fixture=True)
    assert info.live is False
    assert info.meta.get("live") is False
    assert info.meta.get("source") == "fixture"


def test_fixture_batches_labeled():
    batches = build_fixture_batches(n_batches=2, samples_per_batch=8)
    assert len(batches) == 2
    for b in batches:
        assert b.live is False
        assert b.source == "fixture"
        assert b.meta.get("live") is False
        assert b.meta.get("source") == "fixture"
        assert "Chestnut" not in b.teacher


def test_teach_pipeline_emits_live_false():
    events: list[dict] = []

    async def emit(ev: dict) -> None:
        events.append(ev)

    async def _run() -> None:
        batches = await run_teach_pipeline(
            "test-teach-job",
            emit,
            prefer="fixture",
            tick=0.0,
            write_files=False,
            n_batches=2,
        )
        assert batches
        assert all(b.live is False for b in batches)
        assert all(b.source == "fixture" for b in batches)

    asyncio.run(_run())

    parsed = [DistilleryEvent.model_validate(e) for e in events]
    assert any(e.kind == EventKind.stage and e.stage == StageName.teach for e in parsed)
    assert any(e.kind == EventKind.progress for e in parsed)
    samples = [e for e in parsed if e.kind == EventKind.sample]
    assert samples
    for s in samples:
        assert s.payload.get("meta", {}).get("live") is False
        assert s.payload.get("meta", {}).get("source") == "fixture"
    # decision must not choose Chestnut
    decisions = [e for e in parsed if e.kind == EventKind.decision]
    assert decisions
    assert "Chestnut" not in (decisions[0].payload.get("chosen") or "")


def test_ingest_fixture_does_not_force_teacher_config(monkeypatch):
    monkeypatch.delenv("DISTILLERY_TEACHER_FIXTURE", raising=False)
    monkeypatch.setenv("DISTILLERY_INGEST_FIXTURE", "1")
    cfg = load_teacher_config()
    assert cfg.force_fixture is False
