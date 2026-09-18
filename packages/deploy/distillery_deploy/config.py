"""Deploy / flash settings — SSH env pattern matches ingest."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]

# Highland / openpilot layout on mici — overridable via MICI_MODEL_PATH
DEFAULT_MODEL_PATH = "/data/openpilot/selfdrive/modeld/models/driving_supercombo.onnx"
REMOTE_FILENAME = "driving_supercombo.onnx"


@dataclass(frozen=True)
class DeployConfig:
    ssh_host: str | None = None
    ssh_user: str = "comma"
    ssh_key_path: str | None = None
    # Full remote path including filename mici expects
    remote_model_path: str = DEFAULT_MODEL_PATH
    repo_root: Path = field(default_factory=lambda: _REPO_ROOT)
    export_dir: Path = field(
        default_factory=lambda: _REPO_ROOT / "artifacts" / "export"
    )

    @property
    def ssh_available(self) -> bool:
        return bool(self.ssh_host)

    @property
    def remote_filename(self) -> str:
        return Path(self.remote_model_path).name or REMOTE_FILENAME


def load_deploy_config() -> DeployConfig:
    """Resolve SSH + remote model path from env (same vars as ingest)."""
    ssh_host = os.environ.get("MICI_SSH_HOST") or os.environ.get("COMMA_SSH_HOST") or None
    ssh_user = (
        os.environ.get("MICI_SSH_USER") or os.environ.get("COMMA_SSH_USER") or "comma"
    )
    ssh_key = os.environ.get("MICI_SSH_KEY") or os.environ.get("COMMA_SSH_KEY") or None
    remote = (
        os.environ.get("MICI_MODEL_PATH")
        or os.environ.get("COMMA_MODEL_PATH")
        or DEFAULT_MODEL_PATH
    ).strip()
    return DeployConfig(
        ssh_host=ssh_host,
        ssh_user=ssh_user,
        ssh_key_path=ssh_key,
        remote_model_path=remote,
        repo_root=_REPO_ROOT,
        export_dir=_REPO_ROOT / "artifacts" / "export",
    )
