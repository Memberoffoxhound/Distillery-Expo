"""Route / segment / cam metadata shapes for ingest."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

CamName = Literal["road", "wide", "driver", "other"]
SourceName = Literal["connect", "ssh", "public", "fixture"]


class CamSample(BaseModel):
    """One cam surface the Expo UI can bind (SamplePayload-compatible)."""

    cam: CamName
    label: str
    placeholder: bool = True
    uri: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class SegmentInfo(BaseModel):
    """One route segment with per-cam file metadata."""

    segment_id: str
    index: int
    duration_s: float | None = None
    cams: dict[str, dict[str, Any]] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)


class RouteInfo(BaseModel):
    """Truthful-shaped route listing entry (Connect-like)."""

    route_id: str
    dongle_id: str
    display_name: str
    source: SourceName
    start_time: str | None = None
    end_time: str | None = None
    length_s: float | None = None
    segment_count: int = 0
    segments: list[SegmentInfo] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)

    def summary_dict(self) -> dict[str, Any]:
        return {
            "route_id": self.route_id,
            "dongle_id": self.dongle_id,
            "display_name": self.display_name,
            "source": self.source,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "length_s": self.length_s,
            "segment_count": self.segment_count,
            "meta": self.meta,
        }
