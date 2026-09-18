"""Load ingest settings from configs/default.yaml (+ env overrides)."""

from __future__ import annotations

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
        ssh_key_path=ssh_key,
        force_fixture=force,
        repo_root=_REPO_ROOT,
    )
