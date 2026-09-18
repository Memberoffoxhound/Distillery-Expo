"""Device / Connect discovery for Expo pickers (no env archaeology)."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from distillery_ingest.config import IngestConfig, load_ingest_config, _REPO_ROOT

log = logging.getLogger(__name__)

# Non-secret path under .cache/ (gitignored). JWT content must never be committed.
_JWT_CACHE = _REPO_ROOT / ".cache" / "connect_jwt"
# SSH host/user/port/identity path (path only — not key bytes). Gitignored via .cache/.
_SSH_CACHE = _REPO_ROOT / ".cache" / "ssh_config.json"
# Dongle id (non-secret). Gitignored via .cache/. Empty until GUI Save / env.
_DONGLE_CACHE = _REPO_ROOT / ".cache" / "dongle_id"


@dataclass
class DiscoveredDevice:
    """One ADB (LAN/USB) device for the Expo picker."""

    id: str
    model: str | None = None
    state: str = "unknown"
    transport: Literal["usb", "tcp", "unknown"] = "unknown"
    suggested_host: str | None = None
    product: str | None = None
    device: str | None = None
    transport_id: str | None = None
    raw: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def ensure_jwt_from_cache() -> str | None:
    """If COMMA_JWT/CONNECT_JWT unset, load from .cache/connect_jwt into process env."""
    if os.environ.get("COMMA_JWT") or os.environ.get("CONNECT_JWT"):
        return os.environ.get("COMMA_JWT") or os.environ.get("CONNECT_JWT")
    if not _JWT_CACHE.is_file():
        return None
    try:
        token = _JWT_CACHE.read_text(encoding="utf-8").strip()
    except OSError as exc:
        log.warning("failed reading JWT cache: %s", exc)
        return None
    if not token:
        return None
    os.environ["COMMA_JWT"] = token
    return token


def set_connect_jwt(jwt: str, *, persist: bool = True) -> dict[str, Any]:
    """Store Connect JWT in process env (+ optional .cache file). Never log the token."""
    token = (jwt or "").strip()
    if not token:
        raise ValueError("jwt must be a non-empty string")
    os.environ["COMMA_JWT"] = token
    # Keep CONNECT_JWT in sync for callers that read either name
    os.environ["CONNECT_JWT"] = token
    cached = False
    if persist:
        try:
            _JWT_CACHE.parent.mkdir(parents=True, exist_ok=True)
            _JWT_CACHE.write_text(token + "\n", encoding="utf-8")
            # Restrict perms when possible (best-effort on shared boxes)
            try:
                _JWT_CACHE.chmod(0o600)
            except OSError:
                pass
            cached = True
        except OSError as exc:
            log.warning("failed writing JWT cache: %s", exc)
    return connect_status()


def clear_connect_jwt(*, clear_cache: bool = True) -> dict[str, Any]:
    os.environ.pop("COMMA_JWT", None)
    os.environ.pop("CONNECT_JWT", None)
    if clear_cache and _JWT_CACHE.is_file():
        try:
            _JWT_CACHE.unlink()
        except OSError as exc:
            log.warning("failed removing JWT cache: %s", exc)
    return connect_status()


def connect_status(cfg: IngestConfig | None = None) -> dict[str, Any]:
    """Status for GET /discover/connect — no secret material in the payload."""
    ensure_jwt_from_cache()
    cfg = cfg or load_ingest_config()
    jwt = cfg.connect_jwt
    masked = None
    if jwt:
        if len(jwt) <= 8:
            masked = "***"
        else:
            masked = f"{jwt[:4]}…{jwt[-4:]}"
    cache_path = None
    if _JWT_CACHE.is_file():
        try:
            cache_path = str(_JWT_CACHE.relative_to(_REPO_ROOT))
        except ValueError:
            cache_path = str(_JWT_CACHE)
    return {
        "configured": bool(jwt),
        "available": cfg.connect_available,
        "base_url": cfg.connect_base_url,
        "dongle_id": cfg.dongle_id,
        "jwt_masked": masked,
        "jwt_source": _jwt_source(),
        "cache_path": cache_path,
    }


def _jwt_source() -> str | None:
    if os.environ.get("COMMA_JWT"):
        # Distinguish live env vs cache-hydrated env: if cache matches, say cache
        if _JWT_CACHE.is_file():
            try:
                cached = _JWT_CACHE.read_text(encoding="utf-8").strip()
                if cached and cached == os.environ.get("COMMA_JWT"):
                    # Could still be env that was written via POST — report "env+cache"
                    return "env+cache"
            except OSError:
                pass
        return "env"
    if os.environ.get("CONNECT_JWT"):
        return "env"
    if _JWT_CACHE.is_file():
        return "cache"
    return None


def ensure_dongle_from_cache() -> str | None:
    """If DISTILLERY_DONGLE_ID unset, load from .cache/dongle_id into process env."""
    existing = (os.environ.get("DISTILLERY_DONGLE_ID") or "").strip()
    if existing:
        return existing
    cache = _DONGLE_CACHE
    if not cache.is_file():
        return None
    try:
        token = cache.read_text(encoding="utf-8").strip()
    except OSError as exc:
        log.warning("failed reading dongle cache: %s", exc)
        return None
    if not token:
        return None
    os.environ["DISTILLERY_DONGLE_ID"] = token
    return token


def set_dongle_id(dongle_id: str, *, persist: bool = True) -> dict[str, Any]:
    """Store dongle id in process env (+ optional .cache file). Mirror JWT/SSH Save."""
    value = (dongle_id or "").strip()
    if not value:
        raise ValueError("dongle_id must be a non-empty string")
    os.environ["DISTILLERY_DONGLE_ID"] = value
    cached = False
    if persist:
        try:
            _DONGLE_CACHE.parent.mkdir(parents=True, exist_ok=True)
            _DONGLE_CACHE.write_text(value + "\n", encoding="utf-8")
            try:
                _DONGLE_CACHE.chmod(0o600)
            except OSError:
                pass
            cached = True
        except OSError as exc:
            log.warning("failed writing dongle cache: %s", exc)
    status = dongle_status()
    status["persisted"] = cached
    return status


def clear_dongle_id(*, clear_cache: bool = True) -> dict[str, Any]:
    os.environ.pop("DISTILLERY_DONGLE_ID", None)
    if clear_cache and _DONGLE_CACHE.is_file():
        try:
            _DONGLE_CACHE.unlink()
        except OSError as exc:
            log.warning("failed removing dongle cache: %s", exc)
    return dongle_status()


def dongle_status(cfg: IngestConfig | None = None) -> dict[str, Any]:
    """Status for GET /dongle — no demo default; empty until Save."""
    ensure_dongle_from_cache()
    cfg = cfg or load_ingest_config()
    dongle = (cfg.dongle_id or "").strip()
    cache_path = None
    if _DONGLE_CACHE.is_file():
        try:
            cache_path = str(_DONGLE_CACHE.relative_to(_REPO_ROOT))
        except ValueError:
            cache_path = str(_DONGLE_CACHE)
    return {
        "dongle_id": dongle or None,
        "configured": bool(dongle),
        "source": _dongle_source(),
        "cache_path": cache_path,
        "cams": list(cfg.cams),
        "connect_available": cfg.connect_available,
        "ssh_available": cfg.ssh_available,
        "force_fixture": cfg.force_fixture,
    }


def _dongle_source() -> str | None:
    if (os.environ.get("DISTILLERY_DONGLE_ID") or "").strip():
        if _DONGLE_CACHE.is_file():
            try:
                cached = _DONGLE_CACHE.read_text(encoding="utf-8").strip()
                if cached and cached == os.environ.get("DISTILLERY_DONGLE_ID", "").strip():
                    return "env+cache"
            except OSError:
                pass
        return "env"
    if _DONGLE_CACHE.is_file():
        return "cache"
    return None


def ensure_ssh_from_cache() -> dict[str, Any] | None:
    """If MICI_SSH_HOST unset, load from .cache/ssh_config.json into process env."""
    if os.environ.get("MICI_SSH_HOST") or os.environ.get("COMMA_SSH_HOST"):
        return None
    if not _SSH_CACHE.is_file():
        return None
    try:
        data = json.loads(_SSH_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        log.warning("failed reading SSH cache: %s", exc)
        return None
    if not isinstance(data, dict):
        return None
    host = str(data.get("host") or "").strip()
    if not host:
        return None
    os.environ["MICI_SSH_HOST"] = host
    user = str(data.get("user") or "comma").strip() or "comma"
    os.environ.setdefault("MICI_SSH_USER", user)
    try:
        port = int(data.get("port") if data.get("port") is not None else 22)
    except (TypeError, ValueError):
        port = 22
    os.environ.setdefault("MICI_SSH_PORT", str(port))
    identity = str(data.get("identity_path") or "").strip() or None
    if identity and not (os.environ.get("MICI_SSH_KEY") or os.environ.get("COMMA_SSH_KEY")):
        os.environ["MICI_SSH_KEY"] = identity
    return data


def set_ssh_config(
    host: str,
    user: str = "comma",
    port: int = 22,
    identity_path: str | None = None,
    *,
    persist: bool = True,
) -> dict[str, Any]:
    """Store SSH target in process env (+ optional .cache JSON). Path only — no key bytes."""
    h = (host or "").strip()
    if not h:
        raise ValueError("host must be a non-empty string")
    u = (user or "comma").strip() or "comma"
    try:
        p = int(port) if port is not None else 22
    except (TypeError, ValueError) as exc:
        raise ValueError("port must be an integer") from exc
    if p < 1 or p > 65535:
        raise ValueError("port must be between 1 and 65535")
    ident = (identity_path or "").strip() or None

    os.environ["MICI_SSH_HOST"] = h
    os.environ["COMMA_SSH_HOST"] = h
    os.environ["MICI_SSH_USER"] = u
    os.environ["COMMA_SSH_USER"] = u
    os.environ["MICI_SSH_PORT"] = str(p)
    os.environ["COMMA_SSH_PORT"] = str(p)
    if ident:
        os.environ["MICI_SSH_KEY"] = ident
        os.environ["COMMA_SSH_KEY"] = ident
    else:
        os.environ.pop("MICI_SSH_KEY", None)
        os.environ.pop("COMMA_SSH_KEY", None)

    cached = False
    if persist:
        payload = {
            "host": h,
            "user": u,
            "port": p,
            "identity_path": ident,
        }
        try:
            _SSH_CACHE.parent.mkdir(parents=True, exist_ok=True)
            _SSH_CACHE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            try:
                _SSH_CACHE.chmod(0o600)
            except OSError:
                pass
            cached = True
        except OSError as exc:
            log.warning("failed writing SSH cache: %s", exc)
    status = ssh_status()
    status["persisted"] = cached
    return status


def clear_ssh_config(*, clear_cache: bool = True) -> dict[str, Any]:
    for key in (
        "MICI_SSH_HOST",
        "COMMA_SSH_HOST",
        "MICI_SSH_USER",
        "COMMA_SSH_USER",
        "MICI_SSH_PORT",
        "COMMA_SSH_PORT",
        "MICI_SSH_KEY",
        "COMMA_SSH_KEY",
    ):
        os.environ.pop(key, None)
    if clear_cache and _SSH_CACHE.is_file():
        try:
            _SSH_CACHE.unlink()
        except OSError as exc:
            log.warning("failed removing SSH cache: %s", exc)
    return ssh_status()


def probe_ssh(*, timeout: float = 5.0) -> dict[str, Any]:
    """Short non-interactive SSH check. Honest fail; never hang forever."""
    ensure_ssh_from_cache()
    cfg = load_ingest_config()
    host = cfg.ssh_host
    if not host:
        return {"ok": False, "error": "SSH host not configured"}
    user = cfg.ssh_user or "comma"
    port = getattr(cfg, "ssh_port", 22) or 22
    target = f"{user}@{host}"
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={max(1, int(timeout))}",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-p",
        str(port),
    ]
    if cfg.ssh_key_path:
        cmd.extend(["-i", cfg.ssh_key_path])
    cmd.extend([target, "true"])
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 1.0,
            check=False,
        )
    except FileNotFoundError:
        return {"ok": False, "error": "ssh not found on PATH"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"ssh probe timed out after {timeout:.0f}s"}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    if proc.returncode == 0:
        return {"ok": True, "error": None}
    err = (proc.stderr or proc.stdout or f"ssh exit {proc.returncode}").strip()
    # Keep error short for UI
    if len(err) > 240:
        err = err[:237] + "…"
    return {"ok": False, "error": err or f"ssh exit {proc.returncode}"}


def ssh_status(cfg: IngestConfig | None = None) -> dict[str, Any]:
    """Status for GET /discover/ssh — host/user/port; identity is a path (OK)."""
    ensure_ssh_from_cache()
    cfg = cfg or load_ingest_config()
    cache_path = None
    if _SSH_CACHE.is_file():
        try:
            cache_path = str(_SSH_CACHE.relative_to(_REPO_ROOT))
        except ValueError:
            cache_path = str(_SSH_CACHE)
    port = getattr(cfg, "ssh_port", 22) or 22
    return {
        "configured": bool(cfg.ssh_host),
        "available": cfg.ssh_available,
        "host": cfg.ssh_host,
        "user": cfg.ssh_user,
        "port": port,
        "identity_path": cfg.ssh_key_path,
        "key_set": bool(cfg.ssh_key_path),
        "cache_path": cache_path,
        "source": _ssh_source(),
    }


def _ssh_source() -> str | None:
    if os.environ.get("MICI_SSH_HOST") or os.environ.get("COMMA_SSH_HOST"):
        if _SSH_CACHE.is_file():
            try:
                data = json.loads(_SSH_CACHE.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("host"):
                    env_host = os.environ.get("MICI_SSH_HOST") or os.environ.get("COMMA_SSH_HOST")
                    if str(data.get("host")).strip() == (env_host or "").strip():
                        return "env+cache"
            except (OSError, ValueError, TypeError):
                pass
        return "env"
    if _SSH_CACHE.is_file():
        return "cache"
    return None


_KV_RE = re.compile(r"(\w+):(\S+)")


def _classify_transport(serial: str) -> tuple[Literal["usb", "tcp", "unknown"], str | None]:
    # Network ADB: host:port
    if re.match(r"^\d{1,3}(?:\.\d{1,3}){3}:\d+$", serial):
        return "tcp", serial.split(":", 1)[0]
    if ":" in serial and not serial.startswith("emulator-"):
        # emulators use emulator-5554; other host:port forms
        host_part = serial.rsplit(":", 1)[0]
        if host_part and not host_part.startswith("emulator"):
            return "tcp", host_part
    if serial.startswith("emulator-"):
        return "unknown", None
    return "usb", None


def parse_adb_devices_output(text: str) -> list[DiscoveredDevice]:
    """Parse `adb devices -l` stdout into DiscoveredDevice rows."""
    devices: list[DiscoveredDevice] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("list of devices"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        kv = {m.group(1): m.group(2) for m in _KV_RE.finditer(line)}
        transport, suggested = _classify_transport(serial)
        devices.append(
            DiscoveredDevice(
                id=serial,
                model=kv.get("model"),
                state=state,
                transport=transport,
                suggested_host=suggested,
                product=kv.get("product"),
                device=kv.get("device"),
                transport_id=kv.get("transport_id"),
                raw=line,
            )
        )
    return devices


def list_adb_devices(*, adb_bin: str = "adb", timeout: float = 8.0) -> dict[str, Any]:
    """Run `adb devices -l` and return a picker-friendly payload."""
    adb_path = _which(adb_bin)
    if not adb_path:
        return {
            "ok": False,
            "adb_available": False,
            "error": "adb not found on PATH",
            "devices": [],
        }
    try:
        proc = subprocess.run(
            [adb_path, "devices", "-l"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "ok": False,
            "adb_available": True,
            "error": str(exc),
            "devices": [],
        }
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or f"adb exit {proc.returncode}").strip()
        return {
            "ok": False,
            "adb_available": True,
            "error": err,
            "devices": [],
        }
    devices = parse_adb_devices_output(proc.stdout or "")
    return {
        "ok": True,
        "adb_available": True,
        "error": None,
        "devices": [d.to_dict() for d in devices],
    }


def _which(name: str) -> str | None:
    from shutil import which

    return which(name)


def discovery_overview(cfg: IngestConfig | None = None) -> dict[str, Any]:
    """Combined discovery snapshot for Expo (devices + connect + ssh + fixture)."""
    ensure_jwt_from_cache()
    ensure_ssh_from_cache()
    ensure_dongle_from_cache()
    cfg = cfg or load_ingest_config()
    adb = list_adb_devices()
    dongle = dongle_status(cfg)
    return {
        "dongle_id": dongle.get("dongle_id"),
        "dongle": dongle,
        "cams": list(cfg.cams),
        "devices": adb,
        "connect": connect_status(cfg),
        "ssh": ssh_status(cfg),
        "fixture": {
            "available": True,
            "label": "fixture",
            "offline_fallback": True,
            "forced": cfg.force_fixture,
        },
        "sources": {
            "connect": cfg.connect_available,
            "ssh": cfg.ssh_available,
            "fixture": True,
        },
    }


def apply_discovered_overrides(
    cfg: IngestConfig,
    *,
    ssh_host: str | None = None,
    device_id: str | None = None,
) -> IngestConfig:
    """Return a config copy with optional SSH host from discovery / query.

    device_id: if it looks like host:port (network ADB), use host as MICI_SSH_HOST
    when ssh_host is not explicitly provided.
    """
    host = (ssh_host or "").strip() or None
    if not host and device_id:
        transport, suggested = _classify_transport(device_id.strip())
        if transport == "tcp" and suggested:
            host = suggested
        elif transport == "tcp" and ":" in device_id:
            host = device_id.strip().rsplit(":", 1)[0]
    if not host:
        return cfg
    # frozen dataclass — rebuild
    return IngestConfig(
        dongle_id=cfg.dongle_id,
        cams=cfg.cams,
        connect_jwt=cfg.connect_jwt,
        connect_base_url=cfg.connect_base_url,
        ssh_host=host,
        ssh_user=cfg.ssh_user,
        ssh_port=getattr(cfg, "ssh_port", 22) or 22,
        ssh_key_path=cfg.ssh_key_path,
        force_fixture=cfg.force_fixture,
        repo_root=cfg.repo_root,
    )
