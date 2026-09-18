"""big_driving_supercombo fetch/cache — no small-model fallback."""

from __future__ import annotations

from pathlib import Path

import pytest

from distillery_teacher.comma_master import BIG_TEACHER_NAME, select_comma_master_teacher
from distillery_teacher.download import (
    TeacherArtifactStatus,
    cached_big_teacher_ok,
    ensure_big_teacher_onnx,
)


def test_select_default_is_big_only(monkeypatch):
    monkeypatch.setenv("DISTILLERY_TEACHER_FIXTURE", "1")
    t = select_comma_master_teacher(force_fixture=True)
    assert t is not None
    assert t["name"] == BIG_TEACHER_NAME
    assert t["name"] != "driving_supercombo"
    assert "label" in t
    assert "big_driving_supercombo" in t["label"]
    assert t["live"] is False
    assert t["source"] == "fixture"


def test_select_never_defaults_to_small(monkeypatch):
    monkeypatch.setenv("DISTILLERY_TEACHER_FIXTURE", "1")
    t = select_comma_master_teacher(None, force_fixture=True)
    assert t["name"] == "big_driving_supercombo"


def test_ensure_fixture_labeled(tmp_path, monkeypatch):
    monkeypatch.setenv("DISTILLERY_TEACHER_FIXTURE", "1")
    st = ensure_big_teacher_onnx(tmp_path, force_fixture=True)
    assert st.live is False
    assert st.source == "fixture"
    assert st.name == BIG_TEACHER_NAME
    assert "fixture" in st.label
    assert BIG_TEACHER_NAME in st.label
    assert st.path is None


def test_ensure_offline_no_small_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("DISTILLERY_TEACHER_FIXTURE", raising=False)
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)
    # Force all URLs to fail quickly
    monkeypatch.setattr(
        "distillery_teacher.download._URL_CANDIDATES",
        ["http://127.0.0.1:1/nope.onnx"],
    )
    st = ensure_big_teacher_onnx(tmp_path, timeout=1.0)
    assert st.live is False
    assert st.source == "fixture"
    assert st.name == BIG_TEACHER_NAME
    assert st.ok is False
    assert "no small-model" in st.detail.lower() or "fallback" in st.detail.lower()
    assert not (tmp_path / "driving_supercombo.onnx").exists()


def test_cache_skip_when_checksum_ok(tmp_path, monkeypatch):
    monkeypatch.delenv("DISTILLERY_TEACHER_FIXTURE", raising=False)
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)
    onnx = tmp_path / "big_driving_supercombo.onnx"
    payload = b"FAKE_ONNX_BYTES_FOR_CACHE_TEST" * 40  # >1KiB
    onnx.write_bytes(payload)
    # First call writes sidecar via cached path
    st1 = cached_big_teacher_ok(tmp_path)
    assert st1 is not None
    assert st1.cached is True
    assert st1.live is True
    assert st1.sha256
    assert "comma master" in st1.label

    calls = {"n": 0}

    def _boom(*_a, **_k):
        calls["n"] += 1
        raise RuntimeError("should not download")

    monkeypatch.setattr("distillery_teacher.download._download_url", _boom)
    st2 = ensure_big_teacher_onnx(tmp_path)
    assert calls["n"] == 0
    assert st2.cached is True
    assert st2.path == onnx


def test_cache_redownload_on_checksum_mismatch(tmp_path, monkeypatch):
    monkeypatch.delenv("DISTILLERY_TEACHER_FIXTURE", raising=False)
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)
    onnx = tmp_path / "big_driving_supercombo.onnx"
    onnx.write_bytes(b"ORIGINAL_BYTES_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX")
    sha = tmp_path / "big_driving_supercombo.onnx.sha256"
    sha.write_text("deadbeef" * 8 + "\n", encoding="utf-8")

    def _fake_download(url, dest, *, progress=None, timeout=120.0):
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = b"NEW_ONNX_CONTENT_YYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYY"
        dest.write_bytes(data)
        if progress:
            progress(1.0, "done")
        return len(data)

    monkeypatch.setattr("distillery_teacher.download._download_url", _fake_download)
    monkeypatch.setattr(
        "distillery_teacher.download._URL_CANDIDATES",
        ["http://example.test/big.onnx"],
    )
    st = ensure_big_teacher_onnx(tmp_path)
    assert st.ok is True
    assert st.live is True
    assert st.cached is False
    assert onnx.read_bytes().startswith(b"NEW_ONNX")
    assert sha.read_text().strip() == st.sha256


def test_api_teachers_default_big(monkeypatch):
    monkeypatch.setenv("DISTILLERY_TEACHER_FIXTURE", "1")
    monkeypatch.setenv("DISTILLERY_INGEST_FIXTURE", "1")
    from fastapi.testclient import TestClient
    from api.main import app

    with TestClient(app) as client:
        r = client.get("/teachers", params={"force_fixture": True})
    assert r.status_code == 200
    data = r.json()
    assert data["default_teacher"] == BIG_TEACHER_NAME
    assert data["selected"]["name"] == BIG_TEACHER_NAME
    assert "big_driving_supercombo" in (data.get("label") or "")
    assert data["selected"]["live"] is False
