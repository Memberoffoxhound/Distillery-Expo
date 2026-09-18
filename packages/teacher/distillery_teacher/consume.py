"""Teach-time consume of Craig's artifacts/teachers/big_driving_supercombo cache.

Exact contract (Craig PR #22 / download.py):
  artifacts/teachers/big_driving_supercombo.onnx
  artifacts/teachers/big_driving_supercombo.onnx.sha256   # bare hex or sha256sum line
  artifacts/teachers/big_driving_supercombo.json          # optional meta

Happy path = verified live cache. Missing / mismatch / explicit CI flag ->
labeled fixture last-resort (live=false / not licensed; ok=False). Never the
default. Never driving_supercombo. No Chestnut.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from distillery_teacher.download import (
    BIG_TEACHER_FILENAME,
    BIG_TEACHER_NAME,
    TeacherArtifactStatus,
    _sha256_file,
    artifact_paths,
    cached_big_teacher_ok,
    teachers_dir,
)


class TeacherChecksumError(Exception):
    """Cached big teacher failed SHA-256 verification."""


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes")


def _fixture_status(*, reason: str, error: str | None = None) -> TeacherArtifactStatus:
    # Last-resort only — never soft-sell as a valid live teach outcome.
    return TeacherArtifactStatus(
        ok=False,
        live=False,
        cached=False,
        path=None,
        sha256=None,
        source="fixture",
        label=f"fixture · {BIG_TEACHER_NAME}",
        detail=(
            f"fixture · {BIG_TEACHER_NAME} — {reason} "
            f"(live=false / not licensed; last-resort CI only; "
            f"no driving_supercombo fallback; no Chestnut)"
        ),
        error=error,
    )


def verify_cached_big_teacher(dest_dir: Path | None = None) -> TeacherArtifactStatus:
    """Strict checksum verify of Craig's cache paths. No download, no small-model scan.

    Raises TeacherChecksumError when ONNX exists but sidecar mismatches.
    Returns labeled fixture status (ok=False) when cache missing — not a live pass.
    """
    onnx, sha_path, _meta = artifact_paths(dest_dir)
    if not onnx.is_file() or onnx.stat().st_size < 1024:
        # Also refuse if only the small model is present under teachers_dir
        small = teachers_dir(dest_dir) / "driving_supercombo.onnx"
        detail = "cache miss under artifacts/teachers/"
        if small.is_file():
            detail = (
                "big_driving_supercombo.onnx missing — "
                "driving_supercombo.onnx present but ignored (no small-model fallback)"
            )
        return _fixture_status(reason=detail)

    if not sha_path.is_file():
        raise TeacherChecksumError(
            f"checksum sidecar missing for {BIG_TEACHER_FILENAME} — "
            f"expected {sha_path.name} (refuse unverified cache)"
        )

    expected = sha_path.read_text(encoding="utf-8").strip().split()[0].lower()
    digest = _sha256_file(onnx)
    if digest != expected:
        raise TeacherChecksumError(
            f"checksum mismatch for {BIG_TEACHER_FILENAME}: "
            f"got {digest[:12]}… expected {expected[:12]}… "
            f"(corrupt cache — will not use as live weights)"
        )

    cached = cached_big_teacher_ok(dest_dir)
    if cached is not None:
        return cached

    # Sidecar matched but cached_big_teacher_ok declined (e.g. tiny file) —
    # still return verified status.
    return TeacherArtifactStatus(
        ok=True,
        live=True,
        cached=True,
        path=onnx,
        sha256=digest,
        source="commaai/openpilot@master",
        label=f"comma master · {BIG_TEACHER_NAME}",
        detail=f"verified {onnx.name} ({onnx.stat().st_size} bytes)",
        bytes=onnx.stat().st_size,
    )


def consume_big_teacher_for_teach(
    dest_dir: Path | None = None,
    *,
    force_fixture: bool = False,
) -> TeacherArtifactStatus:
    """Resolve teacher artifact for teach soft-label pass.

    Prefer verified live cache under artifacts/teachers/.
    Fixture only via explicit force_fixture / DISTILLERY_TEACHER_FIXTURE (CI).
    On missing/checksum-fail -> labeled fixture (ok=False; never default).
    Never returns / selects driving_supercombo.
    """
    if force_fixture or _env_truthy("DISTILLERY_TEACHER_FIXTURE"):
        return _fixture_status(reason="force_fixture / DISTILLERY_TEACHER_FIXTURE")

    try:
        return verify_cached_big_teacher(dest_dir)
    except TeacherChecksumError as exc:
        return _fixture_status(reason="checksum verify failed", error=str(exc))


def consume_as_dict(
    dest_dir: Path | None = None,
    *,
    force_fixture: bool = False,
) -> dict[str, Any]:
    return consume_big_teacher_for_teach(
        dest_dir, force_fixture=force_fixture
    ).as_dict()
