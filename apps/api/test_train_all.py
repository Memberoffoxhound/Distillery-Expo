"""Minimal API tests — /ready, /teachers, /jobs/train_all."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("DISTILLERY_INGEST_FIXTURE", "1")
    monkeypatch.setenv("DISTILLERY_ALLOW_TOY_TRAIN", "1")
    monkeypatch.delenv("COMMA_JWT", raising=False)
    monkeypatch.delenv("CONNECT_JWT", raising=False)
    from api.main import app

    with TestClient(app) as c:
        yield c


def test_teachers_fixture(client):
    r = client.get("/teachers", params={"force_fixture": True})
    assert r.status_code == 200
    data = r.json()
    assert data["count"] >= 1
    assert isinstance(data["teachers"], list)
    assert data["teachers"][0].get("name")
    # fixture path labeled
    assert any(
        t.get("source") == "fixture" or t.get("live") is False for t in data["teachers"]
    )


def test_ready_structure(client):
    r = client.get("/ready", params={"allow_toy": True, "force_fixture": True})
    assert r.status_code == 200
    data = r.json()
    assert "ok" in data and "gaps" in data
    assert isinstance(data["gaps"], list)
    assert data["ok"] is True
    assert data["gaps"] == []


def test_ready_alias(client):
    r = client.get("/jobs/train_all/ready", params={"allow_toy": True, "force_fixture": True})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_train_all_409_when_not_ready(client, monkeypatch):
    monkeypatch.delenv("DISTILLERY_ALLOW_TOY_TRAIN", raising=False)
    r = client.post("/jobs/train_all", json={"source": "auto", "allow_toy": False})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail.get("ready") is False
    codes = {g.get("code") for g in detail.get("gaps") or []}
    assert codes  # at least one gap


def test_train_all_starts_when_ready(client):
    r = client.post(
        "/jobs/train_all",
        json={"source": "fixture", "allow_toy": True, "force_fixture": True},
    )
    assert r.status_code == 200
    job = r.json()
    assert job["kind"] == "train_all"
    assert job["status"] in ("pending", "running", "done")


def test_health_has_device(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "tinygrad" in data and "device" in data and "mode" in data
