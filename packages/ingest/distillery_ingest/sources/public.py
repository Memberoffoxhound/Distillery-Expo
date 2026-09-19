"""Public / shared Connect routes — browse when mici ADB/SSH is offline."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from distillery_ingest.config import IngestConfig, is_banned_demo_dongle
from distillery_ingest.models import RouteInfo
from distillery_ingest.sources.base import RouteSource
from distillery_ingest.sources.connect import ConnectRouteSource

log = logging.getLogger(__name__)


class PublicConnectRouteSource(RouteSource):
    """List routes from shared/public Connect drives (JWT only; no dongle required).

    Uses the same comma Connect API as My Connect:
      GET /v1/me/devices → GET /v1/devices/{dongle}/routes

    Shared devices (is_owner=false) contribute all readable routes.
    Owned devices contribute only routes marked is_public=true.
    Never queries the labeled demo/fixture dongle id.
    """

    name = "public"  # type: ignore[assignment]

    def __init__(self, cfg: IngestConfig, client: httpx.Client | None = None) -> None:
        self.cfg = cfg
        self._client = client
        self._connect = ConnectRouteSource(cfg, client=client)

    def available(self) -> bool:
        return self.cfg.public_available

    def list_routes(self, *, limit: int = 20) -> list[RouteInfo]:
        if not self.cfg.connect_jwt:
            raise RuntimeError("Connect JWT required for public routes")
        devices = self._list_devices()
        out: list[RouteInfo] = []
        for device in devices:
            if not isinstance(device, dict):
                continue
            dongle = str(device.get("dongle_id") or "").strip()
            if not dongle or is_banned_demo_dongle(dongle):
                continue
            is_owner = bool(device.get("is_owner"))
            try:
                rows = self._device_route_rows(dongle, limit=limit)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                if status in (401, 403):
                    raise
                log.warning("public: skip device %s routes: %s", dongle[:8], exc)
                continue
            except Exception as exc:  # noqa: BLE001
                log.warning("public: skip device %s routes: %s", dongle[:8], exc)
                continue

            alias = str(device.get("alias") or dongle)
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if is_owner and not bool(row.get("is_public")):
                    # Owned private routes belong under My Connect, not Public.
                    continue
                route = self._connect._map_route(row, segments=False)
                # Retag as public picker source; keep Connect provenance in meta.
                meta = dict(route.meta or {})
                meta.update(
                    {
                        "label": "public",
                        "fixture": False,
                        "connect_label": "connect",
                        "shared": not is_owner,
                        "is_public": bool(row.get("is_public")),
                        "device_alias": alias,
                        "is_owner": is_owner,
                    }
                )
                route = route.model_copy(update={"source": "public", "meta": meta})
                out.append(route)
                if len(out) >= limit:
                    return out
        return out

    def get_route(self, route_id: str) -> RouteInfo | None:
        """Resolve one route via Connect route endpoint (public/shared readable)."""
        if not self.cfg.connect_jwt:
            return None
        # Canonical fullname is dongle|date — refuse demo dongle prefix.
        dongle = route_id.split("|", 1)[0].strip() if "|" in route_id else ""
        if is_banned_demo_dongle(dongle):
            return None
        try:
            data = self._connect._get(f"/v1/route/{route_id}")
        except httpx.HTTPStatusError:
            return None
        if not isinstance(data, dict):
            return None
        if is_banned_demo_dongle(str(data.get("dongle_id") or dongle)):
            return None
        route = self._connect._map_route(data, segments=True)
        meta = dict(route.meta or {})
        meta.update(
            {
                "label": "public",
                "fixture": False,
                "is_public": bool(data.get("is_public")),
            }
        )
        return route.model_copy(update={"source": "public", "meta": meta})

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"JWT {self.cfg.connect_jwt}",
            "Accept": "application/json",
        }

    def _get(self, path: str) -> Any:
        url = f"{self.cfg.connect_base_url}{path}"
        if self._client is not None:
            r = self._client.get(url, headers=self._headers(), timeout=30.0)
            r.raise_for_status()
            return r.json()
        with httpx.Client(timeout=30.0) as client:
            r = client.get(url, headers=self._headers())
            r.raise_for_status()
            return r.json()

    def _list_devices(self) -> list[dict[str, Any]]:
        data = self._get("/v1/me/devices")
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
        if isinstance(data, dict):
            rows = data.get("devices") or data.get("data") or []
            if isinstance(rows, list):
                return [d for d in rows if isinstance(d, dict)]
        return []

    def _device_route_rows(self, dongle: str, *, limit: int) -> list[dict[str, Any]]:
        data = self._get(f"/v1/devices/{dongle}/routes?limit={limit}")
        rows = data if isinstance(data, list) else (
            data.get("routes") or data.get("data") or [] if isinstance(data, dict) else []
        )
        return [r for r in rows if isinstance(r, dict)]
