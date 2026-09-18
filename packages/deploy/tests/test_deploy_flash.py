"""Deploy flash — eval gate, honest SSH skip, mocked scp success."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import asyncio

import pytest

from distillery_deploy.artifacts import prepare_push_source, resolve_local_onnx
from distillery_deploy.config import DEFAULT_MODEL_PATH, load_deploy_config
from distillery_deploy.ssh_push import push_supercombo_ssh
from distillery_deploy.pipeline import run_flash_pipeline


@pytest.fixture()
def export_dir(tmp_path, monkeypatch):
    d = tmp_path / "export"
    d.mkdir()
    monkeypatch.setenv("MICI_SSH_HOST", "")
    monkeypatch.delenv("MICI_SSH_HOST", raising=False)
    monkeypatch.delenv("COMMA_SSH_HOST", raising=False)
    return d


def test_resolve_prefers_driving_supercombo(export_dir, monkeypatch):
    preferred = export_dir / "driving_supercombo.onnx"
    preferred.write_bytes(b"onnx")
    legacy = export_dir / "student_modelV2_io.onnx"
    legacy.write_bytes(b"legacy")
    cfg = load_deploy_config()
    # Patch export_dir via dataclass replace
    from dataclasses import replace

    cfg = replace(cfg, export_dir=export_dir)
    assert resolve_local_onnx(cfg=cfg).name == "driving_supercombo.onnx"
    assert resolve_local_onnx(str(legacy), cfg=cfg).name == "student_modelV2_io.onnx"


def test_resolve_falls_back_to_legacy(export_dir):
    from dataclasses import replace

    legacy = export_dir / "student_modelV2_io.onnx"
    legacy.write_bytes(b"legacy")
    cfg = replace(load_deploy_config(), export_dir=export_dir)
    assert resolve_local_onnx(cfg=cfg) == legacy


def test_prepare_renames_legacy(tmp_path):
    src = tmp_path / "student_modelV2_io.onnx"
    src.write_bytes(b"x")
    out = prepare_push_source(src, staging_dir=tmp_path / "stage")
    assert out.name == "driving_supercombo.onnx"
    assert out.read_bytes() == b"x"


def test_push_no_ssh_honest_skip(export_dir, monkeypatch):
    from dataclasses import replace

    art = export_dir / "driving_supercombo.onnx"
    art.write_bytes(b"model")
    monkeypatch.delenv("MICI_SSH_HOST", raising=False)
    cfg = replace(load_deploy_config(), export_dir=export_dir, ssh_host=None)
    result = push_supercombo_ssh(art, cfg=cfg)
    assert result.device_write is False
    assert result.live is False
    assert result.skipped is True
    assert result.reason == "ssh_unavailable"
    assert "live=false" in result.detail.lower() or "MICI_SSH_HOST" in result.detail


def test_push_mocked_scp_success(export_dir, monkeypatch):
    from dataclasses import replace

    art = export_dir / "driving_supercombo.onnx"
    art.write_bytes(b"model")
    monkeypatch.setenv("MICI_SSH_HOST", "mici.local")
    monkeypatch.setenv("MICI_SSH_USER", "comma")
    cfg = replace(
        load_deploy_config(),
        export_dir=export_dir,
        ssh_host="mici.local",
        ssh_user="comma",
        remote_model_path=DEFAULT_MODEL_PATH,
    )
    seen = {}

    def fake_scp(cmd, **kwargs):
        seen["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    result = push_supercombo_ssh(art, cfg=cfg, scp_runner=fake_scp)
    assert result.ok is True
    assert result.live is True
    assert result.device_write is True
    assert result.remote_path.endswith("driving_supercombo.onnx")
    assert "scp" in seen["cmd"][0]
    assert any(str(c).endswith("driving_supercombo.onnx") or "driving_supercombo.onnx" in str(c) for c in seen["cmd"])


def test_pipeline_refuses_without_eval():
    events = []

    async def emit(e):
        events.append(e)

    async def _run():
        return await run_flash_pipeline("j1", emit, confirmed=True, eval_passed=False)

    out = asyncio.run(_run())
    assert out["device_write"] is False
    assert out["reason"] == "eval_gate"
    assert any(e.get("stage") == "flash" for e in events)


def test_pipeline_no_ssh_honest(export_dir, monkeypatch):
    from dataclasses import replace

    art = export_dir / "driving_supercombo.onnx"
    art.write_bytes(b"model")
    monkeypatch.delenv("MICI_SSH_HOST", raising=False)
    cfg = replace(load_deploy_config(), export_dir=export_dir, ssh_host=None)
    events = []

    async def emit(e):
        events.append(e)

    async def _run():
        return await run_flash_pipeline(
            "j2",
            emit,
            confirmed=True,
            eval_passed=True,
            onnx_path=str(art),
            cfg=cfg,
            tick=0.0,
        )

    out = asyncio.run(_run())
    assert out["device_write"] is False
    assert out["live"] is False
    blob = str(events).lower()
    assert "live=false" in blob or "ssh" in blob


def test_pipeline_mocked_scp_success(export_dir):
    from dataclasses import replace

    art = export_dir / "student_modelV2_io.onnx"
    art.write_bytes(b"legacy-model")
    cfg = replace(
        load_deploy_config(),
        export_dir=export_dir,
        ssh_host="mici.test",
        remote_model_path=DEFAULT_MODEL_PATH,
    )

    def fake_scp(cmd, **kwargs):
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    events = []

    async def emit(e):
        events.append(e)

    async def _run():
        return await run_flash_pipeline(
            "j3",
            emit,
            confirmed=True,
            eval_passed=True,
            onnx_path=str(art),
            cfg=cfg,
            tick=0.0,
            scp_runner=fake_scp,
        )

    out = asyncio.run(_run())
    assert out["device_write"] is True
    assert out["live"] is True
    assert out["remote_path"].endswith("driving_supercombo.onnx")
