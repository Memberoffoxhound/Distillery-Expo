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
ConnectScope = Literal["mine", "public"]

# Explicit prefer=ssh|connect must never silently swap to fixture.
_EXPLICIT_LIVE = frozenset({"ssh", "connect"})


@dataclass
class ListRoutesResult:
    """list_routes outcome — unpacks as (source, routes) for callers."""

    source: RouteSource
    routes: list[RouteInfo]
    message: str | None = None
    empty_reason: str | None = None
    error: str | None = None

    def __iter__(self):
        yield self.source
        yield self.routes


def resolve_source(
    cfg: IngestConfig | None = None,
    *,
    prefer: SourcePreference = "auto",
) -> RouteSource:
    """Primary structure is Connect, then SSH; fixture when creds unavailable.

    Explicit prefer=ssh|connect returns that source even when creds are missing
    so callers can report an honest empty/error instead of a silent fixture swap.
    force_fixture / prefer=fixture still wins.
    """
    cfg = cfg or load_ingest_config()

    if prefer == "fixture" or cfg.force_fixture:
        return FixtureRouteSource(cfg)

    connect = ConnectRouteSource(cfg)
    ssh = SshRouteSource(cfg)
    fixture = FixtureRouteSource(cfg)

    if prefer == "connect":
        return connect
    if prefer == "ssh":
        return ssh

    # auto: Connect → SSH → labeled fixture (last resort)
    if connect.available():
        return connect
    if ssh.available():
        return ssh
    return fixture


def _ssh_empty_message(cfg: IngestConfig, *, error: str | None = None) -> tuple[str, str]:
    """Phil copy for explicit SSH empty/error."""
    if error:
        return f"SSH error · {error}", "ssh_error"
    if not cfg.ssh_host:
        return "SSH not configured · set host (Save SSH) then refresh", "ssh_not_configured"
    if not (cfg.dongle_id or "").strip():
        return "Dongle ID required · set via GUI Save", "dongle_id_required"
    return f"SSH ok · 0 routes under {REALDATA}", "empty_realdata"


def _connect_empty_message(cfg: IngestConfig, *, error: str | None = None) -> tuple[str, str]:
    if error:
        return f"Connect error · {error}", "connect_error"
    if not (cfg.dongle_id or "").strip():
        return "Dongle ID required · set via GUI Save", "dongle_id_required"
    if not cfg.connect_jwt:
        return "Connect not configured · paste JWT then Save", "connect_not_configured"
    return "Connect ok · 0 routes for this dongle", "empty_connect"


def _public_empty_message(cfg: IngestConfig, *, error: str | None = None) -> tuple[str, str]:
    if error:
        low = error.lower()
        if "401" in low or "403" in low or "unauthorized" in low or "forbidden" in low:
            return f"Connect auth failed · {error}", "connect_unauthorized"
        return f"Connect error · {error}", "connect_error"
    if not cfg.connect_jwt:
        return "Connect not configured · paste JWT then Save", "connect_not_configured"
    return "Connect ok · 0 public/shared routes", "empty_public"


def list_routes(
    cfg: IngestConfig | None = None,
    *,
    prefer: SourcePreference = "auto",
    limit: int = 20,
    scope: ConnectScope | None = None,
) -> ListRoutesResult:
    """Resolve source and list routes.

    Explicit prefer=ssh|connect: never silently fall back to fixture on empty
    or error — return honest empty + message/empty_reason/error.
    Missing dongle on Connect/SSH → dongle_id_required (not fixture dongle).
    prefer=auto (and missing creds): still falls back to labeled fixture.

    scope=public (with prefer=connect|auto): list shared/public Connect drives
    via /v1/me/devices — JWT only, no local dongle, never demo id.
    """
    cfg = cfg or load_ingest_config()
    want_public = scope == "public" and prefer in ("connect", "auto") and not cfg.force_fixture

    # Public/shared Connect browse — JWT only; honest empty on missing JWT / 401
    if want_public:
        connect = ConnectRouteSource(cfg)
        if not cfg.connect_jwt:
            msg, reason = _public_empty_message(cfg)
            return ListRoutesResult(
                source=connect,
                routes=[],
                message=msg,
                empty_reason=reason,
            )
        try:
            routes = connect.list_public_routes(limit=limit)
        except Exception as exc:  # noqa: BLE001
            log.warning("connect public list_routes failed: %s — honest empty", exc)
            err = str(exc).strip() or type(exc).__name__
            msg, reason = _public_empty_message(cfg, error=err)
            return ListRoutesResult(
                source=connect,
                routes=[],
                message=msg,
                empty_reason=reason,
                error=err,
            )
        if routes:
            return ListRoutesResult(source=connect, routes=routes)
        msg, reason = _public_empty_message(cfg)
        return ListRoutesResult(
            source=connect,
            routes=[],
            message=msg,
            empty_reason=reason,
        )

    # force_fixture already handled inside resolve_source
    source = resolve_source(cfg, prefer=prefer)
    explicit = prefer in _EXPLICIT_LIVE and not cfg.force_fixture

    # Honest gap before hitting Connect/SSH when dongle unset
    if explicit and not (cfg.dongle_id or "").strip():
        if prefer == "ssh":
            msg, reason = _ssh_empty_message(cfg)
        else:
            msg, reason = _connect_empty_message(cfg)
        return ListRoutesResult(
            source=source,
            routes=[],
            message=msg,
            empty_reason=reason,
        )

    try:
        routes = source.list_routes(limit=limit)
    except Exception as exc:  # noqa: BLE001
        if explicit:
            log.warning("%s list_routes failed: %s — honest empty (no fixture)", source.name, exc)
            err = str(exc).strip() or type(exc).__name__
            if prefer == "ssh":
                msg, reason = _ssh_empty_message(cfg, error=err)
            else:
                msg, reason = _connect_empty_message(cfg, error=err)
            return ListRoutesResult(
                source=source,
                routes=[],
                message=msg,
                empty_reason=reason,
                error=err,
            )
        log.warning("%s list_routes failed: %s — fixture fallback", source.name, exc)
        fixture = FixtureRouteSource(cfg)
        return ListRoutesResult(source=fixture, routes=fixture.list_routes(limit=limit))

    if routes:
        return ListRoutesResult(source=source, routes=routes)

    # Empty list
    if explicit:
        if prefer == "ssh":
            msg, reason = _ssh_empty_message(cfg)
        else:
            msg, reason = _connect_empty_message(cfg)
        return ListRoutesResult(
            source=source,
            routes=[],
            message=msg,
            empty_reason=reason,
        )

    # auto / fixture path: empty live → labeled fixture (only when not already fixture)
    if source.name == "fixture":
        return ListRoutesResult(source=source, routes=routes)

    log.warning("%s list_routes empty — fixture fallback", source.name)
    fixture = FixtureRouteSource(cfg)
    return ListRoutesResult(source=fixture, routes=fixture.list_routes(limit=limit))


def get_route(
    route_id: str,
    cfg: IngestConfig | None = None,
    *,
    prefer: SourcePreference = "auto",
) -> tuple[RouteSource, RouteInfo]:
    cfg = cfg or load_ingest_config()
    source = resolve_source(cfg, prefer=prefer)
    explicit = prefer in _EXPLICIT_LIVE and not cfg.force_fixture
    if explicit and not (cfg.dongle_id or "").strip():
        raise LookupError("dongle_id required · set via GUI Save")
    try:
        route = source.get_route(route_id)
        if route is not None:
            return source, route
        if explicit:
            raise LookupError(f"route not found on {source.name}: {route_id}")
    except Exception as exc:  # noqa: BLE001
        if explicit:
            log.warning("%s get_route failed: %s — no fixture swap", source.name, exc)
            raise
        log.warning("%s get_route failed: %s — fixture fallback", source.name, exc)
    fixture = FixtureRouteSource(cfg)
    route = fixture.get_route(route_id) or fixture.list_routes()[0]
    return fixture, route
