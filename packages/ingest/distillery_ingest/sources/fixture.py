"""Offline fixture source — truthful Connect-shaped routes when creds missing."""

from __future__ import annotations

import json
from pathlib import Path

from distillery_ingest.config import IngestConfig
from distillery_ingest.models import CamSample, RouteInfo, SegmentInfo
from distillery_ingest.sources.base import RouteSource

# Canonical M1 thin-slice route (labeled fixture in meta)
FIXTURE_ROUTE_ID = "3e2de7ed673817c2|2024-06-15--14-30-00"

_CAM_FILES = {
    "road": "fcamera.hevc",
    "wide": "ecamera.hevc",
    "driver": "dcamera.hevc",
}


def _fixture_path(cfg: IngestConfig) -> Path:
    return Path(__file__).resolve().parents[1].parent / "fixtures" / "sample_route.json"


def build_fixture_route(cfg: IngestConfig, route_id: str | None = None) -> RouteInfo:
    """Build a Connect-shaped route with road/wide/driver cam metadata."""
    rid = route_id or FIXTURE_ROUTE_ID
    fixture_dongle = FIXTURE_ROUTE_ID.split("|", 1)[0]
    configured = (cfg.dongle_id or "").strip()
    # Keep dongle prefix aligned with saved id when set; else keep labeled fixture id
    if "|" not in rid:
        rid = f"{configured or fixture_dongle}|{rid}"
    elif configured and not rid.startswith(configured):
        # Prefer configured dongle in display, keep given id for stability in tests
        pass

    path = _fixture_path(cfg)
    if path.is_file():
        data = json.loads(path.read_text())
        return RouteInfo.model_validate(data)

    segments: list[SegmentInfo] = []
    for idx in range(3):
        cams: dict[str, dict] = {}
        for cam, fname in _CAM_FILES.items():
            cams[cam] = {
                "filename": fname,
                "path": f"/data/media/0/realdata/{rid.replace('|', '/')}/{idx}/{fname}",
                "codec": "hevc",
                "fps": 20,
                "width": 1164 if cam != "driver" else 864,
                "height": 874 if cam != "driver" else 648,
                "exists": True,
            }
        segments.append(
            SegmentInfo(
                segment_id=f"{rid}/{idx}",
                index=idx,
                duration_s=60.0,
                cams=cams,
                meta={"fixture": True},
            )
        )

    return RouteInfo(
        route_id=rid,
        dongle_id=configured or fixture_dongle,
        display_name=f"fixture · {rid.split('|')[-1]}",
        source="fixture",
        start_time="2024-06-15T19:30:00+00:00",
        end_time="2024-06-15T19:33:00+00:00",
        length_s=180.0,
        segment_count=len(segments),
        segments=segments,
        meta={
            "fixture": True,
            "label": "fixture",
            "reason": "Connect/SSH credentials unavailable",
            "cams": list(cfg.cams),
        },
    )


def cam_samples_for_route(route: RouteInfo, cams: tuple[str, ...]) -> list[CamSample]:
    """≥1 SamplePayload-shaped entry per requested cam, UX-bindable meta."""
    seg0 = route.segments[0] if route.segments else None
    samples: list[CamSample] = []
    for cam in cams:
        cam_meta = (seg0.cams.get(cam) if seg0 else None) or {}
        uri = cam_meta.get("path")
        samples.append(
            CamSample(
                cam=cam if cam in ("road", "wide", "driver") else "other",  # type: ignore[arg-type]
                label=f"{cam} · {route.display_name}",
                placeholder=True,
                uri=uri,
                meta={
                    "fixture": route.source == "fixture" or bool(route.meta.get("fixture")),
                    "source": route.source,
                    "route_id": route.route_id,
                    "dongle_id": route.dongle_id,
                    "segment_id": seg0.segment_id if seg0 else None,
                    "fps": cam_meta.get("fps", 20),
                    "width": cam_meta.get("width"),
                    "height": cam_meta.get("height"),
                    "codec": cam_meta.get("codec", "hevc"),
                    "filename": cam_meta.get("filename"),
                    "label": "fixture" if route.source == "fixture" else route.source,
                },
            )
        )
    return samples


class FixtureRouteSource(RouteSource):
    name = "fixture"  # type: ignore[assignment]

    def __init__(self, cfg: IngestConfig) -> None:
        self.cfg = cfg
        self._route = build_fixture_route(cfg)

    def available(self) -> bool:
        return True

    def list_routes(self, *, limit: int = 20) -> list[RouteInfo]:
        return [self._route][:limit]

    def get_route(self, route_id: str) -> RouteInfo | None:
        if route_id in (self._route.route_id, FIXTURE_ROUTE_ID, "fixture"):
            return self._route
        # Allow dongle|suffix match on fixture date suffix
        if route_id.endswith(self._route.route_id.split("|")[-1]):
            return self._route
        return None
