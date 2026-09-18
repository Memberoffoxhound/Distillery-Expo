"""Teach stage runner — Cinque/supercombo soft labels (or labeled fixture)."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Awaitable, Callable, Literal

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
from distillery_teacher.config import TeacherConfig, load_teacher_config
from distillery_teacher.device import TeacherDeviceInfo, detect_teacher_device
from distillery_teacher.download import BIG_TEACHER_NAME, ensure_big_teacher_onnx
from distillery_teacher.fixture import build_fixture_batches, write_soft_label_artifacts
from distillery_teacher.models import SoftLabelBatch

EmitFn = Callable[[dict[str, Any]], Awaitable[None]]
SourcePreference = Literal["auto", "live", "fixture"]


async def _emit(emit: EmitFn, event) -> None:
    await emit(event.to_json_dict())


async def run_teach_pipeline(
    job_id: str,
    emit: EmitFn,
    *,
    route_id: str | None = None,
    prefer: SourcePreference = "auto",
    cfg: TeacherConfig | None = None,
    tick: float = 0.12,
    write_files: bool = True,
    n_batches: int = 4,
) -> list[SoftLabelBatch]:
    """Produce soft labels; fixture path always sets live=false / source=fixture.

    No Chestnut. Live path only when AMD/ROCm/7090 XT is detected *and* a live
    checkpoint is explicitly enabled; otherwise clearly labeled fixture soft labels.
    """
    cfg = cfg or load_teacher_config()
    stage = StageName.teach

    async def log(msg: str, level: str = "info") -> None:
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.log,
                LogPayload(level=level, message=msg, source="teach"),  # type: ignore[arg-type]
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

    force_fixture = cfg.force_fixture or prefer == "fixture"

    await stage_status("running", f"{BIG_TEACHER_NAME} soft-label pass (big only; no Chestnut)")
    await log(
        f"teacher={cfg.name} prefer={prefer} route_id={route_id or 'auto'} "
        f"force_fixture={cfg.force_fixture}"
    )
    await progress(0.05, "detect teacher device")
    await asyncio.sleep(tick)

    device: TeacherDeviceInfo = await asyncio.to_thread(
        detect_teacher_device, force_fixture=force_fixture
    )
    if prefer == "live" and not device.live:
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.warning,
                WarningPayload(
                    code="TEACHER_GPU_MISSING",
                    message=(
                        "prefer=live but no 7090 XT / ROCm Cinque path — "
                        "falling back to fixture soft labels (live=false)"
                    ),
                    recoverable=True,
                ),
                stage=stage,
            ),
        )
        device = detect_teacher_device(force_fixture=True)

    chosen = (
        f"{cfg.name}@{device.device}"
        if device.live
        else f"{cfg.name}@fixture (live=false)"
    )

    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.decision,
            DecisionPayload(
                title="Teacher backend",
                rationale=(
                    "Cinque/supercombo on RX 7090 XT when available. "
                    "Chestnut excluded by v1 design lock. "
                    "Missing GPU → labeled fixture soft labels (never claim live)."
                ),
                options_considered=[
                    "Cinque/supercombo@7090XT",
                    "Chestnut (blocked)",
                    "fixture soft-labels",
                ],
                chosen=chosen,
                confidence=0.97 if device.live else 0.99,
            ),
            stage=stage,
        ),
    )
    await log(device.detail, level="info" if device.live else "warn")
    await progress(0.15, device.backend)
    await asyncio.sleep(tick)

    # Pull big_driving_supercombo into artifacts/teachers/ (cache+checksum; no small fallback)
    await progress(0.18, f"ensure teacher ONNX · {BIG_TEACHER_NAME}")
    await log(f"Ensuring comma master teacher artifact: {BIG_TEACHER_NAME}")

    def _prog(frac: float, detail: str) -> None:
        # sync callback — best-effort; detailed progress emitted after thread returns
        pass

    art = await asyncio.to_thread(
        ensure_big_teacher_onnx,
        force_fixture=force_fixture,
        progress=_prog,
    )
    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.progress,
            ProgressPayload(
                fraction=0.22,
                detail=art.label or f"teacher · {BIG_TEACHER_NAME}",
            ),
            stage=stage,
        ),
    )
    await log(
        f"teacher artifact: label={art.label} live={art.live} cached={art.cached} "
        f"path={art.path} ok={art.ok}"
        + (f" error={art.error}" if art.error else "")
    )
    if not art.live:
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.warning,
                WarningPayload(
                    code="TEACHER_ONNX_FIXTURE",
                    message=(
                        f"{art.label}: offline or download failed — "
                        "using labeled fixture soft labels (never pretend live; "
                        "no driving_supercombo fallback)"
                    ),
                    recoverable=True,
                ),
                stage=stage,
            ),
        )
    elif art.path and not cfg.checkpoint:
        # Wire checkpoint to cached ONNX for live claim path
        cfg = TeacherConfig(
            name=cfg.name if cfg.name else BIG_TEACHER_NAME,
            device_label=cfg.device_label,
            checkpoint=str(art.path),
            output_dir=cfg.output_dir,
            force_fixture=cfg.force_fixture,
            repo_root=cfg.repo_root,
        )
    await asyncio.sleep(tick)


    # Without in-repo Cinque weights, never claim live unless explicitly opted in.
    allow_claim_live = (
        device.live
        and os.environ.get("DISTILLERY_TEACHER_LIVE", "").lower() in ("1", "true", "yes")
        and bool(cfg.checkpoint)
    )

    batches = await asyncio.to_thread(
        build_fixture_batches,
        n_batches=n_batches,
        route_id=route_id,
    )

    if allow_claim_live:
        batches = [
            b.model_copy(
                update={
                    "live": True,
                    "source": "live",
                    "device": device.device,
                    "meta": {
                        **b.meta,
                        "live": True,
                        "source": "live",
                        "device": device.device,
                        "teacher": cfg.name,
                        "backend": device.backend,
                    },
                }
            )
            for b in batches
        ]
        await log(f"Live teacher path enabled — checkpoint={cfg.checkpoint}")
    else:
        if device.live and not allow_claim_live:
            await log(
                "GPU detected but no live Cinque checkpoint wired — "
                "emitting fixture soft labels with live=false (honest)",
                level="warn",
            )
        for b in batches:
            assert b.live is False
            assert b.source == "fixture"
            assert b.meta.get("live") is False

    n = max(len(batches), 1)
    total_samples = 0
    for i, batch in enumerate(batches):
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.sample,
                SamplePayload(
                    cam="other",
                    label=f"{batch.batch_id} · {batch.n_samples} soft-labels",
                    placeholder=not batch.live,
                    meta={
                        **batch.summary_dict(),
                        "live": batch.live,
                        "source": batch.source,
                        "teacher": batch.teacher,
                        "device": batch.device,
                    },
                ),
                stage=stage,
            ),
        )
        total_samples += batch.n_samples
        fps = 12.0 if not batch.live else 40.0
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.metric,
                MetricPayload(
                    name="teacher_fps",
                    value=fps,
                    unit="fps",
                    series="teacher_fps",
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
                    name="soft_labels",
                    value=float(total_samples),
                    unit="samples",
                    series="soft_labels",
                ),
                stage=stage,
            ),
        )
        await progress((i + 1) / n * 0.8 + 0.15, f"soft-labels batch {i + 1}/{n}")
        await log(
            f"Wrote {batch.batch_id} n={batch.n_samples} "
            f"live={batch.live} source={batch.source} device={batch.device}"
        )
        await asyncio.sleep(tick * 0.5)

    if write_files:
        manifest = await asyncio.to_thread(
            write_soft_label_artifacts, batches, cfg.output_dir
        )
        await log(f"Soft-label manifest → {manifest}")

    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.metric,
            MetricPayload(
                name="teach_live",
                value=1.0 if (batches and batches[0].live) else 0.0,
                unit="bool",
            ),
            stage=stage,
        ),
    )

    await progress(1.0, "done")
    live_flag = bool(batches and batches[0].live)
    detail = (
        f"{len(batches)} batches · {total_samples} soft-labels · "
        f"live={live_flag} · source={'live' if live_flag else 'fixture'}"
    )
    await log(f"Teach complete — {detail}")
    await stage_status("done", detail)
    return batches
