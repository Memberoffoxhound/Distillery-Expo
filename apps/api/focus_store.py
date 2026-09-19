"""Thin focus-coach store — .cache/focus_history.json (coach contract for Graig)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FOCUS_CACHE = _REPO_ROOT / ".cache" / "focus_history.json"
_MAX_HISTORY = 40


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty() -> dict[str, Any]:
    return {"focus": None, "history": []}


def load_focus() -> dict[str, Any]:
    """Return {focus, history[]} — history newest-first."""
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
        cleaned.append(
            {
                "id": str(item.get("id") or uuid4()),
                "text": text,
                "ts": str(item.get("ts") or _now()),
            }
        )
    return {"focus": focus, "history": cleaned}


def save_focus(text: str, *, persist: bool = True) -> dict[str, Any]:
    """Set current focus and prepend history. Returns {focus, history[]}."""
    text = (text or "").strip()
    if not text:
        raise ValueError("focus text required")
    state = load_focus()
    entry = {"id": str(uuid4()), "text": text, "ts": _now()}
    history = [entry] + [
        h for h in state["history"] if str(h.get("text") or "").strip() != text
    ]
    history = history[:_MAX_HISTORY]
    out = {"focus": text, "history": history}
    if persist:
        _FOCUS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _FOCUS_CACHE.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return out
