"""Download + cache comma master big_driving_supercombo.onnx (big teacher only).

Never falls back to driving_supercombo / small model. Offline → labeled fixture
status (live=false), never pretend live. No Chestnut.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TEACHERS_DIR = _REPO_ROOT / "artifacts" / "teachers"

BIG_TEACHER_NAME = "big_driving_supercombo"
BIG_TEACHER_REF = "selfdrive/modeld/models/big_driving_supercombo.onnx"
BIG_TEACHER_FILENAME = f"{BIG_TEACHER_NAME}.onnx"

# Candidate URLs (Git LFS media first, then raw, then API-provided download_url).
_URL_CANDIDATES = [
    f"https://media.githubusercontent.com/media/commaai/openpilot/master/{BIG_TEACHER_REF}",
    f"https://github.com/commaai/openpilot/raw/master/{BIG_TEACHER_REF}",
    f"https://raw.githubusercontent.com/commaai/openpilot/master/{BIG_TEACHER_REF}",
]

ProgressCb = Callable[[float, str], None]


@dataclass
class TeacherArtifactStatus:
    """Result of ensure_big_teacher_onnx."""

    name: str = BIG_TEACHER_NAME
    ok: bool = False
    live: bool = False
    cached: bool = False
    path: Path | None = None
    sha256: str | None = None
    source: str = "fixture"
    label: str = f"fixture · {BIG_TEACHER_NAME}"
    detail: str = ""
    error: str | None = None
    bytes: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "live": self.live,
            "cached": self.cached,
            "path": str(self.path) if self.path else None,
            "sha256": self.sha256,
            "source": self.source,
            "label": self.label,
            "detail": self.detail,
            "error": self.error,
            "bytes": self.bytes,
            "role": "big",
            "teacher": BIG_TEACHER_NAME,
        }


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes")


def teachers_dir(root: Path | None = None) -> Path:
    return Path(root) if root else DEFAULT_TEACHERS_DIR


def artifact_paths(dest_dir: Path | None = None) -> tuple[Path, Path, Path]:
    d = teachers_dir(dest_dir)
    onnx = d / BIG_TEACHER_FILENAME
    sha = d / f"{BIG_TEACHER_FILENAME}.sha256"
    meta = d / f"{BIG_TEACHER_NAME}.json"
    return onnx, sha, meta


def _sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            buf = f.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def _write_sidecar(onnx: Path, sha_path: Path, meta_path: Path, *, source: str) -> str:
    digest = _sha256_file(onnx)
    sha_path.write_text(digest + "\n", encoding="utf-8")
    meta = {
        "name": BIG_TEACHER_NAME,
        "filename": BIG_TEACHER_FILENAME,
        "ref": BIG_TEACHER_REF,
        "sha256": digest,
        "bytes": onnx.stat().st_size,
        "source": source,
        "label": f"comma master · {BIG_TEACHER_NAME}",
        "live": True,
        "role": "big",
    }
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return digest


def cached_big_teacher_ok(dest_dir: Path | None = None) -> TeacherArtifactStatus | None:
    """Return status if cached ONNX exists and matches sidecar checksum."""
    onnx, sha_path, meta_path = artifact_paths(dest_dir)
    if not onnx.is_file() or onnx.stat().st_size < 1024:
        return None
    expected = None
    if sha_path.is_file():
        expected = sha_path.read_text(encoding="utf-8").strip().split()[0]
    digest = _sha256_file(onnx)
    if expected and digest != expected:
        log.warning("teacher cache checksum mismatch — will re-download")
        return None
    # If no sidecar yet, write one (treat as valid cache).
    if not expected:
        digest = _write_sidecar(onnx, sha_path, meta_path, source="commaai/openpilot@master")
    label = f"comma master · {BIG_TEACHER_NAME}"
    return TeacherArtifactStatus(
        ok=True,
        live=True,
        cached=True,
        path=onnx,
        sha256=digest,
        source="commaai/openpilot@master",
        label=label,
        detail=f"cached {onnx.name} ({onnx.stat().st_size} bytes)",
        bytes=onnx.stat().st_size,
    )


def _download_url(
    url: str,
    dest: Path,
    *,
    progress: ProgressCb | None = None,
    timeout: float = 120.0,
) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".partial")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "distillery-expo-teacher-pull"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        # Reject tiny LFS pointer stubs pretending to be the model.
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "text/" in ctype and total and total < 500:
            raise RuntimeError(f"refusing LFS pointer-like response from {url}")
        written = 0
        with partial.open("wb") as out:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                out.write(chunk)
                written += len(chunk)
                if progress and total:
                    progress(min(0.99, written / total), f"download {BIG_TEACHER_NAME} {written}/{total}")
                elif progress:
                    progress(0.5, f"download {BIG_TEACHER_NAME} {written} bytes")
    if written < 1024:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"download too small ({written} bytes) from {url}")
    # Peek for git-lfs pointer
    head = partial.read_bytes()[:120]
    if head.startswith(b"version https://git-lfs.github.com/spec/v1"):
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"got git-lfs pointer, not blob, from {url}")
    partial.replace(dest)
    return written


def ensure_big_teacher_onnx(
    dest_dir: Path | None = None,
    *,
    force_fixture: bool = False,
    force_download: bool = False,
    progress: ProgressCb | None = None,
    timeout: float = 120.0,
    download_url: str | None = None,
) -> TeacherArtifactStatus:
    """Ensure artifacts/teachers/big_driving_supercombo.onnx is present.

    Prefer live cache under artifacts/teachers/. Skip if cached + checksum ok.
    Offline / explicit force_fixture -> labeled fixture (ok=False; never default).
    Never claims live; never swaps to small.
    """
    # Explicit CI / offline only — never the default happy path.
    if force_fixture or _env_truthy("DISTILLERY_TEACHER_FIXTURE"):
        return TeacherArtifactStatus(
            ok=False,
            live=False,
            cached=False,
            path=None,
            source="fixture",
            label=f"fixture · {BIG_TEACHER_NAME}",
            detail=(
                "fixture teacher — force_fixture / DISTILLERY_TEACHER_FIXTURE "
                "(live=false / not licensed; last-resort CI only; big only; no Chestnut)"
            ),
        )

    if not force_download:
        cached = cached_big_teacher_ok(dest_dir)
        if cached is not None:
            if progress:
                progress(1.0, f"cached {BIG_TEACHER_NAME}")
            return cached

    onnx, sha_path, meta_path = artifact_paths(dest_dir)
    urls: list[str] = []
    if download_url:
        urls.append(download_url)
    urls.extend(_URL_CANDIDATES)

    last_err: str | None = None
    for url in urls:
        try:
            if progress:
                progress(0.05, f"fetching {BIG_TEACHER_NAME} from comma master")
            nbytes = _download_url(url, onnx, progress=progress, timeout=timeout)
            digest = _write_sidecar(
                onnx, sha_path, meta_path, source="commaai/openpilot@master"
            )
            if progress:
                progress(1.0, f"downloaded {BIG_TEACHER_NAME}")
            return TeacherArtifactStatus(
                ok=True,
                live=True,
                cached=False,
                path=onnx,
                sha256=digest,
                source="commaai/openpilot@master",
                label=f"comma master · {BIG_TEACHER_NAME}",
                detail=f"downloaded {nbytes} bytes from {url}",
                bytes=nbytes,
            )
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, RuntimeError) as exc:
            last_err = str(exc).strip() or repr(exc)
            log.warning("teacher download failed via %s: %s", url, last_err)
            continue

    # Offline / all URLs failed — honest fixture for the BIG teacher only.
    return TeacherArtifactStatus(
        ok=False,
        live=False,
        cached=False,
        path=None,
        source="fixture",
        label=f"fixture · {BIG_TEACHER_NAME}",
        detail=(
            f"offline or download failed for {BIG_TEACHER_NAME} "
            f"(live=false; no small-model fallback; no Chestnut)"
        ),
        error=last_err,
    )


# Back-compat alias
ensure_teacher_onnx = ensure_big_teacher_onnx
