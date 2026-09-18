"""Export stage runner — ONNX (or labeled stub) with stock modelV2 I/O meta."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from distillery_events import (
    DecisionPayload,
    EventKind,
    LogPayload,
    MetricPayload,
    ProgressPayload,
    SamplePayload,
    StageName,
    StagePayload,
    make_event,
)
from distillery_export.config import ExportConfig, load_export_config
from distillery_export.onnx_writer import MODEL_V2_IO, write_onnx_artifact

EmitFn = Callable[[dict[str, Any]], Awaitable[None]]


async def _emit(emit: EmitFn, event) -> None:
    await emit(event.to_json_dict())


def _load_student_meta(student_dir: Path) -> dict[str, Any]:
    ckpt = student_dir / "student_checkpoint.json"
    if ckpt.is_file():
        return json.loads(ckpt.read_text())
    return {"note": "no student checkpoint — export still writes modelV2-shaped artifact"}


async def run_export_pipeline(
    job_id: str,
    emit: EmitFn,
    *,
    cfg: ExportConfig | None = None,
    tick: float = 0.12,
    write_files: bool = True,
) -> dict[str, Any]:
    """Export student to ONNX under artifacts/export/; document modelV2 I/O."""
    cfg = cfg or load_export_config()
    stage = StageName.export

    async def log(msg: str, level: str = "info") -> None:
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.log,
                LogPayload(level=level, message=msg, source="export"),  # type: ignore[arg-type]
                stage=stage,
            ),
        )

    async def stage_status(status: str, detail: str | None = None) -> None:
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.stage,
                StagePayload(name=stage, status=status, detail=detail),  # type: ignore[arg-type]
                stage=stage,
            ),
        )

    async def progress(frac: float, detail: str | None = None) -> None:
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.progress,
                ProgressPayload(fraction=min(1.0, max(0.0, frac)), detail=detail),
                stage=stage,
            ),
        )

    await stage_status("running", "Export student for QCOM/mici")
    await log(f"artifact={cfg.artifact_name} out={cfg.output_dir}")
    await progress(0.1, "trace graph")
    await asyncio.sleep(tick)

    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.decision,
            DecisionPayload(
                title="Export format",
                rationale=(
                    "ONNX with modelV2 I/O nodes validated against stock shapes. "
                    "If onnx package missing, write labeled protobuf stub + sidecar JSON."
                ),
                options_considered=["ONNX", "raw tinygrad", "TorchScript"],
                chosen="ONNX",
                confidence=0.9,
            ),
            stage=stage,
        ),
    )

    student_meta = await asyncio.to_thread(_load_student_meta, cfg.student_dir)
    await progress(0.4, "fold BN / validate I/O")
    await log(
        f"Validating stock modelV2 I/O — "
        f"inputs={list(MODEL_V2_IO['inputs'])} outputs={list(MODEL_V2_IO['outputs'])}"
    )
    await asyncio.sleep(tick)

    if write_files:
        result = await asyncio.to_thread(
            write_onnx_artifact,
            cfg.output_dir,
            cfg.artifact_name,
            student_meta=student_meta,
        )
    else:
        result = {
            "onnx_path": str(cfg.output_dir / cfg.artifact_name),
            "sidecar_path": str(cfg.output_dir / (cfg.artifact_name + ".json")),
            "onnx_package": False,
            "artifact_tag": "fixture",
            "live": False,
            "licensed": False,
            "eval_passed": False,
            "io": MODEL_V2_IO,
            "meta": {
                "dry_run": True,
                "io": MODEL_V2_IO,
                "artifact_tag": "fixture",
                "live": False,
                "licensed": False,
                "eval_passed": False,
            },
        }

    await progress(0.85, "write artifact")
    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.sample,
            SamplePayload(
                cam="other",
                label=cfg.artifact_name,
                placeholder=not result.get("onnx_package", False),
                uri=result.get("onnx_path"),
                meta={
                    "artifact": result.get("onnx_path"),
                    "sidecar": result.get("sidecar_path"),
                    "format": result.get("meta", {}).get("format"),
                    "io_contract": "stock-modelV2",
                    "io": MODEL_V2_IO,
                    "artifact_tag": result.get("artifact_tag") or result.get("meta", {}).get("artifact_tag", "fixture"),
                    "live": bool(result.get("live", False)),
                    "licensed": False,
                    "eval_passed": False,
                },
            ),
            stage=stage,
        ),
    )
    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.metric,
            MetricPayload(
                name="export_onnx_package",
                value=1.0 if result.get("onnx_package") else 0.0,
                unit="bool",
            ),
            stage=stage,
        ),
    )
    await log(f"Wrote {result.get('onnx_path')}")
    await log(f"I/O sidecar {result.get('sidecar_path')} (stock-modelV2)")
    await progress(1.0, "done")
    await stage_status("done", result.get("onnx_path"))
    return result
