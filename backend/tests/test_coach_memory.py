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
