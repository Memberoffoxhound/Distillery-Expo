"""Resolve local ONNX artifact for mici drop-in flash."""

from __future__ import annotations

import shutil
from pathlib import Path

from distillery_deploy.config import REMOTE_FILENAME, DeployConfig, load_deploy_config

# Prefer mici drop-in name; keep legacy export name as fallback until Graig rename lands everywhere
_CANDIDATES = (
    "driving_supercombo.onnx",
    "student_modelV2_io.onnx",
)


def resolve_local_onnx(
    preferred: str | Path | None = None,
    *,
    cfg: DeployConfig | None = None,
) -> Path | None:
    """Pick local artifact for flash.

    Order:
      1. preferred path (pipeline-returned onnx_path) if it exists
      2. artifacts/export/driving_supercombo.onnx
      3. artifacts/export/student_modelV2_io.onnx
    """
    cfg = cfg or load_deploy_config()
    if preferred:
        p = Path(preferred)
        if p.is_file():
            return p
    for name in _CANDIDATES:
        cand = cfg.export_dir / name
        if cand.is_file():
            return cand
    return None


def prepare_push_source(
    local_path: Path,
    *,
    staging_dir: Path | None = None,
) -> Path:
    """Ensure the file we scp is named driving_supercombo.onnx (mici drop-in).

    If local is already that name, return as-is. Otherwise copy/rename into staging.
    """
    local_path = Path(local_path)
    if local_path.name == REMOTE_FILENAME:
        return local_path
    stage = staging_dir or (local_path.parent / ".flash_staging")
    stage.mkdir(parents=True, exist_ok=True)
    dest = stage / REMOTE_FILENAME
    shutil.copy2(local_path, dest)
    return dest
