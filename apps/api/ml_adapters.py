"""Resolve Graig ML stage runners; temporary fixture fallbacks until packages land.

Public entrypoints (Graig-owned packages):
  from distillery_teacher import run_teach_pipeline
  from distillery_student import run_train_pipeline
  from distillery_export import run_export_pipeline
  from distillery_eval import run_eval_pipeline

Fallback stubs live HERE (apps/api) only — never claim live GPU/device.
Fixture events carry live=false / meta.fixture=true.
"""

from __future__ import annotations

import asyncio
import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

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

EmitFn = Callable[[dict[str, Any]], Awaitable[None]]

_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class EvalResult:
    """Minimal shape Phil's flash gate reads; Graig's real result should expose eval_passed."""

    eval_passed: bool
    scores: dict[str, float] = field(default_factory=dict)
    fixture: bool = True
    detail: str = ""


@dataclass
class TeachResult:
    soft_label_count: int = 0
    fixture: bool = True
    live: bool = False
    artifact_dir: Optional[str] = None


@dataclass
class TrainResult:
    final_loss: float = 0.0
    steps: int = 0
    fixture: bool = True
    live: bool = False
    checkpoint_path: Optional[str] = None


@dataclass
class ExportResult:
    onnx_path: str = ""
    fixture: bool = True
    live: bool = False
    io_contract: str = "stock-modelV2"


def _try_runner(module_name: str, attr: str):
    try:
        mod = importlib.import_module(module_name)
        fn = getattr(mod, attr, None)
        if callable(fn):
            return fn
    except Exception:  # noqa: BLE001 — packages may not be installed yet
        return None
    return None


async def _emit(emit: EmitFn, event) -> None:
    await emit(event.to_json_dict())


# ---------------------------------------------------------------------------
# Fixture fallbacks (API-local; clearly non-live)
# ---------------------------------------------------------------------------


async def _fixture_teach(
    job_id: str,
    emit: EmitFn,
    *,
    tick: float = 0.08,
    **_kwargs: Any,
) -> TeachResult:
    stage = StageName.teach
    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.stage,
            StagePayload(
                name=stage,
                status="running",
                detail="Fixture soft-labels (no live 7090 XT)",
            ),
            stage=stage,
        ),
    )
    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.warning,
            WarningPayload(
                code="FIXTURE_TEACHER",
                message="Teacher running fixture path — live=false (7090 XT / Cinque not attached)",
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
                title="Teacher backend",
                rationale=(
                    "Cinque/supercombo on RX 7090 XT is the live path (Graig). "
                    "This job uses a labeled fixture soft-label scaffold — not a live GPU claim."
                ),
                options_considered=[
                    "Cinque/supercombo@7090XT (live)",
                    "Chestnut (blocked)",
                    "fixture soft-labels (offline)",
                ],
                chosen="fixture soft-labels (offline)",
                confidence=0.7,
            ),
            stage=stage,
        ),
    )
    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.log,
            LogPayload(
                level="info",
                message="fixture teach: emitting placeholder soft-labels [live=false]",
                source="teach",
            ),
            stage=stage,
        ),
    )
    out_dir = _REPO_ROOT / "artifacts" / "soft_labels"
    out_dir.mkdir(parents=True, exist_ok=True)
    n_batches = 6
    soft_n = 0
    for i in range(1, n_batches + 1):
        soft_n += 512
        # Placeholder fps — not a live GPU measurement
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.metric,
                MetricPayload(
                    name="teacher_fps",
                    value=0.0,
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
                    value=float(soft_n),
                    unit="samples",
                    series="soft_labels",
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
                    name="soft_label_agreement",
                    value=round(0.82 + 0.02 * i / n_batches, 4),
                    series="soft_label_agreement",
                ),
                stage=stage,
            ),
        )
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.progress,
                ProgressPayload(fraction=i / n_batches, detail=f"soft-labels batch {i}/{n_batches}"),
                stage=stage,
            ),
        )
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.sample,
                SamplePayload(
                    cam="road",
                    label=f"soft-label batch {i} [fixture]",
                    placeholder=True,
                    meta={
                        "fixture": True,
                        "live": False,
                        "label": "fixture",
                        "batch": i,
                        "teacher": "Cinque/supercombo",
                        "device": "fixture (not 7090 XT)",
                    },
                ),
                stage=stage,
            ),
        )
        await asyncio.sleep(tick)

    marker = out_dir / "fixture_soft_labels.json"
    marker.write_text(
        '{"kind":"fixture","live":false,"soft_labels":%d,"note":"placeholder for Graig live path"}\n'
        % soft_n,
        encoding="utf-8",
    )
    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.log,
            LogPayload(
                level="info",
                message=f"Teacher fixture complete — soft_labels={soft_n} path={marker} [live=false]",
                source="teach",
            ),
            stage=stage,
        ),
    )
    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.stage,
            StagePayload(
                name=stage,
                status="done",
                detail=f"{soft_n} soft-labels · fixture · live=false",
            ),
            stage=stage,
        ),
    )
    return TeachResult(
        soft_label_count=soft_n,
        fixture=True,
        live=False,
        artifact_dir=str(marker),
    )


async def _fixture_train(
    job_id: str,
    emit: EmitFn,
    *,
    tick: float = 0.08,
    **_kwargs: Any,
) -> TrainResult:
    stage = StageName.train
    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.stage,
            StagePayload(
                name=stage,
                status="running",
                detail="Fixture distill → stock-modelV2 I/O (no live tinygrad)",
            ),
            stage=stage,
        ),
    )
    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.warning,
            WarningPayload(
                code="FIXTURE_STUDENT",
                message="Student train running fixture path — live=false (tinygrad / GPU not attached)",
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
                    "Keep stock modelV2 cam/control I/O so the ONNX student flashes to mici/QCOM. "
                    "This run is a labeled fixture loss curve — Graig owns the real tinygrad loop."
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
    loss = 1.85
    steps = 10
    ckpt_dir = _REPO_ROOT / "artifacts" / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    for step in range(1, steps + 1):
        loss *= 0.88
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.metric,
                MetricPayload(name="train_loss", value=round(loss, 4), series="train_loss"),
                stage=stage,
            ),
        )
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.metric,
                MetricPayload(name="lr", value=3e-4 * (0.95**step), series="lr"),
                stage=stage,
            ),
        )
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.progress,
                ProgressPayload(fraction=step / steps, detail=f"step {step * 50}/{steps * 50}"),
                stage=stage,
            ),
        )
        await asyncio.sleep(tick)

    ckpt = ckpt_dir / "student_modelV2_fixture.pt"
    ckpt.write_text(
        '{"kind":"fixture","live":false,"io":"stock-modelV2","final_loss":%s}\n' % round(loss, 4),
        encoding="utf-8",
    )
    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.log,
            LogPayload(
                level="info",
                message=f"Train fixture done — loss={loss:.4f} ckpt={ckpt} [live=false]",
                source="train",
            ),
            stage=stage,
        ),
    )
    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.stage,
            StagePayload(
                name=stage,
                status="done",
                detail=f"loss={loss:.4f} · fixture · live=false",
            ),
            stage=stage,
        ),
    )
    return TrainResult(
        final_loss=round(loss, 4),
        steps=steps,
        fixture=True,
        live=False,
        checkpoint_path=str(ckpt),
    )


async def _fixture_export(
    job_id: str,
    emit: EmitFn,
    *,
    tick: float = 0.08,
    **_kwargs: Any,
) -> ExportResult:
    stage = StageName.export
    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.stage,
            StagePayload(
                name=stage,
                status="running",
                detail="Fixture ONNX export (stock-modelV2 I/O)",
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
                title="Export format",
                rationale="ONNX with modelV2 I/O nodes — mici-fit student artifact.",
                options_considered=["ONNX", "raw tinygrad", "TorchScript"],
                chosen="ONNX",
                confidence=0.9,
            ),
            stage=stage,
        ),
    )
    onnx_dir = _REPO_ROOT / "artifacts" / "export"
    onnx_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = onnx_dir / "driving_supercombo.onnx"
    for i, detail in enumerate(["trace graph", "fold BN", "validate I/O", "write artifact"], 1):
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.progress,
                ProgressPayload(fraction=i / 4, detail=detail),
                stage=stage,
            ),
        )
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.log,
                LogPayload(level="info", message=f"export: {detail} [fixture]", source="export"),
                stage=stage,
            ),
        )
        await asyncio.sleep(tick)

    # Placeholder ONNX bytes — clearly labeled, not a real graph
    onnx_path.write_bytes(
        b"FIXTURE_ONNX_PLACEHOLDER live=false io=stock-modelV2 note=Graig owns real export\n"
    )
    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.metric,
            MetricPayload(name="onnx_bytes", value=float(onnx_path.stat().st_size), unit="bytes"),
            stage=stage,
        ),
    )
    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.log,
            LogPayload(
                level="info",
                message=f"Wrote {onnx_path} [fixture · live=false · stock-modelV2 I/O]",
                source="export",
            ),
            stage=stage,
        ),
    )
    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.stage,
            StagePayload(
                name=stage,
                status="done",
                detail=f"{onnx_path} · fixture",
            ),
            stage=stage,
        ),
    )
    return ExportResult(onnx_path=str(onnx_path), fixture=True, live=False)


async def _fixture_eval(
    job_id: str,
    emit: EmitFn,
    *,
    tick: float = 0.08,
    force_pass: bool = False,
    force_fail: bool = False,
    **_kwargs: Any,
) -> EvalResult:
    """Emit real scorecard numbers. Default = honest FAIL (stub not licensed to unlock flash).

    Phil/Bruce lock: never greenwash empty pass. Fixture/stub student stays
    eval_passed=False unless force_pass (tests only).
    """
    stage = StageName.eval
    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.stage,
            StagePayload(
                name=stage,
                status="running",
                detail="Fixture offline scorecard (stub — not licensed)",
            ),
            stage=stage,
        ),
    )
    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.warning,
            WarningPayload(
                code="FIXTURE_EVAL_NOT_LICENSED",
                message=(
                    "Eval fixture emits real scorecard numbers with live=false. "
                    "Default outcome is FAIL — stub student is not licensed to unlock flash."
                ),
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
                title="Flash gate thresholds",
                rationale=(
                    "Require teacher agreement ≥ 0.92 and lateral MAE ≤ 0.08. "
                    "API fixture defaults to honest fail (no teenagers with permits)."
                ),
                options_considered=["strict (≥0.95)", "standard (≥0.92)", "lenient (≥0.85)"],
                chosen="standard (≥0.92)",
                confidence=0.88,
            ),
            stage=stage,
        ),
    )
    # Real numbers always — never empty. Default = below gate (honest fail).
    if force_pass and not force_fail:
        scores = {
            "teacher_agreement": 0.941,
            "lateral_mae": 0.062,
            "longitudinal_mae": 0.079,
            "desire_top1": 0.903,
            "route_replay": 0.927,
        }
    else:
        scores = {
            "teacher_agreement": 0.71,
            "lateral_mae": 0.142,
            "longitudinal_mae": 0.168,
            "desire_top1": 0.64,
            "route_replay": 0.69,
        }
    for i, (name, val) in enumerate(scores.items(), 1):
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.metric,
                MetricPayload(name=name, value=val, series="eval"),
                stage=stage,
            ),
        )
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.progress,
                ProgressPayload(fraction=i / len(scores), detail=name),
                stage=stage,
            ),
        )
        await asyncio.sleep(tick * 0.5)

    gate_ok = scores["teacher_agreement"] >= 0.92 and scores["lateral_mae"] <= 0.08
    # Default False: stub/fixture is not licensed even if someone tampers scores upward
    passed = bool(force_pass and gate_ok and not force_fail)
    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.metric,
            MetricPayload(name="eval_pass", value=1.0 if passed else 0.0, series="eval"),
            stage=stage,
        ),
    )
    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.log,
            LogPayload(
                level="info" if passed else "warn",
                message=(
                    "Eval PASS — flash gate unlocked (awaiting confirm) [force_pass test]"
                    if passed
                    else "Eval FAIL — flash confirm stays blocked [fixture stub not licensed · live=false]"
                ),
                source="eval",
            ),
            stage=stage,
        ),
    )
    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.stage,
            StagePayload(
                name=stage,
                status="done",
                detail=("PASS" if passed else "FAIL") + " · fixture scorecard · live=false",
            ),
            stage=stage,
        ),
    )
    return EvalResult(
        eval_passed=passed,
        scores=scores,
        fixture=True,
        detail="fixture scorecard not-licensed" if not passed else "fixture force_pass",
    )


async def _fixture_flash(
    job_id: str,
    emit: EmitFn,
    *,
    confirmed: bool,
    tick: float = 0.08,
    **_kwargs: Any,
) -> dict[str, Any]:
    """UI-only / simulated flash — never writes to a real device."""
    stage = StageName.flash
    if not confirmed:
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.stage,
                StagePayload(name=stage, status="skipped", detail="Flash not confirmed"),
                stage=stage,
            ),
        )
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.log,
                LogPayload(
                    level="warn",
                    message="Flash skipped — no confirm; nothing written to device",
                    source="flash",
                ),
                stage=stage,
            ),
        )
        return {"flashed": False, "live": False, "device_write": False}

    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.stage,
            StagePayload(
                name=stage,
                status="running",
                detail="Simulated flash (UI-only — no device write)",
            ),
            stage=stage,
        ),
    )
    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.warning,
            WarningPayload(
                code="FIXTURE_FLASH",
                message="Flash is simulated — live=false; never auto-writes to mici",
                recoverable=True,
            ),
            stage=stage,
        ),
    )
    for i, step in enumerate(["verify artifact", "transfer (sim)", "qcom load (sim)", "reboot check (sim)"], 1):
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.progress,
                ProgressPayload(fraction=i / 4, detail=step),
                stage=stage,
            ),
        )
        await _emit(
            emit,
            make_event(
                job_id,
                EventKind.log,
                LogPayload(level="info", message=f"flash: {step} [live=false]", source="flash"),
                stage=stage,
            ),
        )
        await asyncio.sleep(tick)
    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.log,
            LogPayload(
                level="info",
                message="Flash complete (simulated) — no real device write [live=false]",
                source="flash",
            ),
            stage=stage,
        ),
    )
    await _emit(
        emit,
        make_event(
            job_id,
            EventKind.stage,
            StagePayload(name=stage, status="done", detail="simulated · live=false"),
            stage=stage,
        ),
    )
    return {"flashed": True, "live": False, "device_write": False, "fixture": True}


# ---------------------------------------------------------------------------
# Public resolvers — prefer Graig live packages; fixture adapters are last-resort only
# ---------------------------------------------------------------------------


def resolve_teach():
    return _try_runner("distillery_teacher", "run_teach_pipeline") or _fixture_teach


def resolve_train():
    return _try_runner("distillery_student", "run_train_pipeline") or _fixture_train


def resolve_export():
    return _try_runner("distillery_export", "run_export_pipeline") or _fixture_export


def resolve_eval():
    return _try_runner("distillery_eval", "run_eval_pipeline") or _fixture_eval


def resolve_flash():
    """Deploy flash: prefer distillery_deploy if Graig lands it; else API sim."""
    return _try_runner("distillery_deploy", "run_flash_pipeline") or _fixture_flash


def backend_status() -> dict[str, Any]:
    """Honest meta for /health or debugging — which paths are live vs fixture."""
    return {
        "teach": "graig" if _try_runner("distillery_teacher", "run_teach_pipeline") else "fixture",
        "train": "graig" if _try_runner("distillery_student", "run_train_pipeline") else "fixture",
        "export": "graig" if _try_runner("distillery_export", "run_export_pipeline") else "fixture",
        "eval": "graig" if _try_runner("distillery_eval", "run_eval_pipeline") else "fixture",
        "flash": "graig" if _try_runner("distillery_deploy", "run_flash_pipeline") else "fixture",
    }


def coerce_eval_passed(result: Any) -> bool:
    """Hard default False — only explicit True unlocks flash (no greenwash)."""
    if result is None:
        return False
    if isinstance(result, EvalResult):
        return result.eval_passed is True
    if isinstance(result, dict):
        return result.get("eval_passed", False) is True
    return getattr(result, "eval_passed", False) is True



def probe_tinygrad() -> dict[str, Any]:
    """Probe tinygrad Device — GPU or CPU; never 7090-locked.

    Returns keys consumed by /health and /status/runtime:
      tinygrad: "ok" | "missing" | "fixture"
      device: { found, ready, kind, name, backend }
      mode: "live" | "fixture"
    """
    device_blank: dict[str, Any] = {
        "found": False,
        "ready": False,
        "kind": None,
        "name": None,
        "backend": None,
    }
    try:
        import tinygrad  # noqa: F401
        from tinygrad import Device
    except Exception as exc:  # noqa: BLE001 — import OR init failures
        return {
            "tinygrad": "missing",
            "device": {**device_blank, "error": str(exc)[:200]},
            "mode": "fixture",
            "detail": "tinygrad not importable — fixture mode",
        }

    backend = None
    name = None
    kind: str | None = "unknown"
    ready = False
    found = False
    err: str | None = None

    try:
        backend = str(getattr(Device, "DEFAULT", None) or "CPU")
        found = True
        name = backend
        upper = backend.upper()
        if any(tok in upper for tok in ("CUDA", "GPU", "HIP", "METAL", "CL", "OPENCL", "AMD", "NV", "INTEL", "QCOM", "VULKAN")):
            # Exclude pure CPU tokens
            if upper in ("CPU", "LLVM", "DSP"):
                kind = "cpu"
            else:
                kind = "gpu"
        elif upper in ("CPU", "LLVM", "DSP") or upper.startswith("CPU"):
            kind = "cpu"
        else:
            kind = "unknown"

        # Touch the device to confirm readiness (best-effort; CPU always ok)
        try:
            # Device[backend] materializes; .renderer / stringification is enough signal
            _dev = Device[backend]
            ready = _dev is not None
            # Prefer a richer name when available
            name = str(getattr(_dev, "name", None) or backend)
        except Exception as exc:  # noqa: BLE001
            err = str(exc)[:200]
            # Still "found" if DEFAULT resolved; readiness false
            ready = False
            if kind == "cpu":
                # CPU backends are usually fine even if Device[] quirks
                ready = True
    except Exception as exc:  # noqa: BLE001
        err = str(exc)[:200]
        found = False
        ready = False

    device = {
        "found": found,
        "ready": ready,
        "kind": kind if found else None,
        "name": name,
        "backend": backend,
    }
    if err:
        device["error"] = err

    # Live when importable; fixture only when missing. CPU counts as live.
    mode = "live" if found else "fixture"
    tg = "ok" if found and ready else ("ok" if found else "missing")
    if found and not ready:
        tg = "ok"  # present but not ready — still not "missing"; UI can read device.ready
    return {
        "tinygrad": tg if found else "missing",
        "device": device,
        "mode": mode if found else "fixture",
        "detail": None,
    }


def _device_from_student_probe(raw: dict[str, Any]) -> dict[str, Any]:
    """Map Graig probe_train_device → /health device shape."""
    return {
        "found": bool(raw.get("device_found")),
        "ready": bool(raw.get("device_ready")),
        "kind": raw.get("device_kind"),
        "name": raw.get("device_name"),
        "backend": raw.get("device_name") or raw.get("backend"),
        "detail": raw.get("detail"),
        "live": raw.get("live"),
        "source": raw.get("source"),
    }


def runtime_status() -> dict[str, Any]:
    """Compose health/runtime payload — prefer Graig probe_train_device."""
    try:
        from distillery_student import probe_train_device

        raw = probe_train_device()
        tg = raw.get("tinygrad") or "missing"
        mode = "fixture" if tg in ("missing", "fixture") else "live"
        # CPU counts as live when tinygrad ok
        if tg == "ok":
            mode = "live"
        return {
            "ok": True,
            "tinygrad": tg,
            "device": _device_from_student_probe(raw),
            "mode": mode,
            "ml_backends": backend_status(),
            "detail": raw.get("detail"),
            "probe": "distillery_student.probe_train_device",
        }
    except Exception as exc:  # noqa: BLE001
        tg = probe_tinygrad()
        return {
            "ok": True,
            "tinygrad": tg["tinygrad"],
            "device": tg["device"],
            "mode": tg["mode"],
            "ml_backends": backend_status(),
            "detail": tg.get("detail") or f"student probe unavailable: {exc}"[:200],
            "probe": "local_thin",
        }
