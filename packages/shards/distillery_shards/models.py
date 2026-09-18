"""Training shard descriptor shapes for M2 pack stage."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ShardStatus = Literal["pending", "packing", "ready", "failed"]


class ShardDescriptor(BaseModel):
    """One packed training shard (frame window + labels + soft-target placeholders)."""

    shard_id: str
    route_id: str
    segment_id: str | None = None
    frame_start: int
    frame_end: int
    frame_count: int
    fps: int = 20
    cams: list[str] = Field(default_factory=list)
    labels: dict[str, Any] = Field(default_factory=dict)
    teacher_soft_targets: dict[str, Any] = Field(default_factory=dict)
    size_bytes: int = 0
    status: ShardStatus = "pending"
    meta: dict[str, Any] = Field(default_factory=dict)

    def summary_dict(self) -> dict[str, Any]:
        return {
            "shard_id": self.shard_id,
            "route_id": self.route_id,
            "segment_id": self.segment_id,
            "frame_count": self.frame_count,
            "size_bytes": self.size_bytes,
            "status": self.status,
            "meta": self.meta,
        }


class ShardSample(BaseModel):
    """SamplePayload-compatible event for Expo Shard pane / Jony binding."""

    cam: Literal["road", "wide", "driver", "other"] = "other"
    label: str
    placeholder: bool = True
    uri: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
