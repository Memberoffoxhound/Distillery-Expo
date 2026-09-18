"""API contracts — teach/train events + eval-gate-before-flash."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("DISTILLERY_INGEST_FIXTURE", "1")
    monkeypatch.setenv("DISTILLERY_TEACHER_FIXTURE", "1")
    monkeypatch.setenv("DISTILLERY_STUDENT_FIXTURE", "1")
    monkeypatch.delenv("COMMA_JWT", raising=False)
    monkeypatch.delenv("MICI_SSH_HOST", raising=False)
    from api.main import app

    with TestClient(app) as c:
        yield c


def _wait_done(client, job_id: str, timeout_s: float = 8.0):
    events = []
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(0.05)
        er = client.get(f"/jobs/{job_id}/events")
        assert er.status_code == 200
        body = er.json()
        events = body["events"]
        jr = client.get(f"/jobs/{job_id}")
        if jr.json()["status"] in ("done", "failed", "gated"):
            return body, jr.json()
    return client.get(f"/jobs/{job_id}/events").json(), client.get(f"/jobs/{job_id}").json()


def test_teach_job_streams_stage_metrics(client):
    r = client.post("/jobs/teach", json={"source": "fixture"})
    assert r.status_code == 200
    job = r.json()
    assert job["kind"] == "teach"
    body, summary = _wait_done(client, job["id"])
    assert summary["status"] == "done"
    events = body["events"]
    assert any(e.get("stage") == "teach" and e["kind"] == "stage" for e in events)
    assert any(e.get("stage") == "teach" and e["kind"] == "progress" for e in events)
    metrics = {
        e["payload"]["name"]
        for e in events
        if e["kind"] == "metric" and e.get("stage") == "teach"
    }
    assert "teacher_fps" in metrics or "soft_labels" in metrics
    # Honest non-live labeling somewhere in teach stream
    blob = str(events).lower()
    assert "live=false" in blob or "fixture" in blob


def test_train_job_streams_train_loss(client):
    r = client.post("/jobs/train", json={"source": "fixture"})
    assert r.status_code == 200
    job = r.json()
    assert job["kind"] == "train"
    body, summary = _wait_done(client, job["id"])
    assert summary["status"] == "done"
    events = body["events"]
    losses = [
        e
        for e in events
        if e["kind"] == "metric"
        and e.get("stage") == "train"
        and e["payload"].get("name") == "train_loss"
    ]
    assert len(losses) >= 1
    assert any(e.get("stage") == "train" and e["kind"] == "progress" for e in events)


def test_flash_confirm_blocked_without_eval_pass(client):
    r = client.post("/jobs/teach", json={})
    assert r.status_code == 200
    job_id = r.json()["id"]
    _wait_done(client, job_id)
    # No eval on this job → eval_passed defaults False
    events = client.get(f"/jobs/{job_id}/events").json()
    assert events.get("eval_passed") is False
    blocked = client.post(
        f"/jobs/{job_id}/flash/confirm",
        json={"confirm": True},
    )
    assert blocked.status_code == 403
    detail = blocked.json()["detail"]
    assert detail["blocked"] is True
    assert detail["eval_passed"] is False


def test_eval_fixture_emits_scorecard_and_defaults_fail(client):
    r = client.post("/jobs/eval", json={})
    assert r.status_code == 200
    job_id = r.json()["id"]
    body, summary = _wait_done(client, job_id)
    assert summary["status"] == "done"
    assert body["eval_passed"] is False
    names = {
        e["payload"]["name"]
        for e in body["events"]
        if e["kind"] == "metric" and e.get("stage") == "eval"
    }
    # Real scorecard numbers present — never empty greenwash
    for key in (
        "teacher_agreement",
        "lateral_mae",
        "longitudinal_mae",
        "desire_top1",
        "route_replay",
    ):
        assert key in names
    assert "eval_pass" in names or "eval_passed" in names
    gate_vals = [
        e["payload"]["value"]
        for e in body["events"]
        if e["kind"] == "metric"
        and e["payload"].get("name") in ("eval_pass", "eval_passed")
    ]
    assert gate_vals and float(gate_vals[-1]) == 0.0
    blocked = client.post(f"/jobs/{job_id}/flash/confirm", json={"confirm": True})
    assert blocked.status_code == 403


def test_eval_force_pass_unlocks_flash_confirm_only(client, monkeypatch):
    """Confirm only after eval_passed=True; never device_write from confirm alone.

    Graig fixture eval honestly fails — use API fixture adapter + force_pass for unlock.
    """
    from api import ml_adapters
    from api import main as api_main

    monkeypatch.setattr(ml_adapters, "resolve_eval", lambda: ml_adapters._fixture_eval)
    monkeypatch.setattr(api_main, "resolve_eval", lambda: ml_adapters._fixture_eval)

    r = client.post("/jobs/eval", json={"force_pass": True})
    assert r.status_code == 200
    job_id = r.json()["id"]
    body, _ = _wait_done(client, job_id)
    assert body["eval_passed"] is True
    ok = client.post(f"/jobs/{job_id}/flash/confirm", json={"confirm": True})
    assert ok.status_code == 200
    data = ok.json()
    assert data["ok"] is True
    assert data["eval_passed"] is True
    assert data.get("device_write") is False


def test_health_reports_ml_backends(client):
    r = client.get("/health")
    assert r.status_code == 200
    backends = r.json()["ml_backends"]
    assert set(backends) >= {"teach", "train", "export", "eval", "flash"}
