"""Distillery Expo — stock-modelV2-I/O student distill loop."""

from .config import StudentConfig, load_student_config
from .device import probe_train_device, resolve_torch_device
from .hours import (
    DEFAULT_MIN_TRAIN_HOURS,
    InsufficientHoursError,
    estimate_driving_hours,
    hours_meet_floor,
    toy_train_allowed,
)
from .pipeline import run_train_pipeline
from .readiness import check_train_readiness

__all__ = [
    "StudentConfig",
    "load_student_config",
    "run_train_pipeline",
    "probe_train_device",
    "resolve_torch_device",
    "estimate_driving_hours",
    "hours_meet_floor",
    "toy_train_allowed",
    "InsufficientHoursError",
    "DEFAULT_MIN_TRAIN_HOURS",
    "check_train_readiness",
]
