"""Kurs-Texte: vollständig, ganze Sätze, passend zu den Lektionen der Coach-Stimme."""

from __future__ import annotations

import re

import pytest

from cstaktik import coach_voice
from cstaktik.course_texts import LESSONS, STAGES, path

TEXT_FIELDS = ("goal", "what", "why", "spot", "measure")
DRILL_FIELDS = ("name", "where", "minutes", "steps", "done")
_END = re.compile(r"[.!?]$")


def _all_texts():
    """(Ort, Text) für jeden Text, der als ganzer Satz gelesen wird."""
    for s in STAGES:
        yield f"stage {s['key']}.intro", s["intro"]
    for lid, les in LESSONS.items():
        for f in TEXT_FIELDS:
            yield f"{lid}.{f}", les[f]
        for i, step in enumerate(les["how"]):
            yield f"{lid}.how[{i}]", step
        for i, step in enumerate(les["drill"]["steps"]):
            yield f"{lid}.drill.steps[{i}]", step
        yield f"{lid}.drill.done", les["drill"]["done"]


def test_stage_keys_and_intros():
    assert [s["key"] for s in STAGES] == ["shoot", "duel", "utility", "team", "round"]
    for s in STAGES:
        assert s["title"].strip() and s["intro"].strip()


def test_lessons_match_coach_voice():
    assert set(LESSONS) == set(coach_voice.LESSONS) - {"duel"}
    for lid, les in LESSONS.items():
        assert les["title"] == coach_voice.LESSONS[lid][0]


@pytest.mark.parametrize("lid", list(LESSONS))
def test_lesson_fields_complete(lid):
    les = LESSONS[lid]
    assert les["stage"] in {s["key"] for s in STAGES}
    for f in ("title", *TEXT_FIELDS):
        assert isinstance(les[f], str) and les[f].strip(), f
    assert 3 <= len(les["how"]) <= 4
    assert all(isinstance(x, str) and x.strip() for x in les["how"])
    d = les["drill"]
    for f in DRILL_FIELDS:
        assert d[f], f
    assert isinstance(d["minutes"], int) and d["minutes"] > 0
    assert 3 <= len(d["steps"]) <= 5
    assert all(isinstance(x, str) and x.strip() for x in d["steps"])


def test_no_list_separators():
    texts = list(_all_texts()) + [(f"{lid}.drill.{f}", LESSONS[lid]["drill"][f])
                                  for lid in LESSONS for f in ("name", "where")]
    texts += [(f"{lid}.title", LESSONS[lid]["title"]) for lid in LESSONS]
    for where, t in texts:
        assert "·" not in t and "|" not in t, where


def test_sentences_end_with_punctuation():
    for where, t in _all_texts():
        assert t == t.strip(), where
        assert _END.search(t), where
        assert t[0].isupper() or t[0].isdigit(), where


def test_path_covers_all_lessons_in_stage_order():
    p = path()
    assert sorted(p) == sorted(LESSONS) and len(p) == len(LESSONS)
    order = [s["key"] for s in STAGES]
    stages = [order.index(LESSONS[k]["stage"]) for k in p]
    assert stages == sorted(stages)
    assert p[0] == "moving_shot"
