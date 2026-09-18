"""Graig consume — Craig artifacts/teachers contract; big only; checksum honesty."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from distillery_teacher.consume import (
    TeacherChecksumError,
    consume_big_teacher_for_teach,
    verify_cached_big_teacher,
)
from distillery_teacher.download import BIG_TEACHER_FILENAME, BIG_TEACHER_NAME


def _write_craig_cache(dirpath: Path, body: bytes, *, bad_sha: bool = False) -> Path:
    dirpath.mkdir(parents=True, exist_ok=True)
    onnx = dirpath / BIG_TEACHER_FILENAME
    onnx.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    sha = dirpath / f"{BIG_TEACHER_FILENAME}.sha256"
    sha.write_text(("0" * 64 if bad_sha else digest) + "\n")
    return onnx


def test_consume_verified_big_cache(tmp_path, monkeypatch):
    monkeypatch.delenv("DISTILLERY_TEACHER_FIXTURE", raising=False)
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)
    # Small model present must be ignored
    (tmp_path / "driving_supercombo.onnx").write_bytes(b"SMALL" * 400)
    _write_craig_cache(tmp_path, b"BIG_TEACHER_WEIGHTS_OK" * 200)
    art = consume_big_teacher_for_teach(tmp_path, force_fixture=False)
    assert art.name == BIG_TEACHER_NAME
    assert art.live is True
    assert art.ok is True
    assert art.path is not None
    assert art.path.name == BIG_TEACHER_FILENAME
    assert art.path.name.startswith("big_")


def test_consume_ignores_small_only(tmp_path, monkeypatch):
    monkeypatch.delenv("DISTILLERY_TEACHER_FIXTURE", raising=False)
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)
    (tmp_path / "driving_supercombo.onnx").write_bytes(b"SMALL_ONLY" * 400)
    art = consume_big_teacher_for_teach(tmp_path, force_fixture=False)
    assert art.name == BIG_TEACHER_NAME
    assert art.source == "fixture"
    assert art.live is False
    assert "driving_supercombo" in (art.detail or "")
    assert "no small-model fallback" in art.detail or "ignored" in art.detail


def test_checksum_mismatch_raises_and_consume_fixtures(tmp_path, monkeypatch):
    monkeypatch.delenv("DISTILLERY_TEACHER_FIXTURE", raising=False)
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)
    _write_craig_cache(tmp_path, b"CORRUPT_OR_TAMPERED_WEIGHTS" * 200, bad_sha=True)
    with pytest.raises(TeacherChecksumError):
        verify_cached_big_teacher(tmp_path)
    art = consume_big_teacher_for_teach(tmp_path, force_fixture=False)
    assert art.source == "fixture"
    assert art.live is False
    assert art.error
    assert "checksum" in art.error.lower() or "mismatch" in art.error.lower()


def test_force_fixture_never_claims_live(tmp_path):
    _write_craig_cache(tmp_path, b"REAL_LOOKING" * 200)
    art = consume_big_teacher_for_teach(tmp_path, force_fixture=True)
    assert art.source == "fixture"
    assert art.live is False
    assert art.name == BIG_TEACHER_NAME
