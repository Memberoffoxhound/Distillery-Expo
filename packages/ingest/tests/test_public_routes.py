"""Public/shared Connect routes + demo dongle ban."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest


def test_sanitize_bans_demo_dongle():
    from distillery_ingest.config import (
        DEMO_DONGLE_ID,
        is_banned_demo_dongle,
        sanitize_dongle_id,
    )

    assert is_banned_demo_dongle(DEMO_DONGLE_ID)
    assert is_banned_demo_dongle("3E2DE7ED673817C2")
    assert sanitize_dongle_id(DEMO_DONGLE_ID) == ""
    assert sanitize_dongle_id("aabbccddeeff0011") == "aabbccddeeff0011"


def test_load_config_clears_demo_from_cache(tmp_path, monkeypatch):
    from distillery_ingest import config as cfg_mod

    cache = tmp_path / "dongle_id"
    cache.write_text("3e2de7ed673817c2\n", encoding="utf-8")
    monkeypatch.setattr(cfg_mod, "_DONGLE_CACHE", cache)
    monkeypatch.delenv("DISTILLERY_DONGLE_ID", raising=False)
    monkeypatch.delenv("COMMA_JWT", raising=False)
    monkeypatch.delenv("CONNECT_JWT", raising=False)

    loaded = cfg_mod.load_ingest_config()
    assert loaded.dongle_id == ""
    assert not cache.is_file() or cache.read_text().strip() != "3e2de7ed673817c2"


def test_set_dongle_rejects_demo(tmp_path, monkeypatch):
    from distillery_ingest import discover as disc

    monkeypatch.setattr(disc, "_DONGLE_CACHE", tmp_path / "dongle_id")
    monkeypatch.delenv("DISTILLERY_DONGLE_ID", raising=False)
    with pytest.raises(ValueError, match="demo dongle"):
        disc.set_dongle_id("3e2de7ed673817c2", persist=True)


def test_public_routes_needs_jwt_honest(monkeypatch, tmp_path):
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)
    monkeypatch.delenv("COMMA_JWT", raising=False)
    monkeypatch.delenv("CONNECT_JWT", raising=False)
    monkeypatch.delenv("DISTILLERY_DONGLE_ID", raising=False)
    monkeypatch.setattr(
        "distillery_ingest.discover._JWT_CACHE",
        tmp_path / "connect_jwt",
    )
    monkeypatch.setattr(
        "distillery_ingest.config._DONGLE_CACHE",
        tmp_path / "dongle_id",
    )

    from distillery_ingest.resolve import list_routes

    result = list_routes(prefer="connect", scope="public", limit=10)
    assert result.source.name == "connect"
    assert result.routes == []
    assert result.empty_reason == "connect_not_configured"


def test_public_routes_lists_shared_and_public(monkeypatch, tmp_path):
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)
    monkeypatch.setenv("COMMA_JWT", "test-jwt-token")
    monkeypatch.delenv("DISTILLERY_DONGLE_ID", raising=False)
    monkeypatch.setattr(
        "distillery_ingest.config._DONGLE_CACHE",
        tmp_path / "dongle_id",
    )
    monkeypatch.setattr(
        "distillery_ingest.discover._JWT_CACHE",
        tmp_path / "connect_jwt",
    )

    devices = [
        {"dongle_id": "1111222233334444", "alias": "shared-car", "is_owner": False},
        {"dongle_id": "aaaabbbbccccdddd", "alias": "mine", "is_owner": True},
        {"dongle_id": "3e2de7ed673817c2", "alias": "demo-banned", "is_owner": False},
    ]
    routes_by_dongle = {
        "1111222233334444": [
            {
                "fullname": "1111222233334444|2024-01-01--10-00-00",
                "dongle_id": "1111222233334444",
                "is_public": False,
                "length": 12.0,
                "maxqlog": 3,
            }
        ],
        "aaaabbbbccccdddd": [
            {
                "fullname": "aaaabbbbccccdddd|2024-02-02--11-00-00",
                "dongle_id": "aaaabbbbccccdddd",
                "is_public": True,
                "length": 5.0,
                "maxqlog": 1,
            },
            {
                "fullname": "aaaabbbbccccdddd|2024-02-03--12-00-00",
                "dongle_id": "aaaabbbbccccdddd",
                "is_public": False,
                "length": 9.0,
                "maxqlog": 2,
            },
        ],
    }

    def fake_get(self, path: str):
        if path.startswith("/v1/me/devices"):
            return devices
        if "/routes" in path:
            for dongle, rows in routes_by_dongle.items():
                if dongle in path:
                    return rows
            return []
        raise AssertionError(f"unexpected path {path}")

    from distillery_ingest.sources.connect import ConnectRouteSource

    monkeypatch.setattr(ConnectRouteSource, "_get", fake_get)

    from distillery_ingest.resolve import list_routes

    result = list_routes(prefer="connect", scope="public", limit=20)
    assert result.source.name == "connect"
    ids = {r.route_id for r in result.routes}
    assert "1111222233334444|2024-01-01--10-00-00" in ids  # shared
    assert "aaaabbbbccccdddd|2024-02-02--11-00-00" in ids  # public on owned
    assert "aaaabbbbccccdddd|2024-02-03--12-00-00" not in ids  # private owned skip
    # Demo device never queried / never returned
    assert not any("3e2de7ed" in r.route_id for r in result.routes)
    assert all((r.meta or {}).get("scope") in ("shared", "public") for r in result.routes)


def test_api_routes_scope_public(monkeypatch, tmp_path):
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)
    monkeypatch.delenv("COMMA_JWT", raising=False)
    monkeypatch.delenv("CONNECT_JWT", raising=False)
    monkeypatch.delenv("DISTILLERY_DONGLE_ID", raising=False)
    monkeypatch.setattr(
        "distillery_ingest.discover._JWT_CACHE",
        tmp_path / "connect_jwt",
    )
    monkeypatch.setattr(
        "distillery_ingest.config._DONGLE_CACHE",
        tmp_path / "dongle_id",
    )

    from api.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        r = c.get("/routes", params={"source": "connect", "scope": "public"})
    assert r.status_code == 200
    data = r.json()
    assert data["source"] == "connect"
    assert data["scope"] == "public"
    assert data["routes"] == []
    assert data.get("empty_reason") == "connect_not_configured"
    # Must not invent demo dongle
    assert data.get("dongle_id") in (None, "")


def test_connect_list_routes_refuses_demo(monkeypatch, tmp_path):
    monkeypatch.setenv("COMMA_JWT", "jwt")
    monkeypatch.setenv("DISTILLERY_DONGLE_ID", "3e2de7ed673817c2")
    monkeypatch.setattr(
        "distillery_ingest.config._DONGLE_CACHE",
        tmp_path / "dongle_id",
    )

    from distillery_ingest.config import load_ingest_config
    from distillery_ingest.sources.connect import ConnectRouteSource

    cfg = load_ingest_config()
    # Config must sanitize demo away
    assert cfg.dongle_id == ""

    # Even if somehow constructed with demo id, list_routes refuses
    from distillery_ingest.config import IngestConfig

    bad = IngestConfig(dongle_id="3e2de7ed673817c2", connect_jwt="jwt")
    src = ConnectRouteSource(bad)
    with pytest.raises(RuntimeError, match="demo dongle banned|Dongle ID required"):
        src.list_routes(limit=5)
