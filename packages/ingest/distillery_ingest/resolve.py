"""Pick Connect → SSH → fixture; expose list_routes for API/CLI."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from distillery_ingest.config import IngestConfig, load_ingest_config
from distillery_ingest.models import RouteInfo
from distillery_ingest.sources.base import RouteSource
from distillery_ingest.sources.connect import ConnectRouteSource
from distillery_ingest.sources.fixture import FixtureRouteSource
from distillery_ingest.sources.ssh import REALDATA, SshRouteSource

log = logging.getLogger(__name__)

SourcePreference = Literal["auto", "connect", "ssh", "fixture"]


@dataclass(frozen=True)
class ListRoutesResult:
    """Honest listing result — never silently swaps live → fixture."""

    source: RouteSource
    routes: list[RouteInfo]
    ok: bool = True
    error: str | None = None
    message: str | None = None
    path: str | None = None
    prefer: SourcePreference = "auto"

    @property
    def count(self) -> int:
        return len(self.routes)

    def __iter__(self):
        """Unpack as (source, routes) for legacy callers."""
        yield self.source
        yield self.routes


def resolve_source(
    cfg: IngestConfig | None = None,
    *,
    prefer: SourcePreference = "auto",
) -> RouteSource:
    """Primary structure is Connect, then SSH; fixture when creds unavailable.

    Explicit prefer=ssh|connect always returns that source (even if unconfigured)
    so list/get can report an honest error instead of silently using fixture.
    """
    cfg = cfg or load_ingest_config()

    if prefer == "fixture" or cfg.force_fixture:
        return FixtureRouteSource(cfg)

    connect = ConnectRouteSource(cfg)
    ssh = SshRouteSource(cfg)

    if prefer == "connect":
        return connect
    if prefer == "ssh":
        return ssh

    # auto: Connect → SSH → fixture
    if connect.available():
        return connect
    if ssh.available():
        return ssh
    return FixtureRouteSource(cfg)


def _ssh_path() -> str:
    return REALDATA


def _live_message(source: RouteSource, *, count: int, error: str | None = None) -> str:
    if source.name == "ssh":
        if error:
            return f"SSH error · {error}"
        return f"SSH ok · {count} routes under {REALDATA}"
    if source.name == "connect":
        if error:
            return f"Connect error · {error}"
        return f"Connect ok · {count} routes"
    if error:
        return f"fixture error · {error}"
    return f"fixture · {count} routes"


def list_routes(
    cfg: IngestConfig | None = None,
    *,
    prefer: SourcePreference = "auto",
    limit: int = 20,
) -> ListRoutesResult:
    """Resolve source and list routes.

    Explicit ssh/connect (and auto when a live source was selected) never
    silently fall back to fixture on empty list or errors. Fixture only when
    prefer=fixture, force_fixture, or auto with no live credentials.
    """
    cfg = cfg or load_ingest_config()
    source = resolve_source(cfg, prefer=prefer)
    path = _ssh_path() if source.name == "ssh" else None

    try:
        routes = source.list_routes(limit=limit)
    except Exception as exc:  # noqa: BLE001
        err = str(exc).strip() or repr(exc)
        # Live sources (or explicit ssh/connect prefer): honest error, no fixture swap.
        if source.name != "fixture":
            log.warning("%s list_routes failed: %s — no fixture fallback", source.name, exc)
            return ListRoutesResult(
                source=source,
                routes=[],
                ok=False,
                error=err,
                message=_live_message(source, count=0, error=err),
                path=path,
                prefer=prefer,
            )
        log.warning("fixture list_routes failed: %s", exc)
        return ListRoutesResult(
            source=source,
            routes=[],
            ok=False,
            error=err,
            message=_live_message(source, count=0, error=err),
            path=path,
            prefer=prefer,
        )

    # Empty live listing: honest empty (Phil: empty realdata felt like "no routes"
    # because we used to swap in fixture silently).
    if not routes and source.name != "fixture":
        msg = _live_message(source, count=0)
        log.info("%s", msg)
        return ListRoutesResult(
            source=source,
            routes=[],
            ok=True,
            error=None,
            message=msg,
            path=path,
            prefer=prefer,
        )

    msg = _live_message(source, count=len(routes))
    return ListRoutesResult(
        source=source,
        routes=routes,
        ok=True,
        error=None,
        message=msg,
        path=path,
        prefer=prefer,
    )


def get_route(
    route_id: str,
    cfg: IngestConfig | None = None,
    *,
    prefer: SourcePreference = "auto",
) -> tuple[RouteSource, RouteInfo | None]:
    """Fetch one route. Live prefer/source: no silent fixture swap on miss/error."""
    cfg = cfg or load_ingest_config()
    source = resolve_source(cfg, prefer=prefer)
    try:
        route = source.get_route(route_id)
        if route is not None:
            return source, route
    except Exception as exc:  # noqa: BLE001
        if source.name != "fixture":
            log.warning("%s get_route failed: %s — no fixture fallback", source.name, exc)
            return source, None
        log.warning("fixture get_route failed: %s", exc)
        return source, None

    if source.name != "fixture":
        return source, None

    fixture = FixtureRouteSource(cfg)
    route = fixture.get_route(route_id) or (
        fixture.list_routes()[0] if fixture.list_routes() else None
    )
    return fixture, route
