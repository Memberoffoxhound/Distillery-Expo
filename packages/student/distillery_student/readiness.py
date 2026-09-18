"""Train-all readiness gaps for Craig's one-click path.

Structured ``check_train_readiness(...) -> {ok, gaps:[{code,message}]}``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from distillery_student.config import StudentConfig, load_student_config
from distillery_student.device import probe_train_device
from distillery_student.hours import (
    DEFAULT_MIN_TRAIN_HOURS,
    estimate_driving_hours,
    hours_meet_floor,
    toy_train_allowed,
)
from distillery_student.train_loop import load_soft_label_summary


def check_train_readiness(
    *,
    cfg: StudentConfig | None = None,
    soft_labels_dir: Path | str | None = None,
    shards_dir: Path | str | None = None,
    force_fixture: bool | None = None,
    allow_toy: bool | None = None,
    teacher_name: str | None = None,
    min_hours: float | None = None,
) -> dict[str, Any]:
    """Return readiness for a full train path.

    ``gaps`` codes (stable):
      - ``insufficient_hours`` — driving data below floor (and not toy-allowed)
      - ``device_not_ready`` — tinygrad device probe not ready
      - ``teacher_not_selected`` — no comma-master / Cinque teacher selected
    """
    cfg = cfg or load_student_config()
    soft_dir = Path(soft_labels_dir) if soft_labels_dir else cfg.soft_labels_dir
    shard_dir = Path(shards_dir) if shards_dir else cfg.shards_dir
    fixture = cfg.force_fixture if force_fixture is None else force_fixture
    toy = cfg.allow_toy_train if allow_toy is None else allow_toy
    if toy is False and allow_toy is None:
        toy = toy_train_allowed(config_allow=cfg.allow_toy_train)
    floor = float(min_hours if min_hours is not None else cfg.min_train_hours)

    gaps: list[dict[str, str]] = []

    soft = load_soft_label_summary(soft_dir)
    hours_info = estimate_driving_hours(
        soft_labels_dir=soft_dir,
        shards_dir=shard_dir,
        soft_summary=soft,
    )
    gate = hours_meet_floor(hours_info, min_hours=floor, allow_toy=bool(toy))
    if not gate.get("ok"):
        gaps.append(
            {
                "code": "insufficient_hours",
                "message": (
                    f"Need ≥{floor:g}h driving data; have "
                    f"{hours_info.get('hours')}h "
                    f"(known={hours_info.get('known')}). "
                    "Set DISTILLERY_ALLOW_TOY_TRAIN=1 for CI only "
                    "(live=false / not licensed)."
                ),
            }
        )

    device = probe_train_device(force_fixture=bool(fixture))
    if not device.get("device_ready") and not (toy or fixture):
        gaps.append(
            {
                "code": "device_not_ready",
                "message": (
                    f"Train device not ready "
                    f"(tinygrad={device.get('tinygrad')}, "
                    f"kind={device.get('device_kind')}, "
                    f"name={device.get('device_name')}). "
                    f"{device.get('detail') or ''}"
                ).strip(),
            }
        )

    teacher_selected: dict[str, Any] | None = None
    try:
        from distillery_teacher.comma_master import select_comma_master_teacher

        teacher_selected = select_comma_master_teacher(
            teacher_name, force_fixture=bool(fixture)
        )
    except Exception as exc:  # noqa: BLE001
        teacher_selected = None
        gaps.append(
            {
                "code": "teacher_not_selected",
                "message": f"comma-master teacher listing failed: {exc}",
            }
        )

    if teacher_selected is None and not any(g["code"] == "teacher_not_selected" for g in gaps):
        gaps.append(
            {
                "code": "teacher_not_selected",
                "message": (
                    "No comma-master teacher selected "
                    f"(requested={teacher_name!r}). "
                    "Call list_comma_master_teachers() / select driving_supercombo "
                    "(no Chestnut)."
                ),
            }
        )
    elif teacher_selected is not None and teacher_selected.get("source") == "fixture":
        # Fixture teacher is selectable for CI but still a gap for live train_all
        # unless toy override is on — Craig can see the gap and decide.
        if not toy:
            gaps.append(
                {
                    "code": "teacher_not_selected",
                    "message": (
                        "comma-master teacher is fixture-only "
                        f"({teacher_selected.get('name')}, live=false). "
                        "Select a live openpilot master artifact or set "
                        "DISTILLERY_ALLOW_TOY_TRAIN=1 for CI."
                    ),
                }
            )

    ok = len(gaps) == 0
    return {
        "ok": ok,
        "gaps": gaps,
        "hours": hours_info,
        "hours_gate": gate,
        "device": device,
        "teacher": teacher_selected,
        "min_train_hours": floor,
        "allow_toy": bool(toy),
        "live": False,
        "licensed": False,
    }
