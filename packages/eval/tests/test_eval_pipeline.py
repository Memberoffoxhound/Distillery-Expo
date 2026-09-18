"""Eval pipeline — real numbers; fixture must not greenwash eval_passed."""

from __future__ import annotations

import asyncio

import pytest

from distillery_events import DistilleryEvent, EventKind, StageName
from distillery_eval import compute_scorecard, load_eval_config, run_eval_pipeline
from distillery_teacher.fixture import build_fixture_batches, write_soft_label_artifacts


@pytest.fixture(autouse=True)
def _fixture_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DISTILLERY_EVAL_FIXTURE", "1")
    monkeypatch.setenv("DISTILLERY_INGEST_FIXTURE", "1")


def test_scorecard_fixture_defaults_to_fail(tmp_path):
    """Fixture soft labels + stub student → real metrics, usually fail gate."""
    soft_dir = tmp_path / "soft"
    batches = build_fixture_batches(n_batches=2, samples_per_batch=16)
    write_soft_label_artifacts(batches, soft_dir)

    cfg = load_eval_config()
    # Override dirs onto tmp
    from dataclasses import replace

    cfg = replace(
        cfg,
        soft_labels_dir=soft_dir,
        student_dir=tmp_path / "student",
        output_dir=tmp_path / "eval",
        force_fixture=True,
    )
    card = compute_scorecard(cfg, student_meta={"final_loss": 1.2})
    assert card["live"] is False
    assert card["source"] == "fixture"
    # Real numbers present
    assert "teacher_agreement" in card["metrics"]
    assert isinstance(card["metrics"]["teacher_agreement"], float)
    assert isinstance(card["eval_passed"], bool)
    # No teenagers with permits: fixture stub student must NOT auto-pass
    assert card["eval_passed"] is False
    assert "not licensed" in card["license_note"].lower() or card["eval_passed"] is False


def test_scorecard_can_pass_only_when_thresholds_met(tmp_path, monkeypatch):
    """If we loosen thresholds enough, a real pass is allowed — still live=false."""
    # Hours floor would otherwise force insufficient_hours; toy allow for this unit case.
    monkeypatch.setenv("DISTILLERY_ALLOW_TOY_TRAIN", "1")
    soft_dir = tmp_path / "soft"
    batches = build_fixture_batches(n_batches=1, samples_per_batch=8)
    write_soft_label_artifacts(batches, soft_dir)
    from dataclasses import replace

    cfg = replace(
        load_eval_config(),
        soft_labels_dir=soft_dir,
        student_dir=tmp_path / "student",
        force_fixture=True,
        allow_toy_train=True,
        min_teacher_agreement=0.0,
        max_lateral_mae=999.0,
        max_longitudinal_mae=999.0,
        min_desire_top1=0.0,
        min_route_replay=0.0,
    )
    card = compute_scorecard(cfg, student_meta={"final_loss": 0.01})
    assert card["live"] is False
    assert card["eval_passed"] is True  # thresholds actually met
    assert card["source"] == "fixture"


def test_scorecard_insufficient_hours_forces_fail(tmp_path, monkeypatch):
    monkeypatch.delenv("DISTILLERY_ALLOW_TOY_TRAIN", raising=False)
    soft_dir = tmp_path / "soft"
    batches = build_fixture_batches(n_batches=1, samples_per_batch=8)
    write_soft_label_artifacts(batches, soft_dir)
    from dataclasses import replace

    cfg = replace(
        load_eval_config(),
        soft_labels_dir=soft_dir,
        student_dir=tmp_path / "student",
        force_fixture=True,
        allow_toy_train=False,
        min_train_hours=50.0,
        min_teacher_agreement=0.0,
        max_lateral_mae=999.0,
        max_longitudinal_mae=999.0,
        min_desire_top1=0.0,
        min_route_replay=0.0,
    )
    card = compute_scorecard(cfg, student_meta={"final_loss": 0.01})
    assert card["eval_passed"] is False
    assert card.get("fail_reason") == "insufficient_hours"
    assert card["gates"].get("hours") is False


def test_eval_pipeline_emits_eval_passed_false_on_fixture():
    events: list[dict] = []

    async def emit(ev: dict) -> None:
        events.append(ev)

    async def _run() -> None:
        result = await run_eval_pipeline(
            "test-eval-job",
            emit,
            tick=0.0,
            write_files=False,
        )
        assert result["live"] is False
        assert result["source"] == "fixture"
        assert result["eval_passed"] is False  # honest fail on fixture stub
        assert "eval_passed" in result

    asyncio.run(_run())

    parsed = [DistilleryEvent.model_validate(e) for e in events]
    assert any(e.kind == EventKind.stage and e.stage == StageName.eval for e in parsed)
    passed_metrics = [
        e
        for e in parsed
        if e.kind == EventKind.metric and e.payload.get("name") == "eval_passed"
    ]
    assert passed_metrics
    assert passed_metrics[0].payload["value"] == 0.0
    # Must have emitted real scorecard metrics (not just the gate bool)
    names = {
        e.payload.get("name")
        for e in parsed
        if e.kind == EventKind.metric
    }
    assert "teacher_agreement" in names
    assert "lateral_mae" in names
