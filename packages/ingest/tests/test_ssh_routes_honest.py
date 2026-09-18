"""SSH /routes honesty — empty realdata and SSH errors must not swap to fixture."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from distillery_ingest.config import IngestConfig
from distillery_ingest.resolve import list_routes, resolve_source
from distillery_ingest.sources.ssh import REALDATA, SshRouteSource


@pytest.fixture()
def ssh_cfg(monkeypatch) -> IngestConfig:
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)
    monkeypatch.delenv("COMMA_JWT", raising=False)
    monkeypatch.delenv("CONNECT_JWT", raising=False)
    monkeypatch.setenv("MICI_SSH_HOST", "192.168.1.50")
    monkeypatch.setenv("MICI_SSH_USER", "comma")
    return IngestConfig(
        dongle_id="3e2de7ed673817c2",
        ssh_host="192.168.1.50",
        ssh_user="comma",
        force_fixture=False,
    )


def test_resolve_prefer_ssh_returns_ssh_even_when_host_set(ssh_cfg):
    src = resolve_source(ssh_cfg, prefer="ssh")
    assert src.name == "ssh"
    assert isinstance(src, SshRouteSource)


def test_list_routes_ssh_empty_no_fixture(ssh_cfg, monkeypatch):
    monkeypatch.setattr(
        SshRouteSource,
        "list_routes",
        lambda self, *, limit=20: [],
    )
    result = list_routes(ssh_cfg, prefer="ssh", limit=10)
    assert result.source.name == "ssh"
    assert result.ok is True
    assert result.error is None
    assert result.routes == []
    assert result.count == 0
    assert result.path == REALDATA
    assert "0 routes" in (result.message or "")
    assert REALDATA in (result.message or "")
    assert all(r.source != "fixture" for r in result.routes)


def test_list_routes_ssh_error_no_fixture(ssh_cfg, monkeypatch):
    def _boom(self, *, limit=20):
        raise RuntimeError("Permission denied (publickey)")

    monkeypatch.setattr(SshRouteSource, "list_routes", _boom)
    result = list_routes(ssh_cfg, prefer="ssh", limit=10)
    assert result.source.name == "ssh"
    assert result.ok is False
    assert result.routes == []
    assert result.count == 0
    assert "Permission denied" in (result.error or "")
    assert "SSH error" in (result.message or "")
    assert result.path == REALDATA


def test_list_routes_auto_ssh_empty_no_fixture(ssh_cfg, monkeypatch):
    """auto resolves to SSH when host set — empty must stay honest."""
    monkeypatch.setattr(SshRouteSource, "list_routes", lambda self, *, limit=20: [])
    result = list_routes(ssh_cfg, prefer="auto", limit=10)
    assert result.source.name == "ssh"
    assert result.ok is True
    assert result.routes == []
    assert "fixture" not in (result.message or "").lower() or "0 routes" in (
        result.message or ""
    )


def test_list_routes_explicit_fixture_still_works(monkeypatch):
    monkeypatch.setenv("DISTILLERY_INGEST_FIXTURE", "1")
    monkeypatch.delenv("MICI_SSH_HOST", raising=False)
    result = list_routes(prefer="fixture", limit=5)
    assert result.source.name == "fixture"
    assert result.ok is True
    assert result.count >= 1
    assert result.routes[0].meta.get("fixture") is True or result.routes[
        0
    ].meta.get("label") == "fixture"


def test_api_routes_ssh_empty_honest(monkeypatch):
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)
    monkeypatch.delenv("COMMA_JWT", raising=False)
    monkeypatch.setenv("MICI_SSH_HOST", "10.0.0.9")
    monkeypatch.setattr(SshRouteSource, "list_routes", lambda self, *, limit=20: [])

    from api.main import app

    with TestClient(app) as client:
        r = client.get("/routes", params={"source": "ssh", "limit": 10})
    assert r.status_code == 200
    data = r.json()
    assert data["source"] == "ssh"
    assert data["ok"] is True
    assert data["count"] == 0
    assert data["routes"] == []
    assert data["path"] == REALDATA
    assert "0 routes" in (data.get("message") or "")
    assert REALDATA in (data.get("message") or "")
    assert data.get("error") in (None, "")


def test_api_routes_ssh_error_honest(monkeypatch):
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)
    monkeypatch.delenv("COMMA_JWT", raising=False)
    monkeypatch.setenv("MICI_SSH_HOST", "10.0.0.9")

    def _boom(self, *, limit=20):
        raise RuntimeError("ssh: connect to host 10.0.0.9 port 22: Connection refused")

    monkeypatch.setattr(SshRouteSource, "list_routes", _boom)

    from api.main import app

    with TestClient(app) as client:
        r = client.get("/routes", params={"source": "ssh"})
    assert r.status_code == 200
    data = r.json()
    assert data["source"] == "ssh"
    assert data["ok"] is False
    assert data["count"] == 0
    assert data["routes"] == []
    assert data["error"]
    assert "SSH error" in (data.get("message") or "")
    assert not any(
        (row.get("meta") or {}).get("fixture") for row in data["routes"]
    )


def test_api_routes_fixture_explicit(monkeypatch):
    monkeypatch.setenv("DISTILLERY_INGEST_FIXTURE", "1")
    from api.main import app

    with TestClient(app) as client:
        r = client.get("/routes", params={"source": "fixture"})
    assert r.status_code == 200
    data = r.json()
    assert data["source"] == "fixture"
    assert data["ok"] is True
    assert data["count"] >= 1
    assert len(data["routes"]) >= 1
