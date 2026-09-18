"""Teacher soft-label descriptor shapes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

SoftLabelSource = Literal["live", "fixture"]


class SoftLabelBatch(BaseModel):
    """One soft-label batch produced by Cinque/supercombo (or fixture)."""

    batch_id: str
    shard_id: str | None = None
    route_id: str | None = None
    n_samples: int
    teacher: str = "Cinque/supercombo"
    device: str = "fixture"
    live: bool = False
    source: SoftLabelSource = "fixture"
    soft_targets: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)

    def summary_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "shard_id": self.shard_id,
            "route_id": self.route_id,
            "n_samples": self.n_samples,
            "teacher": self.teacher,
            "device": self.device,
            "live": self.live,
            "source": self.source,
            "meta": self.meta,
        }
