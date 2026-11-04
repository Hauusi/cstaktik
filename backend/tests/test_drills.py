"""Coaching-Session: Wenn-dann-Plan, Entscheidungen mit wachsendem Abstand, Kurz-Check, Warm-up."""

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from synth import BRO, ME

from cstaktik import accounts, api, course_texts, drills, history, pipeline

O = {"Origin": "http://testserver"}


def _sc(rnd, lesson="utility", report="m1.html"):
    return {"sid": ME, "round": rnd, "tick": 1000 * rnd, "from": 1000 * rnd - 200, "report": report, "lesson": lesson,
            "aktion": "Richtung Gegner", "pro_best": "gehalten", "clip": {"dec": -3.0, "frames": [], "kills": [], "nades": [], "ids": []}}


def test_plans_are_if_then_for_every_lesson():
    assert set(course_texts.PLANS) == set(course_texts.LESSONS)
    for lid, plans in course_texts.PLANS.items():
        assert len(plans) == 3 and all(p.startswith("Wenn ") and ", dann " in p for p in plans), lid


def test_plan_before_match():
    drills.set_plan(ME, "utility", "Wenn A, dann B.", "m1.html", "2026-01-01T10:00")
    drills.set_plan(ME, "alone", "Wenn C, dann D.", "m2.html", "2026-01-02T10:00")
    assert drills.plan_before(ME, "2026-01-02T10:00")["text"] == "Wenn A, dann B."  # galt für das Match danach
    assert drills.plan_before(ME, "2026-01-03T10:00")["lesson"] == "alone"
    assert drills.plan_before(ME, "2026-01-01T10:00") is None
    assert drills.current_plan(ME)["text"] == "Wenn C, dann D."


def test_spacing_and_interleaving():
    scenes = [_sc(1), _sc(2), _sc(3, "alone"), _sc(4, "utility"), {**_sc(5), "clip": None}]
    now = datetime(2026, 1, 10, 12)
    first = drills.due(ME, scenes, 3, now=now, focus="utility")
    assert [s["round"] for s in first] == [1, 2, 3]  # offene zuerst, Fokus vorne, höchstens zwei je Lektion, ohne Clip nie
    drills.record(ME, drills.scene_key(scenes[0]), "gehalten", "Richtung Gegner", "gehalten")  # wie die Pros
    drills.record(ME, drills.scene_key(scenes[1]), "Richtung Gegner", "Richtung Gegner", "gehalten")  # anders
    keys = lambda xs: [s["round"] for s in xs]  # noqa: E731
    assert 1 not in keys(drills.due(ME, scenes, 5, now=datetime.now()))  # gerade beantwortet: noch nicht fällig
    later = drills.due(ME, scenes, 5, now=datetime.now() + timedelta(days=1, minutes=1))
    assert 1 in keys(later) and 2 in keys(later)  # nach einem Tag wieder da
    drills.record(ME, drills.scene_key(scenes[0]), "gehalten", "Richtung Gegner", "gehalten")
    assert 1 not in keys(drills.due(ME, scenes, 5, now=datetime.now() + timedelta(days=2)))  # zweites Mal: 3 Tage
    assert 1 in keys(drills.due(ME, scenes, 5, now=datetime.now() + timedelta(days=3, minutes=1)))


def test_warmup_streak():
    d = drills.load(ME)
    d["warmups"] = ["2026-01-08T10:00:00", "2026-01-09T10:00:00", "2026-01-10T09:00:00", "2026-01-05T10:00:00"]
    drills._save(ME, d)
    assert drills.warmup_streak(ME, datetime(2026, 1, 10, 20)) == 3
    assert drills.warmup_streak(ME, datetime(2026, 1, 11, 20)) == 3  # gestern zählt noch
    assert drills.warmup_streak(ME, datetime(2026, 1, 13, 20)) == 0


def _entries():
    pipeline.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    for i, at in ((1, "2026-01-01T10:00"), (2, "2026-01-02T10:00")):
        history.save({"id": f"m{i}", "map": "de_mirage", "rounds": 20, "analyzed_at": at, "report_file": f"m{i}.html",
                      "players": {ME: {"name": "Ich", "rounds": 20}}, "score_by": {ME: [13, 7]},
                      "lessons": {ME: {"utility": 1}}, "scenes": [_sc(3, report=f"m{i}.html")],
                      "focus_check": {ME: {"focus": {"lesson": "utility", "target": 1.0}, "check": None}}},
                     pipeline.HISTORY_DIR)
        (pipeline.REPORTS_DIR / f"m{i}.html").write_text("<html></html>")


def test_session_endpoints_and_check():
    _entries()
    accounts.add_user("Hausi", "Geheim-12345")
    accounts.link_steamid("Hausi", ME)
    a = TestClient(api.app)
    a.post("/login", data={"name": "Hausi", "password": "Geheim-12345"}, headers=O)
    plan = course_texts.PLANS["utility"][1]
    assert a.post("/session/plan", json={"report": "m1.html", "lesson": "utility", "text": plan}, headers=O).json()["ok"]
    assert a.post("/session/plan", json={"report": "m1.html", "lesson": "x", "text": plan}, headers=O).status_code == 400
    assert a.post("/session/plan", json={"report": "m1.html", "lesson": "utility", "text": plan, "p": BRO},
                  headers=O).json()["ok"]  # fremde SteamID: es bleibt der eigene Spieler
    assert drills.current_plan(ME)["text"] == plan
    # Kurz-Check im nächsten Match: der Plan steht zwischen zwei anderen, das Ergebnis aus der Lektion
    page = a.get("/m/m2.html").text
    assert 'data-step="check"' in page and f'data-plan="{plan}"' in page and page.count('class="ck-o"') == 3
    assert "In diesem Match kam der Fehler einmal in 20 Runden vor." in page  # Ergebnis der Lektion
    assert 'data-step="check"' not in a.get("/m/m1.html").text  # für das erste Match gab es noch keinen Plan
    # Entscheidung speichern
    key = "m2.html#3-3000"
    r = a.post("/session/answer", json={"key": key, "choice": "gehalten"}, headers=O).json()
    assert r == {"ok": True, "pro": True}
    assert a.post("/session/answer", json={"key": key, "choice": "tanzen"}, headers=O).status_code == 404
    assert a.post("/session/answer", json={"key": "m2.html#9-1", "choice": "gehalten"}, headers=O).status_code == 404
    assert drills.load(ME)["answers"][key][0]["same"] is False
    # Session erledigt: Startseite zeigt Plan und Warm-up statt "Session starten"
    assert "Session starten" in a.get("/").text
    assert a.post("/session/done", json={"report": "m2.html"}, headers=O).json()["ok"]
    home = a.get("/").text
    assert "Session starten" not in home and plan in home and "Vor dem nächsten Match" in home
    assert a.post("/session/done", json={"report": "m2.html", "warmup": True}, headers=O).json()["ok"]
    assert drills.warmup_streak(ME) == 1
    w = a.get("/warmup").text
    assert "Dein Plan heute" in w and plan in w
    b = TestClient(api.app)
    accounts.add_user("Bruder", "Geheim-12345")
    accounts.link_steamid("Bruder", BRO)
    b.post("/login", data={"name": "Bruder", "password": "Geheim-12345"}, headers=O)
    assert b.post("/session/answer", json={"key": key, "choice": "gehalten"}, headers=O).status_code == 404
