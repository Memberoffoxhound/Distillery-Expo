"""Train pipeline — emits loss curves; stock modelV2 I/O contract."""

from __future__ import annotations

import asyncio

from distillery_events import DistilleryEvent, EventKind, StageName
from distillery_student import load_student_config, run_train_pipeline


def test_config_io_compatible():
    cfg = load_student_config()
    assert cfg.io_compatible is True
    assert "modelV2" in cfg.name or cfg.io_compatible


def test_train_pipeline_emits_loss_metrics():
    events: list[dict] = []

    async def emit(ev: dict) -> None:
        events.append(ev)

    async def _run() -> None:
        result = await run_train_pipeline(
            "test-train-job",
            emit,
            tick=0.0,
            write_files=False,
            steps=4,
        )
        assert result["io_contract"] == "stock-modelV2"
        assert result["steps"] == 4
        assert "final_loss" in result

    asyncio.run(_run())

    parsed = [DistilleryEvent.model_validate(e) for e in events]
    assert any(e.kind == EventKind.stage and e.stage == StageName.train for e in parsed)
    losses = [
        e
        for e in parsed
        if e.kind == EventKind.metric and e.payload.get("name") == "train_loss"
    ]
    assert len(losses) == 4
    # Loss should trend downward on this toy schedule
    vals = [e.payload["value"] for e in losses]
    assert vals[-1] < vals[0]
