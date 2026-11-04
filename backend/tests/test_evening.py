"""Spielabend: Rating je Match-Nummer des Tages, Rat erst mit genug Abenden und deutlichem Abfall."""

from cstaktik import course_texts, evening

ME = "1"


def _board(kills, deaths, rounds=20):
    return {"rounds": rounds, "kills": kills, "deaths": deaths, "assists": 0, "dmg": 80 * rounds, "hs": 0,
            "kast": 14, "survived": rounds - deaths, "k1": kills, "k2": 0, "k3": 0, "k4": 0, "k5": 0, "ok": 0, "od": 0,
            "traded": 0, "assists_known": False, "dmg_known": True}


def _hist(days, good=(20, 12), bad=(10, 18)):
    out = []
    for d in range(days):
        for i in range(3):
            k, de = good if i < 2 else bad  # drittes Match des Tages deutlich schwächer
            out.append({"id": f"{d}-{i}", "analyzed_at": f"2026-01-{10 + d:02d}T{18 + i}:00:00",
                        "board": {ME: _board(k, de)}})
    return out


def test_curve_and_advice():
    c = evening.curve(_hist(3), ME)
    assert [r["label"] for r in c["rows"]] == ["1.", "2.", "3."] and c["multi_days"] == 3
    assert c["stop_after"] == 2 and c["drop"][2] == 3 and c["drop"][0] > c["drop"][1]
    h = _hist(3)
    assert evening.index_today(h, ME, h[2]) == 3 and evening.index_today(h, ME, h[3]) == 1


def test_no_advice_with_few_evenings():
    c = evening.curve(_hist(2), ME)
    assert c["stop_after"] is None and c["multi_days"] == 2
    flat = evening.curve(_hist(3, bad=(20, 12)), ME)
    assert flat["stop_after"] is None  # kein Abfall: kein Rat


def test_routine_per_lesson():
    assert set(course_texts.ROUTINE_STEP) == set(course_texts.LESSONS)
    r = course_texts.routine("utility")
    assert len(r) == 3 and "„Granate zuerst“" in r[1]
