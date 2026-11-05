"""Gedächtnis für Entscheidungen und Meilensteine."""

from cstaktik import coach_memory, coach_story, drills

ME = "1"


def _scene(i, own, enemy, best="gehalten"):
    return {"sid": ME, "round": i, "tick": i * 100, "report": "m1.html", "lesson": "outnumbered", "pro_best": best,
            "snap": {"own": own, "enemy": enemy}}


def test_decision_patterns_need_enough_scenes():
    scenes = [_scene(i, 2, 4) for i in range(1, 7)]
    hist = [{"id": "m1", "report_file": "m1.html", "scenes": scenes}]
    for sc in scenes[:4]:
        drills.record(ME, drills.scene_key(sc), "Richtung Gegner", "Richtung Gegner", "gehalten", "x", "y")
    assert coach_memory.lines(hist, ME) == []  # erst 4 Szenen
    for sc in scenes[4:]:
        drills.record(ME, drills.scene_key(sc), "gehalten", "Richtung Gegner", "gehalten", "y", "y")
    ls = coach_memory.lines(hist, ME)
    assert ls[0] == ("In Unterzahl entscheidest du dich in 4 von 6 Szenen für „Peeken“. Wie die Pros warst du in 2 von 6. "
                     "Die Pros wählen dort meistens „Halten“.")
    assert ls[1].startswith("Bei der Frage, worauf es ankommt, lagst du in 2 von 6 Szenen richtig.")


def _board(k):
    return {"rounds": 20, "kills": k, "deaths": 15, "hs": 5, "ok": 2, "od": 2, "k1": k, "k2": 0, "k3": 0, "k4": 0, "k5": 0,
            "assists": 2, "kast": 12, "survived": 5, "dmg": 1500, "traded": 2, "assists_known": True, "dmg_known": True}


def test_milestones():
    before = [{"id": f"b{i}", "board": {ME: _board(10)}} for i in range(5)]
    h = {"id": "m9", "board": {ME: _board(25)},
         "focus_check": {ME: {"mastered": "alone", "new": True, "focus": {"lesson": "utility"}}}}
    m = coach_story.milestones(h, ME, before, warm_streak=7)
    assert "„Nicht ohne Trade-Partner peeken“" in m[0]
    assert m[1] == "Ab heute haben wir ein neues Thema: „Erst Utility, dann Duell“."
    assert m[2] == "Dein bestes Rating seit 5 Matches." and m[3].startswith("7 Tage in Folge")
    assert coach_story.milestones({"id": "x"}, ME, []) == []
    assert coach_story.pick(["a", "b", "c"], "m1") == coach_story.pick(["a", "b", "c"], "m1")


def test_map_brief():
    rows = [[r, "t" if r <= 10 else "ct", r > 10 or r % 3 == 0, 1, 1, 50] for r in range(1, 21)]
    ms = [{"id": f"m{i}", "map": "de_mirage", "analyzed_at": f"2026-01-0{i + 1}T10:00", "players": {ME: {}},
           "score_by": {ME: [13, 7] if i else [7, 13]}, "by_round": {ME: rows}, "lessons": {ME: {"alone": 2, "duel": 9}},
           "deaths": [{"sid": ME, "place": "Apartments"}] * 3 + [{"sid": ME, "place": "Mid"}] * 2} for i in range(3)]
    b = coach_story.map_brief(ms, ME, "de_mirage", {"text": "Wenn A, dann B."}, {"text": "Wenn wir C, dann D."}, "Cue")
    assert b[0] == "Mirage. Deine letzten 3 Matches hier: 2 gewonnen, 1 verloren."
    assert "Als T gewinnt ihr hier 30 % der Runden, als CT 100 %. Die T-Seite ist eure Baustelle" in b[1]
    assert b[2] == "Dein häufigster Fehler hier: „Nicht ohne Trade-Partner peeken“, 6 Mal in 3 Matches."
    assert b[3].startswith("Am häufigsten stirbst du in") and "(9 von 15 Toden)" in b[3]
    assert b[4:] == ["Deine Abmachung gilt auch hier: „Wenn A, dann B.“", "Und zu zweit: „Wenn wir C, dann D.“",
                     "Dein Schlüsselwort: „Cue“. Viel Erfolg."]
    assert coach_story.map_brief([], ME, "de_inferno")[0].startswith("Auf Inferno hast du noch kein Match")


def test_pause_line_in_push(monkeypatch):
    from cstaktik import evening, notify

    monkeypatch.setattr(evening, "curve", lambda hist, sid: {"stop_after": 2})
    monkeypatch.setattr(evening, "index_today", lambda hist, sid, h: 3)
    m = notify.match_message({"id": "x", "map": "de_mirage"}, ME, [{"id": "x"}])
    assert "Das war dein 3. Match heute." in m["body"] and "Pause" in m["body"]
    monkeypatch.setattr(evening, "index_today", lambda hist, sid, h: 1)
    assert "Pause" not in notify.match_message({"id": "x", "map": "de_mirage"}, ME, [{"id": "x"}])["body"]
