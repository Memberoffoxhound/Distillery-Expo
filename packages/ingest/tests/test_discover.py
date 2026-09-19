"""Discovery helpers — ADB parse, Connect JWT cache, overview shapes."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from distillery_ingest.discover import (
    apply_discovered_overrides,
    clear_connect_jwt,
    clear_dongle_id,
    clear_ssh_config,
    connect_status,
    discover_suggested_dongle_id,
    discovery_overview,
    ensure_dongle_from_cache,
    ensure_ssh_from_cache,
    list_adb_devices,
    normalize_discovered_dongle_id,
    parse_adb_devices_output,
    probe_ssh,
    read_dongle_id_via_adb,
    read_dongle_id_via_ssh,
    set_connect_jwt,
    set_dongle_id,
    set_ssh_config,
    ssh_status,
)
from distillery_ingest.config import load_ingest_config


ADB_SAMPLE = """\
List of devices attached
emulator-5554          device product:sdk_gphone64_x86_64 model:sdk_gphone64_x86_64 device:emu64xa transport_id:1
9A281FFBA0012C         device usb:1-1 product:comma_mici model:mici device:mici transport_id:2
192.168.1.42:5555      device product:comma_mici model:mici device:mici transport_id:3
"""


def test_parse_adb_devices_usb_and_tcp():
    devices = parse_adb_devices_output(ADB_SAMPLE)
    assert len(devices) == 3
    by_id = {d.id: d for d in devices}
    assert by_id["9A281FFBA0012C"].transport == "usb"
    assert by_id["9A281FFBA0012C"].model == "mici"
    assert by_id["9A281FFBA0012C"].suggested_host is None
    tcp = by_id["192.168.1.42:5555"]
    assert tcp.transport == "tcp"
    assert tcp.suggested_host == "192.168.1.42"
    assert tcp.state == "device"


def test_list_adb_devices_without_adb(monkeypatch):
    monkeypatch.setattr(
        "distillery_ingest.discover._which",
        lambda _name: None,
    )
    out = list_adb_devices()
    assert out["ok"] is False
    assert out["adb_available"] is False
    assert out["devices"] == []


def test_set_connect_jwt_persist_and_status(tmp_path, monkeypatch):
    cache = tmp_path / "connect_jwt"
    monkeypatch.setattr("distillery_ingest.discover._JWT_CACHE", cache)
    monkeypatch.delenv("COMMA_JWT", raising=False)
    monkeypatch.delenv("CONNECT_JWT", raising=False)
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)

    status = set_connect_jwt("abcdEFGHijklMNOP", persist=True)
    assert status["configured"] is True
    assert status["jwt_masked"] == "abcd…MNOP"
    assert cache.is_file()
    assert os.environ.get("COMMA_JWT") == "abcdEFGHijklMNOP"

    # clear env; ensure_jwt_from_cache rehydrates from .cache file
    monkeypatch.delenv("COMMA_JWT", raising=False)
    monkeypatch.delenv("CONNECT_JWT", raising=False)
    from distillery_ingest.discover import ensure_jwt_from_cache

    token = ensure_jwt_from_cache()
    assert token == "abcdEFGHijklMNOP"
    assert os.environ.get("COMMA_JWT") == "abcdEFGHijklMNOP"

    cleared = clear_connect_jwt()
    assert cleared["configured"] is False
    assert not cache.is_file()


def test_apply_discovered_overrides_tcp_device():
    cfg = load_ingest_config()
    updated = apply_discovered_overrides(cfg, device_id="10.0.0.5:5555")
    assert updated.ssh_host == "10.0.0.5"
    explicit = apply_discovered_overrides(
        cfg, device_id="10.0.0.5:5555", ssh_host="10.0.0.9"
    )
    assert explicit.ssh_host == "10.0.0.9"


def test_discovery_overview_shape(monkeypatch):
    monkeypatch.setenv("DISTILLERY_INGEST_FIXTURE", "1")
    monkeypatch.delenv("COMMA_JWT", raising=False)
    monkeypatch.delenv("MICI_SSH_HOST", raising=False)
    monkeypatch.setattr(
        "distillery_ingest.discover.list_adb_devices",
        lambda: {"ok": True, "adb_available": True, "error": None, "devices": []},
    )
    snap = discovery_overview()
    assert "devices" in snap and "connect" in snap and "ssh" in snap
    assert snap["fixture"]["label"] == "fixture"
    assert snap["fixture"]["offline_fallback"] is True
    assert snap["sources"]["fixture"] is True


def test_set_ssh_config_persist_and_status(tmp_path, monkeypatch):
    cache = tmp_path / "ssh_config.json"
    monkeypatch.setattr("distillery_ingest.discover._SSH_CACHE", cache)
    for key in (
        "MICI_SSH_HOST",
        "COMMA_SSH_HOST",
        "MICI_SSH_USER",
        "COMMA_SSH_USER",
        "MICI_SSH_PORT",
        "COMMA_SSH_PORT",
        "MICI_SSH_KEY",
        "COMMA_SSH_KEY",
        "DISTILLERY_INGEST_FIXTURE",
    ):
        monkeypatch.delenv(key, raising=False)

    status = set_ssh_config(
        "192.168.1.50",
        user="comma",
        port=22,
        identity_path="/tmp/id_ed25519",
        persist=True,
    )
    assert status["configured"] is True
    assert status["host"] == "192.168.1.50"
    assert status["user"] == "comma"
    assert status["port"] == 22
    assert status["identity_path"] == "/tmp/id_ed25519"
    assert status["key_set"] is True
    assert cache.is_file()
    assert os.environ.get("MICI_SSH_HOST") == "192.168.1.50"

    # clear env; ensure_ssh_from_cache rehydrates
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
        monkeypatch.delenv(key, raising=False)

    data = ensure_ssh_from_cache()
    assert data is not None
    assert data["host"] == "192.168.1.50"
    assert os.environ.get("MICI_SSH_HOST") == "192.168.1.50"

    st = ssh_status()
    assert st["configured"] is True
    assert st["port"] == 22
    assert st["cache_path"] is not None

    cleared = clear_ssh_config()
    assert cleared["configured"] is False
    assert not cache.is_file()


def test_set_ssh_config_requires_host():
    import pytest

    with pytest.raises(ValueError, match="host"):
        set_ssh_config("")


def test_probe_ssh_honest_fail_when_unconfigured(monkeypatch):
    monkeypatch.delenv("MICI_SSH_HOST", raising=False)
    monkeypatch.delenv("COMMA_SSH_HOST", raising=False)
    monkeypatch.setattr(
        "distillery_ingest.discover._SSH_CACHE",
        Path("/nonexistent/ssh_config.json"),
    )
    out = probe_ssh(timeout=2.0)
    assert out["ok"] is False
    assert "not configured" in (out.get("error") or "").lower()


def test_discovery_overview_ssh_fields(monkeypatch):
    monkeypatch.setenv("DISTILLERY_INGEST_FIXTURE", "1")
    monkeypatch.setenv("MICI_SSH_HOST", "10.0.0.8")
    monkeypatch.setenv("MICI_SSH_USER", "comma")
    monkeypatch.setenv("MICI_SSH_PORT", "2222")
    monkeypatch.setattr(
        "distillery_ingest.discover.list_adb_devices",
        lambda: {"ok": True, "adb_available": True, "error": None, "devices": []},
    )
    snap = discovery_overview()
    ssh = snap["ssh"]
    assert ssh["host"] == "10.0.0.8"
    assert ssh["port"] == 2222
    assert "identity_path" in ssh
    assert "cache_path" in ssh


def test_set_dongle_id_persist_and_status(tmp_path, monkeypatch):
    cache = tmp_path / "dongle_id"
    monkeypatch.setattr("distillery_ingest.discover._DONGLE_CACHE", cache)
    monkeypatch.setattr("distillery_ingest.config._DONGLE_CACHE", cache)
    monkeypatch.delenv("DISTILLERY_DONGLE_ID", raising=False)
    monkeypatch.delenv("DISTILLERY_INGEST_FIXTURE", raising=False)

    status = set_dongle_id("abcdef0123456789", persist=True)
    assert status["configured"] is True
    assert status["dongle_id"] == "abcdef0123456789"
    assert cache.is_file()
    assert os.environ.get("DISTILLERY_DONGLE_ID") == "abcdef0123456789"

    monkeypatch.delenv("DISTILLERY_DONGLE_ID", raising=False)
    token = ensure_dongle_from_cache()
    assert token == "abcdef0123456789"
    assert os.environ.get("DISTILLERY_DONGLE_ID") == "abcdef0123456789"

    cleared = clear_dongle_id()
    assert cleared["configured"] is False
    assert cleared.get("dongle_id") in (None, "")
    assert not cache.is_file()



def test_normalize_discovered_dongle_id():
    assert normalize_discovered_dongle_id("AABBCCDDEEFF0011") == "aabbccddeeff0011"
    # Labeled demo/fixture id must never be suggested / auto-hydrated
    assert normalize_discovered_dongle_id("3e2de7ed673817c2") is None
    assert normalize_discovered_dongle_id("UnregisteredDevice") is None
    assert normalize_discovered_dongle_id("") is None
    # ADB serial / short hex must not be treated as a dongle id
    assert normalize_discovered_dongle_id("9A281FFBA0012C") is None
    assert normalize_discovered_dongle_id("192.168.1.42") is None


def test_discover_suggested_dongle_id_from_adb(monkeypatch):
    monkeypatch.setattr(
        "distillery_ingest.discover.list_adb_devices",
        lambda: {
            "ok": True,
            "adb_available": True,
            "error": None,
            "devices": [
                {
                    "id": "9A281FFBA0012C",
                    "model": "mici",
                    "device": "mici",
                    "product": "comma_mici",
                    "state": "device",
                }
            ],
        },
    )
    monkeypatch.setattr(
        "distillery_ingest.discover.read_dongle_id_via_adb",
        lambda **kwargs: {
            "ok": True,
            "dongle_id": "deadbeefcafebabe",
            "serial": kwargs.get("serial"),
            "error": None,
        },
    )
    monkeypatch.setattr(
        "distillery_ingest.discover.read_dongle_id_via_ssh",
        lambda **kwargs: {"ok": False, "dongle_id": None, "error": "SSH host not configured"},
    )
    out = discover_suggested_dongle_id()
    assert out["suggested_dongle_id"] == "deadbeefcafebabe"
    assert out["discovered_from"] == "adb"
    assert out["dongle_discovery_source"] == "adb"
    assert out["dongle_discovery_serial"] == "9A281FFBA0012C"


def test_discover_suggested_dongle_id_falls_back_to_ssh(monkeypatch):
    monkeypatch.setenv("MICI_SSH_HOST", "192.168.1.50")
    monkeypatch.setattr(
        "distillery_ingest.discover.list_adb_devices",
        lambda: {"ok": True, "adb_available": True, "error": None, "devices": []},
    )
    monkeypatch.setattr(
        "distillery_ingest.discover.read_dongle_id_via_ssh",
        lambda **kwargs: {"ok": True, "dongle_id": "feedfacefeedface", "error": None},
    )
    out = discover_suggested_dongle_id()
    assert out["suggested_dongle_id"] == "feedfacefeedface"
    assert out["discovered_from"] == "ssh"
    assert out["dongle_discovery_source"] == "ssh"


def test_discover_suggested_dongle_id_honest_null(monkeypatch):
    monkeypatch.setattr(
        "distillery_ingest.discover.list_adb_devices",
        lambda: {"ok": True, "adb_available": True, "error": None, "devices": []},
    )
    monkeypatch.setattr(
        "distillery_ingest.discover.read_dongle_id_via_ssh",
        lambda **kwargs: {"ok": False, "dongle_id": None, "error": "SSH host not configured"},
    )
    out = discover_suggested_dongle_id()
    assert out["suggested_dongle_id"] is None
    assert out["discovered_from"] is None
    assert out["dongle_discovery_source"] is None


def test_discovery_overview_includes_suggested(monkeypatch, tmp_path):
    monkeypatch.setenv("DISTILLERY_INGEST_FIXTURE", "1")
    monkeypatch.delenv("DISTILLERY_DONGLE_ID", raising=False)
    cache = tmp_path / "dongle_id"
    monkeypatch.setattr("distillery_ingest.discover._DONGLE_CACHE", cache)
    monkeypatch.setattr("distillery_ingest.config._DONGLE_CACHE", cache)
    monkeypatch.setattr(
        "distillery_ingest.discover.list_adb_devices",
        lambda: {"ok": True, "adb_available": True, "error": None, "devices": []},
    )
    monkeypatch.setattr(
        "distillery_ingest.discover.discover_suggested_dongle_id",
        lambda **kwargs: {
            "suggested_dongle_id": "aabbccddeeff0011",
            "discovered_from": "ssh",
            "dongle_discovery_source": "ssh",
            "dongle_discovery_serial": None,
            "dongle_discovery_error": None,
        },
    )
    snap = discovery_overview()
    assert snap["suggested_dongle_id"] == "aabbccddeeff0011"
    assert snap["discovered_from"] == "ssh"
    assert snap["dongle_discovery_source"] == "ssh"
    # Auto-hydrate persists the discovered id (not a demo default)
    assert snap.get("dongle_id") == "aabbccddeeff0011"
    assert snap.get("auto_hydrated") is True
