"""Minimal API tests — GET/POST /focus coach stub."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    cache = tmp_path / "focus_history.json"
    monkeypatch.setattr("api.focus_store._FOCUS_CACHE", cache)
    from api.main import app

    with TestClient(app) as c:
        yield c, cache


def test_focus_empty(client):
    c, _ = client
    r = c.get("/focus")
    assert r.status_code == 200
    data = r.json()
    assert data["focus"] is None
    assert data["history"] == []


def test_focus_post_and_history(client):
    c, cache = client
    r = c.post("/focus", json={"focus": "stop lights, stop signs"})
    assert r.status_code == 200
    data = r.json()
    assert data["focus"] == "stop lights, stop signs"
    assert len(data["history"]) == 1
    assert data["history"][0]["text"] == "stop lights, stop signs"
    assert cache.is_file()

    r2 = c.post("/focus", json={"focus": "cut-ins"})
    assert r2.status_code == 200
    hist = r2.json()["history"]
    assert hist[0]["text"] == "cut-ins"
    assert hist[1]["text"] == "stop lights, stop signs"

    r3 = c.get("/focus")
    assert r3.json()["focus"] == "cut-ins"
    assert [h["text"] for h in r3.json()["history"]] == [
        "cut-ins",
        "stop lights, stop signs",
    ]


def test_focus_rejects_empty(client):
    c, _ = client
    r = c.post("/focus", json={"focus": "   "})
    assert r.status_code in (400, 422)


def test_train_all_accepts_focus(client, monkeypatch):
    c, _ = client
    monkeypatch.setenv("DISTILLERY_INGEST_FIXTURE", "1")
    monkeypatch.setenv("DISTILLERY_ALLOW_TOY_TRAIN", "1")

    def _ready_cpu_probe(*, force_fixture: bool = False):
        return {
            "device_found": True,
            "device_ready": True,
            "device_kind": "cpu",
            "device_name": "CPU",
            "torch": "ok",
            "live": False,
            "source": "torch",
            "data_source": "fixture" if force_fixture else "live",
            "detail": "torch device=cpu kind=cpu",
        }

    monkeypatch.setattr("api.main.probe_train_device", _ready_cpu_probe)
    monkeypatch.setattr(
        "distillery_student.readiness.probe_train_device", _ready_cpu_probe
    )
    monkeypatch.setattr(
        "distillery_student.device.probe_train_device", _ready_cpu_probe
    )

    r = c.post(
        "/jobs/train_all",
        json={
            "source": "fixture",
            "allow_toy": True,
            "force_fixture": True,
            "focus": "stop signs",
        },
    )
    assert r.status_code == 200
    assert r.json()["kind"] == "train_all"
    stored = c.get("/focus").json()
    assert stored["focus"] == "stop signs"
