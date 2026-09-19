"""Smoke tests — ingest event contract matches DistilleryEvent / SamplePayload."""

from __future__ import annotations

import asyncio
import os

import pytest

from distillery_events import DistilleryEvent, EventKind, SamplePayload, StageName
from distillery_ingest import load_ingest_config, run_ingest_pipeline
from distillery_ingest.resolve import list_routes, resolve_source
from distillery_ingest.sources.fixture import FIXTURE_ROUTE_ID, cam_samples_for_route


@pytest.fixture(autouse=True)
def _force_fixture(monkeypatch):
    monkeypatch.setenv("DISTILLERY_INGEST_FIXTURE", "1")
    monkeypatch.delenv("COMMA_JWT", raising=False)
    monkeypatch.delenv("CONNECT_JWT", raising=False)
    monkeypatch.delenv("MICI_SSH_HOST", raising=False)


def test_config_resolves_dongle(monkeypatch, tmp_path):
    monkeypatch.delenv("DISTILLERY_DONGLE_ID", raising=False)
    monkeypatch.setattr("distillery_ingest.config._DONGLE_CACHE", tmp_path / "dongle_id")
    cfg = load_ingest_config()
    # Empty until env / .cache / GUI Save — no demo default
    assert cfg.dongle_id == ""
    assert cfg.dongle_configured is False
    assert set(cfg.cams) >= {"road", "wide", "driver"}


def test_resolve_falls_back_to_fixture(monkeypatch, tmp_path):
    monkeypatch.delenv("DISTILLERY_DONGLE_ID", raising=False)
    monkeypatch.setattr("distillery_ingest.config._DONGLE_CACHE", tmp_path / "dongle_id")
    src = resolve_source(prefer="auto")
    assert src.name == "fixture"
    routes = src.list_routes()
    assert len(routes) >= 1
    assert routes[0].meta.get("fixture") is True or routes[0].meta.get("label") == "fixture"
    # Labeled fixture sample keeps its fixture dongle id
    assert routes[0].dongle_id == "3e2de7ed673817c2"


def test_fixture_has_three_cams_metadata():
    src = resolve_source(prefer="fixture")
    route = src.get_route(FIXTURE_ROUTE_ID) or src.list_routes()[0]
    assert route.segment_count >= 1
    assert route.segments
    seg = route.segments[0]
    for cam in ("road", "wide", "driver"):
        assert cam in seg.cams
        assert seg.cams[cam].get("fps") == 20
        assert seg.cams[cam].get("filename")
    samples = cam_samples_for_route(route, ("road", "wide", "driver"))
    assert {s.cam for s in samples} == {"road", "wide", "driver"}
    for s in samples:
        assert s.meta.get("label") == "fixture"
        assert s.placeholder is True


def test_ingest_pipeline_emits_stage_progress_and_samples():
    events: list[dict] = []

    async def emit(ev: dict) -> None:
        events.append(ev)

    async def _run() -> None:
        await run_ingest_pipeline(
            "test-job",
            emit,
            prefer="fixture",
            tick=0.0,
        )

    asyncio.run(_run())

    # Validate DistilleryEvent shape
    parsed = [DistilleryEvent.model_validate(e) for e in events]
    kinds = {e.kind for e in parsed}
    assert EventKind.stage in kinds
    assert EventKind.progress in kinds
    assert EventKind.sample in kinds

    stages = [e for e in parsed if e.kind == EventKind.stage]
    assert any(e.payload.get("status") == "running" for e in stages)
    assert any(e.payload.get("status") == "done" for e in stages)
    assert all(e.stage == StageName.ingest for e in stages)

    samples = [e for e in parsed if e.kind == EventKind.sample]
    cams = {e.payload["cam"] for e in samples}
    assert cams >= {"road", "wide", "driver"}
    for e in samples:
        SamplePayload.model_validate(e.payload)
        assert e.payload.get("placeholder") is True
        assert e.payload.get("meta", {}).get("route_id")
        assert e.payload.get("meta", {}).get("dongle_id") == "3e2de7ed673817c2"


def test_list_routes_api_shape():
    src, routes = list_routes(prefer="fixture", limit=5)
    assert src.name == "fixture"
    summary = routes[0].summary_dict()
    for key in ("route_id", "dongle_id", "display_name", "source", "segment_count", "meta"):
        assert key in summary


def test_explicit_ssh_empty_no_fixture_swap(monkeypatch):
    """prefer=ssh + empty realdata → honest empty, never silent fixture."""
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)
    monkeypatch.setenv("MICI_SSH_HOST", "192.168.1.50")
    monkeypatch.setenv("DISTILLERY_DONGLE_ID", "aabbccddeeff0011")

    from distillery_ingest.config import load_ingest_config
    from distillery_ingest.resolve import list_routes
    from distillery_ingest.sources.ssh import REALDATA, SshRouteSource

    cfg = load_ingest_config()
    assert cfg.force_fixture is False
    assert cfg.ssh_host == "192.168.1.50"

    monkeypatch.setattr(SshRouteSource, "list_routes", lambda self, *, limit=20: [])

    result = list_routes(cfg, prefer="ssh", limit=10)
    src, routes = result
    assert src.name == "ssh"
    assert routes == []
    assert result.empty_reason == "empty_realdata"
    assert result.message == f"SSH ok · 0 routes under {REALDATA}"
    assert result.error is None


def test_explicit_ssh_error_no_fixture_swap(monkeypatch):
    """prefer=ssh + SSH failure → honest empty/error, not fixture routes."""
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)
    monkeypatch.setenv("MICI_SSH_HOST", "192.168.1.50")
    monkeypatch.setenv("DISTILLERY_DONGLE_ID", "aabbccddeeff0011")

    from distillery_ingest.config import load_ingest_config
    from distillery_ingest.resolve import list_routes
    from distillery_ingest.sources.ssh import SshRouteSource

    cfg = load_ingest_config()

    def _boom(self, *, limit=20):
        raise RuntimeError("Permission denied (publickey)")

    monkeypatch.setattr(SshRouteSource, "list_routes", _boom)

    result = list_routes(cfg, prefer="ssh", limit=10)
    src, routes = result
    assert src.name == "ssh"
    assert routes == []
    assert result.empty_reason == "ssh_error"
    assert result.error and "Permission denied" in result.error
    assert result.message and result.message.startswith("SSH error")


def test_auto_still_falls_back_to_fixture_on_ssh_empty(monkeypatch):
    """prefer=auto keeps labeled fixture fallback when live is empty."""
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)
    monkeypatch.setenv("MICI_SSH_HOST", "192.168.1.50")
    monkeypatch.setenv("DISTILLERY_DONGLE_ID", "aabbccddeeff0011")
    monkeypatch.delenv("COMMA_JWT", raising=False)
    monkeypatch.delenv("CONNECT_JWT", raising=False)

    from distillery_ingest.config import load_ingest_config
    from distillery_ingest.resolve import list_routes
    from distillery_ingest.sources.ssh import SshRouteSource

    # Avoid hydrate from .cache/connect_jwt if present
    cfg = load_ingest_config()
    # Force no connect by clearing jwt on a copy-like override via monkeypatch env already

    monkeypatch.setattr(SshRouteSource, "list_routes", lambda self, *, limit=20: [])
    # If connect is somehow configured, stub it empty too
    from distillery_ingest.sources.connect import ConnectRouteSource

    monkeypatch.setattr(ConnectRouteSource, "available", lambda self: False)

    result = list_routes(cfg, prefer="auto", limit=5)
    src, routes = result
    assert src.name == "fixture"
    assert len(routes) >= 1


def test_explicit_connect_unset_dongle_no_fixture(monkeypatch, tmp_path):
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)
    monkeypatch.delenv("DISTILLERY_DONGLE_ID", raising=False)
    monkeypatch.setenv("COMMA_JWT", "testjwtTOKEN12345678")
    monkeypatch.setattr("distillery_ingest.config._DONGLE_CACHE", tmp_path / "dongle_id")

    from distillery_ingest.config import load_ingest_config
    from distillery_ingest.resolve import list_routes

    cfg = load_ingest_config()
    assert cfg.dongle_configured is False
    result = list_routes(cfg, prefer="connect", limit=5)
    src, routes = result
    assert src.name == "connect"
    assert routes == []
    assert result.empty_reason == "dongle_id_required"
    assert result.message and "Dongle ID required" in result.message


def test_set_dongle_then_connect_uses_id(monkeypatch, tmp_path):
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)
    monkeypatch.delenv("DISTILLERY_DONGLE_ID", raising=False)
    monkeypatch.setenv("COMMA_JWT", "testjwtTOKEN12345678")
    cache = tmp_path / "dongle_id"
    monkeypatch.setattr("distillery_ingest.config._DONGLE_CACHE", cache)
    monkeypatch.setattr("distillery_ingest.discover._DONGLE_CACHE", cache)

    from distillery_ingest.discover import set_dongle_id
    from distillery_ingest.config import load_ingest_config
    from distillery_ingest.models import RouteInfo
    from distillery_ingest.resolve import list_routes
    from distillery_ingest.sources.connect import ConnectRouteSource

    status = set_dongle_id("1122334455667788", persist=True)
    assert status["dongle_id"] == "1122334455667788"
    assert cache.is_file()

    def _list(self, *, limit=20):
        return [
            RouteInfo(
                route_id=f"{self.cfg.dongle_id}|x",
                dongle_id=self.cfg.dongle_id,
                display_name="x",
                source="connect",
                segment_count=0,
                meta={"label": "connect", "fixture": False},
            )
        ]

    monkeypatch.setattr(ConnectRouteSource, "list_routes", _list)
    cfg = load_ingest_config()
    assert cfg.dongle_id == "1122334455667788"
    result = list_routes(cfg, prefer="connect", limit=3)
    src, routes = result
    assert src.name == "connect"
    assert routes[0].dongle_id == "1122334455667788"



def test_demo_dongle_cache_ignored(monkeypatch, tmp_path):
    """Leftover demo id in .cache → treat as unset; never configure Connect around it."""
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)
    monkeypatch.delenv("DISTILLERY_DONGLE_ID", raising=False)
    monkeypatch.setenv("COMMA_JWT", "testjwtTOKEN12345678")
    cache = tmp_path / "dongle_id"
    cache.write_text("3e2de7ed673817c2\n", encoding="utf-8")
    monkeypatch.setattr("distillery_ingest.config._DONGLE_CACHE", cache)
    monkeypatch.setattr("distillery_ingest.discover._DONGLE_CACHE", cache)

    from distillery_ingest.config import DEMO_DONGLE_ID, load_ingest_config
    from distillery_ingest.discover import ensure_dongle_from_cache
    from distillery_ingest.resolve import list_routes
    from distillery_ingest.sources.connect import ConnectRouteSource

    queried: list[str] = []

    def _list(self, *, limit=20):
        queried.append(self.cfg.dongle_id)
        raise AssertionError("Connect must not be queried with demo dongle")

    monkeypatch.setattr(ConnectRouteSource, "list_routes", _list)

    assert ensure_dongle_from_cache() is None
    cfg = load_ingest_config()
    assert cfg.dongle_id == ""
    assert cfg.dongle_configured is False
    assert not cache.is_file() or cache.read_text(encoding="utf-8").strip() != DEMO_DONGLE_ID

    result = list_routes(cfg, prefer="connect", limit=5)
    assert result.source.name == "connect"
    assert result.routes == []
    assert result.empty_reason == "dongle_id_required"
    assert queried == []


def test_set_dongle_rejects_demo_id(monkeypatch, tmp_path):
    monkeypatch.setattr("distillery_ingest.discover._DONGLE_CACHE", tmp_path / "dongle_id")
    monkeypatch.setattr("distillery_ingest.config._DONGLE_CACHE", tmp_path / "dongle_id")
    monkeypatch.delenv("DISTILLERY_DONGLE_ID", raising=False)

    from distillery_ingest.config import DEMO_DONGLE_ID
    from distillery_ingest.discover import set_dongle_id

    with pytest.raises(ValueError, match="fixture/demo"):
        set_dongle_id(DEMO_DONGLE_ID, persist=True)


def test_public_no_jwt_honest_empty(monkeypatch, tmp_path):
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)

    from distillery_ingest.config import IngestConfig
    from distillery_ingest.resolve import list_routes
    from distillery_ingest.sources.public import PublicConnectRouteSource

    cfg = IngestConfig(dongle_id="", connect_jwt=None, force_fixture=False, repo_root=tmp_path)
    result = list_routes(cfg, prefer="public", limit=5)
    assert result.source.name == "public"
    assert result.routes == []
    assert result.empty_reason == "connect_not_configured"
    assert "Connect not configured" in (result.message or "")
    assert isinstance(result.source, PublicConnectRouteSource)


def test_public_jwt_ok_real_list_or_honest_empty(monkeypatch, tmp_path):
    """JWT present → real public list from me/devices, or honest empty_public (no fixture)."""
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)

    from distillery_ingest.config import IngestConfig
    from distillery_ingest.models import RouteInfo
    from distillery_ingest.resolve import list_routes
    from distillery_ingest.sources.public import PublicConnectRouteSource

    cfg = IngestConfig(
        dongle_id="",
        connect_jwt="testjwtTOKEN12345678",
        force_fixture=False,
        repo_root=tmp_path,
    )

    def _list_shared(self, *, limit=20):
        return [
            RouteInfo(
                route_id="aabbccddeeff0011|2024-06-01--12-00-00",
                dongle_id="aabbccddeeff0011",
                display_name="shared-drive",
                source="public",
                segment_count=2,
                meta={"label": "public", "fixture": False, "shared": True},
            )
        ]

    monkeypatch.setattr(PublicConnectRouteSource, "list_routes", _list_shared)
    result = list_routes(cfg, prefer="public", limit=5)
    assert result.source.name == "public"
    assert len(result.routes) == 1
    assert result.routes[0].source == "public"
    assert result.routes[0].meta.get("fixture") is not True
    assert result.empty_reason is None

    monkeypatch.setattr(PublicConnectRouteSource, "list_routes", lambda self, *, limit=20: [])
    empty = list_routes(cfg, prefer="public", limit=5)
    assert empty.source.name == "public"
    assert empty.routes == []
    assert empty.empty_reason == "empty_public"
    assert "0 public" in (empty.message or "")


def test_public_skips_demo_dongle_device(monkeypatch, tmp_path):
    """Public listing must never query the demo dongle even if it appears in me/devices."""
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)

    from distillery_ingest.config import DEMO_DONGLE_ID, IngestConfig
    from distillery_ingest.sources.public import PublicConnectRouteSource

    cfg = IngestConfig(connect_jwt="jwt", force_fixture=False, repo_root=tmp_path)
    src = PublicConnectRouteSource(cfg)
    queried: list[str] = []

    def _devices(self):
        return [
            {"dongle_id": DEMO_DONGLE_ID, "is_owner": False, "alias": "demo"},
            {"dongle_id": "aabbccddeeff0011", "is_owner": False, "alias": "friend"},
        ]

    def _rows(self, dongle, *, limit):
        queried.append(dongle)
        return [
            {
                "fullname": f"{dongle}|2024-01-01--00-00-00",
                "dongle_id": dongle,
                "is_public": False,
                "maxqlog": 1,
            }
        ]

    monkeypatch.setattr(PublicConnectRouteSource, "_list_devices", _devices)
    monkeypatch.setattr(PublicConnectRouteSource, "_device_route_rows", _rows)
    routes = src.list_routes(limit=10)
    assert DEMO_DONGLE_ID not in queried
    assert queried == ["aabbccddeeff0011"]
    assert len(routes) == 1
    assert routes[0].dongle_id == "aabbccddeeff0011"
    assert routes[0].source == "public"
