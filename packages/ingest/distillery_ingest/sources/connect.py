"""comma Connect route source — primary structure when JWT is present."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from distillery_ingest.config import IngestConfig
from distillery_ingest.models import RouteInfo, SegmentInfo
from distillery_ingest.sources.base import RouteSource

log = logging.getLogger(__name__)

# Connect API shapes vary; we map into RouteInfo without inventing a parallel bus.
_CAM_MAP = {
    "fcamera.hevc": "road",
    "ecamera.hevc": "wide",
    "dcamera.hevc": "driver",
    "qcamera.ts": "road",
}


class ConnectRouteSource(RouteSource):
    name = "connect"  # type: ignore[assignment]

    def __init__(self, cfg: IngestConfig, client: httpx.Client | None = None) -> None:
        self.cfg = cfg
        self._client = client

    def available(self) -> bool:
        return self.cfg.connect_available

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

    def list_routes(self, *, limit: int = 20) -> list[RouteInfo]:
        """List routes for dongle via Connect.

        Primary endpoint shape: GET /v1/devices/{dongle}/routes
        (falls back gracefully on HTTP errors — caller should use fixture).
        """
        dongle = (self.cfg.dongle_id or "").strip()
        if not dongle:
            return []
        data = self._get(f"/v1/devices/{dongle}/routes?limit={limit}")
        rows = data if isinstance(data, list) else data.get("routes") or data.get("data") or []
        out: list[RouteInfo] = []
        for row in rows[:limit]:
            if not isinstance(row, dict):
                continue
            out.append(self._map_route(row, segments=False))
        return out

    def get_route(self, route_id: str) -> RouteInfo | None:
        dongle = (self.cfg.dongle_id or "").strip()
        if not dongle:
            return None
        # Canonical Connect route key is often fullname = dongle|date
        path = f"/v1/devices/{dongle}/routes/{route_id}"
        try:
            data = self._get(path)
        except httpx.HTTPStatusError:
            # Some deployments use encoded fullname query
            data = self._get(f"/v1/route/{route_id}")
        if not isinstance(data, dict):
            return None
        return self._map_route(data, segments=True)

    def _map_route(self, row: dict[str, Any], *, segments: bool) -> RouteInfo:
        route_id = str(
            row.get("fullname")
            or row.get("route_id")
            or row.get("name")
            or f"{self.cfg.dongle_id}|unknown"
        )
        segs: list[SegmentInfo] = []
        if segments:
            raw_segs = row.get("segments") or row.get("segment_numbers") or []
            if isinstance(raw_segs, list) and raw_segs and isinstance(raw_segs[0], int):
                for idx in raw_segs:
                    segs.append(self._segment_stub(route_id, int(idx), row))
            elif isinstance(raw_segs, list):
                for i, s in enumerate(raw_segs):
                    if isinstance(s, dict):
                        segs.append(self._segment_from_dict(route_id, i, s))
                    elif isinstance(s, int):
                        segs.append(self._segment_stub(route_id, s, row))

        length = row.get("length") or row.get("length_s") or row.get("duration")
        return RouteInfo(
            route_id=route_id,
            dongle_id=str(row.get("dongle_id") or self.cfg.dongle_id),
            display_name=str(row.get("display_name") or route_id.split("|")[-1]),
            source="connect",
            start_time=_iso(row.get("start_time") or row.get("starttime")),
            end_time=_iso(row.get("end_time") or row.get("endtime")),
            length_s=float(length) if length is not None else None,
            segment_count=int(row.get("maxqlog") or row.get("segment_count") or len(segs) or 0),
            segments=segs,
            meta={"fixture": False, "label": "connect", "raw_keys": sorted(row.keys())[:24]},
        )

    def _segment_stub(self, route_id: str, idx: int, row: dict[str, Any]) -> SegmentInfo:
        cams = {
            cam: {
                "filename": fname,
                "path": f"connect://{route_id}/{idx}/{fname}",
                "codec": "hevc",
                "fps": 20,
                "exists": True,
            }
            for fname, cam in _CAM_MAP.items()
            if cam in self.cfg.cams
        }
        # Dedupe by cam name (qcamera maps to road too)
        deduped: dict[str, dict] = {}
        for cam, meta in cams.items():
            deduped.setdefault(cam, meta)
        return SegmentInfo(
            segment_id=f"{route_id}/{idx}",
            index=idx,
            duration_s=60.0,
            cams=deduped,
            meta={"source": "connect"},
        )

    def _segment_from_dict(self, route_id: str, idx: int, s: dict[str, Any]) -> SegmentInfo:
        index = int(s.get("index", s.get("segment", idx)))
        cams: dict[str, dict] = {}
        files = s.get("files") or s.get("cams") or {}
        if isinstance(files, dict):
            for key, val in files.items():
                cam = _CAM_MAP.get(str(key), key if key in self.cfg.cams else None)
                if not cam:
                    continue
                if isinstance(val, dict):
                    cams[str(cam)] = val
                else:
                    cams[str(cam)] = {"path": str(val), "filename": str(key)}
        if not cams:
            return self._segment_stub(route_id, index, {})
        return SegmentInfo(
            segment_id=str(s.get("segment_id") or f"{route_id}/{index}"),
            index=index,
            duration_s=float(s["duration_s"]) if s.get("duration_s") is not None else 60.0,
            cams=cams,
            meta={"source": "connect"},
        )


def _iso(val: Any) -> str | None:
    if val is None:
        return None
    return str(val)
