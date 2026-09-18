"""Flash stage runner — SSH push gated by eval_passed + explicit confirm."""

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
from distillery_deploy.config import DeployConfig, load_deploy_config
from distillery_deploy.ssh_push import push_supercombo_ssh

EmitFn = Callable[[dict[str, Any]], Awaitable[None]]


async def _emit(emit: EmitFn, event) -> None:
    await emit(event.to_json_dict())


async def run_flash_pipeline(
    job_id: str,
    emit: EmitFn,
    *,
    confirmed: bool = False,
    eval_passed: bool = False,
    onnx_path: str | None = None,
    cfg: DeployConfig | None = None,
    tick: float = 0.06,
    scp_runner=None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Push driving_supercombo.onnx over SSH after eval_passed + confirm.

    Never auto-writes. device_write=True only on real successful scp.
    Missing SSH → honest skip with live=false (never pretend device write).
    """
    cfg = cfg or load_deploy_config()
    stage = StageName.flash

    async def log(msg: str, level: str = "info") -> None:
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.log,
                LogPayload(level=level, message=msg, source="flash"),  # type: ignore[arg-type]
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

    # Gate 1: eval must have passed
    if not eval_passed:
        await log(
            "Flash refused — eval_passed=false (no device write) [live=false]",
            level="warn",
        )
        await stage_status("skipped", "Blocked: eval_passed=false")
        return {
            "flashed": False,
            "live": False,
            "device_write": False,
            "skipped": True,
            "reason": "eval_gate",
        }

    # Gate 2: explicit confirm
    if not confirmed:
        await log(
            "Flash skipped — no explicit confirm; nothing written to device [live=false]",
            level="warn",
        )
        await stage_status("skipped", "Flash not confirmed")
        return {
            "flashed": False,
            "live": False,
            "device_write": False,
            "skipped": True,
            "reason": "not_confirmed",
        }

    await stage_status("running", "SSH flash driving_supercombo.onnx → mici")
    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.decision,
            DecisionPayload(
                title="Flash deploy",
                rationale=(
                    "Eval passed + operator confirm. Push drop-in "
                    "driving_supercombo.onnx over SSH to mici modeld path. "
                    "Never auto-write; never claim device_write without scp success."
                ),
                options_considered=[
                    "scp driving_supercombo.onnx",
                    "auto-flash (forbidden)",
                    "skip",
                ],
                chosen="scp driving_supercombo.onnx",
                confidence=1.0,
            ),
            stage=stage,
        ),
    )
    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.progress,
            ProgressPayload(fraction=0.2, detail="resolve local artifact"),
            stage=stage,
        ),
    )
    await asyncio.sleep(tick)

    push = await asyncio.to_thread(
        push_supercombo_ssh,
        onnx_path,
        cfg=cfg,
        scp_runner=scp_runner,
    )

    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.progress,
            ProgressPayload(
                fraction=1.0 if push.device_write else 0.6,
                detail=push.reason,
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
                name="device_write",
                value=1.0 if push.device_write else 0.0,
                unit="bool",
                series="flash",
            ),
            stage=stage,
        ),
    )

    if push.skipped and push.reason == "ssh_unavailable":
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.warning,
                WarningPayload(
                    code="SSH_UNAVAILABLE",
                    message=push.detail,
                    recoverable=True,
                ),
                stage=stage,
            ),
        )
        await log(push.detail, level="warn")
        await stage_status("skipped", "SSH unavailable · live=false · no device write")
        return push.as_dict()

    if not push.ok:
        await log(
            f"Flash failed — {push.detail} [live=false · device_write=false]",
            level="error",
        )
        await stage_status("failed", push.detail or push.reason)
        return push.as_dict()

    await log(
        f"Flash OK — wrote {push.remote_path} on {push.remote_host} "
        f"from {push.local_path} [live=true · device_write=true]",
        level="info",
    )
    await stage_status("done", f"device_write=true · {push.remote_path}")
    return push.as_dict()
