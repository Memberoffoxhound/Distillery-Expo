"""Focus coach — plain English → tags/weights; train loss bias."""

from __future__ import annotations

from distillery_student.focus import coach_focus, focus_for_train, weighted_mse_factor
from distillery_student.train_loop import run_distill_steps


def test_coach_parses_stop_and_cutins():
    c = coach_focus("stop lights, stop signs, cut-ins")
    assert c is not None
    assert "stop_lights" in c["tags"]
    assert "stop_signs" in c["tags"]
    assert "cut_ins" in c["tags"]
    assert c["sample_weight"] > 1.0
    assert c["loss_weights"]["plan_lat"] >= 1.0
    assert c["loss_weights"]["plan_long"] >= 1.0
    assert len(c["dim_weights"]) == 8
    assert c["curriculum"]["phase"] == "emphasis"


def test_coach_fallback_tokens():
    c = coach_focus("weird custom thing and another")
    assert c is not None
    assert len(c["tags"]) >= 1
    assert c["sample_weight"] >= 1.0


def test_coach_empty():
    assert coach_focus("") is None
    assert coach_focus("   ") is None
    assert focus_for_train(text=None) is None


def test_focus_for_train_prefers_coached():
    raw = coach_focus("pedestrians")
    assert raw is not None
    out = focus_for_train(text="ignored", coached=raw)
    assert out is raw


def test_weighted_mse_factor_defaults():
    assert weighted_mse_factor(None) == [1.0] * 8
    assert weighted_mse_factor([2.0, 3.0], n=4) == [2.0, 3.0, 1.0, 1.0]


def test_distill_focus_raises_sample_weight():
    plain = run_distill_steps(steps=3, seed=1.5)
    focused = run_distill_steps(steps=3, seed=1.5, focus="cut-ins")
    assert focused[0]["sample_weight"] > 1.0
    assert plain[0].get("sample_weight", 1.0) == 1.0
    assert focused[0]["train_loss"] != plain[0]["train_loss"]
