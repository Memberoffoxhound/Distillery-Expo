"""API smoke — POST /jobs/shard over existing WS job channel."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("DISTILLERY_INGEST_FIXTURE", "1")
    monkeypatch.setenv("DISTILLERY_SHARD_FIXTURE", "1")
    monkeypatch.delenv("COMMA_JWT", raising=False)
    monkeypatch.delenv("MICI_SSH_HOST", raising=False)
    from api.main import app

    with TestClient(app) as c:
        yield c


def test_shard_job_streams_samples(client):
    r = client.post("/jobs/shard", json={"source": "fixture"})
    assert r.status_code == 200
    job = r.json()
    assert job["kind"] == "shard"
    job_id = job["id"]

    events = []
    for _ in range(80):
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
    shard_samples = [
        e for e in events if e["kind"] == "sample" and e.get("stage") == "shard"
    ]
    assert len(shard_samples) >= 1
    meta = shard_samples[0]["payload"]["meta"]
    for key in ("shard_id", "route_id", "frame_count", "size_bytes", "status"):
        assert key in meta
    assert not any(e.get("stage") == "flash" for e in events)


def test_shard_job_accepts_route_id(client):
    r = client.post(
        "/jobs/shard",
        json={"source": "fixture", "route_id": "3e2de7ed673817c2|2024-06-15--14-30-00"},
    )
    assert r.status_code == 200
    assert r.json()["kind"] == "shard"
