"""Distillery Expo API — jobs + WebSocket event stream."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from api.demo_runner import STAGES, run_demo_pipeline
from api.ml_adapters import (
    coerce_eval_passed,
    resolve_eval,
    resolve_export,
    resolve_flash,
    resolve_teach,
    resolve_train,
    runtime_status,
)
from distillery_ingest import load_ingest_config, run_ingest_pipeline
from distillery_ingest.discover import (
    apply_discovered_overrides,
    connect_status,
    enrich_dongle_response,
    discovery_overview,
    dongle_status,
    list_adb_devices,
    probe_ssh,
    set_connect_jwt,
    set_dongle_id,
    set_ssh_config,
    ssh_status,
)
from distillery_ingest.resolve import list_routes as ingest_list_routes
from distillery_shards import run_shard_pipeline
from distillery_student import check_train_readiness, probe_train_device
from distillery_teacher import list_comma_master_teachers, select_comma_master_teacher

import inspect


async def _call_stage(runner, job_id: str, emit, **kwargs):
    """Pass only kwargs accepted by Graig (or fixture) runner signature."""
    sig = inspect.signature(runner)
    accepted = set(sig.parameters) - {"job_id", "emit"}
    # Prefer **varkw if present
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        return await runner(job_id, emit, **kwargs)
    filtered = {k: v for k, v in kwargs.items() if k in accepted}
    return await runner(job_id, emit, **filtered)


app = FastAPI(
    title="Distillery Expo API",
    version="0.4.1",
    description="tinygrad distill control room — teach→train→export→eval + gated flash",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class JobRecord(BaseModel):
    id: str
    kind: str = "demo"
    status: str = "pending"  # pending|running|gated|done|failed
    created_at: str
    events: list[dict[str, Any]] = Field(default_factory=list)
    flash_confirmed: bool = False
    flash_done: bool = False
    device_write: bool = False
    route_id: str | None = None
    eval_passed: bool = False
    onnx_path: str | None = None


class JobSummary(BaseModel):
    id: str
    kind: str
    status: str
    created_at: str
    event_count: int
    route_id: str | None = None


class IngestJobRequest(BaseModel):
    route_id: str | None = None
    source: Literal["auto", "connect", "ssh", "fixture"] = "auto"


class ShardJobRequest(BaseModel):
    route_id: str | None = None
    source: Literal["auto", "connect", "ssh", "fixture"] = "auto"


class TeachJobRequest(BaseModel):
    route_id: str | None = None
    source: Literal["auto", "connect", "ssh", "fixture"] = "auto"


class TrainJobRequest(BaseModel):
    route_id: str | None = None
    source: Literal["auto", "connect", "ssh", "fixture"] = "auto"


class ExportJobRequest(BaseModel):
    route_id: str | None = None
    checkpoint_path: str | None = None


class EvalJobRequest(BaseModel):
    route_id: str | None = None
    onnx_path: str | None = None
    force_fail: bool = False
    # Test-only: fixture stub defaults to FAIL (not licensed). force_pass unlocks gate intentionally.
    force_pass: bool = False


class PipelineJobRequest(BaseModel):
    """Sequential teach→train→export→eval→(gated)flash for Expo simple-user path."""
    route_id: str | None = None
    source: Literal["auto", "connect", "ssh", "fixture"] = "auto"
    include_flash: bool = True


class TrainAllRequest(BaseModel):
    """One-click ingest→shard→teach→train→export→eval (never auto-flash)."""
    route_id: str | None = None
    source: Literal["auto", "connect", "ssh", "fixture"] = "auto"
    teacher: str | None = None
    allow_toy: bool = False
    force_fixture: bool = False


class TeacherPullRequest(BaseModel):
    """Pull big_driving_supercombo only into artifacts/teachers/ (never small model)."""
    force_fixture: bool = False
    force_download: bool = False


class ConnectJwtRequest(BaseModel):
    """Set comma Connect JWT without shell/env archaeology."""
    jwt: str = Field(..., min_length=1)
    persist: bool = True


class SshConfigRequest(BaseModel):
    """Set mici SSH target without MICI_SSH_HOST scavenger hunt."""
    host: str = Field(..., min_length=1)
    user: str = "comma"
    port: int = 22
    identity_path: str | None = None
    persist: bool = True
    test: bool = False


class DongleIdRequest(BaseModel):
    """Set mici dongle id without DISTILLERY_DONGLE_ID scavenger hunt."""
    dongle_id: str = Field(..., min_length=1)
    persist: bool = True


# In-memory job store
_jobs: dict[str, JobRecord] = {}
_subscribers: dict[str, list[asyncio.Queue]] = {}
_flash_events: dict[str, asyncio.Event] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _summary(job: JobRecord) -> JobSummary:
    return JobSummary(
        id=job.id,
        kind=job.kind,
        status=job.status,
        created_at=job.created_at,
        event_count=len(job.events),
        route_id=job.route_id,
    )


async def _broadcast(job_id: str, event: dict[str, Any]) -> None:
    job = _jobs.get(job_id)
    if job is None:
        return
    job.events.append(event)
    # Update job status from stage events
    # Phil gate: only explicit eval_pass==1.0 sets True (never infer empty pass)
    if event.get("kind") == "metric" and event.get("stage") == "eval":
        payload = event.get("payload") or {}
        if payload.get("name") in ("eval_pass", "eval_passed"):
            try:
                job.eval_passed = float(payload.get("value") or 0) >= 1.0
            except (TypeError, ValueError):
                job.eval_passed = False
    if event.get("kind") == "stage":
        payload = event.get("payload") or {}
        st = payload.get("status")
        name = payload.get("name")
        if st == "gated":
            job.status = "gated"
        elif st == "failed":
            job.status = "failed"
        elif name == "flash" and st in ("done", "skipped"):
            job.status = "done"
        elif job.kind == "ingest" and name == "ingest" and st == "done":
            job.status = "done"
        elif job.kind == "shard" and name == "shard" and st == "done":
            job.status = "done"
        elif job.kind == "teach" and name == "teach" and st == "done":
            job.status = "done"
        elif job.kind == "train" and name == "train" and st == "done":
            job.status = "done"
        elif job.kind == "export" and name == "export" and st == "done":
            job.status = "done"
        elif job.kind == "eval" and name == "eval" and st == "done":
            job.status = "done"
        elif job.kind == "teacher_pull" and name == "teach" and st == "done":
            job.status = "done"
        elif job.kind == "teacher_pull" and name == "teach" and st == "failed":
            job.status = "failed"
        elif st == "running" and job.status == "pending":
            job.status = "running"
    for q in list(_subscribers.get(job_id, [])):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


async def _wait_flash(job_id: str) -> bool:
    ev = _flash_events.setdefault(job_id, asyncio.Event())
    try:
        await asyncio.wait_for(ev.wait(), timeout=120.0)
        return True
    except asyncio.TimeoutError:
        # Demo: auto-confirm so headless smoke tests finish
        job = _jobs.get(job_id)
        if job and not job.flash_confirmed:
            await _broadcast(
                job_id,
                {
                    "id": str(uuid4()),
                    "ts": _now(),
                    "job_id": job_id,
                    "kind": "log",
                    "stage": "flash",
                    "payload": {
                        "level": "warn",
                        "message": "Flash confirm timeout — demo auto-confirm",
                        "source": "flash",
                    },
                },
            )
            return True
        return False


async def _run_demo_job(job_id: str) -> None:
    job = _jobs[job_id]
    job.status = "running"

    async def emit(event: dict[str, Any]) -> None:
        await _broadcast(job_id, event)

    try:
        await run_demo_pipeline(
            job_id,
            emit,
            gated_flash=True,
            wait_flash_confirm=lambda: _wait_flash(job_id),
            tick=0.28,
        )
        if job.status not in ("done", "failed"):
            job.status = "done"
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        await _broadcast(
            job_id,
            {
                "id": str(uuid4()),
                "ts": _now(),
                "job_id": job_id,
                "kind": "log",
                "stage": None,
                "payload": {
                    "level": "error",
                    "message": f"Job failed: {exc}",
                    "source": "api",
                },
            },
        )


async def _run_ingest_job(
    job_id: str,
    *,
    route_id: str | None,
    prefer: str,
) -> None:
    job = _jobs[job_id]
    job.status = "running"

    async def emit(event: dict[str, Any]) -> None:
        await _broadcast(job_id, event)

    try:
        route = await run_ingest_pipeline(
            job_id,
            emit,
            route_id=route_id,
            prefer=prefer,  # type: ignore[arg-type]
            tick=0.12,
        )
        job.route_id = route.route_id
        if job.status not in ("done", "failed"):
            job.status = "done"
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        await _broadcast(
            job_id,
            {
                "id": str(uuid4()),
                "ts": _now(),
                "job_id": job_id,
                "kind": "log",
                "stage": "ingest",
                "payload": {
                    "level": "error",
                    "message": f"Ingest failed: {exc}",
                    "source": "ingest",
                },
            },
        )



async def _run_shard_job(
    job_id: str,
    *,
    route_id: str | None,
    prefer: str,
) -> None:
    job = _jobs[job_id]
    job.status = "running"

    async def emit(event: dict[str, Any]) -> None:
        await _broadcast(job_id, event)

    try:
        shards = await run_shard_pipeline(
            job_id,
            emit,
            route_id=route_id,
            prefer=prefer,  # type: ignore[arg-type]
            tick=0.12,
        )
        if shards:
            job.route_id = shards[0].route_id
        if job.status not in ("done", "failed"):
            job.status = "done"
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        await _broadcast(
            job_id,
            {
                "id": str(uuid4()),
                "ts": _now(),
                "job_id": job_id,
                "kind": "log",
                "stage": "shard",
                "payload": {
                    "level": "error",
                    "message": f"Shard pack failed: {exc}",
                    "source": "shard",
                },
            },
        )



async def _run_teach_job(
    job_id: str,
    *,
    route_id: str | None = None,
    prefer: str = "auto",
) -> None:
    job = _jobs[job_id]
    job.status = "running"

    async def emit(event: dict[str, Any]) -> None:
        await _broadcast(job_id, event)

    try:
        result = await _call_stage(
            resolve_teach(),
            job_id,
            emit,
            route_id=route_id,
            prefer=prefer if prefer in ("auto", "live", "fixture") else "auto",
            tick=0.08,
        )
        if route_id:
            job.route_id = route_id
        if job.status not in ("done", "failed"):
            job.status = "done"
        _ = result
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        await _broadcast(
            job_id,
            {
                "id": str(uuid4()),
                "ts": _now(),
                "job_id": job_id,
                "kind": "log",
                "stage": "teach",
                "payload": {
                    "level": "error",
                    "message": f"Teach failed: {exc}",
                    "source": "teach",
                },
            },
        )


async def _run_train_job(
    job_id: str,
    *,
    route_id: str | None = None,
    prefer: str = "auto",
) -> None:
    job = _jobs[job_id]
    job.status = "running"

    async def emit(event: dict[str, Any]) -> None:
        await _broadcast(job_id, event)

    try:
        result = await _call_stage(
            resolve_train(),
            job_id,
            emit,
            route_id=route_id,
            prefer=prefer if prefer in ("auto", "live", "fixture") else "auto",
            tick=0.08,
        )
        if route_id:
            job.route_id = route_id
        if job.status not in ("done", "failed"):
            job.status = "done"
        _ = result
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        await _broadcast(
            job_id,
            {
                "id": str(uuid4()),
                "ts": _now(),
                "job_id": job_id,
                "kind": "log",
                "stage": "train",
                "payload": {
                    "level": "error",
                    "message": f"Train failed: {exc}",
                    "source": "train",
                },
            },
        )


async def _run_export_job(
    job_id: str,
    *,
    route_id: str | None = None,
    checkpoint_path: str | None = None,
) -> None:
    job = _jobs[job_id]
    job.status = "running"

    async def emit(event: dict[str, Any]) -> None:
        await _broadcast(job_id, event)

    try:
        result = await _call_stage(
            resolve_export(),
            job_id,
            emit,
            route_id=route_id,
            checkpoint_path=checkpoint_path,
            tick=0.08,
        )
        onnx = getattr(result, "onnx_path", None)
        if isinstance(result, dict):
            onnx = result.get("onnx_path", onnx)
        if onnx:
            job.onnx_path = str(onnx)
        if job.status not in ("done", "failed"):
            job.status = "done"
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        await _broadcast(
            job_id,
            {
                "id": str(uuid4()),
                "ts": _now(),
                "job_id": job_id,
                "kind": "log",
                "stage": "export",
                "payload": {
                    "level": "error",
                    "message": f"Export failed: {exc}",
                    "source": "export",
                },
            },
        )


async def _run_eval_job(
    job_id: str,
    *,
    route_id: str | None = None,
    onnx_path: str | None = None,
    force_fail: bool = False,
    force_pass: bool = False,
) -> None:
    job = _jobs[job_id]
    job.status = "running"

    async def emit(event: dict[str, Any]) -> None:
        await _broadcast(job_id, event)

    try:
        result = await _call_stage(
            resolve_eval(),
            job_id,
            emit,
            route_id=route_id,
            onnx_path=onnx_path or job.onnx_path,
            force_fail=force_fail,
            force_pass=force_pass,
            tick=0.08,
        )
        job.eval_passed = coerce_eval_passed(result)
        if job.status not in ("done", "failed"):
            job.status = "done"
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.eval_passed = False
        await _broadcast(
            job_id,
            {
                "id": str(uuid4()),
                "ts": _now(),
                "job_id": job_id,
                "kind": "log",
                "stage": "eval",
                "payload": {
                    "level": "error",
                    "message": f"Eval failed: {exc}",
                    "source": "eval",
                },
            },
        )


async def _run_pipeline_job(
    job_id: str,
    *,
    route_id: str | None = None,
    prefer: str = "auto",
    include_flash: bool = True,
) -> None:
    """teach → train → export → eval → gated flash (confirm required; never auto-write)."""
    job = _jobs[job_id]
    job.status = "running"

    async def emit(event: dict[str, Any]) -> None:
        await _broadcast(job_id, event)

    try:
        prefer_ml = prefer if prefer in ("auto", "live", "fixture") else "auto"
        await _call_stage(
            resolve_teach(), job_id, emit, route_id=route_id, prefer=prefer_ml, tick=0.06
        )
        await _call_stage(
            resolve_train(), job_id, emit, route_id=route_id, prefer=prefer_ml, tick=0.06
        )
        export_result = await _call_stage(
            resolve_export(), job_id, emit, route_id=route_id, tick=0.06
        )
        onnx = getattr(export_result, "onnx_path", None)
        if isinstance(export_result, dict):
            onnx = export_result.get("onnx_path", onnx)
        if onnx:
            job.onnx_path = str(onnx)

        eval_result = await _call_stage(
            resolve_eval(),
            job_id,
            emit,
            route_id=route_id,
            onnx_path=job.onnx_path,
            tick=0.06,
        )
        job.eval_passed = coerce_eval_passed(eval_result)

        if not include_flash:
            if job.status not in ("done", "failed", "gated"):
                job.status = "done"
            return

        # Gate flash: only enter gated state when eval passed
        from distillery_events import (
            DecisionPayload,
            EventKind,
            LogPayload,
            StageName,
            StagePayload,
            make_event,
        )

        stage = StageName.flash
        if not job.eval_passed:
            await emit(
                make_event(
                    job_id,
                    EventKind.log,
                    LogPayload(
                        level="warn",
                        message="Flash blocked — eval did not pass (no device write)",
                        source="flash",
                    ),
                    stage=stage,
                ).to_json_dict()
            )
            await emit(
                make_event(
                    job_id,
                    EventKind.stage,
                    StagePayload(
                        name=stage,
                        status="skipped",
                        detail="Blocked: eval_passed=false",
                    ),
                    stage=stage,
                ).to_json_dict()
            )
            job.status = "done"
            return

        await emit(
            make_event(
                job_id,
                EventKind.stage,
                StagePayload(
                    name=stage,
                    status="gated",
                    detail="Awaiting explicit flash confirm (eval passed)",
                ),
                stage=stage,
            ).to_json_dict()
        )
        await emit(
            make_event(
                job_id,
                EventKind.decision,
                DecisionPayload(
                    title="Flash policy",
                    rationale=(
                        "Design lock: flash is always gated. Confirm only after eval_passed. "
                        "Never auto-write to device."
                    ),
                    options_considered=[
                        "wait for confirm",
                        "auto-flash (forbidden)",
                        "abort",
                    ],
                    chosen="wait for confirm",
                    confidence=1.0,
                ),
                stage=stage,
            ).to_json_dict()
        )
        await emit(
            make_event(
                job_id,
                EventKind.log,
                LogPayload(
                    level="warn",
                    message="FLASH GATED — confirm required; eval_passed=true",
                    source="flash",
                ),
                stage=stage,
            ).to_json_dict()
        )

        confirmed = await _wait_flash(job_id)
        # Pipeline never auto-writes on timeout without confirm flag.
        # Confirm endpoint may have already run deploy (flash_done).
        if confirmed and job.flash_confirmed:
            if not job.flash_done:
                result = await _call_stage(
                    resolve_flash(),
                    job_id,
                    emit,
                    confirmed=True,
                    eval_passed=job.eval_passed,
                    onnx_path=job.onnx_path,
                    tick=0.06,
                )
                if isinstance(result, dict):
                    job.device_write = bool(result.get("device_write"))
                    job.flash_done = True
        else:
            await _call_stage(
                resolve_flash(),
                job_id,
                emit,
                confirmed=False,
                eval_passed=job.eval_passed,
                onnx_path=job.onnx_path,
                tick=0.0,
            )
        if job.status not in ("done", "failed"):
            job.status = "done"
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        await _broadcast(
            job_id,
            {
                "id": str(uuid4()),
                "ts": _now(),
                "job_id": job_id,
                "kind": "log",
                "stage": None,
                "payload": {
                    "level": "error",
                    "message": f"Pipeline failed: {exc}",
                    "source": "api",
                },
            },
        )



async def _run_train_all_job(
    job_id: str,
    *,
    route_id: str | None = None,
    prefer: str = "auto",
) -> None:
    """ingest → shard → teach → train → export → eval. Never flashes."""
    job = _jobs[job_id]
    job.status = "running"

    async def emit(event: dict[str, Any]) -> None:
        await _broadcast(job_id, event)

    try:
        prefer_ml = prefer if prefer in ("auto", "live", "fixture") else "auto"
        # Ingest
        route = await run_ingest_pipeline(
            job_id,
            emit,
            route_id=route_id,
            prefer=prefer,  # type: ignore[arg-type]
            tick=0.08,
        )
        rid = getattr(route, "route_id", None) or route_id
        if rid:
            job.route_id = str(rid)
        # Shard
        await run_shard_pipeline(
            job_id,
            emit,
            route_id=rid,
            prefer=prefer,  # type: ignore[arg-type]
            tick=0.08,
        )
        # Pull big_driving_supercombo into artifacts/teachers/ before teach (cache+checksum)
        from distillery_teacher.download import BIG_TEACHER_NAME, ensure_big_teacher_onnx

        await _broadcast(
            job_id,
            {
                "id": str(uuid4()),
                "ts": _now(),
                "job_id": job_id,
                "kind": "progress",
                "stage": "teach",
                "payload": {
                    "fraction": 0.02,
                    "detail": f"ensure teacher ONNX · {BIG_TEACHER_NAME}",
                },
            },
        )
        art = await asyncio.to_thread(
            ensure_big_teacher_onnx,
            force_fixture=(prefer_ml == "fixture"),
        )
        await _broadcast(
            job_id,
            {
                "id": str(uuid4()),
                "ts": _now(),
                "job_id": job_id,
                "kind": "log",
                "stage": "teach",
                "payload": {
                    "level": "info" if art.live else "warn",
                    "message": (
                        f"teacher ready: {art.label} cached={art.cached} "
                        f"path={art.path} live={art.live}"
                        + (f" err={art.error}" if art.error else "")
                    ),
                    "source": "teach",
                },
            },
        )
        await _call_stage(
            resolve_teach(), job_id, emit, route_id=rid, prefer=prefer_ml, tick=0.06
        )
        await _call_stage(
            resolve_train(), job_id, emit, route_id=rid, prefer=prefer_ml, tick=0.06
        )
        export_result = await _call_stage(
            resolve_export(), job_id, emit, route_id=rid, tick=0.06
        )
        onnx = getattr(export_result, "onnx_path", None)
        if isinstance(export_result, dict):
            onnx = export_result.get("onnx_path", onnx)
        if onnx:
            job.onnx_path = str(onnx)
        eval_result = await _call_stage(
            resolve_eval(),
            job_id,
            emit,
            route_id=rid,
            onnx_path=job.onnx_path,
            tick=0.06,
        )
        job.eval_passed = coerce_eval_passed(eval_result)
        if job.status not in ("done", "failed", "gated"):
            job.status = "done"
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        await _broadcast(
            job_id,
            {
                "id": str(uuid4()),
                "ts": _now(),
                "job_id": job_id,
                "kind": "log",
                "stage": None,
                "payload": {
                    "level": "error",
                    "message": f"train_all failed: {exc}",
                    "source": "api",
                },
            },
        )



async def _run_teacher_pull_job(
    job_id: str,
    *,
    force_fixture: bool = False,
    force_download: bool = False,
) -> None:
    """Pull big_driving_supercombo into artifacts/teachers/ with progress on the job bus."""
    from distillery_teacher.download import BIG_TEACHER_NAME, ensure_big_teacher_onnx

    job = _jobs[job_id]
    job.status = "running"
    loop = asyncio.get_running_loop()
    progress_q: asyncio.Queue[tuple[float, str] | None] = asyncio.Queue()

    def _prog(frac: float, detail: str) -> None:
        try:
            loop.call_soon_threadsafe(progress_q.put_nowait, (float(frac), str(detail)))
        except Exception:  # noqa: BLE001
            pass

    async def _drain_progress() -> None:
        while True:
            item = await progress_q.get()
            if item is None:
                break
            frac, detail = item
            await _broadcast(
                job_id,
                {
                    "id": str(uuid4()),
                    "ts": _now(),
                    "job_id": job_id,
                    "kind": "progress",
                    "stage": "teach",
                    "payload": {
                        "fraction": max(0.0, min(1.0, frac)),
                        "detail": detail,
                        "teacher": BIG_TEACHER_NAME,
                    },
                },
            )

    drain_task = asyncio.create_task(_drain_progress())
    try:
        await _broadcast(
            job_id,
            {
                "id": str(uuid4()),
                "ts": _now(),
                "job_id": job_id,
                "kind": "stage",
                "stage": "teach",
                "payload": {
                    "name": "teach",
                    "status": "running",
                    "detail": f"pull · {BIG_TEACHER_NAME}",
                },
            },
        )
        await _broadcast(
            job_id,
            {
                "id": str(uuid4()),
                "ts": _now(),
                "job_id": job_id,
                "kind": "progress",
                "stage": "teach",
                "payload": {
                    "fraction": 0.02,
                    "detail": f"ensure teacher ONNX · {BIG_TEACHER_NAME}",
                    "teacher": BIG_TEACHER_NAME,
                },
            },
        )
        art = await asyncio.to_thread(
            ensure_big_teacher_onnx,
            force_fixture=force_fixture,
            force_download=force_download,
            progress=_prog,
        )
        await progress_q.put(None)
        await drain_task

        # Graig consume: checksum-verify artifacts/teachers cache after pull.
        # Success → live label; fail/offline → labeled fixture (never small model).
        from distillery_teacher.consume import consume_big_teacher_for_teach

        await _broadcast(
            job_id,
            {
                "id": str(uuid4()),
                "ts": _now(),
                "job_id": job_id,
                "kind": "progress",
                "stage": "teach",
                "payload": {
                    "fraction": 0.92,
                    "detail": f"verify checksum · {BIG_TEACHER_NAME}",
                    "teacher": BIG_TEACHER_NAME,
                },
            },
        )
        consumed = await asyncio.to_thread(
            consume_big_teacher_for_teach,
            force_fixture=force_fixture or not art.live,
        )
        # Consume is source of truth for teach label (checksum → live or fixture).
        art = consumed

        art_dict = art.as_dict()
        level = "info" if art.live else "warn"
        await _broadcast(
            job_id,
            {
                "id": str(uuid4()),
                "ts": _now(),
                "job_id": job_id,
                "kind": "log",
                "stage": "teach",
                "payload": {
                    "level": level,
                    "message": (
                        f"teacher pull: {art.label} cached={art.cached} "
                        f"live={art.live} ok={art.ok} path={art.path}"
                        + (f" err={art.error}" if art.error else "")
                    ),
                    "source": "teacher_pull",
                    "teacher": art_dict,
                },
            },
        )
        await _broadcast(
            job_id,
            {
                "id": str(uuid4()),
                "ts": _now(),
                "job_id": job_id,
                "kind": "decision",
                "stage": "teach",
                "payload": {
                    "title": "Teacher artifact",
                    "rationale": art.detail or art.label,
                    "options_considered": [BIG_TEACHER_NAME],
                    "chosen": art.label,
                    "confidence": 1.0 if art.live else 0.0,
                    "teacher": art_dict,
                    "live": art.live,
                    "cached": art.cached,
                    "ok": art.ok,
                    "label": art.label,
                    "sha256": art.sha256,
                },
            },
        )
        # Offline / fixture is an honest gap, not a crash — job still completes.
        if not art.live:
            await _broadcast(
                job_id,
                {
                    "id": str(uuid4()),
                    "ts": _now(),
                    "job_id": job_id,
                    "kind": "warning",
                    "stage": "teach",
                    "payload": {
                        "code": "TEACHER_NOT_LIVE",
                        "message": (
                            art.error
                            or art.detail
                            or f"fixture · {BIG_TEACHER_NAME} (live=false; no small-model fallback)"
                        ),
                        "recoverable": True,
                        "label": art.label,
                        "teacher": BIG_TEACHER_NAME,
                    },
                },
            )
        await _broadcast(
            job_id,
            {
                "id": str(uuid4()),
                "ts": _now(),
                "job_id": job_id,
                "kind": "progress",
                "stage": "teach",
                "payload": {
                    "fraction": 1.0,
                    "detail": art.label,
                    "teacher": BIG_TEACHER_NAME,
                    "live": art.live,
                    "cached": art.cached,
                    "ok": art.ok,
                    "label": art.label,
                    "sha256": art.sha256,
                    "consumed": True,
                    "path": str(art.path) if art.path else None,
                },
            },
        )
        await _broadcast(
            job_id,
            {
                "id": str(uuid4()),
                "ts": _now(),
                "job_id": job_id,
                "kind": "stage",
                "stage": "teach",
                "payload": {
                    "name": "teach",
                    "status": "done",
                    "detail": art.label,
                    "teacher": art_dict,
                    "label": art.label,
                    "live": art.live,
                    "ok": art.ok,
                },
            },
        )
        if job.status not in ("done", "failed"):
            job.status = "done"
    except Exception as exc:  # noqa: BLE001
        try:
            await progress_q.put(None)
            await drain_task
        except Exception:  # noqa: BLE001
            drain_task.cancel()
        job.status = "failed"
        await _broadcast(
            job_id,
            {
                "id": str(uuid4()),
                "ts": _now(),
                "job_id": job_id,
                "kind": "stage",
                "stage": "teach",
                "payload": {
                    "name": "teach",
                    "status": "failed",
                    "detail": f"teacher pull failed: {exc}",
                },
            },
        )
        await _broadcast(
            job_id,
            {
                "id": str(uuid4()),
                "ts": _now(),
                "job_id": job_id,
                "kind": "log",
                "stage": "teach",
                "payload": {
                    "level": "error",
                    "message": f"teacher pull failed: {exc}",
                    "source": "teacher_pull",
                },
            },
        )


@app.get("/health")
async def health() -> dict[str, Any]:
    """Liveness + PyTorch device status (CUDA / ROCm / MPS / CPU; not 7090-locked)."""
    rt = runtime_status()
    out = {
        "ok": True,
        "status": "ok",
        "service": "distillery-expo",
        "torch": rt.get("torch"),
        "device": rt["device"],
        "mode": rt["mode"],
        "ml_backends": rt["ml_backends"],
        "probe": rt.get("probe"),
        "detail": rt.get("detail"),
    }
    # Leftover tinygrad presence only (not train backend)
    if "tinygrad" in rt:
        out["tinygrad"] = rt["tinygrad"]
    if rt.get("tinygrad_note") is not None:
        out["tinygrad_note"] = rt["tinygrad_note"]
    return out


@app.get("/status/runtime")
async def status_runtime() -> dict[str, Any]:
    """Explicit runtime/device probe for Expo status chips."""
    return runtime_status()


@app.get("/stages")
async def list_stages() -> dict[str, list[str]]:
    return {"stages": [s.value for s in STAGES]}


@app.get("/dongle")
async def get_dongle() -> dict[str, Any]:
    """Dongle + Connect/SSH posture, plus ADB readiness for Expo status chips.

    dongle_id is null/empty until POST /dongle (or DISTILLERY_DONGLE_ID / .cache)
    or auto-hydrate from ADB/SSH DongleId. Never returns a hardcoded demo default.
    When ADB/SSH can read /data/params/d/DongleId, includes suggested_dongle_id
    and discovered_from (adb|ssh|null).
    """
    status = dongle_status()
    adb = list_adb_devices()
    adb_available = bool(adb.get("adb_available"))
    devices = adb.get("devices") or []
    if not adb_available:
        adb_status = "not_on_path"
    elif not adb.get("ok", False):
        adb_status = "error"
    else:
        adb_status = "ready"
    enriched = enrich_dongle_response(status, adb=adb, auto_hydrate=True)
    return {
        **enriched,
        "adb_available": adb_available,
        "adb_status": adb_status,
        "adb_device_count": len(devices),
    }




@app.post("/dongle")
async def post_dongle(body: DongleIdRequest) -> dict[str, Any]:
    """Set/use dongle id (process env + optional .cache/dongle_id; not committed)."""
    try:
        status = set_dongle_id(body.dongle_id, persist=body.persist)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    adb = list_adb_devices()
    adb_available = bool(adb.get("adb_available"))
    devices = adb.get("devices") or []
    if not adb_available:
        adb_status = "not_on_path"
    elif not adb.get("ok", False):
        adb_status = "error"
    else:
        adb_status = "ready"
    # Manual Save already configured — never auto-overwrite; still expose suggestions.
    enriched = enrich_dongle_response(status, adb=adb, auto_hydrate=False)
    return {
        **enriched,
        "adb_available": adb_available,
        "adb_status": adb_status,
        "adb_device_count": len(devices),
    }




@app.get("/discover")
async def discover_all() -> dict[str, Any]:
    """Combined discovery snapshot: ADB devices + Connect + SSH + fixture label."""
    return discovery_overview()


@app.get("/discover/devices")
async def discover_devices() -> dict[str, Any]:
    """LAN/USB ADB device list for the Expo picker (`adb devices -l`)."""
    return list_adb_devices()


@app.get("/discover/connect")
async def discover_connect_get() -> dict[str, Any]:
    """comma Connect status (JWT configured? masked) — no shell docs required."""
    return connect_status()


@app.post("/discover/connect")
async def discover_connect_set(body: ConnectJwtRequest) -> dict[str, Any]:
    """Set/use Connect JWT (process env + optional .cache/connect_jwt; not committed)."""
    try:
        return set_connect_jwt(body.jwt, persist=body.persist)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/discover/ssh")
async def discover_ssh_get() -> dict[str, Any]:
    """SSH status (host/user/port/identity path) — no key bytes, no shell docs."""
    return ssh_status()


@app.post("/discover/ssh")
async def discover_ssh_set(body: SshConfigRequest) -> dict[str, Any]:
    """Set SSH host/user/port (+ optional identity path) → env + .cache/ssh_config.json."""
    try:
        status = set_ssh_config(
            body.host,
            user=body.user or "comma",
            port=body.port if body.port is not None else 22,
            identity_path=body.identity_path,
            persist=body.persist,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if body.test:
        probe = probe_ssh(timeout=5.0)
        return {**status, "probe": probe}
    return status


@app.post("/discover/ssh/test")
async def discover_ssh_test() -> dict[str, Any]:
    """Short non-interactive SSH probe; honest fail (~5s timeout)."""
    return probe_ssh(timeout=5.0)



@app.get("/teachers")
async def get_teachers(
    force_fixture: bool = Query(False),
) -> dict[str, Any]:
    """List commaai/openpilot@master teachers; default selected = big_driving_supercombo.

    Live label: ``comma master · big_driving_supercombo``. Offline → fixture labeled.
    Never silently selects driving_supercombo.
    """
    from distillery_teacher.download import BIG_TEACHER_NAME, cached_big_teacher_ok

    teachers = list_comma_master_teachers(force_fixture=force_fixture)
    selected = select_comma_master_teacher(force_fixture=force_fixture)
    cached = None if force_fixture else cached_big_teacher_ok()
    artifact = cached.as_dict() if cached is not None else None
    if selected is not None and artifact and artifact.get("live"):
        selected = dict(selected)
        selected["label"] = artifact.get("label") or f"comma master · {BIG_TEACHER_NAME}"
        selected["artifact_path"] = artifact.get("path")
        selected["sha256"] = artifact.get("sha256")
        selected["live"] = True
        selected["source"] = artifact.get("source")
    label = (selected or {}).get("label")
    if not label and selected:
        label = (
            f"comma master · {selected.get('name')}"
            if selected.get("live")
            else f"fixture · {selected.get('name')}"
        )
    return {
        "teachers": teachers,
        "selected": selected,
        "count": len(teachers),
        "source": (selected or {}).get("source")
        or ("fixture" if force_fixture else "commaai/openpilot@master"),
        "label": label or f"fixture · {BIG_TEACHER_NAME}",
        "teacher_artifact": artifact,
        "default_teacher": BIG_TEACHER_NAME,
    }


@app.post("/teachers/pull")
async def pull_teachers(
    background_tasks: BackgroundTasks,
    body: TeacherPullRequest | None = None,
) -> dict[str, Any]:
    """Pull **big_driving_supercombo only** into ``artifacts/teachers/``.

    Creates a ``teacher_pull`` job; progress streams on ``/ws/jobs/{id}``
    (same bus as other jobs). Idempotent: skips re-download when cache
    checksum is OK. Offline / failure → labeled fixture for the **big**
    teacher (never small model, never pretend live).

    Start training / ``train_all`` still calls ``ensure_big_teacher_onnx``
    if the artifact is missing.
    """
    from distillery_teacher.download import BIG_TEACHER_NAME, cached_big_teacher_ok

    body = body or TeacherPullRequest()
    job_id = str(uuid4())
    rec = JobRecord(
        id=job_id,
        kind="teacher_pull",
        status="pending",
        created_at=_now(),
    )
    _jobs[job_id] = rec
    _subscribers[job_id] = []
    background_tasks.add_task(
        _run_teacher_pull_job,
        job_id,
        force_fixture=body.force_fixture,
        force_download=body.force_download,
    )
    cached = None if body.force_fixture else cached_big_teacher_ok()
    snapshot = cached.as_dict() if cached is not None else None
    label = (
        (snapshot or {}).get("label")
        if snapshot
        else (
            f"fixture · {BIG_TEACHER_NAME}"
            if body.force_fixture
            else f"pulling · {BIG_TEACHER_NAME}"
        )
    )
    return {
        **_summary(rec).model_dump(),
        "teacher": BIG_TEACHER_NAME,
        "default_teacher": BIG_TEACHER_NAME,
        "label": label,
        "live": bool(snapshot.get("live")) if snapshot else False,
        "cached": bool(snapshot.get("cached")) if snapshot else False,
        "ok": bool(snapshot.get("ok")) if snapshot else None,
        "teacher_artifact": snapshot,
        "ws": f"/ws/jobs/{job_id}",
        "events_url": f"/jobs/{job_id}/events",
    }


@app.get("/ready")
async def get_ready(
    teacher: str | None = Query(None),
    allow_toy: bool = Query(False),
    force_fixture: bool = Query(False),
) -> dict[str, Any]:
    """Structured train-all readiness gaps (mici/connect/hours/torch/teacher)."""
    # Enrich Graig gaps with mici/connect when discover is available
    report = check_train_readiness(
        teacher_name=teacher,
        allow_toy=allow_toy,
        force_fixture=force_fixture,
    )
    extra: list[dict[str, str]] = []
    try:
        adb = list_adb_devices()
        devices = adb.get("devices") or []
        online = [
            d for d in devices
            if str(d.get("state") or d.get("status") or "").lower() == "device"
        ]
        ssh = ssh_status() if "ssh_status" in dir() else None
        try:
            from distillery_ingest.discover import ssh_status as _ssh_status
            ssh = _ssh_status()
        except Exception:
            ssh = {"configured": False}
        mici_ok = bool(online) or bool(ssh.get("configured") or ssh.get("available") or ssh.get("host"))
        if not mici_ok and not (allow_toy or force_fixture):
            extra.append(
                {
                    "code": "mici_not_found",
                    "message": "No ADB mici device and no SSH host — connect mici on LAN/USB",
                }
            )
        conn = connect_status()
        if not (conn.get("configured") or conn.get("available")) and not (allow_toy or force_fixture):
            extra.append(
                {
                    "code": "connect_not_configured",
                    "message": "Connect JWT not configured — POST /discover/connect or use fixture",
                }
            )
        dongle = dongle_status()
        if not dongle.get("configured") and not (allow_toy or force_fixture):
            extra.append(
                {
                    "code": "dongle_id_required",
                    "message": "Dongle ID required — POST /dongle (GUI Save) then refresh",
                }
            )
    except Exception as exc:  # noqa: BLE001
        extra.append({"code": "discover_error", "message": str(exc)[:200]})

    gaps = list(report.get("gaps") or []) + extra
    ok = len(gaps) == 0
    return {
        "ok": ok,
        "ready": ok,
        "gaps": gaps,
        "hours": report.get("hours"),
        "hours_gate": report.get("hours_gate"),
        "device": report.get("device"),
        "teacher": report.get("teacher"),
        "min_train_hours": report.get("min_train_hours"),
        "allow_toy": report.get("allow_toy"),
        "force_fixture": force_fixture,
        "probe": probe_train_device(force_fixture=force_fixture),
        "live": False,
        "licensed": False,
    }


@app.get("/jobs/train_all/ready")
async def get_train_all_ready(
    teacher: str | None = Query(None),
    allow_toy: bool = Query(False),
    force_fixture: bool = Query(False),
) -> dict[str, Any]:
    """Alias of GET /ready for Expo Start-training binding."""
    return await get_ready(teacher=teacher, allow_toy=allow_toy, force_fixture=force_fixture)


@app.post("/jobs/train_all", response_model=JobSummary)
async def start_train_all(
    background_tasks: BackgroundTasks,
    body: TrainAllRequest | None = None,
) -> JobSummary:
    """One-click ingest→…→eval. 409 with gaps if not ready. Never auto-flashes."""
    body = body or TrainAllRequest()
    force_fixture = body.force_fixture or body.source == "fixture"
    report = await get_ready(
        teacher=body.teacher,
        allow_toy=body.allow_toy,
        force_fixture=force_fixture,
    )
    if not report.get("ok"):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "train_all not ready",
                "gaps": report.get("gaps") or [],
                "ready": False,
            },
        )
    job_id = str(uuid4())
    rec = JobRecord(
        id=job_id,
        kind="train_all",
        status="pending",
        created_at=_now(),
        route_id=body.route_id,
    )
    _jobs[job_id] = rec
    _subscribers[job_id] = []
    background_tasks.add_task(
        _run_train_all_job,
        job_id,
        route_id=body.route_id,
        prefer=body.source,
    )
    return _summary(rec)


@app.get("/routes")
async def get_routes(
    source: Literal["auto", "connect", "ssh", "fixture"] = Query("auto"),
    limit: int = Query(20, ge=1, le=100),
    scope: Literal["mine", "public"] | None = Query(
        None,
        description="connect scope: mine (dongle) or public (shared/public drives via /v1/me/devices)",
    ),
    device: str | None = Query(
        None,
        description="Discovered ADB device id (serial or host:port); may set SSH host",
    ),
    ssh_host: str | None = Query(
        None,
        description="Override MICI_SSH_HOST for this listing (from discovery picker)",
    ),
) -> dict[str, Any]:
    """List mici routes for the configured dongle (Connect / SSH / fixture).

    After discovery, pass `device` and/or `ssh_host` (+ `source`) so the picker
    does not require shell env archaeology.

    Explicit source=ssh|connect never silently swaps to fixture when empty/error —
    response stays source=ssh|connect with routes=[] and message/empty_reason.

    scope=public (+ source=connect|auto): shared/public Connect drives — JWT only,
    no local dongle, never queries demo id 3e2de7ed….
    """
    cfg = apply_discovered_overrides(
        load_ingest_config(),
        ssh_host=ssh_host,
        device_id=device,
    )
    result = ingest_list_routes(cfg, prefer=source, limit=limit, scope=scope)
    src, routes = result
    effective_scope = scope
    if effective_scope is None and source in ("connect", "auto"):
        if any((r.meta or {}).get("scope") in ("public", "shared") for r in routes):
            effective_scope = "public"
        else:
            effective_scope = "mine"
    out: dict[str, Any] = {
        "dongle_id": cfg.dongle_id or None,
        "source": src.name,
        "scope": effective_scope,
        "device": device,
        "ssh_host": cfg.ssh_host,
        "routes": [r.summary_dict() for r in routes],
    }
    if getattr(result, "message", None):
        out["message"] = result.message
    if getattr(result, "empty_reason", None):
        out["empty_reason"] = result.empty_reason
    if getattr(result, "error", None):
        out["error"] = result.error
    return out


@app.get("/routes/{route_id:path}")
async def get_route_detail(
    route_id: str,
    source: Literal["auto", "connect", "ssh", "fixture"] = Query("auto"),
) -> dict[str, Any]:
    from distillery_ingest.resolve import get_route as ingest_get_route

    cfg = load_ingest_config()
    try:
        src, route = ingest_get_route(route_id, cfg, prefer=source)
    except Exception as exc:  # noqa: BLE001 — explicit live sources must not 500 as fixture
        if source in ("ssh", "connect"):
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise
    return {"source": src.name, "route": route.model_dump(mode="json")}


@app.post("/jobs/demo", response_model=JobSummary)
async def start_demo(background_tasks: BackgroundTasks) -> JobSummary:
    job_id = str(uuid4())
    rec = JobRecord(id=job_id, kind="demo", status="pending", created_at=_now())
    _jobs[job_id] = rec
    _flash_events[job_id] = asyncio.Event()
    _subscribers[job_id] = []
    background_tasks.add_task(_run_demo_job, job_id)
    return _summary(rec)


@app.post("/jobs/ingest", response_model=JobSummary)
async def start_ingest(
    background_tasks: BackgroundTasks,
    body: IngestJobRequest | None = None,
) -> JobSummary:
    """Start an ingest-only job; events stream on existing /ws/jobs/{id}."""
    body = body or IngestJobRequest()
    job_id = str(uuid4())
    rec = JobRecord(
        id=job_id,
        kind="ingest",
        status="pending",
        created_at=_now(),
        route_id=body.route_id,
    )
    _jobs[job_id] = rec
    _subscribers[job_id] = []
    background_tasks.add_task(
        _run_ingest_job,
        job_id,
        route_id=body.route_id,
        prefer=body.source,
    )
    return _summary(rec)



@app.post("/jobs/shard", response_model=JobSummary)
async def start_shard(
    background_tasks: BackgroundTasks,
    body: ShardJobRequest | None = None,
) -> JobSummary:
    """Start a shard-pack job; events stream on existing /ws/jobs/{id}."""
    body = body or ShardJobRequest()
    job_id = str(uuid4())
    rec = JobRecord(
        id=job_id,
        kind="shard",
        status="pending",
        created_at=_now(),
        route_id=body.route_id,
    )
    _jobs[job_id] = rec
    _subscribers[job_id] = []
    background_tasks.add_task(
        _run_shard_job,
        job_id,
        route_id=body.route_id,
        prefer=body.source,
    )
    return _summary(rec)


@app.post("/jobs/teach", response_model=JobSummary)
async def start_teach(
    background_tasks: BackgroundTasks,
    body: TeachJobRequest | None = None,
) -> JobSummary:
    """Start teach job (Graig teacher or labeled fixture). Events on /ws/jobs/{id}."""
    body = body or TeachJobRequest()
    job_id = str(uuid4())
    rec = JobRecord(
        id=job_id,
        kind="teach",
        status="pending",
        created_at=_now(),
        route_id=body.route_id,
    )
    _jobs[job_id] = rec
    _subscribers[job_id] = []
    background_tasks.add_task(
        _run_teach_job,
        job_id,
        route_id=body.route_id,
        prefer=body.source,
    )
    return _summary(rec)


@app.post("/jobs/train", response_model=JobSummary)
async def start_train(
    background_tasks: BackgroundTasks,
    body: TrainJobRequest | None = None,
) -> JobSummary:
    """Start train job (Graig student or labeled fixture). Events on /ws/jobs/{id}."""
    body = body or TrainJobRequest()
    job_id = str(uuid4())
    rec = JobRecord(
        id=job_id,
        kind="train",
        status="pending",
        created_at=_now(),
        route_id=body.route_id,
    )
    _jobs[job_id] = rec
    _subscribers[job_id] = []
    background_tasks.add_task(
        _run_train_job,
        job_id,
        route_id=body.route_id,
        prefer=body.source,
    )
    return _summary(rec)


@app.post("/jobs/export", response_model=JobSummary)
async def start_export(
    background_tasks: BackgroundTasks,
    body: ExportJobRequest | None = None,
) -> JobSummary:
    """Export mici-fit ONNX student (Graig export or labeled fixture)."""
    body = body or ExportJobRequest()
    job_id = str(uuid4())
    rec = JobRecord(
        id=job_id,
        kind="export",
        status="pending",
        created_at=_now(),
        route_id=body.route_id,
    )
    _jobs[job_id] = rec
    _subscribers[job_id] = []
    background_tasks.add_task(
        _run_export_job,
        job_id,
        route_id=body.route_id,
        checkpoint_path=body.checkpoint_path,
    )
    return _summary(rec)


@app.post("/jobs/eval", response_model=JobSummary)
async def start_eval(
    background_tasks: BackgroundTasks,
    body: EvalJobRequest | None = None,
) -> JobSummary:
    """Offline scorecard; sets job.eval_passed for flash gate."""
    body = body or EvalJobRequest()
    job_id = str(uuid4())
    rec = JobRecord(
        id=job_id,
        kind="eval",
        status="pending",
        created_at=_now(),
        route_id=body.route_id,
        onnx_path=body.onnx_path,
    )
    _jobs[job_id] = rec
    _subscribers[job_id] = []
    background_tasks.add_task(
        _run_eval_job,
        job_id,
        route_id=body.route_id,
        onnx_path=body.onnx_path,
        force_fail=body.force_fail,
        force_pass=body.force_pass,
    )
    return _summary(rec)


@app.post("/jobs/pipeline", response_model=JobSummary)
async def start_pipeline(
    background_tasks: BackgroundTasks,
    body: PipelineJobRequest | None = None,
) -> JobSummary:
    """Sequential teach→train→export→eval→gated flash for Expo simple-user path."""
    body = body or PipelineJobRequest()
    job_id = str(uuid4())
    rec = JobRecord(
        id=job_id,
        kind="pipeline",
        status="pending",
        created_at=_now(),
        route_id=body.route_id,
    )
    _jobs[job_id] = rec
    _subscribers[job_id] = []
    _flash_events[job_id] = asyncio.Event()
    background_tasks.add_task(
        _run_pipeline_job,
        job_id,
        route_id=body.route_id,
        prefer=body.source,
        include_flash=body.include_flash,
    )
    return _summary(rec)


@app.get("/jobs/{job_id}", response_model=JobSummary)
async def get_job(job_id: str) -> JobSummary:
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return _summary(job)


@app.get("/jobs/{job_id}/events")
async def get_events(job_id: str) -> dict[str, Any]:
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return {
        "job_id": job_id,
        "events": job.events,
        "eval_passed": job.eval_passed,
        "onnx_path": job.onnx_path,
        "flash_confirmed": job.flash_confirmed,
        "flash_done": job.flash_done,
        "device_write": job.device_write,
    }


class FlashConfirm(BaseModel):
    confirm: bool = True


@app.post("/jobs/{job_id}/flash/confirm")
async def confirm_flash(job_id: str, body: FlashConfirm) -> dict[str, Any]:
    """Explicit confirm only. Rejected unless this job reported eval_passed.

    After gates: run distillery_deploy SSH push of driving_supercombo.onnx.
    device_write=True only on real successful scp — never pretend.
    """
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    if not body.confirm:
        return {"ok": False, "message": "confirm=false ignored"}
    if not job.eval_passed:
        raise HTTPException(
            status_code=403,
            detail={
                "ok": False,
                "blocked": True,
                "reason": "eval_gate",
                "message": "Flash confirm rejected — eval has not passed for this job",
                "eval_passed": False,
            },
        )
    job.flash_confirmed = True
    ev = _flash_events.setdefault(job_id, asyncio.Event())
    ev.set()

    async def emit(event: dict[str, Any]) -> None:
        await _broadcast(job_id, event)

    result = await _call_stage(
        resolve_flash(),
        job_id,
        emit,
        confirmed=True,
        eval_passed=True,
        onnx_path=job.onnx_path,
        tick=0.0,
    )
    device_write = False
    live = False
    detail = ""
    remote_path = None
    if isinstance(result, dict):
        device_write = bool(result.get("device_write"))
        live = bool(result.get("live"))
        detail = str(result.get("detail") or result.get("reason") or "")
        remote_path = result.get("remote_path")
    job.device_write = device_write
    job.flash_done = True
    if job.status not in ("failed",):
        job.status = "done"

    return {
        "ok": True,
        "job_id": job_id,
        "flash_confirmed": True,
        "eval_passed": True,
        "device_write": device_write,
        "live": live,
        "remote_path": remote_path,
        "detail": detail,
        "note": (
            "Device write succeeded via SSH"
            if device_write
            else "Confirm accepted; no device write (SSH missing, scp failed, or artifact absent) — live=false"
        ),
    }


@app.websocket("/ws/jobs/{job_id}")
async def ws_jobs(websocket: WebSocket, job_id: str) -> None:
    await websocket.accept()
    job = _jobs.get(job_id)
    if not job:
        await websocket.send_json({"error": "job not found"})
        await websocket.close()
        return

    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    _subscribers.setdefault(job_id, []).append(q)

    # Replay existing events
    for ev in job.events:
        await websocket.send_json(ev)

    try:
        while True:
            # Multiplex: wait for new event OR client message (flash confirm)
            get_ev = asyncio.create_task(q.get())
            get_msg = asyncio.create_task(websocket.receive_json())
            done, pending = await asyncio.wait(
                {get_ev, get_msg},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
            if get_ev in done and not get_ev.cancelled():
                try:
                    event = get_ev.result()
                    await websocket.send_json(event)
                except Exception:  # noqa: BLE001
                    break
            if get_msg in done and not get_msg.cancelled():
                try:
                    msg = get_msg.result()
                    if isinstance(msg, dict) and msg.get("type") == "flash_confirm":
                        if not job.eval_passed:
                            await websocket.send_json(
                                {
                                    "id": str(uuid4()),
                                    "ts": _now(),
                                    "job_id": job_id,
                                    "kind": "log",
                                    "stage": "flash",
                                    "payload": {
                                        "level": "warn",
                                        "message": "Flash confirm blocked — eval has not passed",
                                        "source": "flash",
                                    },
                                }
                            )
                        else:
                            job.flash_confirmed = True
                            _flash_events.setdefault(job_id, asyncio.Event()).set()
                            await websocket.send_json(
                                {
                                    "id": str(uuid4()),
                                    "ts": _now(),
                                    "job_id": job_id,
                                    "kind": "log",
                                    "stage": "flash",
                                    "payload": {
                                        "level": "info",
                                        "message": "Flash confirmed by operator",
                                        "source": "flash",
                                    },
                                }
                            )
                except WebSocketDisconnect:
                    break
                except Exception:  # noqa: BLE001
                    # ignore malformed client messages
                    pass
            # Exit when job done and queue drained
            if job.status in ("done", "failed") and q.empty():
                await asyncio.sleep(0.15)
                if q.empty():
                    break
    except WebSocketDisconnect:
        pass
    finally:
        subs = _subscribers.get(job_id, [])
        if q in subs:
            subs.remove(q)
