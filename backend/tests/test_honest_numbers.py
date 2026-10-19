"""Zahlen ehrlich zeigen: Urteile nur mit genug Fällen, eine Einheit je Zahl, wessen Daten, keine Spoiler."""

from cstaktik import impact


def _bar(mine, pro, n, unit=" ms", lower=True, tol=80):
    from cstaktik import api

    tpl = api._env.from_string('{% from "bars.html" import cmpbar %}{{ cmpbar("X", mine, pro, unit, lower, 1200, tol, n) }}')
    return tpl.render(mine=mine, pro=pro, unit=unit, lower=lower, tol=tol, n=n)


def test_cmpbar_never_says_equal_for_a_big_gap_with_few_cases():
    html = _bar(202, 141, 16)  # echtes Match: 202 ms gegen Pros 141 ms aus 16 Fällen
    assert "langsamer, zu wenige Fälle für ein Urteil" in html and "etwa gleich" not in html
    assert 'cb-m no' not in html and 'cb-m ok' not in html  # keine Farbe ohne Urteil
    assert "· langsamer" in _bar(260, 141, 40) and "cb-m no" in _bar(260, 141, 40)
    assert "etwa gleich" in _bar(150, 141, 16)
    assert "zu wenige Fälle für ein Urteil" in _bar(150, 141, 5)
    assert "etwas schlechter, kein klarer Unterschied" in _bar(50, 56, 30, " %", False, 8)


def test_rank_text_and_matches_unit():
    assert impact.rank_text([(6, 10)]) == "Platz 6 von 10"
    assert impact.rank_text([(6, 10), (5, 10)]) == "im Schnitt Platz 5,5 von 10"
    assert impact.rank_text([(6, 10), (4, 10)]) == "im Schnitt Platz 5 von 10"
    assert impact.rank_text([]) is None


def test_quiz_scene_hides_spoilers_until_reveal():
    from cstaktik import api

    sc = {"snap": {"own": 4, "enemy": 5, "planted": False, "secs": 53.0, "time_left": 62, "kind": "bewegt"},
          "aktion": "gehalten",
          "info": "Info: 1 Gegner auf dem Radar sichtbar. babaya0310 war vorher nicht gesichtet, also eine Überraschung."}
    q = api._quiz_scene(dict(sc))
    assert q["lage_info"] == "1 Gegner auf dem Radar sichtbar."
    assert "Überraschung" in q["reveal_info"] and "babaya" not in q["lage_info"]
    assert q["uhr"] == "Uhr 1:02, Bombe nicht gelegt"  # Spieluhr, nicht 0:53 seit Rundenstart
    assert q["did"] == "Position halten" and "losgegangen" in q["did_note"]  # Laufen und Wertung erklärt
    q = api._quiz_scene({"snap": {"own": 2, "enemy": 1, "planted": True, "secs": 90, "time_left": 23},
                         "aktion": "Richtung Gegner", "info": "Info: Kein Gegner auf dem Radar. X war ab 1:20 sichtbar."})
    assert q["uhr"] == "Bombe liegt, noch 0:23" and q["lage_info"] == "Kein Gegner auf dem Radar."
    assert q["reveal_info"] == "X war ab 1:20 sichtbar."


def test_karte_opens_with_own_player_and_only_his_deaths():
    from cstaktik.report.progress import build

    hist = [{"map": "de_mirage", "rounds": 30, "analyzed_at": "2026-10-19T10:00",
             "players": {"bro": {"name": "entozs", "rounds": 30}, "me": {"name": "cntoz", "rounds": 30}},
             "lessons": {"bro": {"utility": 7}, "me": {"utility": 11}},
             "deaths": [{"sid": "bro", "place": "A", "x": 0, "y": 0}, {"sid": "me", "place": "B", "x": 1, "y": 1}]}]
    d = build(hist, ["me"], me="me")
    assert [p["name"] for p in d["players"]] == ["cntoz"] and d["me"] == "me"
    les = d["players"][0]["lessons"][0]
    assert les["total"] == 11 and les["last"] == {"count": 11, "rounds": 30}  # wie Start/Training: 11x, 3,7
    assert {x["sid"] for x in d["maps"][0]["deaths"]} == {"me"}
    d = build(hist, None, me="me")
    assert d["players"][0]["sid"] == "me"  # ohne Login beide, der eigene zuerst


def test_kabine_without_own_match_says_no_data():
    from fastapi.testclient import TestClient

    from cstaktik import api

    t = TestClient(api.app).get("/briefing/de_inferno").text
    assert "Noch keine eigenen Daten zu Inferno" in t
