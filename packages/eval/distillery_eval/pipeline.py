"""Eval stage runner — honest scorecard; eval_passed only if thresholds met."""

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
from distillery_eval.config import EvalConfig, load_eval_config
from distillery_eval.scorecard import compute_scorecard, write_scorecard

EmitFn = Callable[[dict[str, Any]], Awaitable[None]]


async def _emit(emit: EmitFn, event) -> None:
    await emit(event.to_json_dict())


async def run_eval_pipeline(
    job_id: str,
    emit: EmitFn,
    *,
    cfg: EvalConfig | None = None,
    tick: float = 0.12,
    write_files: bool = True,
) -> dict[str, Any]:
    """Replay scorecard with REAL numbers. Never greenwash eval_passed.

    Fixture/offline: live=false, and eval_passed=false unless measured metrics
    actually clear thresholds ("not licensed yet" when they don't).
    """
    cfg = cfg or load_eval_config()
    stage = StageName.eval

    async def log(msg: str, level: str = "info") -> None:
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.log,
                LogPayload(level=level, message=msg, source="eval"),  # type: ignore[arg-type]
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

    await stage_status("running", "Offline scorecard (honest numbers)")
    await log("Computing replay metrics against teacher soft labels…")
    await progress(0.1, "load soft labels + student")
    await asyncio.sleep(tick)

    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.decision,
            DecisionPayload(
                title="Flash gate thresholds",
                rationale=(
                    f"Require teacher agreement ≥ {cfg.min_teacher_agreement} and "
                    f"lateral MAE ≤ {cfg.max_lateral_mae} before enabling flash confirm. "
                    "No teenagers with driver’s permits — fixture must not fake a pass."
                ),
                options_considered=["strict (≥0.95)", "standard (≥0.92)", "lenient (≥0.85)"],
                chosen=f"standard (≥{cfg.min_teacher_agreement})",
                confidence=0.88,
            ),
            stage=stage,
        ),
    )

    scorecard = await asyncio.to_thread(compute_scorecard, cfg)
    await progress(0.5, "score metrics")

    for name, val in scorecard["metrics"].items():
        if name.startswith("n_"):
            continue
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.metric,
                MetricPayload(name=name, value=float(val), series="eval"),
                stage=stage,
            ),
        )
        await asyncio.sleep(tick * 0.25)

    # Critical: emit eval_passed as a metric Craig can gate on (1.0 / 0.0)
    passed = bool(scorecard["eval_passed"])
    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.metric,
            MetricPayload(
                name="eval_passed",
                value=1.0 if passed else 0.0,
                unit="bool",
                series="eval",
            ),
            stage=stage,
        ),
    )
    # Also a decision payload with eval_passed in rationale/chosen for bus readers
    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.decision,
            DecisionPayload(
                title="Eval gate",
                rationale=(
                    f"eval_passed={passed} live={scorecard['live']} "
                    f"source={scorecard['source']} — {scorecard['license_note']}. "
                    f"gates={scorecard['gates']}"
                ),
                options_considered=["pass", "fail"],
                chosen="pass" if passed else "fail",
                confidence=1.0 if passed else 0.0,
            ),
            stage=stage,
        ),
    )

    if not passed:
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.warning,
                WarningPayload(
                    code="EVAL_NOT_LICENSED",
                    message=(
                        "Eval FAIL — not licensed for flash "
                        f"(live={scorecard['live']} source={scorecard['source']}). "
                        "Honest fail beats a pretty fake pass."
                    ),
                    recoverable=True,
                ),
                stage=stage,
            ),
        )
        await log(
            f"Eval FAIL — eval_passed=false · live={scorecard['live']} "
            f"· {scorecard['license_note']}",
            level="warn",
        )
    else:
        await log(
            f"Eval PASS — eval_passed=true · live={scorecard['live']} "
            f"· thresholds cleared on measured numbers"
        )

    if write_files:
        path = await asyncio.to_thread(write_scorecard, cfg.output_dir, scorecard)
        await log(f"Scorecard → {path}")

    await progress(1.0, "scorecard ready")
    detail = (
        f"eval_passed={passed} · live={scorecard['live']} · source={scorecard['source']}"
    )
    await stage_status("done", detail)

    # Return shape Craig can store on JobRecord
    return {
        "eval_passed": passed,
        "live": scorecard["live"],
        "source": scorecard["source"],
        "metrics": scorecard["metrics"],
        "gates": scorecard["gates"],
        "thresholds": scorecard["thresholds"],
        "license_note": scorecard["license_note"],
        "scorecard": scorecard,
    }
