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
    make_event,
)
from distillery_student.config import StudentConfig, load_student_config
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
    """Lightweight distill loop; emits stage=train loss curves as metrics."""
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
    await log(
        f"student={cfg.name} target={cfg.target} "
        f"soft_labels live={soft_live} source={soft_source}"
    )
    await progress(0.05, "load soft labels")
    await asyncio.sleep(tick)

    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.decision,
            DecisionPayload(
                title="Student I/O contract",
                rationale=(
                    "Keep stock modelV2 cam/control I/O so artifact flashes to "
                    "mici/QCOM without adapter layers. No Chestnut student."
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

    records = await asyncio.to_thread(
        run_distill_steps, steps=n_steps, lr=cfg.lr
    )
    backend = "tinygrad" if records and records[0].get("backend") == 1.0 else "pure-python"
    await log(f"Distill backend={backend} steps={n_steps}")

    final_loss = records[-1]["train_loss"] if records else 0.0
    for i, rec in enumerate(records):
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.metric,
                MetricPayload(
                    name="train_loss",
                    value=rec["train_loss"],
                    series="train_loss",
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
                    name="lr",
                    value=rec["lr"],
                    series="lr",
                ),
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
            },
        )
        result["checkpoint"] = str(ckpt)
        await log(f"Wrote student checkpoint → {ckpt}")

    await log(f"Train done — final loss {final_loss:.4f}")
    await progress(1.0, "done")
    await stage_status("done", f"loss={final_loss:.4f} · {backend}")
    return result
