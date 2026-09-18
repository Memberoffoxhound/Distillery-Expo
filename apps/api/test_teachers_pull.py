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

def test_teachers_pull_consume_live_after_ensure(client, monkeypatch, tmp_path):
    """After ensure writes cache, consume checksum-verifies → live comma master label."""
    monkeypatch.delenv("DISTILLERY_TEACHER_FIXTURE", raising=False)
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)

    import hashlib
    from api import main as api_main
    import distillery_teacher.download as dl
    from distillery_teacher.download import TeacherArtifactStatus

    body = b"BIG_TEACHER_LIVE_WEIGHTS_FOR_CONSUME_BIND" * 80
    onnx = tmp_path / "big_driving_supercombo.onnx"
    onnx.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    (tmp_path / "big_driving_supercombo.onnx.sha256").write_text(digest + "\n")

    def _ensure(dest_dir=None, *, force_fixture=False, force_download=False, progress=None, **_k):
        if progress:
            progress(0.5, "download big_driving_supercombo …")
        # Write into default teachers dir consume will read — point DEFAULT via monkeypatch
        return TeacherArtifactStatus(
            ok=True,
            live=True,
            cached=True,
            path=onnx,
            sha256=digest,
            source="commaai/openpilot@master",
            label=f"comma master · {BIG_TEACHER_NAME}",
            detail="ensured",
            bytes=len(body),
        )

    monkeypatch.setattr(dl, "ensure_big_teacher_onnx", _ensure)
    monkeypatch.setattr(dl, "DEFAULT_TEACHERS_DIR", tmp_path)
    monkeypatch.setattr(
        "distillery_teacher.consume.teachers_dir", lambda root=None: tmp_path if root is None else root
    )
    monkeypatch.setattr(
        "distillery_teacher.download.teachers_dir", lambda root=None: tmp_path if root is None else root
    )
    # Also patch artifact_paths resolution used by consume
    monkeypatch.setattr(
        "distillery_teacher.consume.artifact_paths",
        lambda dest_dir=None: (
            tmp_path / "big_driving_supercombo.onnx",
            tmp_path / "big_driving_supercombo.onnx.sha256",
            tmp_path / "big_driving_supercombo.json",
        ),
    )
    monkeypatch.setattr(
        "distillery_teacher.download.artifact_paths",
        lambda dest_dir=None: (
            tmp_path / "big_driving_supercombo.onnx",
            tmp_path / "big_driving_supercombo.onnx.sha256",
            tmp_path / "big_driving_supercombo.json",
        ),
    )

    r = client.post("/teachers/pull", json={})
    assert r.status_code == 200
    job_id = r.json()["id"]
    events = client.get(f"/jobs/{job_id}/events").json()["events"]
    verify = [
        e
        for e in events
        if e.get("kind") == "progress"
        and "verify checksum" in str((e.get("payload") or {}).get("detail") or "")
    ]
    assert verify, "expected consume verify progress event"
    done = [
        e
        for e in events
        if e.get("kind") == "stage" and (e.get("payload") or {}).get("status") == "done"
    ]
    assert done
    payload = done[-1].get("payload") or {}
    assert payload.get("live") is True
    assert "comma master" in (payload.get("detail") or payload.get("label") or "")
    teacher = payload.get("teacher") or {}
    assert teacher.get("name") == BIG_TEACHER_NAME
    assert teacher.get("live") is True
    # final progress carries consumed flag
    finals = [
        e
        for e in events
        if e.get("kind") == "progress" and (e.get("payload") or {}).get("fraction") == 1.0
    ]
    assert finals
    assert (finals[-1].get("payload") or {}).get("consumed") is True
    assert (finals[-1].get("payload") or {}).get("live") is True


def test_teachers_pull_consume_checksum_fail_stays_fixture(client, monkeypatch, tmp_path):
    """Corrupt sidecar → consume fixtures; never silent small model / never pretend live."""
    monkeypatch.delenv("DISTILLERY_TEACHER_FIXTURE", raising=False)
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)

    import distillery_teacher.download as dl
    from distillery_teacher.download import TeacherArtifactStatus

    body = b"TAMPERED_OR_CORRUPT_BIG_TEACHER" * 80
    onnx = tmp_path / "big_driving_supercombo.onnx"
    onnx.write_bytes(body)
    (tmp_path / "big_driving_supercombo.onnx.sha256").write_text(("0" * 64) + "\n")
    # small model present must be ignored
    (tmp_path / "driving_supercombo.onnx").write_bytes(b"SMALL" * 400)

    def _ensure(dest_dir=None, *, force_fixture=False, force_download=False, progress=None, **_k):
        if progress:
            progress(0.6, "download done")
        return TeacherArtifactStatus(
            ok=True,
            live=True,  # ensure claims live — consume must overturn
            cached=True,
            path=onnx,
            sha256="0" * 64,
            source="commaai/openpilot@master",
            label=f"comma master · {BIG_TEACHER_NAME}",
            detail="ensured-but-bad-sha",
            bytes=len(body),
        )

    monkeypatch.setattr(dl, "ensure_big_teacher_onnx", _ensure)
    paths = (
        tmp_path / "big_driving_supercombo.onnx",
        tmp_path / "big_driving_supercombo.onnx.sha256",
        tmp_path / "big_driving_supercombo.json",
    )
    monkeypatch.setattr("distillery_teacher.consume.artifact_paths", lambda dest_dir=None: paths)
    monkeypatch.setattr("distillery_teacher.download.artifact_paths", lambda dest_dir=None: paths)
    monkeypatch.setattr(
        "distillery_teacher.consume.teachers_dir", lambda root=None: tmp_path if root is None else root
    )
    monkeypatch.setattr(
        "distillery_teacher.download.teachers_dir", lambda root=None: tmp_path if root is None else root
    )
    monkeypatch.setattr(dl, "cached_big_teacher_ok", lambda dest_dir=None: None)

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
    payload = done[-1].get("payload") or {}
    assert payload.get("live") is False
    detail = payload.get("detail") or ""
    assert "fixture" in detail and BIG_TEACHER_NAME in detail
    teacher = payload.get("teacher") or {}
    assert teacher.get("name") == BIG_TEACHER_NAME
    assert teacher.get("name") != "driving_supercombo"
    assert teacher.get("live") is False
    warns = [e for e in events if e.get("kind") == "warning"]
    assert warns
    assert (warns[-1].get("payload") or {}).get("code") == "TEACHER_NOT_LIVE"

