"""Distillery Expo — Cinque/supercombo teacher soft-label producer (no Chestnut)."""

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
]
