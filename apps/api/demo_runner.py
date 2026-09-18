"""Background demo pipeline — emits realistic staged events (no GPU)."""

from __future__ import annotations

import asyncio
import random
from typing import Awaitable, Callable

from distillery_events import (
    DecisionPayload,
    EventKind,
    LogPayload,
    MetricPayload,
    ProgressPayload,
    SamplePayload,
    StageName,
    StagePayload,
    WarningPayload,
    make_event,
)

EmitFn = Callable[[dict], Awaitable[None]]

STAGES = [
    StageName.ingest,
    StageName.shard,
    StageName.teach,
    StageName.train,
    StageName.export,
    StageName.eval,
    StageName.flash,
]


async def _emit(emit: EmitFn, event) -> None:
    await emit(event.to_json_dict())


async def run_demo_pipeline(
    job_id: str,
    emit: EmitFn,
    *,
    gated_flash: bool = True,
    wait_flash_confirm: Callable[[], Awaitable[bool]] | None = None,
    tick: float = 0.35,
) -> None:
    """Run ingest→…→flash demo, streaming events via emit()."""

    async def log(stage: StageName, msg: str, level: str = "info") -> None:
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.log,
                LogPayload(level=level, message=msg, source=stage.value),
                stage=stage,
            ),
        )

    async def decision(
        stage: StageName,
        title: str,
        rationale: str,
        options: list[str],
        chosen: str,
        confidence: float,
    ) -> None:
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.decision,
                DecisionPayload(
                    title=title,
                    rationale=rationale,
                    options_considered=options,
                    chosen=chosen,
                    confidence=confidence,
                ),
                stage=stage,
            ),
        )

    async def metric(stage: StageName, name: str, value: float, unit: str | None = None, series: str | None = None) -> None:
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.metric,
                MetricPayload(name=name, value=value, unit=unit, series=series),
                stage=stage,
            ),
        )

    async def progress(stage: StageName, frac: float, detail: str | None = None) -> None:
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.progress,
                ProgressPayload(fraction=min(1.0, max(0.0, frac)), detail=detail),
                stage=stage,
            ),
        )

    async def stage_status(stage: StageName, status: str, detail: str | None = None) -> None:
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.stage,
                StagePayload(name=stage, status=status, detail=detail),  # type: ignore[arg-type]
                stage=stage,
            ),
        )

    # ---- INGEST ----
    s = StageName.ingest
    await stage_status(s, "running", "Connecting to mici via comma Connect")
    await log(s, "dongle_id=3e2de7ed673817c2 — probing Connect + local SSH")
    await asyncio.sleep(tick)
    await decision(
        s,
        "Route source",
        "Prefer comma Connect for freshness; fall back to local SSH cache if latency > 800ms.",
        ["comma Connect", "local SSH cache", "USB tether"],
        "comma Connect",
        0.91,
    )
    await asyncio.sleep(tick)
    for cam in ("road", "wide", "driver"):
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.sample,
                SamplePayload(
                    cam=cam,  # type: ignore[arg-type]
                    label=f"{cam} preview (placeholder)",
                    placeholder=True,
                    meta={"fps": 20, "dongle": "3e2de7ed673817c2"},
                ),
                stage=s,
            ),
        )
        await progress(s, 0.25 + 0.2 * ["road", "wide", "driver"].index(cam), f"cam:{cam}")
        await asyncio.sleep(tick * 0.6)
    await metric(s, "segments_found", 14, unit="segs")
    await metric(s, "route_hours", 2.4, unit="h")
    await log(s, "Ingest complete — 14 segments / 2.4h")
    await stage_status(s, "done")
    await progress(s, 1.0, "done")

    # ---- SHARD ----
    s = StageName.shard
    await stage_status(s, "running", "Packing training shards")
    await decision(
        s,
        "Shard window",
        "120-frame windows balance teacher soft-label memory vs batch diversity on 7090 XT.",
        ["60-frame", "120-frame", "240-frame"],
        "120-frame",
        0.84,
    )
    for i in range(1, 6):
        await progress(s, i / 5, f"shard {i}/5")
        await metric(s, "shards_written", float(i), series="shards")
        await log(s, f"Wrote shard_{i:03d}.bin ({random.randint(180, 240)} MB)")
        await asyncio.sleep(tick)
    await stage_status(s, "done")

    # ---- TEACH ----
    s = StageName.teach
    await stage_status(s, "running", "Cinque/supercombo on 7090 XT (no Chestnut)")
    await decision(
        s,
        "Teacher backend",
        "Cinque/supercombo on RX 7090 XT. Chestnut excluded by v1 design lock.",
        ["Cinque/supercombo@7090XT", "Chestnut (blocked)", "CPU fallback"],
        "Cinque/supercombo@7090XT",
        0.97,
    )
    await log(s, "Loading Cinque/supercombo weights (placeholder)…")
    await asyncio.sleep(tick)
    for i in range(1, 8):
        fps = 38 + random.uniform(-2, 4)
        await metric(s, "teacher_fps", round(fps, 1), unit="fps", series="teacher_fps")
        await progress(s, i / 7, f"soft-labels batch {i}/7")
        await asyncio.sleep(tick * 0.7)
    await metric(s, "soft_labels", 12800, unit="samples")
    await log(s, "Teacher pass complete — soft labels ready")
    await stage_status(s, "done")

    # ---- TRAIN ----
    s = StageName.train
    await stage_status(s, "running", "Distill → stock-modelV2-I/O student")
    await decision(
        s,
        "Student I/O contract",
        "Keep stock modelV2 cam/control I/O so artifact flashes to mici/QCOM without adapter layers.",
        ["stock-modelV2 I/O", "custom I/O (+adapter)", "Chestnut student (blocked)"],
        "stock-modelV2 I/O",
        0.95,
    )
    loss = 1.85
    for step in range(1, 13):
        loss *= 0.88 + random.uniform(-0.02, 0.01)
        await metric(s, "train_loss", round(loss, 4), series="train_loss")
        await metric(s, "lr", 3e-4 * (0.95 ** step), series="lr")
        await progress(s, step / 12, f"step {step * 50}/600")
        if step == 4:
            await _emit(
                emit,
                make_event(
                    job_id,
                    EventKind.warning,
                    WarningPayload(
                        code="LOSS_SPIKE",
                        message="Transient loss bump at step 200 — continuing (within tolerance)",
                        recoverable=True,
                    ),
                    stage=s,
                ),
            )
        await asyncio.sleep(tick * 0.65)
    await log(s, f"Train done — final loss {loss:.4f}")
    await stage_status(s, "done")

    # ---- EXPORT ----
    s = StageName.export
    await stage_status(s, "running", "Export student for QCOM/mici")
    await decision(
        s,
        "Export format",
        "ONNX with modelV2 I/O nodes validated against stock shapes.",
        ["ONNX", "raw tinygrad", "TorchScript"],
        "ONNX",
        0.9,
    )
    for i, detail in enumerate(["trace graph", "fold BN", "validate I/O", "write artifact"], 1):
        await progress(s, i / 4, detail)
        await log(s, f"export: {detail}")
        await asyncio.sleep(tick)
    await log(s, "Wrote artifacts/student_modelV2_io.onnx")
    await stage_status(s, "done")

    # ---- EVAL ----
    s = StageName.eval
    await stage_status(s, "running", "Offline scorecard")
    await decision(
        s,
        "Flash gate thresholds",
        "Require teacher agreement ≥ 0.92 and lateral MAE ≤ 0.08 before enabling flash confirm.",
        ["strict (≥0.95)", "standard (≥0.92)", "lenient (≥0.85)"],
        "standard (≥0.92)",
        0.88,
    )
    scores = {
        "teacher_agreement": 0.941,
        "lateral_mae": 0.062,
        "longitudinal_mae": 0.079,
        "desire_top1": 0.903,
        "route_replay": 0.927,
    }
    for name, val in scores.items():
        await metric(s, name, val, series="eval")
        await asyncio.sleep(tick * 0.5)
    await progress(s, 1.0, "scorecard ready")
    await log(s, "Eval PASS — flash gate unlocked (awaiting confirm)")
    await stage_status(s, "done")

    # ---- FLASH (gated) ----
    s = StageName.flash
    await stage_status(s, "gated", "Awaiting explicit flash confirm")
    await decision(
        s,
        "Flash policy",
        "Design lock: flash is always gated. Demo waits for confirm (or auto-timeout skip in headless).",
        ["wait for confirm", "auto-flash (forbidden)", "abort"],
        "wait for confirm",
        1.0,
    )
    await log(s, "FLASH GATED — confirm required in Expo UI or API", level="warn")

    confirmed = False
    if wait_flash_confirm is not None:
        confirmed = await wait_flash_confirm()
    else:
        # Headless demo: brief pause then simulate operator confirm
        await asyncio.sleep(tick * 3)
        confirmed = True
        await log(s, "Demo auto-confirm after pause (headless)")

    if confirmed:
        await stage_status(s, "running", "Flashing to mici (simulated)")
        for i, step in enumerate(["verify artifact", "transfer", "qcom load", "reboot check"], 1):
            await progress(s, i / 4, step)
            await log(s, f"flash: {step}")
            await asyncio.sleep(tick)
        await log(s, "Flash complete (simulated) — device ready")
        await stage_status(s, "done")
        await progress(s, 1.0, "done")
    else:
        await stage_status(s, "skipped", "Flash not confirmed")
        await log(s, "Flash skipped — no confirm", level="warn")
