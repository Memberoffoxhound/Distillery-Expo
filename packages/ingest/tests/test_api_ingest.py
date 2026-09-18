"""API smoke — /routes + /jobs/ingest over existing WS job channel."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# Ensure fixture mode before importing app (config reads env at call time — fine)


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("DISTILLERY_INGEST_FIXTURE", "1")
    monkeypatch.delenv("COMMA_JWT", raising=False)
    monkeypatch.delenv("MICI_SSH_HOST", raising=False)
    from api.main import app

    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_dongle(client):
    r = client.get("/dongle")
    assert r.status_code == 200
    assert r.json()["dongle_id"] == "3e2de7ed673817c2"


def test_list_routes_fixture(client):
    r = client.get("/routes", params={"source": "fixture"})
    assert r.status_code == 200
    data = r.json()
    assert data["source"] == "fixture"
    assert data["dongle_id"] == "3e2de7ed673817c2"
    assert len(data["routes"]) >= 1
    assert data["routes"][0]["meta"].get("fixture") is True or data["routes"][0]["meta"].get("label") == "fixture"


def test_ingest_job_streams_samples(client):
    r = client.post("/jobs/ingest", json={"source": "fixture"})
    assert r.status_code == 200
    job = r.json()
    assert job["kind"] == "ingest"
    job_id = job["id"]

    # Poll until done (background task on TestClient runs in-thread)
    import time

    events = []
    for _ in range(50):
        time.sleep(0.05)
        er = client.get(f"/jobs/{job_id}/events")
        assert er.status_code == 200
        events = er.json()["events"]
        jr = client.get(f"/jobs/{job_id}")
        if jr.json()["status"] in ("done", "failed"):
            break

    assert client.get(f"/jobs/{job_id}").json()["status"] == "done"
    kinds = {e["kind"] for e in events}
    assert "stage" in kinds and "sample" in kinds and "progress" in kinds
    cams = {e["payload"]["cam"] for e in events if e["kind"] == "sample"}
    assert cams >= {"road", "wide", "driver"}
    # Flash gating untouched — no flash stage in ingest-only job
    assert not any(e.get("stage") == "flash" for e in events)
