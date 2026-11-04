"""CS-Wissen: Inhalte vollständig und stimmig, Wissens-Check mit Abständen, Seiten, Warm-up."""

import re
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from synth import BRO, ME

from cstaktik import academy, accounts, api, course_texts, drills, history, pipeline

O = {"Origin": "http://testserver"}
FIELDS = {"area", "title", "key", "teach", "example", "mistakes", "drill", "cue", "ask", "quiz", "lessons", "links"}


def test_topics_complete_and_consistent():
    areas = {a["key"] for a in academy.AREAS}
    assert len(academy.TOPICS) >= 40
    assert {t["area"] for t in academy.TOPICS.values()} == areas  # jeder Bereich hat Themen
    ids = [q["id"] for t in academy.TOPICS.values() for q in t["quiz"]]
    assert len(ids) == len(set(ids))  # Frage-IDs eindeutig
    for tid, t in academy.TOPICS.items():
        assert set(t) == FIELDS, tid
        assert 2 <= len(t["teach"]) <= 4 and len(t["example"]) >= 3 and t["mistakes"] and t["quiz"], tid
        assert set(t["drill"]) == {"where", "steps", "done"} and t["drill"]["steps"], tid
        assert all(x in course_texts.LESSONS for x in t["lessons"]), tid
        assert all(x in {"granaten", "duelle", "stats", "lineups", "playbook", "briefing", "mapbook"} for x in t["links"]), tid
        for q in t["quiz"]:
            assert 0 <= q["a"] < len(q["options"]) and len(q["options"]) >= 2 and q["why"], q["id"]
        # ganze Sätze: Absätze enden mit Satzzeichen
        assert all(x.rstrip()[-1] in ".?!" for x in t["teach"] + t["example"]), tid


def test_every_course_lesson_has_knowledge():
    for lid in course_texts.LESSONS:
        assert academy.related(lid), lid


def test_checked_game_values_only():
    """Nur geprüfte Spielwerte: Loss-Bonus, Rundensieg, Bombe, Entschärfen."""
    lb = academy.TOPICS["loss_bonus"]
    assert "1400 $, 1900 $, 2400 $, 2900 $ und höchstens 3400 $" in lb["teach"][0]
    q = {x["id"]: x for x in lb["quiz"]}
    assert q["lb1"]["options"][q["lb1"]["a"]] == "1400 $" and q["lb2"]["options"][q["lb2"]["a"]] == "3250 $"
    assert q["lb3"]["options"][q["lb3"]["a"]] == "3400 $"
    eq = {x["id"]: x for x in academy.TOPICS["equipment"]["quiz"]}
    assert eq["eq1"]["options"][eq["eq1"]["a"]] == "5 Sekunden" and eq["eq2"]["options"][eq["eq2"]["a"]] == "40 Sekunden"


def test_answer_spacing(monkeypatch):
    t0 = datetime(2026, 1, 10, 12)
    monkeypatch.setattr(academy, "_now", lambda: t0)
    r = academy.answer(ME, "cp1", 1)
    assert r["ok"] and r["days"] == 1 and r["box"] == 1
    assert academy.answer(ME, "cp1", 1)["days"] == 3
    assert academy.answer(ME, "cp1", 1)["days"] == 7
    assert academy.answer(ME, "cp1", 1)["days"] == 21
    assert academy.answer(ME, "cp1", 1)["days"] == 21  # bleibt bei 21
    r = academy.answer(ME, "cp1", 0)
    assert not r["ok"] and r["box"] == 0 and r["days"] == 1 and r["a"] == 1 and r["why"]
    st = drills.load(ME)["quiz"]["cp1"]
    assert st["right"] == 5 and st["wrong"] == 1 and st["due"] == (t0 + timedelta(days=1)).isoformat(timespec="seconds")


def test_due_only_seen_or_preferred_topics_wrong_first_mixed(monkeypatch):
    t0 = datetime(2026, 1, 10, 12)
    monkeypatch.setattr(academy, "_now", lambda: t0)
    assert academy.due(ME, 5) == []  # nichts gelesen, kein Thema bevorzugt: keine Fragen aus dem Nichts
    got = academy.due(ME, 2, prefer=["trading"])
    assert [q["topic"] for q in got] == ["trading", "trading"]
    academy.answer(ME, "cp1", 0)  # falsch
    academy.answer(ME, "sm1", 0)  # richtig (a = 0), nach 1 Tag fällig
    monkeypatch.setattr(academy, "_now", lambda: t0 + timedelta(days=1, minutes=1))
    got = academy.due(ME, 3, prefer=["trading"])
    assert {q["id"] for q in got[:2]} == {"cp1", "sm1"} and got[2]["topic"] == "trading"
    assert got[0]["topic"] != got[1]["topic"]
    assert "a" not in got[0] and "why" not in got[0]  # keine Lösung an den Browser vor der Antwort


def test_topic_state():
    academy.mark_read(ME, "smokes")
    d = drills.load(ME)
    assert academy.topic_state("smokes", d) == "gelesen" and academy.topic_state("flashes", d) == "neu"
    academy.answer(ME, "sm1", 1)
    assert academy.topic_state("smokes", drills.load(ME)) == "ueben"
    academy.answer(ME, "sm1", academy.questions()["sm1"][1]["a"])
    academy.answer(ME, "sm2", academy.questions()["sm2"][1]["a"])
    assert academy.topic_state("smokes", drills.load(ME)) == "sitzt"
    ov = academy.overview(ME)
    assert ov["counts"]["sitzt"] == 1 and ov["total"] == len(academy.TOPICS)


def _login():
    pipeline.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    history.save({"id": "m1", "map": "de_mirage", "rounds": 20, "analyzed_at": "2026-01-01T10:00", "report_file": "m1.html",
                  "players": {ME: {"name": "Ich", "rounds": 20}, BRO: {"name": "Bro", "rounds": 20}},
                  "score_by": {ME: [13, 7]}, "lessons": {ME: {"alone": 1}}, "scenes": [],
                  "focus_check": {ME: {"focus": {"lesson": "alone", "target": 1.0}, "check": None}}}, pipeline.HISTORY_DIR)
    (pipeline.REPORTS_DIR / "m1.html").write_text("<html></html>")
    accounts.add_user("Hausi", "Geheim-12345")
    accounts.link_steamid("Hausi", ME)
    a = TestClient(api.app)
    a.post("/login", data={"name": "Hausi", "password": "Geheim-12345"}, headers=O)
    return a


def test_pages_and_answer_endpoint():
    a = _login()
    ov = a.get("/wissen").text
    assert "CS-Wissen" in ov and ov.count('href="/wissen/') == len(academy.TOPICS)
    page = a.get("/wissen/trading").text
    for part in ("Der Kern", "Verstehen", "So sieht es richtig aus", "Typische Fehler", "Üben", "Prüfen"):
        assert part in page, part
    assert 'data-quiz="tr1"' in page and "Lektion: Nicht ohne Trade-Partner peeken" in page
    assert "/duelle" in page and "/stats" in page
    assert "trading" in (drills.load(ME).get("read") or {})  # geöffnet = gelesen
    assert a.get("/wissen/gibtsnicht").status_code == 404
    r = a.post("/wissen/antwort", json={"qid": "tr1", "pick": 1}, headers=O).json()
    assert r["ok"] and r["a"] == 1 and r["days"] == 1
    assert a.post("/wissen/antwort", json={"qid": "tr1", "pick": 9}, headers=O).status_code == 400
    assert a.post("/wissen/antwort", json={"qid": "xx", "pick": 0}, headers=O).status_code == 400
    a.post("/wissen/antwort", json={"qid": "tr2", "pick": 0, "p": BRO}, headers=O)  # eingeloggt zählt nur der eigene
    assert not drills.load(BRO).get("quiz") and "tr2" in drills.load(ME)["quiz"]
    home = a.get("/").text
    assert 'data-tile="wissen"' in home


def test_warmup_quiz_imagery_and_session_link():
    a = _login()
    drills.set_plan(ME, "alone", course_texts.PLANS["alone"][0], "m1.html", "2026-01-01T10:00")
    w = a.get("/warmup").text
    assert "Wissens-Check" in w and len(re.findall(r'data-quiz="', w)) == 2
    assert "Kopfkino" in w and "Zu zweit" in w
    kurs = a.get("/kurs/alone").text
    assert "Mehr im CS-Wissen" in kurs and "/wissen/trading" in kurs


def test_imagery_needs_if_then_plan():
    assert course_texts.imagery(None, "x") == [] and course_texts.imagery("Spiel gut.", "x") == []
    st = course_texts.imagery("Wenn A passiert, dann B.", "Cue")
    assert len(st) == 3 and "„Wenn A passiert, dann B“" in st[0] and "„Cue“" in st[2]
