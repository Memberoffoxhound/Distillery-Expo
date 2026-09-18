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
    backend_status,
    coerce_eval_passed,
    resolve_eval,
    resolve_export,
    resolve_flash,
    resolve_teach,
    resolve_train,
)
from distillery_ingest import load_ingest_config, run_ingest_pipeline
from distillery_ingest.resolve import list_routes as ingest_list_routes
from distillery_shards import run_shard_pipeline

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
    version="0.4.0",
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


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "distillery-expo",
        "ml_backends": backend_status(),
    }


@app.get("/stages")
async def list_stages() -> dict[str, list[str]]:
    return {"stages": [s.value for s in STAGES]}


@app.get("/dongle")
async def get_dongle() -> dict[str, Any]:
    cfg = load_ingest_config()
    return {
        "dongle_id": cfg.dongle_id,
        "cams": list(cfg.cams),
        "connect_available": cfg.connect_available,
        "ssh_available": cfg.ssh_available,
        "force_fixture": cfg.force_fixture,
    }


@app.get("/routes")
async def get_routes(
    source: Literal["auto", "connect", "ssh", "fixture"] = Query("auto"),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """List mici routes for the configured dongle (Connect / SSH / fixture)."""
    cfg = load_ingest_config()
    src, routes = ingest_list_routes(cfg, prefer=source, limit=limit)
    return {
        "dongle_id": cfg.dongle_id,
        "source": src.name,
        "routes": [r.summary_dict() for r in routes],
    }


@app.get("/routes/{route_id:path}")
async def get_route_detail(
    route_id: str,
    source: Literal["auto", "connect", "ssh", "fixture"] = Query("auto"),
) -> dict[str, Any]:
    from distillery_ingest.resolve import get_route as ingest_get_route

    cfg = load_ingest_config()
    src, route = ingest_get_route(route_id, cfg, prefer=source)
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
