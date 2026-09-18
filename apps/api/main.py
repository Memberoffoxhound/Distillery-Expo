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
from distillery_ingest import load_ingest_config, run_ingest_pipeline
from distillery_ingest.resolve import list_routes as ingest_list_routes
from distillery_shards import run_shard_pipeline

app = FastAPI(
    title="Distillery Expo API",
    version="0.3.0",
    description="tinygrad distill control room — M2 shard pack + M1 mici ingest + M0 demo",
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
    route_id: str | None = None


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


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "distillery-expo"}


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
    return {"job_id": job_id, "events": job.events}


class FlashConfirm(BaseModel):
    confirm: bool = True


@app.post("/jobs/{job_id}/flash/confirm")
async def confirm_flash(job_id: str, body: FlashConfirm) -> dict[str, Any]:
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    if not body.confirm:
        return {"ok": False, "message": "confirm=false ignored"}
    job.flash_confirmed = True
    ev = _flash_events.setdefault(job_id, asyncio.Event())
    ev.set()
    return {"ok": True, "job_id": job_id, "flash_confirmed": True}


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
