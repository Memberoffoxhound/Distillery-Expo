"""Load ingest settings from configs/default.yaml (+ env overrides)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Repo root: packages/ingest/distillery_ingest/config.py → ../../../
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CONFIG = _REPO_ROOT / "configs" / "default.yaml"

DEFAULT_DONGLE = "3e2de7ed673817c2"
DEFAULT_CAMS = ("road", "wide", "driver")


@dataclass(frozen=True)
class IngestConfig:
    dongle_id: str = DEFAULT_DONGLE
    cams: tuple[str, ...] = DEFAULT_CAMS
    connect_jwt: str | None = None
    connect_base_url: str = "https://api.commadotai.com"
    ssh_host: str | None = None
    ssh_user: str = "comma"
    ssh_port: int = 22
    ssh_key_path: str | None = None
    force_fixture: bool = False
    repo_root: Path = field(default_factory=lambda: _REPO_ROOT)

    @property
    def connect_available(self) -> bool:
        return bool(self.connect_jwt) and not self.force_fixture

    @property
    def ssh_available(self) -> bool:
        return bool(self.ssh_host) and not self.force_fixture


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def load_ingest_config(config_path: Path | str | None = None) -> IngestConfig:
    """Resolve dongle + cams from YAML; Connect/SSH creds from env."""
    path = Path(config_path) if config_path else _DEFAULT_CONFIG
    raw = _read_yaml(path)
    hardware = raw.get("hardware") or {}
    mici = hardware.get("mici") or {}
    cams_raw = mici.get("cams") or list(DEFAULT_CAMS)
    cams = tuple(str(c) for c in cams_raw)

    dongle = (
        os.environ.get("DISTILLERY_DONGLE_ID")
        or str(raw.get("dongle_id") or DEFAULT_DONGLE)
    ).strip()

    # Prefer env; else hydrate from .cache/connect_jwt (set via POST /discover/connect)
    jwt = os.environ.get("COMMA_JWT") or os.environ.get("CONNECT_JWT") or None
    if not jwt:
        cache = _REPO_ROOT / ".cache" / "connect_jwt"
        if cache.is_file():
            try:
                cached = cache.read_text(encoding="utf-8").strip()
            except OSError:
                cached = ""
            if cached:
                jwt = cached
                os.environ.setdefault("COMMA_JWT", cached)
    ssh_host = os.environ.get("MICI_SSH_HOST") or os.environ.get("COMMA_SSH_HOST") or None
    ssh_user = os.environ.get("MICI_SSH_USER") or os.environ.get("COMMA_SSH_USER") or "comma"
    ssh_key = os.environ.get("MICI_SSH_KEY") or os.environ.get("COMMA_SSH_KEY") or None
    ssh_port_raw = os.environ.get("MICI_SSH_PORT") or os.environ.get("COMMA_SSH_PORT") or "22"
    try:
        ssh_port = int(str(ssh_port_raw).strip() or "22")
    except ValueError:
        ssh_port = 22
    # Prefer env; else hydrate from .cache/ssh_config.json (set via POST /discover/ssh)
    if not ssh_host:
        ssh_cache = _REPO_ROOT / ".cache" / "ssh_config.json"
        if ssh_cache.is_file():
            try:
                cached_ssh = json.loads(ssh_cache.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                cached_ssh = {}
            if isinstance(cached_ssh, dict) and cached_ssh.get("host"):
                ssh_host = str(cached_ssh["host"]).strip() or None
                if ssh_host:
                    os.environ.setdefault("MICI_SSH_HOST", ssh_host)
                if cached_ssh.get("user") and not (
                    os.environ.get("MICI_SSH_USER") or os.environ.get("COMMA_SSH_USER")
                ):
                    ssh_user = str(cached_ssh["user"]).strip() or "comma"
                    os.environ.setdefault("MICI_SSH_USER", ssh_user)
                if cached_ssh.get("port") is not None and not (
                    os.environ.get("MICI_SSH_PORT") or os.environ.get("COMMA_SSH_PORT")
                ):
                    try:
                        ssh_port = int(cached_ssh["port"])
                    except (TypeError, ValueError):
                        pass
                    else:
                        os.environ.setdefault("MICI_SSH_PORT", str(ssh_port))
                if cached_ssh.get("identity_path") and not ssh_key:
                    ssh_key = str(cached_ssh["identity_path"]).strip() or None
                    if ssh_key:
                        os.environ.setdefault("MICI_SSH_KEY", ssh_key)
    force = os.environ.get("DISTILLERY_INGEST_FIXTURE", "").lower() in ("1", "true", "yes")
    base = os.environ.get("CONNECT_BASE_URL") or "https://api.commadotai.com"

    ingest_block = raw.get("ingest") or {}
    if isinstance(ingest_block, dict) and ingest_block.get("force_fixture"):
        force = True

    return IngestConfig(
        dongle_id=dongle,
        cams=cams or DEFAULT_CAMS,
        connect_jwt=jwt,
        connect_base_url=base.rstrip("/"),
        ssh_host=ssh_host,
        ssh_user=ssh_user,
        ssh_port=ssh_port,
        ssh_key_path=ssh_key,
        force_fixture=force,
        repo_root=_REPO_ROOT,
    )
