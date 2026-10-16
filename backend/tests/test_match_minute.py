"""Ein Thema je Spieler überall (Report, Verlauf, Push), persönlicher Debrief, "Dein Match in 60 Sekunden"."""

import json
import re

from fastapi.testclient import TestClient
from synth import BRO, ME, build_match

from cstaktik import accounts, api, coaching, history, notify, pipeline
from cstaktik.coach_voice import LESSONS
from cstaktik.config import load_rules_config
from cstaktik.curriculum import TEACH
from cstaktik.model import Finding
from cstaktik.rules import analyze

O = {"Origin": "http://testserver"}


def _f(sid, name, lid, rnd, cost):
    return Finding(rule_id="death_review", title="t", round=rnd, tick=100 * rnd, steamid=sid, player_name=name,
                   severity="hoch", text="", tip="", evidence={"coach": {"id": lid}, "cost_pct": cost, "f": {}})


def _match_with_lessons():
    """Synth-Match plus Coach-Lektionen: ich 2x allein (teuer), 1x Utility; der Bruder 3x ohne Schuss."""
    m = build_match()
    result = analyze(m, load_rules_config())
    result.findings += [_f(ME, "Ich", "alone", 1, 20), _f(ME, "Ich", "alone", 2, 20), _f(ME, "Ich", "utility", 3, 5),
                        _f(BRO, "Bruder", "no_shot_close", 1, 10), _f(BRO, "Bruder", "no_shot_close", 2, 10),
                        _f(BRO, "Bruder", "no_shot_close", 4, 10)]
    return m, result


def _focus_check():
    """Mein laufender Auftrag ist Utility (kam heute vor), der Bruder hat keinen."""
    check = {"title": LESSONS["utility"][0], "count": 1, "rate": 1.7, "target": 1.0, "met": False, "streak": 0,
             "need": 2, "rounds": 6, "streak_rounds": 0, "need_rounds": 40, "drills": 0}
    return {ME: {"name": "Ich", "new": False, "mastered": None, "check": check,
                 "focus": {"lesson": "utility", "title": LESSONS["utility"][0], "target": 1.0, "baseline": 2.0,
                           "matches": [], "need": 2}},
            BRO: {"name": "Bruder", "new": False, "mastered": None, "check": None, "focus": None}}


def test_one_topic_per_player_in_history_and_report(tmp_path):
    from cstaktik.report.render import render_report

    m, result = _match_with_lessons()
    h = history.summarize(m, result, "r.html")
    assert h["main_lesson"] == "alone"  # vor dem Auftrag: teuerste Lektion
    h["focus_check"] = _focus_check()
    history.set_leads(h)
    # Auftrag kam heute vor: er ist das Thema (Team und ich), der Bruder behält seine eigene Lektion
    assert h["lead"] == h["main_lesson"] == "utility"
    assert h["lead_by"] == {ME: "utility", BRO: "no_shot_close"}
    assert history.lead(h, BRO) == "no_shot_close" and history.lead(h) == "utility"

    html = render_report(m, result, maps_dirs=[tmp_path], focus=_focus_check())
    raw = re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S).group(1)
    db = json.loads(raw)["debrief"]
    # Debrief: gleiche Themen wie im Verlauf, Auftrag-Check und Szenen mit SteamID (persönliche Ansicht)
    assert db["lesson"]["id"] == "utility"
    assert db["by"][ME]["id"] == "utility" and db["by"][BRO]["id"] == "no_shot_close"
    assert db["checks"][0]["sid"] == ME
    findings = json.loads(raw)["findings"]
    assert all(findings[sc["finding"]]["sid"] == BRO for sc in db["by"][BRO]["scenes"])
    assert all(sc["sid"] == BRO for sc in db["by"][BRO]["scenes"])
    # "Der eine Punkt" je Spieler, nur mit window.__ME sichtbar
    assert f'class="mp-me" data-sid="{BRO}" hidden' in html and 'class="mp-team"' in html


def test_old_history_entry_falls_back():
    old = {"main_lesson": "alone", "won": 13, "lost": 7, "players": {ME: {}}}
    # ohne Daten je Spieler: Team-Thema kann das eines anderen sein, Ergebnis nur für Fokus-Spieler
    assert history.lead(old, ME) is None and history.lead(old) == "alone"
    assert history.score(old, ME) is None and history.score({**old, "issues": {ME: {}}}, ME) == (13, 7)
    seq = {**old, "seq": {ME: [[1, "t", True], [2, "t", False], [3, "ct", False]]}}
    assert history.score(seq, ME) == (1, 2)


def test_old_list_seq_does_not_crash():
    """Ältere Einträge speichern ``seq`` als Liste (Sicht des Teams)."""
    h = {"won": 13, "lost": 7, "players": {ME: {"name": "Ich"}}, "issues": {ME: {}}, "seq": [[1, "ct", True]]}
    assert history.score(h, ME) == (13, 7)
    pipeline.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    history.save({**h, "id": "m3", "map": "de_nuke", "analyzed_at": "2026-10-01T10:00", "report_file": "m3.html"},
                 pipeline.HISTORY_DIR)
    c = TestClient(api.app)
    page = c.get("/m/m3.html")
    assert page.status_code == 200 and "13:7" in page.text
    assert c.get("/").status_code == 200 and c.get("/matches").status_code == 200


def test_non_focus_player_gets_no_team_result_or_topic():
    # Der Bruder ist verbunden, spielte aber gegen uns und steht nicht im Fokus: kein fremdes "gewonnen"
    h = {"map": "de_mirage", "won": 13, "lost": 7, "report_file": "r.html",
         "players": {ME: {"name": "Ich"}, BRO: {"name": "Bruder"}}, "score_by": {ME: [13, 7]},
         "seq": {ME: [[1, "ct", True]]}, "lead": "utility", "lead_by": {ME: "utility"},
         "lesson_rank_by": {ME: ["utility"]}}
    assert history.score(h, BRO) is None and history.lead(h, BRO) is None
    assert history.score(h, ME) == (13, 7) and history.lead(h, ME) == "utility"
    msg = notify.match_message(h, BRO)
    assert "13:7" not in msg["title"] and "gewonnen" not in msg["title"] and LESSONS["utility"][0] not in msg["body"]
    view = api._minute_player(h, BRO)
    assert "won" not in view and "result" not in view and "topic" not in view


def _render(findings, **kw):
    from cstaktik.report.render import render_report

    m = build_match()
    result = analyze(m, load_rules_config())
    result.findings += findings
    import tempfile
    from pathlib import Path

    html = render_report(m, result, maps_dirs=[Path(tempfile.mkdtemp())], **kw)
    raw = re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S).group(1)
    return html, json.loads(raw)["debrief"]


def test_report_team_view_hides_personal_blocks():
    m, result = _match_with_lessons()
    html, _ = _render(result.findings[-6:], focus=_focus_check())
    tags = re.findall(r"<[a-z]+[^>]*\bmp-me\b[^>]*>", html)
    assert tags and all(re.search(r"\shidden(\s|>)", t) for t in tags)
    assert "[hidden] { display: none !important; }" in html
    # Ergebnis je Spieler (persönliche Ansicht) neben dem Team-Ergebnis
    assert f'class="mp-me" data-sid="{ME}" hidden' in html and '<div class="mp-team">' in html


def test_report_topic_follows_history_rule():
    # je Lektion nur ein Tod: kein Thema, also keine "Der eine Punkt"-Karte und kein Debrief-Thema
    html, db = _render([_f(ME, "Ich", "alone", 1, 20), _f(BRO, "Bruder", "no_shot_close", 2, 10)])
    assert "Der eine Punkt" not in html and db["lesson"] is None and db["by"] == {}
    # Thema aus dem Verlauf gilt (Report, Startseite und Push gleich)
    fs = [_f(ME, "Ich", "alone", 1, 20), _f(ME, "Ich", "alone", 2, 20), _f(ME, "Ich", "utility", 3, 5)]
    _, db = _render(fs, leads={"lead": "utility", "lead_by": {ME: "utility"}})
    assert db["lesson"]["id"] == "utility" and db["by"][ME]["id"] == "utility"
    _, db = _render(fs)  # ohne Verlauf dieselbe Regel: zwei Tode machen das Thema
    assert db["lesson"]["id"] == "alone" and db["by"][ME]["id"] == "alone"


def test_minute_scenes_for_secondary_lesson():
    sc = {"lesson": "alone", "lessons": ["alone", "utility"], "sid": ME, "round": 3, "tick": 500, "cost": 12,
          "happened": "Allein gestorben."}
    h = {"report_file": "r.html", "players": {ME: {"name": "Ich"}}, "score_by": {ME: [13, 7]},
         "lead_by": {ME: "utility"}, "scenes": [sc, {**sc, "lessons": ["alone"], "round": 5}]}
    assert [x["round"] for x in api._minute_player(h, ME)["scenes"]] == [3]
    # alter Eintrag ohne Lektionen je Szene: seine teuersten Szenen
    old = [{k: v for k, v in sc.items() if k != "lessons"}, {**sc, "round": 6, "cost": 30, "lessons": None}]
    old[1].pop("lessons")
    assert [x["round"] for x in api._minute_player({**h, "scenes": old}, ME)["scenes"]] == [6, 3]


def test_push_per_player_topic_and_result():
    # Wir spielten gegeneinander: ich gewinne 13:7, der Bruder verliert 7:13
    h = {"map": "de_mirage", "won": 13, "lost": 7, "report_file": "r.html",
         "players": {ME: {"name": "Ich"}, BRO: {"name": "Bruder"}},
         "score_by": {ME: [13, 7], BRO: [7, 13]}, "lead": "utility",
         "lead_by": {ME: "utility", BRO: "no_shot_close"}}
    mine, his = notify.match_message(h, ME), notify.match_message(h, BRO)
    assert mine["title"] == "Mirage 13:7 gewonnen" and his["title"] == "Mirage 7:13 verloren"
    assert LESSONS["utility"][0] in mine["body"] and LESSONS["no_shot_close"][0] in his["body"]
    assert LESSONS["utility"][0] not in his["body"]
    assert mine["url"] == "/m/r.html"


def _save_entry():
    pipeline.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    sc = {"lesson": "utility", "sid": ME, "round": 3, "tick": 500, "from": 400, "cost": 12,
          "happened": "Du bist ohne Flash in den Gegner gelaufen."}
    h = {"id": "m1", "map": "de_mirage", "rounds": 20, "analyzed_at": "2999-01-01T10:00", "report_file": "m1.html",
         "won": 13, "lost": 7, "players": {ME: {"name": "Ich"}}, "seq": {ME: []}, "score_by": {ME: [13, 7]},
         "impact": {ME: {"total": 250, "rank": 2, "of": 10}}, "lead": "utility", "lead_by": {ME: "utility"},
         "focus_check": {ME: _focus_check()[ME]}, "scenes": [sc, {**sc, "sid": BRO}]}
    history.save(h, pipeline.HISTORY_DIR)
    (pipeline.REPORTS_DIR / "m1.html").write_text("<html><head><title>Mirage 13:7 – x</title></head></html>")


def test_minute_page_content_and_visibility():
    _save_entry()
    accounts.add_user("Hausi", "Geheim-12345")
    accounts.add_user("Bruder", "Geheim-12345")
    accounts.link_steamid("Hausi", ME)
    accounts.link_steamid("Bruder", BRO)
    b = TestClient(api.app)
    b.post("/login", data={"name": "Bruder", "password": "Geheim-12345"}, headers=O)
    assert b.get("/m/m1.html").status_code == 404  # nicht mitgespielt: gibt es für ihn nicht
    a = TestClient(api.app)
    a.post("/login", data={"name": "Hausi", "password": "Geheim-12345"}, headers=O)
    assert api._is_new({"report_file": "m1.html", "analyzed_at": "2999-01-01T10:00"}, api._seen("Hausi"))
    home = a.get("/").text
    assert 'href="/m/m1.html"' in home and 'href="/reports/m1.html"' in home  # Kurzfassung und ganzer Report
    assert "/konto#push" in home  # noch kein Gerät für Benachrichtigungen
    page = a.get("/m/m1.html").text
    assert "13:7" in page and "Sieg" in page and "+2,5 Runden" in page and "Platz 2 von 10" in page
    assert "1,7 pro 10 Runden" in page and "Nicht geschafft" in page
    assert LESSONS["utility"][0] in page and TEACH["utility"]["mantra"] in page
    assert 'href="/reports/m1.html#s3-400"' in page and "Ganzer Report" in page
    assert not api._is_new({"report_file": "m1.html", "analyzed_at": "2999-01-01T10:00"}, api._seen("Hausi"))
    assert a.get("/m/fremd.html").status_code == 404


def test_minute_page_hides_missing_blocks():
    pipeline.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    history.save({"id": "m2", "map": "de_inferno", "analyzed_at": "2026-10-01T10:00", "report_file": "m2.html",
                  "won": 5, "lost": 13, "players": {ME: {"name": "Ich"}}, "issues": {ME: {}}}, pipeline.HISTORY_DIR)
    page = TestClient(api.app).get("/m/m2.html").text  # ohne Accounts: alle Fokus-Spieler
    assert "5:13" in page and "Niederlage" in page
    assert "Impact" not in page and "Auftrag-Check" not in page and "Thema" not in page


def test_home_builds_weekplan_and_shrinks_upload_with_autodl():
    from cstaktik import autodl, weekplan

    _save_entry()
    coaching.save({"players": {ME: {"focus": {"lesson": "utility", "target": 1.0, "baseline": 2.0,
                                              "created_at": "2026-10-01T10:00", "matches": [], "status": "aktiv"},
                                    "done": [], "drills": []}}}, pipeline.COACHING_FILE)
    c = TestClient(api.app)
    home = c.get("/").text
    assert "Demo hochladen" in home  # ohne automatischen Download: Hochladen bleibt der Weg
    key = weekplan.week_key(weekplan.local_today())
    assert key in coaching.load(pipeline.COACHING_FILE)["players"][ME]["weeks"]  # ohne Besuch auf /training
    assert "erledigt" in home
    autodl.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (autodl.CONFIG_DIR / "config.json").write_text("{}")
    home = c.get("/").text
    assert "Demo selbst hochladen" in home and "<h3>Demo hochladen</h3>" not in home


def test_notify_report_finds_history_entry(monkeypatch):
    _save_entry()
    got = []
    monkeypatch.setattr(notify, "notify_match", lambda h, post=None, hist=None: got.append(h) or 1)
    api._notify_report("m1.html")
    assert got and got[0]["id"] == "m1"


def test_one_off_lesson_is_no_topic():
    from cstaktik import history

    h = {"lesson_rank": ["flash"], "lesson_rank_by": {"1": ["flash"]}, "lessons": {"1": {"flash": 1}}}
    history.set_leads(h)
    assert h["lead"] is None and h["lead_by"]["1"] is None
    h["lessons"] = {"1": {"flash": 2}}
    history.set_leads(h)
    assert h["lead"] == "flash" and h["lead_by"]["1"] == "flash"
