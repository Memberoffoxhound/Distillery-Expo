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


def test_dongle(client, tmp_path, monkeypatch):
    monkeypatch.setattr("distillery_ingest.discover._DONGLE_CACHE", tmp_path / "dongle_id")
    monkeypatch.setattr("distillery_ingest.config._DONGLE_CACHE", tmp_path / "dongle_id")
    monkeypatch.delenv("DISTILLERY_DONGLE_ID", raising=False)
    r = client.get("/dongle")
    assert r.status_code == 200
    data = r.json()
    # No hardcoded demo dongle as user-facing default
    assert data.get("dongle_id") in (None, "")
    assert data.get("configured") is False
    assert "cams" in data
    assert "connect_available" in data
    assert "ssh_available" in data
    assert "force_fixture" in data
    assert isinstance(data["adb_available"], bool)
    assert data["adb_status"] in ("ready", "not_on_path", "error")
    assert isinstance(data["adb_device_count"], int)
    assert data["adb_device_count"] >= 0
    assert "suggested_dongle_id" in data
    # Never invent a default suggested id when nothing is connected
    assert data.get("suggested_dongle_id") in (None, "")
    assert "discovered_from" in data
    assert data.get("discovered_from") in (None, "")
    assert "dongle_discovery_source" in data
    assert "auto_hydrated" in data


def test_list_routes_fixture(client):
    r = client.get("/routes", params={"source": "fixture"})
    assert r.status_code == 200
    data = r.json()
    assert data["source"] == "fixture"
    assert len(data["routes"]) >= 1
    assert data["routes"][0]["meta"].get("fixture") is True or data["routes"][0]["meta"].get("label") == "fixture"
    # Fixture last-resort stays labeled; sample route keeps its fixture dongle id
    assert data["routes"][0]["dongle_id"] == "3e2de7ed673817c2"


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


def test_health_torch_shape(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["status"] == "ok"
    assert data["torch"] in ("ok", "missing")
    assert data["mode"] in ("live", "fixture")
    device = data["device"]
    assert "found" in device and "ready" in device
    assert "kind" in device and "name" in device and "backend" in device
    # torch optional — honest missing + fixture when not installed
    if data["torch"] == "missing":
        assert data["mode"] == "fixture"
        assert device["found"] is False
        assert "torch: missing" in (data.get("detail") or "")
    else:
        assert device["found"] is True
        name = str(device["name"])
        assert name in ("cuda", "mps", "cpu") or name.startswith(("cuda:", "rocm"))
    if data.get("tinygrad_note"):
        label = str(data["tinygrad_note"].get("label", "")).lower()
        assert "not train" in label


def test_status_runtime(client):
    r = client.get("/status/runtime")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["torch"] in ("ok", "missing")
    assert "ml_backends" in data


def test_discover_devices(client):
    r = client.get("/discover/devices")
    assert r.status_code == 200
    data = r.json()
    assert "devices" in data
    assert "adb_available" in data
    assert isinstance(data["devices"], list)


def test_discover_connect_get_and_post(client, tmp_path, monkeypatch):
    cache = tmp_path / "connect_jwt"
    monkeypatch.setattr("distillery_ingest.discover._JWT_CACHE", cache)
    monkeypatch.delenv("COMMA_JWT", raising=False)
    monkeypatch.delenv("CONNECT_JWT", raising=False)

    g = client.get("/discover/connect")
    assert g.status_code == 200
    assert "configured" in g.json()

    p = client.post("/discover/connect", json={"jwt": "testjwtTOKEN1234", "persist": True})
    assert p.status_code == 200
    body = p.json()
    assert body["configured"] is True
    assert body["jwt_masked"]
    assert "test" not in body.get("jwt_masked", "") or "…" in body["jwt_masked"]
    assert cache.is_file()
    # secret must not appear in response keys
    assert "jwt" not in body or body.get("jwt") is None


def test_discover_overview(client):
    r = client.get("/discover")
    assert r.status_code == 200
    data = r.json()
    for key in (
        "devices",
        "connect",
        "ssh",
        "fixture",
        "sources",
        "dongle_id",
        "suggested_dongle_id",
        "discovered_from",
        "dongle_discovery_source",
    ):
        assert key in data
    assert data["fixture"]["label"] == "fixture"


def test_routes_accepts_device_query(client):
    r = client.get(
        "/routes",
        params={"source": "fixture", "device": "192.168.1.9:5555", "limit": 5},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["source"] == "fixture"
    assert data["device"] == "192.168.1.9:5555"
    assert data["ssh_host"] == "192.168.1.9"


def test_discover_ssh_get_and_post(client, tmp_path, monkeypatch):
    cache = tmp_path / "ssh_config.json"
    monkeypatch.setattr("distillery_ingest.discover._SSH_CACHE", cache)
    for key in (
        "MICI_SSH_HOST",
        "COMMA_SSH_HOST",
        "MICI_SSH_USER",
        "COMMA_SSH_USER",
        "MICI_SSH_PORT",
        "COMMA_SSH_PORT",
        "MICI_SSH_KEY",
        "COMMA_SSH_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    g = client.get("/discover/ssh")
    assert g.status_code == 200
    assert "configured" in g.json()
    assert "port" in g.json()

    p = client.post(
        "/discover/ssh",
        json={
            "host": "192.168.1.77",
            "user": "comma",
            "port": 22,
            "identity_path": "/home/user/.ssh/id_ed25519",
            "persist": True,
        },
    )
    assert p.status_code == 200
    body = p.json()
    assert body["configured"] is True
    assert body["host"] == "192.168.1.77"
    assert body["user"] == "comma"
    assert body["port"] == 22
    assert body["identity_path"] == "/home/user/.ssh/id_ed25519"
    assert body["key_set"] is True
    assert cache.is_file()
    # no key material beyond path
    assert "private_key" not in body
    assert "-----" not in str(body)


def test_discover_ssh_test_unconfigured(client, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "distillery_ingest.discover._SSH_CACHE",
        tmp_path / "missing_ssh.json",
    )
    for key in ("MICI_SSH_HOST", "COMMA_SSH_HOST"):
        monkeypatch.delenv(key, raising=False)
    # clear via set empty is invalid; just probe
    r = client.post("/discover/ssh/test")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body.get("error")


def test_routes_ssh_empty_honest(monkeypatch, tmp_path):
    """GET /routes?source=ssh with empty realdata → source=ssh, 0 routes, Phil message."""
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)
    monkeypatch.setenv("MICI_SSH_HOST", "192.168.1.50")
    monkeypatch.setenv("MICI_SSH_USER", "comma")
    monkeypatch.setenv("DISTILLERY_DONGLE_ID", "aabbccddeeff0011")
    # Isolate from on-disk JWT / ssh caches that would change posture
    monkeypatch.setattr(
        "distillery_ingest.discover._SSH_CACHE",
        tmp_path / "ssh_config.json",
    )
    monkeypatch.setattr(
        "distillery_ingest.discover._JWT_CACHE",
        tmp_path / "connect_jwt",
    )

    from distillery_ingest.sources.ssh import REALDATA, SshRouteSource

    monkeypatch.setattr(SshRouteSource, "list_routes", lambda self, *, limit=20: [])

    from api.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        r = c.get("/routes", params={"source": "ssh", "limit": 10})
    assert r.status_code == 200
    data = r.json()
    assert data["source"] == "ssh"
    assert data["ssh_host"] == "192.168.1.50"
    assert data["routes"] == []
    assert data.get("empty_reason") == "empty_realdata"
    assert data.get("message") == f"SSH ok · 0 routes under {REALDATA}"
    # Must not quietly return fixture routes
    assert not any(
        (row.get("meta") or {}).get("fixture") or row.get("source") == "fixture"
        for row in data["routes"]
    )


def test_routes_ssh_error_honest(monkeypatch, tmp_path):
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)
    monkeypatch.setenv("MICI_SSH_HOST", "10.0.0.9")
    monkeypatch.setenv("DISTILLERY_DONGLE_ID", "aabbccddeeff0011")
    monkeypatch.setattr(
        "distillery_ingest.discover._SSH_CACHE",
        tmp_path / "ssh_config.json",
    )
    monkeypatch.setattr(
        "distillery_ingest.discover._JWT_CACHE",
        tmp_path / "connect_jwt",
    )

    from distillery_ingest.sources.ssh import SshRouteSource

    def _boom(self, *, limit=20):
        raise RuntimeError("Connection timed out")

    monkeypatch.setattr(SshRouteSource, "list_routes", _boom)

    from api.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        r = c.get("/routes", params={"source": "ssh"})
    assert r.status_code == 200
    data = r.json()
    assert data["source"] == "ssh"
    assert data["routes"] == []
    assert data.get("empty_reason") == "ssh_error"
    assert "timed out" in (data.get("error") or "").lower() or "timed out" in (
        data.get("message") or ""
    ).lower()


def test_dongle_post_save_and_get(client, tmp_path, monkeypatch):
    cache = tmp_path / "dongle_id"
    monkeypatch.setattr("distillery_ingest.discover._DONGLE_CACHE", cache)
    monkeypatch.setattr("distillery_ingest.config._DONGLE_CACHE", cache)
    monkeypatch.delenv("DISTILLERY_DONGLE_ID", raising=False)

    g = client.get("/dongle")
    assert g.status_code == 200
    assert g.json().get("configured") is False

    p = client.post("/dongle", json={"dongle_id": "aabbccddeeff0011", "persist": True})
    assert p.status_code == 200
    body = p.json()
    assert body["configured"] is True
    assert body["dongle_id"] == "aabbccddeeff0011"
    assert body.get("persisted") is True
    assert cache.is_file()
    assert cache.read_text(encoding="utf-8").strip() == "aabbccddeeff0011"

    g2 = client.get("/dongle")
    assert g2.json()["dongle_id"] == "aabbccddeeff0011"


def test_routes_connect_unset_dongle_honest(monkeypatch, tmp_path):
    """source=connect with no saved dongle → honest gap, never fixture dongle."""
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)
    monkeypatch.delenv("DISTILLERY_DONGLE_ID", raising=False)
    monkeypatch.setenv("COMMA_JWT", "testjwtTOKEN12345678")
    monkeypatch.setattr("distillery_ingest.discover._DONGLE_CACHE", tmp_path / "dongle_id")
    monkeypatch.setattr("distillery_ingest.config._DONGLE_CACHE", tmp_path / "dongle_id")
    monkeypatch.setattr("distillery_ingest.discover._JWT_CACHE", tmp_path / "connect_jwt")
    monkeypatch.setattr("distillery_ingest.discover._SSH_CACHE", tmp_path / "ssh.json")

    from api.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        r = c.get("/routes", params={"source": "connect", "limit": 10})
    assert r.status_code == 200
    data = r.json()
    assert data["source"] == "connect"
    assert data["routes"] == []
    assert data.get("empty_reason") == "dongle_id_required"
    assert "Dongle ID required" in (data.get("message") or "")
    assert data.get("dongle_id") in (None, "")
    assert not any(
        (row.get("meta") or {}).get("fixture") or row.get("source") == "fixture"
        for row in data["routes"]
    )


def test_routes_connect_uses_saved_dongle_id(monkeypatch, tmp_path):
    """POST /dongle then source=connect uses the saved id (mocked Connect list)."""
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)
    monkeypatch.delenv("DISTILLERY_DONGLE_ID", raising=False)
    monkeypatch.setenv("COMMA_JWT", "testjwtTOKEN12345678")
    cache = tmp_path / "dongle_id"
    monkeypatch.setattr("distillery_ingest.discover._DONGLE_CACHE", cache)
    monkeypatch.setattr("distillery_ingest.config._DONGLE_CACHE", cache)
    monkeypatch.setattr("distillery_ingest.discover._JWT_CACHE", tmp_path / "connect_jwt")
    monkeypatch.setattr("distillery_ingest.discover._SSH_CACHE", tmp_path / "ssh.json")

    from distillery_ingest.models import RouteInfo
    from distillery_ingest.sources.connect import ConnectRouteSource

    seen: dict = {}

    def _list(self, *, limit=20):
        seen["dongle_id"] = self.cfg.dongle_id
        return [
            RouteInfo(
                route_id=f"{self.cfg.dongle_id}|2024-01-01--00-00-00",
                dongle_id=self.cfg.dongle_id,
                display_name="live-route",
                source="connect",
                segment_count=1,
                meta={"fixture": False, "label": "connect"},
            )
        ]

    monkeypatch.setattr(ConnectRouteSource, "list_routes", _list)

    from api.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        p = c.post("/dongle", json={"dongle_id": "deadbeefcafebabe", "persist": True})
        assert p.status_code == 200
        assert p.json()["dongle_id"] == "deadbeefcafebabe"
        r = c.get("/routes", params={"source": "connect", "limit": 5})
    assert r.status_code == 200
    data = r.json()
    assert data["source"] == "connect"
    assert data["dongle_id"] == "deadbeefcafebabe"
    assert seen.get("dongle_id") == "deadbeefcafebabe"
    assert len(data["routes"]) == 1
    assert data["routes"][0]["dongle_id"] == "deadbeefcafebabe"
    assert data["routes"][0]["meta"].get("fixture") is not True
