"""Export pipeline — ONNX path + modelV2 I/O sidecar."""

from __future__ import annotations

import asyncio
from pathlib import Path

from distillery_events import DistilleryEvent, EventKind, StageName
from distillery_export import MODEL_V2_IO, load_export_config, run_export_pipeline
from distillery_export.onnx_writer import write_onnx_artifact


def test_model_v2_io_documented():
    assert "input_imgs" in MODEL_V2_IO["inputs"]
    assert "outputs" in MODEL_V2_IO["outputs"]
    assert MODEL_V2_IO["contract"] == "stock-modelV2"


def test_write_onnx_creates_artifact(tmp_path: Path):
    result = write_onnx_artifact(tmp_path, "student_modelV2_io.onnx")
    onnx_path = Path(result["onnx_path"])
    sidecar = Path(result["sidecar_path"])
    assert onnx_path.is_file()
    assert onnx_path.suffix == ".onnx"
    assert onnx_path.stat().st_size > 0
    assert sidecar.is_file()
    assert result["io"]["contract"] == "stock-modelV2"


def test_export_pipeline_emits_artifact():
    events: list[dict] = []

    async def emit(ev: dict) -> None:
        events.append(ev)

    async def _run() -> None:
        cfg = load_export_config()
        # write into default artifacts/export for integration shape
        result = await run_export_pipeline(
            "test-export-job",
            emit,
            cfg=cfg,
            tick=0.0,
            write_files=True,
        )
        assert Path(result["onnx_path"]).is_file()
        assert Path(result["sidecar_path"]).is_file()

    asyncio.run(_run())

    parsed = [DistilleryEvent.model_validate(e) for e in events]
    assert any(e.kind == EventKind.stage and e.stage == StageName.export for e in parsed)
    samples = [e for e in parsed if e.kind == EventKind.sample]
    assert samples
    assert samples[0].payload.get("meta", {}).get("io_contract") == "stock-modelV2"
