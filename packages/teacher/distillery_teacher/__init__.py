"""Distillery Expo — Cinque/supercombo teacher soft-label producer (no Chestnut)."""

from .comma_master import (
    BIG_TEACHER_NAME,
    list_comma_master_teachers,
    select_comma_master_teacher,
)
from .download import (
    TeacherArtifactStatus,
    cached_big_teacher_ok,
    ensure_big_teacher_onnx,
)
from .config import TeacherConfig, load_teacher_config
from .device import TeacherDeviceInfo, detect_teacher_device
from .models import SoftLabelBatch
from .pipeline import run_teach_pipeline

__all__ = [
    "TeacherConfig",
    "load_teacher_config",
    "TeacherDeviceInfo",
    "detect_teacher_device",
    "SoftLabelBatch",
    "run_teach_pipeline",
    "list_comma_master_teachers",
    "select_comma_master_teacher",
    "BIG_TEACHER_NAME",
    "ensure_big_teacher_onnx",
    "cached_big_teacher_ok",
    "TeacherArtifactStatus",
]
