"""Comma-master teacher listing — offline fixture labeled; no Chestnut."""

from __future__ import annotations

from distillery_teacher import list_comma_master_teachers, select_comma_master_teacher
from distillery_teacher.download import BIG_TEACHER_NAME


def test_list_force_fixture_labeled():
    teachers = list_comma_master_teachers(force_fixture=True)
    assert teachers
    for t in teachers:
        assert t["source"] == "fixture"
        assert t["live"] is False
        assert "name" in t
        assert "version" in t
        assert "artifact_ref" in t or "artifact_url" in t
        assert "chestnut" not in t["name"].lower()


def test_select_default_fixture():
    t = select_comma_master_teacher(force_fixture=True)
    assert t is not None
    assert t["source"] == "fixture"
    assert t["live"] is False
    assert t["name"] == "big_driving_supercombo"
    assert "big_driving_supercombo" in t.get("label", "")


def test_select_by_name():
    t = select_comma_master_teacher("driving_supercombo", force_fixture=True)
    assert t is not None
    assert t["name"] == "driving_supercombo"
