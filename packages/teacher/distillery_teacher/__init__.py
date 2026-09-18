"""Distillery Expo — Cinque/supercombo teacher soft-label producer (no Chestnut)."""

from .comma_master import list_comma_master_teachers, select_comma_master_teacher
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
]
