"""Plain-English training focus → structured coach spec for train/teach.

Deterministic keyword coach (ship-today). No external LLM call; tags/weights/
curriculum hints hang onto the existing PyTorch distill path.
"""

from __future__ import annotations

import re
from typing import Any

# (tag, weight, compiled patterns) — first match wins per tag
_TAG_RULES: list[tuple[str, float, re.Pattern[str]]] = [
    ("stop_lights", 1.6, re.compile(r"\b(stop\s*lights?|traffic\s*lights?|red\s*lights?|stoplights?)\b", re.I)),
    ("stop_signs", 1.6, re.compile(r"\b(stop\s*signs?|stopsigns?)\b", re.I)),
    ("cut_ins", 1.8, re.compile(r"\b(cut[-\s]?ins?|cut[-\s]?ting\s+in|lane\s+cut)\b", re.I)),
    ("lane_change", 1.5, re.compile(r"\b(lane\s*changes?|changing\s+lanes?)\b", re.I)),
    ("lead_vehicle", 1.4, re.compile(r"\b(lead(\s+vehicle)?|following|car\s+ahead|acc\b|gap\s+control)\b", re.I)),
    ("curves", 1.4, re.compile(r"\b(curves?|corners?|turns?|bends?)\b", re.I)),
    ("pedestrians", 1.7, re.compile(r"\b(pedestrians?|people\s+crossing|crosswalks?)\b", re.I)),
    ("cyclists", 1.5, re.compile(r"\b(cyclists?|bicycl(?:e|ist)s?|bikes?)\b", re.I)),
    ("merges", 1.5, re.compile(r"\b(merges?|merging|on[-\s]?ramps?)\b", re.I)),
    ("roundabouts", 1.4, re.compile(r"\b(roundabouts?|traffic\s+circles?)\b", re.I)),
    ("highway", 1.2, re.compile(r"\b(highways?|freeways?|interstates?)\b", re.I)),
    ("night", 1.3, re.compile(r"\b(night|dark|low\s*light)\b", re.I)),
    ("rain", 1.3, re.compile(r"\b(rain|wet|storm)\b", re.I)),
    ("parking", 1.2, re.compile(r"\b(parking|parked\s+cars?)\b", re.I)),
]

# Which output heads a tag should emphasize (train soft-label heads)
_TAG_HEADS: dict[str, tuple[str, ...]] = {
    "stop_lights": ("plan_long", "desire"),
    "stop_signs": ("plan_long", "desire"),
    "cut_ins": ("plan_lat", "desire"),
    "lane_change": ("plan_lat", "desire"),
    "lead_vehicle": ("plan_long",),
    "curves": ("plan_lat",),
    "pedestrians": ("plan_long", "desire"),
    "cyclists": ("plan_lat", "desire"),
    "merges": ("plan_lat", "desire"),
    "roundabouts": ("plan_lat", "desire"),
    "highway": ("plan_long",),
    "night": ("desire",),
    "rain": ("plan_lat", "plan_long"),
    "parking": ("plan_lat", "plan_long"),
}

# 8-dim student stub: dims 0-3 ~ lateral/desire-ish, 4-7 ~ longitudinal-ish
_HEAD_DIMS: dict[str, tuple[int, ...]] = {
    "desire": (0, 1),
    "plan_lat": (2, 3, 4),
    "plan_long": (5, 6, 7),
}

_DEFAULT_LOSS = {"desire": 1.0, "plan_lat": 1.0, "plan_long": 1.0}
COACH_VERSION = 1


def _normalize_text(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"\s+", " ", t)
    return t


def _match_tags(text: str) -> list[tuple[str, float]]:
    found: list[tuple[str, float]] = []
    seen: set[str] = set()
    for tag, weight, pat in _TAG_RULES:
        if tag in seen:
            continue
        if pat.search(text):
            found.append((tag, weight))
            seen.add(tag)
    return found


def _loss_weights(tags: list[tuple[str, float]]) -> dict[str, float]:
    weights = dict(_DEFAULT_LOSS)
    if not tags:
        return weights
    for tag, tw in tags:
        for head in _TAG_HEADS.get(tag, ()):
            weights[head] = max(weights[head], 1.0 + 0.35 * tw)
    for k, v in list(weights.items()):
        weights[k] = round(min(2.5, v), 3)
    return weights


def _dim_weights(loss_w: dict[str, float], n: int = 8) -> list[float]:
    dims = [1.0] * n
    for head, idxs in _HEAD_DIMS.items():
        w = float(loss_w.get(head, 1.0))
        for i in idxs:
            if 0 <= i < n:
                dims[i] = round(max(dims[i], w), 3)
    return dims


def _sample_weight(tags: list[tuple[str, float]]) -> float:
    if not tags:
        return 1.0
    mean = sum(w for _, w in tags) / len(tags)
    return round(min(2.0, max(1.0, mean)), 3)


def _curriculum(tags: list[tuple[str, float]]) -> dict[str, Any]:
    priority = [t for t, _ in sorted(tags, key=lambda x: -x[1])]
    hints: list[str] = []
    if any(t in ("stop_lights", "stop_signs") for t, _ in tags):
        hints.append("emphasize longitudinal braking / hold at controls")
    if any(t in ("cut_ins", "lane_change", "merges") for t, _ in tags):
        hints.append("emphasize lateral response + desire shifts")
    if any(t == "lead_vehicle" for t, _ in tags):
        hints.append("emphasize gap / lead tracking")
    if not hints and tags:
        hints.append("reweight soft-label loss toward matched scenario tags")
    return {
        "priority": priority,
        "hints": hints,
        "phase": "emphasis" if tags else "baseline",
    }


def coach_focus(text: str | None) -> dict[str, Any] | None:
    """Parse plain English → structured focus for train/teach.

    Returns None when text is empty. Always includes tags/weights/curriculum
    even when no known keywords match (generic emphasis + raw token tags).
    """
    raw = _normalize_text(text or "")
    if not raw:
        return None

    matched = _match_tags(raw)
    if not matched:
        parts = re.split(r"[,;]|\band\b", raw, flags=re.I)
        soft: list[tuple[str, float]] = []
        for part in parts:
            slug = re.sub(r"[^a-z0-9]+", "_", part.strip().lower()).strip("_")
            if slug and len(slug) >= 2:
                soft.append((slug[:48], 1.25))
        matched = soft[:8] or [("general", 1.1)]

    loss_w = _loss_weights(matched)
    tags = [t for t, _ in matched]
    tag_weights = {t: round(w, 3) for t, w in matched}
    sample_w = _sample_weight(matched)
    dim_w = _dim_weights(loss_w)

    return {
        "version": COACH_VERSION,
        "text": raw,
        "normalized": raw.lower(),
        "tags": tags,
        "tag_weights": tag_weights,
        "loss_weights": loss_w,
        "sample_weight": sample_w,
        "dim_weights": dim_w,
        "curriculum": _curriculum(matched),
    }


def focus_for_train(
    text: str | None = None, coached: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Resolve the structured focus train should use (prefer precomputed)."""
    if isinstance(coached, dict) and coached.get("tags") is not None:
        return coached
    return coach_focus(text)


def weighted_mse_factor(dim_weights: list[float] | None, n: int = 8) -> list[float]:
    """Per-dim multipliers for MSE; defaults to ones."""
    if not dim_weights:
        return [1.0] * n
    out = []
    for i in range(n):
        out.append(float(dim_weights[i]) if i < len(dim_weights) else 1.0)
    return out
