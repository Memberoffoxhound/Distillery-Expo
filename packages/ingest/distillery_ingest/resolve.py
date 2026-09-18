"""Pick Connect → SSH → fixture; expose list_routes for API/CLI."""

from __future__ import annotations

import logging
from typing import Literal

from distillery_ingest.config import IngestConfig, load_ingest_config
from distillery_ingest.models import RouteInfo
from distillery_ingest.sources.base import RouteSource
from distillery_ingest.sources.connect import ConnectRouteSource
from distillery_ingest.sources.fixture import FixtureRouteSource
from distillery_ingest.sources.ssh import SshRouteSource

log = logging.getLogger(__name__)

SourcePreference = Literal["auto", "connect", "ssh", "fixture"]


def resolve_source(
    cfg: IngestConfig | None = None,
    *,
    prefer: SourcePreference = "auto",
) -> RouteSource:
    """Primary structure is Connect, then SSH; fixture when creds unavailable."""
    cfg = cfg or load_ingest_config()

    if prefer == "fixture" or cfg.force_fixture:
        return FixtureRouteSource(cfg)

    connect = ConnectRouteSource(cfg)
    ssh = SshRouteSource(cfg)
    fixture = FixtureRouteSource(cfg)

    if prefer == "connect":
        if connect.available():
            return connect
        log.warning("Connect preferred but JWT missing — using fixture")
        return fixture
    if prefer == "ssh":
        if ssh.available():
            return ssh
        log.warning("SSH preferred but MICI_SSH_HOST missing — using fixture")
        return fixture

    # auto: Connect → SSH → fixture
    if connect.available():
        return connect
    if ssh.available():
        return ssh
    return fixture


def list_routes(
    cfg: IngestConfig | None = None,
    *,
    prefer: SourcePreference = "auto",
    limit: int = 20,
) -> tuple[RouteSource, list[RouteInfo]]:
    """Resolve source and list routes (falls back to fixture on live errors)."""
    cfg = cfg or load_ingest_config()
    source = resolve_source(cfg, prefer=prefer)
    try:
        routes = source.list_routes(limit=limit)
        if routes:
            return source, routes
    except Exception as exc:  # noqa: BLE001
        log.warning("%s list_routes failed: %s — fixture fallback", source.name, exc)
    fixture = FixtureRouteSource(cfg)
    return fixture, fixture.list_routes(limit=limit)


def get_route(
    route_id: str,
    cfg: IngestConfig | None = None,
    *,
    prefer: SourcePreference = "auto",
) -> tuple[RouteSource, RouteInfo]:
    cfg = cfg or load_ingest_config()
    source = resolve_source(cfg, prefer=prefer)
    try:
        route = source.get_route(route_id)
        if route is not None:
            return source, route
    except Exception as exc:  # noqa: BLE001
        log.warning("%s get_route failed: %s — fixture fallback", source.name, exc)
    fixture = FixtureRouteSource(cfg)
    route = fixture.get_route(route_id) or fixture.list_routes()[0]
    return fixture, route
