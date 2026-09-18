"""Train pipeline — emits loss curves; stock modelV2 I/O contract; hours floor."""

from __future__ import annotations

import asyncio
import json

import pytest

from distillery_events import DistilleryEvent, EventKind, StageName
from distillery_student import (
    InsufficientHoursError,
    check_train_readiness,
    estimate_driving_hours,
    hours_meet_floor,
    load_student_config,
    probe_train_device,
    run_train_pipeline,
)


@pytest.fixture(autouse=True)
def _toy_ci(monkeypatch):
    """Existing smoke path uses fixture data — allow toy train for CI."""
    monkeypatch.setenv("DISTILLERY_ALLOW_TOY_TRAIN", "1")


def test_config_io_compatible():
    cfg = load_student_config()
    assert cfg.io_compatible is True
    assert "modelV2" in cfg.name or cfg.io_compatible
    assert cfg.min_train_hours >= 50


def test_probe_train_device_keys_without_tinygrad():
    info = probe_train_device(force_fixture=False)
    for key in (
        "device_found",
        "device_ready",
        "device_kind",
        "device_name",
        "tinygrad",
    ):
        assert key in info
    assert info["tinygrad"] in ("ok", "missing")
    assert info["device_kind"] in ("gpu", "cpu", "unknown")
    assert info["live"] is False


def test_probe_force_fixture_labeled():
    """force_fixture tags data_source — does not invent a dead device."""
    info = probe_train_device(force_fixture=True)
    assert info.get("data_source") == "fixture"
    assert info["live"] is False
    # Real probe: tinygrad ok|missing, never the old fake "fixture" device status
    assert info["tinygrad"] in ("ok", "missing")
    if info["tinygrad"] == "ok":
        assert info["device_ready"] is True
        assert info["device_name"] != "fixture"
    else:
        assert info["device_ready"] is False


def test_hours_floor_refuses_unknown(tmp_path):
    info = estimate_driving_hours(
        soft_labels_dir=tmp_path / "missing",
        shards_dir=tmp_path / "no_shards",
    )
    assert info["known"] is False
    assert info["hours"] == 0.0
    gate = hours_meet_floor(info, min_hours=50.0, allow_toy=False)
    assert gate["ok"] is False
    assert gate["reason"] == "insufficient_hours"
    assert gate["licensed"] is False


def test_hours_floor_toy_allow_not_licensed():
    info = {"hours": 0.1, "known": True, "live": False, "fixture": True}
    gate = hours_meet_floor(info, min_hours=50.0, allow_toy=True)
    assert gate["ok"] is True
    assert gate["toy_override"] is True
    assert gate["licensed"] is False
    assert gate["live"] is False


def test_hours_from_soft_meta(tmp_path):
    soft = tmp_path / "soft"
    soft.mkdir()
    (soft / "manifest.json").write_text(
        json.dumps(
            {
                "live": True,
                "source": "device",
                "driving_hours": 55.5,
                "teacher": "Cinque/supercombo",
                "batches": [],
            }
        )
        + "\n"
    )
    info = estimate_driving_hours(soft_labels_dir=soft)
    assert info["known"] is True
    assert info["hours"] == 55.5
    gate = hours_meet_floor(info, min_hours=50.0, allow_toy=False)
    assert gate["ok"] is True


def test_train_refuses_without_toy_override(monkeypatch, tmp_path):
    monkeypatch.delenv("DISTILLERY_ALLOW_TOY_TRAIN", raising=False)
    from dataclasses import replace

    cfg = replace(
        load_student_config(),
        soft_labels_dir=tmp_path / "soft",
        shards_dir=tmp_path / "shards",
        allow_toy_train=False,
        min_train_hours=50.0,
        force_fixture=True,
    )

    events: list[dict] = []

    async def emit(ev: dict) -> None:
        events.append(ev)

    async def _run() -> None:
        with pytest.raises(InsufficientHoursError):
            await run_train_pipeline(
                "test-train-refuse",
                emit,
                cfg=cfg,
                tick=0.0,
                write_files=False,
                steps=2,
            )

    asyncio.run(_run())
    warn = [
        e
        for e in events
        if e.get("kind") == "warning"
        and (e.get("payload") or {}).get("code") == "INSUFFICIENT_HOURS"
    ]
    assert warn


def test_train_pipeline_emits_loss_metrics():
    events: list[dict] = []

    async def emit(ev: dict) -> None:
        events.append(ev)

    async def _run() -> None:
        result = await run_train_pipeline(
            "test-train-job",
            emit,
            tick=0.0,
            write_files=False,
            steps=4,
        )
        assert result["io_contract"] == "stock-modelV2"
        assert result["steps"] == 4
        assert "final_loss" in result
        assert result["live"] is False
        assert result["licensed"] is False
        assert "device" in result
        assert "hours_gate" in result

    asyncio.run(_run())

    parsed = [DistilleryEvent.model_validate(e) for e in events]
    assert any(e.kind == EventKind.stage and e.stage == StageName.train for e in parsed)
    losses = [
        e
        for e in parsed
        if e.kind == EventKind.metric and e.payload.get("name") == "train_loss"
    ]
    assert len(losses) == 4
    vals = [e.payload["value"] for e in losses]
    assert vals[-1] < vals[0]


def test_check_train_readiness_reports_gaps(monkeypatch, tmp_path):
    """force_fixture ≠ device_not_ready — fixture path with a ready device must not gap device."""
    monkeypatch.delenv("DISTILLERY_ALLOW_TOY_TRAIN", raising=False)
    from dataclasses import replace

    import distillery_student.readiness as readiness_mod

    def _ready_cpu(*, force_fixture: bool = False):
        return {
            "device_found": True,
            "device_ready": True,
            "device_kind": "cpu",
            "device_name": "CPU",
            "tinygrad": "ok",
            "live": False,
            "source": "tinygrad",
            "data_source": "fixture" if force_fixture else "live",
            "detail": "tinygrad Device.DEFAULT=CPU kind=cpu; data path fixture / not licensed",
        }

    monkeypatch.setattr(readiness_mod, "probe_train_device", _ready_cpu)
    cfg = replace(
        load_student_config(),
        soft_labels_dir=tmp_path / "soft",
        shards_dir=tmp_path / "shards",
        allow_toy_train=False,
        force_fixture=True,
        min_train_hours=50.0,
    )
    ready = check_train_readiness(cfg=cfg, force_fixture=True, allow_toy=False)
    assert ready["ok"] is False
    codes = {g["code"] for g in ready["gaps"]}
    assert "insufficient_hours" in codes
    assert "device_not_ready" not in codes
    assert ready["device"]["device_ready"] is True
    assert ready["device"].get("data_source") == "fixture"
    # fixture teacher without toy → teacher_not_selected gap
    assert "teacher_not_selected" in codes
    for g in ready["gaps"]:
        assert "code" in g and "message" in g


def test_check_train_readiness_device_not_ready_when_probe_fails(monkeypatch, tmp_path):
    monkeypatch.delenv("DISTILLERY_ALLOW_TOY_TRAIN", raising=False)
    from dataclasses import replace

    import distillery_student.readiness as readiness_mod

    def _dead_device(*, force_fixture: bool = False):
        return {
            "device_found": False,
            "device_ready": False,
            "device_kind": "unknown",
            "device_name": "none",
            "tinygrad": "missing",
            "live": False,
            "source": "probe",
            "detail": "monkeypatched missing tinygrad",
        }

    monkeypatch.setattr(readiness_mod, "probe_train_device", _dead_device)
    cfg = replace(
        load_student_config(),
        soft_labels_dir=tmp_path / "soft",
        shards_dir=tmp_path / "shards",
        allow_toy_train=True,
        force_fixture=False,
        min_train_hours=50.0,
    )
    ready = check_train_readiness(cfg=cfg, force_fixture=False, allow_toy=True, teacher_name="driving_supercombo")
    codes = {g["code"] for g in ready["gaps"]}
    assert "device_not_ready" in codes


def test_check_train_readiness_missing_live_cache_is_gap(monkeypatch, tmp_path):
    """Live train without artifacts/teachers cache is a gap (unless CI override)."""
    monkeypatch.delenv("DISTILLERY_ALLOW_TOY_TRAIN", raising=False)
    monkeypatch.delenv("DISTILLERY_TEACHER_FIXTURE", raising=False)
    monkeypatch.delenv("DISTILLERY_STUDENT_FIXTURE", raising=False)
    from dataclasses import replace

    import distillery_student.readiness as readiness_mod

    def _ready_cpu(*, force_fixture: bool = False):
        return {
            "device_found": True,
            "device_ready": True,
            "device_kind": "cpu",
            "device_name": "CPU",
            "tinygrad": "ok",
            "live": True,
            "source": "tinygrad",
            "data_source": "live",
            "detail": "tinygrad Device.DEFAULT=CPU",
        }

    monkeypatch.setattr(readiness_mod, "probe_train_device", _ready_cpu)

    # Live listing, but no on-disk cache
    live_teacher = {
        "name": "big_driving_supercombo",
        "version": "master",
        "source": "commaai/openpilot@master",
        "live": True,
        "label": "comma master · big_driving_supercombo",
        "role": "big",
    }

    def _select(name=None, *, force_fixture=False):
        return None if force_fixture else dict(live_teacher)

    import distillery_teacher.comma_master as cm

    monkeypatch.setattr(cm, "select_comma_master_teacher", _select)
    monkeypatch.setattr(
        "distillery_teacher.download.cached_big_teacher_ok",
        lambda *a, **k: None,
    )

    soft = tmp_path / "soft"
    soft.mkdir()
    (soft / "manifest.json").write_text(
        '{"hours": 60, "live": true, "source": "live", "n_samples": 1000}\n'
    )
    cfg = replace(
        load_student_config(),
        soft_labels_dir=soft,
        shards_dir=tmp_path / "shards",
        allow_toy_train=False,
        force_fixture=False,
        min_train_hours=50.0,
    )
    ready = check_train_readiness(cfg=cfg, force_fixture=False, allow_toy=False)
    assert ready["ok"] is False
    codes = {g["code"] for g in ready["gaps"]}
    assert "teacher_not_selected" in codes
    assert any("artifacts/teachers" in g["message"] for g in ready["gaps"])


def test_ingest_fixture_does_not_force_student_config(monkeypatch):
    monkeypatch.delenv("DISTILLERY_STUDENT_FIXTURE", raising=False)
    monkeypatch.setenv("DISTILLERY_INGEST_FIXTURE", "1")
    cfg = load_student_config()
    assert cfg.force_fixture is False
