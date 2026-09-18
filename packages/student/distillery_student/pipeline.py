"""Train stage runner — distill student on soft labels (stock modelV2 I/O)."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from distillery_events import (
    DecisionPayload,
    EventKind,
    LogPayload,
    MetricPayload,
    ProgressPayload,
    StageName,
    StagePayload,
    WarningPayload,
    make_event,
)
from distillery_student.config import StudentConfig, load_student_config
from distillery_student.device import probe_train_device
from distillery_student.hours import (
    InsufficientHoursError,
    estimate_driving_hours,
    hours_meet_floor,
)
from distillery_student.train_loop import (
    load_soft_label_summary,
    run_distill_steps,
    write_checkpoint,
)

EmitFn = Callable[[dict[str, Any]], Awaitable[None]]


async def _emit(emit: EmitFn, event) -> None:
    await emit(event.to_json_dict())


async def run_train_pipeline(
    job_id: str,
    emit: EmitFn,
    *,
    cfg: StudentConfig | None = None,
    tick: float = 0.12,
    write_files: bool = True,
    steps: int | None = None,
) -> dict[str, Any]:
    """Distill loop. Refuses below hours floor unless toy override (live=false)."""
    cfg = cfg or load_student_config()
    stage = StageName.train
    n_steps = steps if steps is not None else cfg.steps

    async def log(msg: str, level: str = "info") -> None:
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.log,
                LogPayload(level=level, message=msg, source="train"),  # type: ignore[arg-type]
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

    await stage_status("running", "Distill → stock-modelV2-I/O student")
    soft = await asyncio.to_thread(load_soft_label_summary, cfg.soft_labels_dir)
    soft_live = bool(soft.get("live"))
    soft_source = str(soft.get("source") or "fixture")

    device = await asyncio.to_thread(probe_train_device, force_fixture=cfg.force_fixture)
    hours_info = await asyncio.to_thread(
        estimate_driving_hours,
        soft_labels_dir=cfg.soft_labels_dir,
        shards_dir=cfg.shards_dir,
        soft_summary=soft,
    )
    gate = hours_meet_floor(
        hours_info,
        min_hours=cfg.min_train_hours,
        allow_toy=cfg.allow_toy_train,
    )

    await log(
        f"student={cfg.name} target={cfg.target} "
        f"soft_labels live={soft_live} source={soft_source} "
        f"hours={hours_info.get('hours')} known={hours_info.get('known')} "
        f"device={device.get('device_name')} tinygrad={device.get('tinygrad')}"
    )
    await progress(0.05, "load soft labels + hours/device probe")
    await asyncio.sleep(tick)

    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.metric,
            MetricPayload(
                name="driving_hours",
                value=float(hours_info.get("hours") or 0.0),
                unit="h",
                series="train",
            ),
            stage=stage,
        ),
    )

    if not gate["ok"]:
        msg = (
            f"Train refused — insufficient_hours "
            f"(hours={gate['hours']} < min={gate['min_hours']}, "
            f"known={gate['known']}). Set DISTILLERY_ALLOW_TOY_TRAIN=1 for "
            f"fixture CI only (live=false / not licensed)."
        )
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.warning,
                WarningPayload(code="INSUFFICIENT_HOURS", message=msg, recoverable=True),
                stage=stage,
            ),
        )
        await log(msg, level="error")
        await stage_status("failed", "insufficient_hours")
        raise InsufficientHoursError(msg, hours_info={**hours_info, **gate})

    licensed = bool(gate.get("licensed"))
    live_label = False
    if gate.get("toy_override"):
        await log(
            "Toy train override active — live=false / not licensed "
            "(DISTILLERY_ALLOW_TOY_TRAIN or allow_toy_train)",
            level="warn",
        )
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.warning,
                WarningPayload(
                    code="TOY_TRAIN_OVERRIDE",
                    message="Train allowed under toy override for CI — live=false / not licensed",
                    recoverable=True,
                ),
                stage=stage,
            ),
        )

    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.decision,
            DecisionPayload(
                title="Student I/O contract",
                rationale=(
                    "Keep stock modelV2 cam/control I/O so artifact flashes to "
                    "mici/QCOM without adapter layers. No Chestnut student. "
                    f"hours_gate={gate['reason']} device_kind={device.get('device_kind')}."
                ),
                options_considered=[
                    "stock-modelV2 I/O",
                    "custom I/O (+adapter)",
                    "Chestnut student (blocked)",
                ],
                chosen="stock-modelV2 I/O",
                confidence=0.95,
            ),
            stage=stage,
        ),
    )

    records = await asyncio.to_thread(run_distill_steps, steps=n_steps, lr=cfg.lr)
    backend = "tinygrad" if records and records[0].get("backend") == 1.0 else "pure-python"
    await log(f"Distill backend={backend} steps={n_steps}")

    final_loss = records[-1]["train_loss"] if records else 0.0
    for i, rec in enumerate(records):
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.metric,
                MetricPayload(name="train_loss", value=rec["train_loss"], series="train_loss"),
                stage=stage,
            ),
        )
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.metric,
                MetricPayload(name="lr", value=rec["lr"], series="lr"),
                stage=stage,
            ),
        )
        await progress((i + 1) / max(n_steps, 1), f"step {int(rec['step'])}/{n_steps}")
        await asyncio.sleep(tick * 0.4)

    result: dict[str, Any] = {
        "final_loss": final_loss,
        "steps": n_steps,
        "backend": backend,
        "io_contract": "stock-modelV2",
        "soft_labels_live": soft_live,
        "soft_labels_source": soft_source,
        "live": live_label,
        "licensed": licensed,
        "hours": hours_info,
        "hours_gate": gate,
        "device": device,
        "checkpoint": None,
    }

    if write_files:
        ckpt = await asyncio.to_thread(
            write_checkpoint,
            cfg.output_dir,
            final_loss=final_loss,
            steps=n_steps,
            meta={
                "io_contract": "stock-modelV2",
                "soft_labels_live": soft_live,
                "soft_labels_source": soft_source,
                "backend": backend,
                "live": live_label,
                "licensed": licensed,
                "hours": hours_info,
                "hours_gate": gate,
                "device": device,
            },
        )
        result["checkpoint"] = str(ckpt)
        await log(f"Wrote student checkpoint → {ckpt}")

    await log(f"Train done — final loss {final_loss:.4f}")
    await progress(1.0, "done")
    await stage_status("done", f"loss={final_loss:.4f} · {backend}")
    return result
