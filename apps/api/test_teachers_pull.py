"""POST /teachers/pull — big_driving_supercombo only, progress bus, honest fixture."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from distillery_teacher.download import (
    BIG_TEACHER_NAME,
    TeacherArtifactStatus,
)


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("DISTILLERY_INGEST_FIXTURE", "1")
    monkeypatch.delenv("COMMA_JWT", raising=False)
    from api.main import app

    with TestClient(app) as c:
        yield c


def test_teachers_pull_fixture_completes_with_label(client, monkeypatch):
    monkeypatch.setenv("DISTILLERY_TEACHER_FIXTURE", "1")

    r = client.post("/teachers/pull", json={"force_fixture": True})
    assert r.status_code == 200
    data = r.json()
    assert data["kind"] == "teacher_pull"
    assert data["teacher"] == BIG_TEACHER_NAME
    assert data["default_teacher"] == BIG_TEACHER_NAME
    assert "big_driving_supercombo" in (data.get("label") or "")
    assert data["ws"].startswith("/ws/jobs/")
    assert data["events_url"].startswith("/jobs/")
    job_id = data["id"]

    # BackgroundTasks run before TestClient returns from request completion path;
    # poll events until stage done.
    ev = client.get(f"/jobs/{job_id}/events")
    assert ev.status_code == 200
    events = ev.json()["events"]
    assert events
    assert any(e.get("kind") == "progress" for e in events)
    stage_done = [
        e
        for e in events
        if e.get("kind") == "stage" and (e.get("payload") or {}).get("status") == "done"
    ]
    assert stage_done
    detail = (stage_done[-1].get("payload") or {}).get("detail") or ""
    assert "fixture" in detail and BIG_TEACHER_NAME in detail
    assert (stage_done[-1].get("payload") or {}).get("live") is False

    job = client.get(f"/jobs/{job_id}")
    assert job.status_code == 200
    assert job.json()["status"] == "done"
    assert job.json()["kind"] == "teacher_pull"


def test_teachers_pull_idempotent_cache_skip(client, monkeypatch, tmp_path):
    """Cache hit → live label, no re-download; progress bus still emits done."""
    monkeypatch.delenv("DISTILLERY_TEACHER_FIXTURE", raising=False)
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)

    onnx = tmp_path / "big_driving_supercombo.onnx"
    onnx.write_bytes(b"CACHED_BIG_TEACHER_ONNX_BYTES_XXXX" * 40)
    digest = __import__("hashlib").sha256(onnx.read_bytes()).hexdigest()
    (tmp_path / "big_driving_supercombo.onnx.sha256").write_text(digest + "\n")

    calls = {"n": 0}

    def _boom(*_a, **_k):
        calls["n"] += 1
        raise RuntimeError("should not download")

    monkeypatch.setattr("distillery_teacher.download._download_url", _boom)

    from api import main as api_main
    import distillery_teacher.download as dl

    async def _run(job_id, *, force_fixture=False, force_download=False):
        job = api_main._jobs[job_id]
        job.status = "running"
        art = dl.ensure_big_teacher_onnx(
            tmp_path,
            force_fixture=force_fixture,
            force_download=force_download,
        )
        await api_main._broadcast(
            job_id,
            {
                "id": "t1",
                "ts": api_main._now(),
                "job_id": job_id,
                "kind": "progress",
                "stage": "teach",
                "payload": {
                    "fraction": 1.0,
                    "detail": art.label,
                    "label": art.label,
                    "live": art.live,
                    "cached": art.cached,
                },
            },
        )
        await api_main._broadcast(
            job_id,
            {
                "id": "t2",
                "ts": api_main._now(),
                "job_id": job_id,
                "kind": "stage",
                "stage": "teach",
                "payload": {
                    "name": "teach",
                    "status": "done",
                    "detail": art.label,
                    "live": art.live,
                    "ok": art.ok,
                    "teacher": art.as_dict(),
                },
            },
        )
        job.status = "done"

    monkeypatch.setattr(api_main, "_run_teacher_pull_job", _run)

    r = client.post("/teachers/pull", json={})
    assert r.status_code == 200
    job_id = r.json()["id"]
    events = client.get(f"/jobs/{job_id}/events").json()["events"]
    done = [
        e
        for e in events
        if e.get("kind") == "stage" and (e.get("payload") or {}).get("status") == "done"
    ]
    assert done
    teacher = (done[-1].get("payload") or {}).get("teacher") or {}
    assert teacher.get("cached") is True
    assert teacher.get("live") is True
    assert teacher.get("name") == BIG_TEACHER_NAME
    assert "comma master" in (teacher.get("label") or "")
    assert calls["n"] == 0


def test_teachers_pull_never_small_on_offline(client, monkeypatch, tmp_path):
    monkeypatch.delenv("DISTILLERY_TEACHER_FIXTURE", raising=False)
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)

    from api import main as api_main

    async def _fake_run(job_id, *, force_fixture=False, force_download=False):
        art = TeacherArtifactStatus(
            ok=False,
            live=False,
            cached=False,
            path=None,
            source="fixture",
            label=f"fixture · {BIG_TEACHER_NAME}",
            detail="offline or download failed (live=false; no small-model fallback)",
            error="connection refused",
        )
        job = api_main._jobs[job_id]
        job.status = "running"
        await api_main._broadcast(
            job_id,
            {
                "id": "w1",
                "ts": api_main._now(),
                "job_id": job_id,
                "kind": "warning",
                "stage": "teach",
                "payload": {
                    "code": "TEACHER_NOT_LIVE",
                    "message": art.detail,
                    "recoverable": True,
                    "label": art.label,
                    "teacher": BIG_TEACHER_NAME,
                },
            },
        )
        await api_main._broadcast(
            job_id,
            {
                "id": "s1",
                "ts": api_main._now(),
                "job_id": job_id,
                "kind": "stage",
                "stage": "teach",
                "payload": {
                    "name": "teach",
                    "status": "done",
                    "detail": art.label,
                    "live": False,
                    "ok": False,
                    "teacher": art.as_dict(),
                },
            },
        )
        job.status = "done"

    monkeypatch.setattr(api_main, "_run_teacher_pull_job", _fake_run)
    r = client.post("/teachers/pull", json={})
    assert r.status_code == 200
    assert r.json()["teacher"] == BIG_TEACHER_NAME
    assert r.json()["teacher"] != "driving_supercombo"
    events = client.get(f"/jobs/{r.json()['id']}/events").json()["events"]
    warns = [e for e in events if e.get("kind") == "warning"]
    assert warns
    assert BIG_TEACHER_NAME in (warns[0].get("payload") or {}).get("label", "")
    assert not (tmp_path / "driving_supercombo.onnx").exists()
