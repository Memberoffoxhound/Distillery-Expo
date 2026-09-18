"""SSH/SCP push of driving_supercombo.onnx to mici — never pretend success."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from distillery_deploy.artifacts import prepare_push_source, resolve_local_onnx
from distillery_deploy.config import DeployConfig, load_deploy_config

log = logging.getLogger(__name__)


@dataclass
class PushResult:
    ok: bool
    live: bool
    device_write: bool
    skipped: bool = False
    reason: str = ""
    local_path: str | None = None
    remote_path: str | None = None
    remote_host: str | None = None
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "live": self.live,
            "device_write": self.device_write,
            "skipped": self.skipped,
            "reason": self.reason,
            "local_path": self.local_path,
            "remote_path": self.remote_path,
            "remote_host": self.remote_host,
            "detail": self.detail,
            "flashed": self.device_write,
        }


def _scp_cmd(cfg: DeployConfig, local: Path, remote_path: str) -> list[str]:
    host = cfg.ssh_host
    assert host
    target = f"{cfg.ssh_user}@{host}:{remote_path}"
    cmd = ["scp", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8"]
    if cfg.ssh_key_path:
        cmd.extend(["-i", cfg.ssh_key_path])
    cmd.extend([str(local), target])
    return cmd


def push_supercombo_ssh(
    local_path: str | Path | None = None,
    *,
    cfg: DeployConfig | None = None,
    scp_runner=None,
) -> PushResult:
    """Push local ONNX to mici as driving_supercombo.onnx.

    If SSH env is missing: honest skip (live=false, device_write=false).
    device_write=True only after successful scp.
    """
    cfg = cfg or load_deploy_config()
    resolved = resolve_local_onnx(local_path, cfg=cfg)
    if resolved is None:
        return PushResult(
            ok=False,
            live=False,
            device_write=False,
            skipped=True,
            reason="no_artifact",
            detail="No local ONNX found (driving_supercombo.onnx or student_modelV2_io.onnx)",
        )

    if not cfg.ssh_available:
        return PushResult(
            ok=False,
            live=False,
            device_write=False,
            skipped=True,
            reason="ssh_unavailable",
            local_path=str(resolved),
            remote_path=cfg.remote_model_path,
            detail=(
                "MICI_SSH_HOST not set — flash skipped, live=false, no device write "
                f"(would target {cfg.remote_model_path})"
            ),
        )

    push_src = prepare_push_source(resolved)
    remote = cfg.remote_model_path
    # Ensure remote path ends with the drop-in filename
    if not remote.endswith("driving_supercombo.onnx"):
        remote = str(Path(remote).parent / "driving_supercombo.onnx")

    cmd = _scp_cmd(cfg, push_src, remote)
    runner = scp_runner or subprocess.run
    try:
        proc = runner(
            cmd,
            capture_output=True,
            text=True,
            timeout=120.0,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001
        return PushResult(
            ok=False,
            live=False,
            device_write=False,
            skipped=False,
            reason="scp_error",
            local_path=str(push_src),
            remote_path=remote,
            remote_host=cfg.ssh_host,
            detail=f"scp failed: {exc}",
        )

    if getattr(proc, "returncode", 1) != 0:
        err = (getattr(proc, "stderr", None) or getattr(proc, "stdout", None) or "").strip()
        return PushResult(
            ok=False,
            live=False,
            device_write=False,
            skipped=False,
            reason="scp_failed",
            local_path=str(push_src),
            remote_path=remote,
            remote_host=cfg.ssh_host,
            detail=err or f"scp exit {getattr(proc, 'returncode', '?')}",
        )

    return PushResult(
        ok=True,
        live=True,
        device_write=True,
        skipped=False,
        reason="ok",
        local_path=str(push_src),
        remote_path=remote,
        remote_host=cfg.ssh_host,
        detail=f"scp ok → {cfg.ssh_user}@{cfg.ssh_host}:{remote}",
    )
