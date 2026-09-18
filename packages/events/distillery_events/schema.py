"""Typed event schema for Distillery Expo — JSON-serializable."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, Field


class EventKind(str, Enum):
    decision = "decision"
    metric = "metric"
    warning = "warning"
    sample = "sample"
    log = "log"
    progress = "progress"
    stage = "stage"


class StageName(str, Enum):
    ingest = "ingest"
    shard = "shard"
    teach = "teach"
    train = "train"
    export = "export"
    eval = "eval"
    flash = "flash"


class DecisionPayload(BaseModel):
    title: str
    rationale: str
    options_considered: list[str] = Field(default_factory=list)
    chosen: Optional[str] = None
    confidence: Optional[float] = None


class MetricPayload(BaseModel):
    name: str
    value: float
    unit: Optional[str] = None
    series: Optional[str] = None  # e.g. "train_loss"


class WarningPayload(BaseModel):
    code: str
    message: str
    recoverable: bool = True


class SamplePayload(BaseModel):
    cam: Literal["road", "wide", "driver", "other"] = "other"
    label: str
    placeholder: bool = True
    uri: Optional[str] = None
    meta: dict[str, Any] = Field(default_factory=dict)


class LogPayload(BaseModel):
    level: Literal["debug", "info", "warn", "error"] = "info"
    message: str
    source: Optional[str] = None


class ProgressPayload(BaseModel):
    fraction: float  # 0.0 – 1.0
    detail: Optional[str] = None


class StagePayload(BaseModel):
    name: StageName
    status: Literal["pending", "running", "done", "failed", "gated", "skipped"]
    detail: Optional[str] = None


Payload = Union[
    DecisionPayload,
    MetricPayload,
    WarningPayload,
    SamplePayload,
    LogPayload,
    ProgressPayload,
    StagePayload,
]


class DistilleryEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    ts: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    job_id: str
    kind: EventKind
    stage: Optional[StageName] = None
    payload: dict[str, Any]

    def to_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def make_event(
    job_id: str,
    kind: EventKind | str,
    payload: BaseModel | dict[str, Any],
    stage: StageName | str | None = None,
) -> DistilleryEvent:
    kind_e = EventKind(kind) if isinstance(kind, str) else kind
    stage_e: Optional[StageName] = None
    if stage is not None:
        stage_e = StageName(stage) if isinstance(stage, str) else stage
    if isinstance(payload, BaseModel):
        payload_dict = payload.model_dump(mode="json")
    else:
        payload_dict = payload
    return DistilleryEvent(
        job_id=job_id,
        kind=kind_e,
        stage=stage_e,
        payload=payload_dict,
    )
