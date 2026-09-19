"""Craig health chip — PyTorch device probe honesty."""

from __future__ import annotations

import sys
import types

from distillery_student.device import probe_train_device


def test_torch_missing_is_honest(monkeypatch):
    """When torch cannot import, report torch: missing (not a fake CPU)."""

    def _missing() -> tuple[str, str, str]:
        return "missing", "none", "unknown"

    monkeypatch.setattr(
        "distillery_student.device._probe_torch_device", _missing
    )
    monkeypatch.setattr(
        "distillery_student.device._leftover_tinygrad_note", lambda: None
    )

    info = probe_train_device(force_fixture=False)
    assert info["torch"] == "missing"
    assert info["device_found"] is False
    assert info["device_ready"] is False
    assert info["device_name"] == "none"
    assert "torch: missing" in info["detail"]
    assert "tinygrad" not in info


def test_torch_cpu_device_string(monkeypatch):
    """Importable torch without CUDA/MPS → device_name=cpu."""
    fake = types.ModuleType("torch")
    fake.cuda = types.SimpleNamespace(is_available=lambda: False)
    fake.backends = types.SimpleNamespace(
        mps=types.SimpleNamespace(is_available=lambda: False)
    )
    fake.version = types.SimpleNamespace(hip=None)
    monkeypatch.setitem(sys.modules, "torch", fake)
    monkeypatch.setattr(
        "distillery_student.device._leftover_tinygrad_note", lambda: None
    )

    info = probe_train_device(force_fixture=False)
    assert info["torch"] == "ok"
    assert info["device_ready"] is True
    assert info["device_name"] == "cpu"
    assert info["device_kind"] == "cpu"
    assert info["source"] == "torch"
    assert "tinygrad" not in info  # train key is torch; leftover is tinygrad_note only


def test_torch_cuda_device_string(monkeypatch):
    fake = types.ModuleType("torch")
    fake.cuda = types.SimpleNamespace(
        is_available=lambda: True,
        current_device=lambda: 0,
        device_count=lambda: 1,
    )
    fake.backends = types.SimpleNamespace(
        mps=types.SimpleNamespace(is_available=lambda: False)
    )
    fake.version = types.SimpleNamespace(hip=None)
    monkeypatch.setitem(sys.modules, "torch", fake)
    monkeypatch.setattr(
        "distillery_student.device._leftover_tinygrad_note", lambda: None
    )

    info = probe_train_device()
    assert info["torch"] == "ok"
    assert info["device_name"] == "cuda"
    assert info["device_kind"] == "gpu"


def test_torch_rocm_device_string(monkeypatch):
    fake = types.ModuleType("torch")
    fake.cuda = types.SimpleNamespace(
        is_available=lambda: True,
        current_device=lambda: 0,
        device_count=lambda: 1,
    )
    fake.backends = types.SimpleNamespace(
        mps=types.SimpleNamespace(is_available=lambda: False)
    )
    fake.version = types.SimpleNamespace(hip="6.0.0")
    monkeypatch.setitem(sys.modules, "torch", fake)
    monkeypatch.setattr(
        "distillery_student.device._leftover_tinygrad_note", lambda: None
    )

    info = probe_train_device()
    assert info["torch"] == "ok"
    assert info["device_name"] == "rocm"
    assert info["device_kind"] == "gpu"


def test_torch_mps_device_string(monkeypatch):
    fake = types.ModuleType("torch")
    fake.cuda = types.SimpleNamespace(is_available=lambda: False)
    fake.backends = types.SimpleNamespace(
        mps=types.SimpleNamespace(is_available=lambda: True)
    )
    fake.version = types.SimpleNamespace(hip=None)
    monkeypatch.setitem(sys.modules, "torch", fake)
    monkeypatch.setattr(
        "distillery_student.device._leftover_tinygrad_note", lambda: None
    )

    info = probe_train_device()
    assert info["torch"] == "ok"
    assert info["device_name"] == "mps"
    assert info["device_kind"] == "gpu"


def test_force_fixture_does_not_kill_ready_torch(monkeypatch):
    fake = types.ModuleType("torch")
    fake.cuda = types.SimpleNamespace(is_available=lambda: False)
    fake.backends = types.SimpleNamespace(
        mps=types.SimpleNamespace(is_available=lambda: False)
    )
    fake.version = types.SimpleNamespace(hip=None)
    monkeypatch.setitem(sys.modules, "torch", fake)
    monkeypatch.setattr(
        "distillery_student.device._leftover_tinygrad_note", lambda: None
    )

    info = probe_train_device(force_fixture=True)
    assert info["data_source"] == "fixture"
    assert info["torch"] == "ok"
    assert info["device_ready"] is True
    assert info["device_name"] == "cpu"
