"""Offline fixture soft labels — always live=false / source=fixture."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from distillery_teacher.models import SoftLabelBatch

TEACHER_NAME = "Cinque/supercombo"


def _fixture_path() -> Path:
    return Path(__file__).resolve().parents[1] / "fixtures" / "soft_labels.json"


def load_fixture_manifest() -> dict[str, Any]:
    path = _fixture_path()
    if path.is_file():
        return json.loads(path.read_text())
    return {
        "label": "fixture",
        "live": False,
        "source": "fixture",
        "teacher": TEACHER_NAME,
        "batches": 4,
        "samples_per_batch": 32,
        "note": "generated at teach time when soft_labels.json absent",
    }


def _pseudo_logits(n: int, dims: int = 8, seed: int = 0) -> list[list[float]]:
    """Deterministic unit-ish vectors without numpy."""
    out: list[list[float]] = []
    for i in range(n):
        row = []
        for d in range(dims):
            v = math.sin((seed + 1) * 0.17 + i * 0.31 + d * 0.47) * 0.5 + 0.5
            row.append(round(v, 5))
        out.append(row)
    return out


def build_fixture_batches(
    *,
    n_batches: int | None = None,
    samples_per_batch: int | None = None,
    route_id: str | None = None,
) -> list[SoftLabelBatch]:
    """Build clearly labeled non-live soft-label batches."""
    manifest = load_fixture_manifest()
    if n_batches is None:
        n_batches = int(manifest.get("batches") or 4)
    if samples_per_batch is None:
        samples_per_batch = int(manifest.get("samples_per_batch") or 32)
    batches: list[SoftLabelBatch] = []
    for i in range(n_batches):
        batch_id = f"soft_{i:03d}"
        shard_id = f"shard_{i:03d}"
        batches.append(
            SoftLabelBatch(
                batch_id=batch_id,
                shard_id=shard_id,
                route_id=route_id,
                n_samples=samples_per_batch,
                teacher=TEACHER_NAME,
                device="fixture",
                live=False,
                source="fixture",
                soft_targets={
                    "kind": "fixture",
                    "desire_logits": _pseudo_logits(samples_per_batch, 8, seed=i),
                    "plan_lat": _pseudo_logits(samples_per_batch, 4, seed=i + 10),
                    "plan_long": _pseudo_logits(samples_per_batch, 4, seed=i + 20),
                },
                meta={
                    "live": False,
                    "source": "fixture",
                    "teacher": TEACHER_NAME,
                    "device": "fixture",
                    "label": "fixture",
                    "reason": "no AMD/ROCm/7090 XT or force_fixture — never claim live GPU",
                },
            )
        )
    return batches


def write_soft_label_artifacts(
    batches: list[SoftLabelBatch],
    output_dir: Path,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for b in batches:
        (output_dir / f"{b.batch_id}.json").write_text(
            json.dumps(b.model_dump(mode="json"), indent=2) + "\n"
        )
        manifest.append(b.summary_dict())
    path = output_dir / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "live": all(b.live for b in batches) if batches else False,
                "source": batches[0].source if batches else "fixture",
                "teacher": TEACHER_NAME,
                "batches": manifest,
            },
            indent=2,
        )
        + "\n"
    )
    return path
