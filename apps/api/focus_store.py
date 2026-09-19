"""Focus-coach store — .cache/focus_history.json + structured coach for train."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from distillery_student.focus import coach_focus

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FOCUS_CACHE = _REPO_ROOT / ".cache" / "focus_history.json"
_MAX_HISTORY = 40


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty() -> dict[str, Any]:
    return {"focus": None, "history": [], "coached": None}


def _clean_coached(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    if not isinstance(raw.get("tags"), list):
        return None
    return raw


def load_focus() -> dict[str, Any]:
    """Return {focus, history[], coached} — history newest-first.

    ``coached`` is the structured training focus train/teach consume.
    """
    if not _FOCUS_CACHE.is_file():
        return _empty()
    try:
        raw = json.loads(_FOCUS_CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty()
    if not isinstance(raw, dict):
        return _empty()
    focus = raw.get("focus")
    if focus is not None:
        focus = str(focus).strip() or None
    history = raw.get("history") or []
    if not isinstance(history, list):
        history = []
    cleaned: list[dict[str, Any]] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        entry: dict[str, Any] = {
            "id": str(item.get("id") or uuid4()),
            "text": text,
            "ts": str(item.get("ts") or _now()),
        }
        coached = _clean_coached(item.get("coached"))
        if coached is None:
            coached = coach_focus(text)
        if coached is not None:
            entry["coached"] = coached
        cleaned.append(entry)

    coached = _clean_coached(raw.get("coached"))
    if coached is None and focus:
        coached = coach_focus(focus)
    return {"focus": focus, "history": cleaned, "coached": coached}


def save_focus(text: str, *, persist: bool = True) -> dict[str, Any]:
    """Set current focus, coach it, prepend history. Returns {focus, history, coached}."""
    text = (text or "").strip()
    if not text:
        raise ValueError("focus text required")
    state = load_focus()
    coached = coach_focus(text)
    entry: dict[str, Any] = {
        "id": str(uuid4()),
        "text": text,
        "ts": _now(),
        "coached": coached,
    }
    history = [entry] + [
        h for h in state["history"] if str(h.get("text") or "").strip() != text
    ]
    history = history[:_MAX_HISTORY]
    out = {"focus": text, "history": history, "coached": coached}
    if persist:
        _FOCUS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _FOCUS_CACHE.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return out


def train_focus_payload(text: str | None = None) -> dict[str, Any] | None:
    """Structured focus train should use — body text or stored coach."""
    if text and str(text).strip():
        return coach_focus(str(text).strip())
    state = load_focus()
    if state.get("coached"):
        return state["coached"]
    if state.get("focus"):
        return coach_focus(str(state["focus"]))
    return None
