"""Coach-Geschichte ohne KI: jede Aussage aus den Daten, keine Sätze ohne Grundlage."""

from cstaktik import coach_story

ME = "1"


def _h(i, alone=3, won=(13, 7), scenes=None, by_round=None, rating_kills=15):
    return {"id": f"m{i}", "map": "de_mirage", "rounds": 20, "analyzed_at": f"2026-01-{i + 1:02d}T10:00",
            "report_file": f"m{i}.html", "players": {ME: {"name": "Hausi", "rounds": 20}},
            "score_by": {ME: list(won)}, "lessons": {ME: {"alone": alone}}, "scenes": scenes or [],
            "by_round": {ME: by_round or []},
            "board": {ME: {"rounds": 20, "kills": rating_kills, "deaths": 15, "hs": 5, "ok": 2, "od": 2, "k1": rating_kills,
                           "k2": 0, "k3": 0, "k4": 0, "k5": 0, "assists": 2, "kast": 12, "survived": 5, "dmg": 1500,
                           "traded": 2, "assists_known": True, "dmg_known": True}}}


def _sc(r, place="Apartments", mate_d=1500):
    return {"sid": ME, "round": r, "tick": r * 100, "lesson": "alone",
            "snap": {"place": place, "mate_d": mate_d, "own": 4, "enemy": 5}}


def test_pattern_with_evidence():
    rows = [[r, "t" if r <= 12 else "ct", r % 2 == 0, 1, 1, 50] for r in range(1, 21)]
    h = _h(9, scenes=[_sc(3), _sc(5), _sc(7), _sc(14, place="Mid")], by_round=rows)
    before = [_h(i, alone=1) for i in range(5)]
    p = coach_story.pattern(h, ME, "alone", before)
    assert p["headline"] == "Heute geht es um eine Sache: Nicht ohne Trade-Partner peeken."
    text = " ".join(p["lines"])
    assert "in 4 Runden passiert (Runden 3, 5, 7 und 14)" in text
    assert "3 davon habt ihr verloren." in text  # 3, 5, 7 ungerade = verloren; 14 gewonnen
    assert "Meistens als T (3 von 4)." in text and "3 Mal in" in text
    assert "im Schnitt 38 m weg" in text
    assert "Bei 20 Runden passiert es dir normalerweise etwa einmal." in text  # heute 3, davor 1 je 20 Runden
    assert "pro 10 Runden" not in text


def test_opening_callback_journey_and_check():
    before = [_h(i, rating_kills=10) for i in range(4)]
    o = coach_story.opening(_h(9, rating_kills=25), ME, before)
    assert o[0].startswith("Mirage, 13:7 gewonnen. Ich ") and "20 Runden" in o[0]
    assert "klar über deinem Schnitt" in o[1]
    cb = coach_story.callback(_h(9, alone=1), ME, {"lesson": "alone", "text": "Wenn A, dann B."}, 1.0)
    assert cb["met"] and "einmal in 20 Runden vor, erlaubt waren 2" in cb["lines"][1] and "gegriffen" in cb["lines"][1]
    cb = coach_story.callback(_h(9, alone=5), ME, {"lesson": "alone", "text": "Wenn A, dann B."}, 1.0)
    assert cb["met"] is False and "Wir bleiben dran" in cb["lines"][1]
    slot = {"focus": {"lesson": "alone", "baseline": 2.0, "created_at": "2026-01-03T10:00",
                      "matches": [{"rate": 1.0, "count": 2, "rounds": 20, "met": True}]},
            "done": [{"lesson": "utility"}]}
    j = coach_story.journey(slot, "alone", 2, 20)
    assert "seit dem 3.1." in j[0] and "etwa 4 Mal pro Match" in j[0] and "zuletzt 2 Mal in 20 Runden" in j[0]
    assert "Noch 1 Match, dann ist die Lektion geschafft." in j[1] and "„Erst Utility, dann Duell“" in j[2]
    assert coach_story.next_check("alone", 1.0, 20).endswith("bei etwa 20 Runden höchstens 2 Mal.")
    assert coach_story.next_check("alone", 0.3, 20).endswith("kein einziges Mal.")


def test_home_message_before_and_after_session():
    h = _h(9, scenes=[_sc(3), _sc(5)])
    m = coach_story.home_message(h, ME, "alone", [h], None, False, None, "Hausi")
    assert m["mode"] == "session" and m["lines"][0] == "Hey Hausi." and "„Nicht ohne Trade-Partner peeken“, 2 Mal" in m["lines"][2]
    m = coach_story.home_message(h, ME, "alone", [h], None, True, {"text": "Wenn X, dann Y.", "if_obstacle": "Wenn Z, dann W."})
    assert "„Wenn X, dann Y.“" in m["lines"][1] and "Wenn Z, dann W." in m["lines"][2]
    assert coach_story.home_message(None, ME, None, [], None, False, None) is None
