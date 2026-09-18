"""List stock driving teachers from commaai/openpilot master (no Chestnut).

Online: probe GitHub contents API / known artifact refs.
Offline / fixture: return clearly labeled ``source=fixture`` teacher entries.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

# Known master-era stock teacher artifacts (post combined-supercombo era).
# Paths relative to commaai/openpilot repo root on branch ``master``.
BIG_TEACHER_NAME = "big_driving_supercombo"
BIG_TEACHER_REF = "selfdrive/modeld/models/big_driving_supercombo.onnx"

_KNOWN_MASTER_TEACHERS: list[dict[str, str]] = [
    {
        "name": "big_driving_supercombo",
        "version": "master",
        "ref": "selfdrive/modeld/models/big_driving_supercombo.onnx",
        "role": "big",
    },
    # Listed for catalog transparency only — NEVER the default / never a silent fallback.
    {
        "name": "driving_supercombo",
        "version": "master",
        "ref": "selfdrive/modeld/models/driving_supercombo.onnx",
        "role": "stock",
    },
]

_GITHUB_CONTENTS = (
    "https://api.github.com/repos/commaai/openpilot/contents/"
    "selfdrive/modeld/models?ref=master"
)
_RAW_BASE = "https://raw.githubusercontent.com/commaai/openpilot/master/"
_BLOB_BASE = "https://github.com/commaai/openpilot/blob/master/"


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes")


def _fixture_teachers(*, reason: str) -> list[dict[str, Any]]:
    """Offline / forced fixture listing — never claim live comma master."""
    out: list[dict[str, Any]] = []
    for known in _KNOWN_MASTER_TEACHERS:
        out.append(
            {
                "name": known["name"],
                "version": "fixture",
                "source": "fixture",
                "artifact_ref": known["ref"],
                "artifact_url": None,
                "live": False,
                "teacher": known["name"],
                "role": known["role"],
                "label": f"fixture · {known['name']}",
                "detail": f"fixture teacher — {reason} (live=false / not licensed; big preferred; no Chestnut)",
            }
        )
    # Always include the named Cinque/supercombo alias used elsewhere in Distillery
    out.append(
        {
            "name": "Cinque/supercombo",
            "version": "fixture",
            "source": "fixture",
            "artifact_ref": "fixture://Cinque/supercombo",
            "artifact_url": None,
            "live": False,
            "teacher": "Cinque/supercombo",
            "role": "alias",
            "detail": f"fixture alias for stock supercombo — {reason}",
        }
    )
    return out


def _fetch_github_models(timeout: float = 5.0) -> list[dict[str, Any]] | None:
    """Return GitHub contents entries for *.onnx driving models, or None on failure."""
    try:
        req = urllib.request.Request(
            _GITHUB_CONTENTS,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "distillery-expo-teacher-list",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, list):
        return None
    return [e for e in data if isinstance(e, dict)]


def _entry_from_github(entry: dict[str, Any]) -> dict[str, Any] | None:
    name = str(entry.get("name") or "")
    if not name.endswith(".onnx"):
        return None
    # Stock driving teachers only — exclude dmonitoring / chestnut / unrelated
    lower = name.lower()
    if "chestnut" in lower or "dmonitoring" in lower or "driver" in lower:
        return None
    if "driving" not in lower and "supercombo" not in lower:
        return None
    path = str(entry.get("path") or f"selfdrive/modeld/models/{name}")
    download = entry.get("download_url") or (_RAW_BASE + path)
    stem = name[: -len(".onnx")]
    role = "big" if stem.startswith("big_") else "stock"
    label_name = stem
    live_label = f"comma master · {label_name}"
    return {
        "name": stem,
        "version": "master",
        "source": "commaai/openpilot@master",
        "artifact_ref": path,
        "artifact_url": download,
        "html_url": entry.get("html_url") or (_BLOB_BASE + path),
        "sha": entry.get("sha"),
        "size": entry.get("size"),
        "live": True,
        "teacher": stem,
        "role": role,
        "label": live_label,
        "detail": "listed from commaai/openpilot master models/",
    }


def list_comma_master_teachers(
    *,
    force_fixture: bool = False,
    timeout: float = 5.0,
) -> list[dict[str, Any]]:
    """List current big/stock driving teachers from openpilot master.

    Returns list of dicts with keys including:
      name, version, source, artifact_url (or None), artifact_ref

    Offline / ``DISTILLERY_TEACHER_FIXTURE=1`` / ``force_fixture`` ->
    ``source=fixture``, ``live=false`` (last-resort CI only; never the default).
    Never lists Chestnut. ``DISTILLERY_INGEST_FIXTURE`` does not force teacher fixture.
    """
    if force_fixture or _env_truthy("DISTILLERY_TEACHER_FIXTURE"):
        return _fixture_teachers(reason="force_fixture / DISTILLERY_TEACHER_FIXTURE")

    entries = _fetch_github_models(timeout=timeout)
    if entries is None:
        return _fixture_teachers(reason="offline or GitHub unreachable")

    teachers: list[dict[str, Any]] = []
    for entry in entries:
        parsed = _entry_from_github(entry)
        if parsed is None:
            continue
        teachers.append(parsed)

    if not teachers:
        # API returned something but no driving onnx — fall back to known refs
        # still labeled as catalog (not live download verified)
        for known in _KNOWN_MASTER_TEACHERS:
            teachers.append(
                {
                    "name": known["name"],
                    "version": "master",
                    "source": "commaai/openpilot@master",
                    "artifact_ref": known["ref"],
                    "artifact_url": _RAW_BASE + known["ref"],
                    "html_url": _BLOB_BASE + known["ref"],
                    "live": True,
                    "teacher": known["name"],
                    "role": known["role"],
                    "label": f"comma master · {known['name']}",
                    "detail": "known master catalog (GitHub listing empty/unexpected)",
                }
            )

    # Filter any Chestnut slip
    teachers = [t for t in teachers if "chestnut" not in str(t.get("name", "")).lower()]
    for t in teachers:
        if "label" not in t:
            if t.get("live") and t.get("source") != "fixture":
                t["label"] = f"comma master · {t.get('name')}"
            else:
                t["label"] = f"fixture · {t.get('name')}"
    # Stable order: big first
    teachers.sort(key=lambda x: 0 if x.get("name") == BIG_TEACHER_NAME else 1)
    return teachers


def _display_label(teacher: dict[str, Any]) -> str:
    """UI/readiness label — big teacher only branding."""
    name = str(teacher.get("name") or BIG_TEACHER_NAME)
    if teacher.get("live") and teacher.get("source") != "fixture":
        return f"comma master · {name}"
    return f"fixture · {name}"


def select_comma_master_teacher(
    name: str | None = None,
    *,
    force_fixture: bool = False,
) -> dict[str, Any] | None:
    """Pick teacher by name. Default: big_driving_supercombo ONLY.

    Never silently falls back to driving_supercombo / small model.
    Offline fixture still labels the *big* teacher (live=false).
    """
    teachers = list_comma_master_teachers(force_fixture=force_fixture)
    if not teachers:
        return None

    def _enrich(t: dict[str, Any]) -> dict[str, Any]:
        out = dict(t)
        out.setdefault("role", "big" if str(out.get("name", "")).startswith("big_") else out.get("role"))
        out["label"] = _display_label(out)
        return out

    if name:
        needle = name.lower().strip()
        # Aliases that mean "the big teacher"
        if needle in (
            "big",
            "big_driving_supercombo",
            "cinque/supercombo",
            "cinque",
            "default",
        ):
            needle = BIG_TEACHER_NAME
        # Explicit small-model request: do not auto-swap to big, but also do not
        # pretend small is the default — return match only if listed.
        for t in teachers:
            if t.get("name", "").lower() == needle or t.get("teacher", "").lower() == needle:
                return _enrich(t)
        return None

    # Default: big_driving_supercombo ONLY — no small-model fallback.
    for t in teachers:
        if t.get("name") == BIG_TEACHER_NAME:
            return _enrich(t)
    # Fixture / listing without big entry → synthesize labeled fixture big gap
    return _enrich(
        {
            "name": BIG_TEACHER_NAME,
            "version": "fixture",
            "source": "fixture",
            "artifact_ref": BIG_TEACHER_REF,
            "artifact_url": None,
            "live": False,
            "teacher": BIG_TEACHER_NAME,
            "role": "big",
            "detail": (
                "big_driving_supercombo unavailable — fixture labeled "
                "(live=false; no driving_supercombo fallback; no Chestnut)"
            ),
        }
    )
