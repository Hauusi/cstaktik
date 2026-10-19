"""Ein Thema je Spieler überall (Report, Verlauf, Push), persönlicher Debrief, "Dein Match in 60 Sekunden"."""

import json
import re

from fastapi.testclient import TestClient
from synth import BRO, ME, build_match

from cstaktik import accounts, api, coaching, course_texts, history, notify, pipeline
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
    """Die Szene der Story gehört zur aktuellen Lektion, auch wenn der Fehler bei diesem Tod nur mitspielte."""
    sc = {"lesson": "alone", "lessons": ["alone", "utility"], "sid": ME, "round": 3, "tick": 500, "cost": 12,
          "happened": "Allein gestorben."}
    h = {"report_file": "r.html", "players": {ME: {"name": "Ich"}}, "score_by": {ME: [13, 7]},
         "focus_check": {ME: {"check": None, "focus": {"lesson": "utility", "target": 1.0}}},
         "scenes": [sc, {**sc, "lessons": ["alone"], "round": 5}]}
    les = api._minute_player(h, ME)["lesson"]
    assert les["id"] == "utility" and les["scene"]["round"] == 3 and les["scene"]["href"] == "/reports/r.html#s3-500"


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
    assert 'href="/m/m1.html"' in home and "Neues Match" in home  # neues Match: eine kompakte Karte
    assert "/konto#push" in home  # noch kein Gerät für Benachrichtigungen
    page = a.get("/m/m1.html").text
    # Story: Ergebnis, deine Lektion (aktuelle Kurs-Lektion), fertig
    assert _steps(page) == ["ergebnis", "lektion", "fertig"]
    assert "13:7" in page and "Sieg" in page and "+2,5</b>" in page and "etwa 2,5 Runden gebracht" in page
    assert "Platz 2 von 10" in page
    # ganze Sätze in Worten des Spielers: wie oft in wie vielen Runden, gegen das Ziel, die Serie
    assert "Deine Lektion" in page and course_texts.LESSONS["utility"]["title"] in page
    assert ("In diesem Match kam der Fehler einmal in 6 Runden vor. Erlaubt waren höchstens 0. Diesmal hat es "
            "nicht gereicht, die Serie beginnt im nächsten Match von vorn.") in page
    assert "Nicht geschafft" in page and "pro 10 Runden" not in page
    assert page.count('href="/reports/m1.html#s') == 1 and 'href="/reports/m1.html#s3-400"' in page  # eine Szene
    assert 'href="/kurs/utility"' in page and "Zur Lektion" in page
    assert 'data-mine="1"' in page and f'data-sid="{ME}"' in page
    assert "Ganzer Report" in page and "Zum Kurs" in page
    for gone in ("Nächstes Match", "Die eine Szene", 'id="deal"'):
        assert gone not in page, gone
    assert a.post("/training/deal", json={"sid": ME, "lesson": "utility", "report": "m1.html"},
                  headers=O).json() == {"ok": True}  # der Button der Story schickt genau das
    assert not api._is_new({"report_file": "m1.html", "analyzed_at": "2999-01-01T10:00"}, api._seen("Hausi"))
    assert a.get("/m/fremd.html").status_code == 404


def test_minute_page_hides_missing_blocks():
    pipeline.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    history.save({"id": "m2", "map": "de_inferno", "analyzed_at": "2026-10-01T10:00", "report_file": "m2.html",
                  "won": 5, "lost": 13, "players": {ME: {"name": "Ich"}}, "issues": {ME: {}}}, pipeline.HISTORY_DIR)
    page = TestClient(api.app).get("/m/m2.html").text  # ohne Accounts: alle Fokus-Spieler
    assert "5:13" in page and "Niederlage" in page
    # ohne Daten: nur Ergebnis und Schluss, kein leerer Schritt
    assert _steps(page) == ["ergebnis", "fertig"]
    assert "Impact" not in page and "Deine Lektion" not in page and "Heute" not in page


def _steps(page):
    return re.findall(r'data-step="([a-z]+)"', page)


def test_minute_story_without_lesson_and_with_running_focus():
    pipeline.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    # Lektionen gezählt, aber zu wenig für eine Einstufung und kein Auftrag: kein Lektions-Schritt
    history.save({"id": "q1", "map": "de_nuke", "analyzed_at": "2026-10-01T10:00", "report_file": "q1.html",
                  "players": {ME: {"name": "Ich"}}, "score_by": {ME: [13, 11]}, "lead_by": {ME: None},
                  "lessons": {ME: {"alone": 1}}, "issues": {ME: {}}}, pipeline.HISTORY_DIR)
    page = TestClient(api.app).get("/m/q1.html").text
    assert _steps(page) == ["ergebnis", "fertig"] and 'href="/reports/q1.html#s' not in page
    # Auftrag läuft, in diesem Match kein Check: die Lektion mit dem Ziel als Satz
    h = {"report_file": "q1.html", "players": {ME: {"name": "Ich"}}, "lead_by": {ME: None}, "lessons": {ME: {}},
         "focus_check": {ME: {"check": None, "focus": {"lesson": "blind", "target": 0.8}}}}
    v = api._minute_player(h, ME)["lesson"]
    assert v["id"] == "blind" and v["says"] == []  # ohne Rundenzahl keine Zahlen
    v = api._minute_player({**h, "rounds": 25}, ME)["lesson"]
    assert v["says"] == ["In diesem Match kam der Fehler keinmal in 25 Runden vor.",
                         "Dein Ziel ist höchstens 2 in so vielen Runden."]  # 0,8 pro 10 Runden bei 25 Runden


def test_minute_story_mastered_points_to_next_lesson():
    check = {"lesson": "moving_shot", "title": LESSONS["moving_shot"][0], "count": 0, "rate": 0.0, "target": 0.6,
             "met": True, "streak": 2, "need": 2, "rounds": 24}
    h = {"report_file": "x.html", "players": {ME: {"name": "Ich", "rounds": 24}}, "lessons": {ME: {}},
         "focus_check": {ME: {"check": check, "mastered": "moving_shot", "new": True,
                              "focus": {"lesson": "crosshair", "target": 1.0}}}}
    v = api._minute_player(h, ME)["lesson"]
    assert v["id"] == "moving_shot" and v["stamp"] == ("ok", "Lektion geschafft")
    assert v["next"] == {"id": "crosshair", "title": course_texts.LESSONS["crosshair"]["title"]}
    assert " ".join(v["says"]) == (
        "In diesem Match kam der Fehler keinmal in 24 Runden vor. Erlaubt waren höchstens 1, du hast das Ziel also "
        "geschafft. Das war dein 2. Match in Folge im Ziel. Damit hast du die Lektion geschafft. Als Nächstes kommt "
        f"die Lektion „{course_texts.LESSONS['crosshair']['title']}“.")


def _both_entry():
    pipeline.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    sc = {"lesson": "no_shot_close", "sid": BRO, "round": 4, "tick": 900, "cost": 10, "happened": "Bruder-Szene."}
    history.save({"id": "b2", "map": "de_mirage", "analyzed_at": "2026-10-01T10:00", "report_file": "b2.html",
                  "players": {ME: {"name": "Ich"}, BRO: {"name": "Bruder"}},
                  "score_by": {ME: [13, 7], BRO: [7, 13]}, "impact": {ME: {"total": 250}, BRO: {"total": -120}},
                  "lead_by": {ME: "utility", BRO: "no_shot_close"}, "scenes": [sc],
                  "focus_check": {ME: {"check": None, "focus": {"lesson": "utility", "target": 1.0}},
                                  BRO: {"check": None, "focus": {"lesson": "no_shot_close", "target": 1.0}}}},
                 pipeline.HISTORY_DIR)


def test_minute_story_pick_player_without_login():
    _both_entry()
    c = TestClient(api.app)
    page = c.get("/m/b2.html").text  # zwei Fokus-Spieler, kein Login: erst wählen
    assert "Wessen Match?" in page and f'href="/m/b2.html?p={BRO}"' in page and f'href="/m/b2.html?p={ME}"' in page
    assert "13:7" not in page and "data-step" not in page
    his = c.get(f"/m/b2.html?p={BRO}").text
    assert "7:13" in his and "Niederlage" in his and LESSONS["no_shot_close"][0] in his
    assert 'href="/reports/b2.html#s4-900"' in his and "Bruder" in his
    assert "13:7" not in his and LESSONS["utility"][0] not in his and 'data-mine="1"' not in his
    assert "13:7" in c.get(f"/m/b2.html?p={ME}").text
    assert "Wessen Match?" in c.get("/m/b2.html?p=fremd").text


def test_minute_story_logged_in_only_own_data():
    _both_entry()
    for u, sid in (("Hausi", ME), ("Bruder", BRO)):
        accounts.add_user(u, "Geheim-12345")
        accounts.link_steamid(u, sid)
    a = TestClient(api.app)
    a.post("/login", data={"name": "Hausi", "password": "Geheim-12345"}, headers=O)
    for url in ("/m/b2.html", f"/m/b2.html?p={BRO}"):  # fremder Spieler per Parameter: trotzdem nur der eigene
        page = a.get(url).text
        assert "Wessen Match?" not in page and "13:7" in page and LESSONS["utility"][0] in page
        assert "7:13" not in page and LESSONS["no_shot_close"][0] not in page and "Bruder" not in page
        assert "#s4-900" not in page and f'data-sid="{ME}"' in page and 'data-mine="1"' in page


def test_lesson_page_builds_weekplan_and_home_keeps_small_upload():
    from cstaktik import autodl, weekplan

    _save_entry()
    coaching.save({"players": {ME: {"focus": {"lesson": "utility", "target": 1.0, "baseline": 2.0,
                                              "created_at": "2026-10-01T10:00", "matches": [], "status": "aktiv"},
                                    "done": [], "drills": []}}}, pipeline.COACHING_FILE)
    c = TestClient(api.app)
    home = c.get("/").text
    assert "Demo selbst hochladen" in home and "Wo finde ich die Demo?" in home
    assert c.get("/kurs/utility").status_code == 200
    key = weekplan.week_key(weekplan.local_today())
    assert key in coaching.load(pipeline.COACHING_FILE)["players"][ME]["weeks"]  # "Übung gemacht" hakt ihn mit ab
    autodl.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (autodl.CONFIG_DIR / "config.json").write_text("{}")
    home = c.get("/").text
    assert "Demo selbst hochladen" in home and "Wo finde ich die Demo?" not in home


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


def _story_entry():
    """Muster aus dem Audit: 30 Runden mit Overtime, Thema Utility, Szenen mit Haupt- und Nebenfehler."""
    rows = []
    for n in range(1, 31):  # T 1-12, CT 13-24, Overtime 25-30
        side = "t" if n <= 12 or 25 <= n <= 27 else "ct"
        rows.append([n, side, n in (3, 7, 10) or 13 <= n <= 23 or n in (26, 27), 1 if n % 2 else 0,
                     1 if n % 3 else 0, 50])
    kills, deaths = sum(r[3] for r in rows), sum(r[4] for r in rows)
    sc = {"sid": ME, "tick": 500, "from": 400, "happened": "x", "lessons": ["utility"]}
    util = {"smoke": 19, "flash": 12, "he": 14, "molotov": 12}
    return {"report_file": "s.html", "rounds": 30,
            "players": {ME: {"name": "Ich", "kills": kills, "deaths": deaths, "adr": 63.9, "rounds": 30, "utility": util}},
            "score_by": {ME: [14, 16]}, "by_round": {ME: rows}, "mech": {ME: {"hs_pct": 41.2}},
            "impact": {ME: {"total": -60, "rank": 6, "of": 10}}, "lead_by": {ME: "utility"},
            "lessons": {ME: {"utility": 11, "alone": 2}}, "util_stats": {ME: {"pre": 0.63}},
            "focus_check": {ME: {"check": None, "new": True, "focus": {"lesson": "utility", "target": 2.2}}},
            "deaths": [{"sid": ME, "place": "Apartments", "side": "t", "round": r} for r in (5, 7, 9, 11)],
            "scenes": [{**sc, "round": 7, "lesson": "alone", "lessons": ["alone", "utility"], "cost": 35,
                        "own": 5, "enemy": 3},
                       {**sc, "round": 3, "lesson": "utility", "cost": 40, "own": 5, "enemy": 3, "nades": ["Smoke"]},
                       {**sc, "round": 12, "lesson": "utility", "cost": 31, "own": 1, "enemy": 2,
                        "nades": ["Flash", "Molotov"]}]}


def test_minute_story_in_player_language():
    h = _story_entry()
    v = api._minute_player(h, ME)
    # Ergebnis: zuerst was Spieler kennen (K/D, ADR, HS), dann T/CT und Overtime
    assert v["stats"] == {"k": 15, "d": 20, "adr": 64, "hs": 41}
    assert [(x["label"], x["won"], x["lost"]) for x in v["sides"]] == [("T-Seite", 3, 9), ("CT-Seite", 11, 1),
                                                                     ("Overtime", 2, 4)]
    assert sum(x["k"] for x in v["sides"]) == 15 and sum(x["d"] for x in v["sides"]) == 20
    assert v["imp"]["meaning"] == "Deine Kills und Tode haben eurem Team zusammen etwa 0,6 Runden gekostet."
    # Lektion: der neue Auftrag (Utility), Zahlen als Sätze in Fehlern und Runden
    les = v["lesson"]
    assert les["id"] == "utility" and les["says"] == ["In diesem Match kam der Fehler 11 Mal in 30 Runden vor.",
                                                     "Ab dem nächsten Match ist dein Ziel höchstens 6 in so vielen Runden."]
    # Szene: Hauptfehler Utility in einer verlorenen Runde; nicht der Lurk-Tod (Nebenfehler), und der Tod in Überzahl
    # in einer gewonnenen Runde kostet wenig, auch wenn die Siegchance kurz sank
    assert les["scene"]["round"] == 12 and les["scene"]["nades"] == ["Flash", "Molotov"]
    assert les["util_late"].startswith("Du wirfst viel, aber zu spät: 57 Granaten in 30 Runden.")
    # Summen passen nicht zu K/D: lieber keine Aufteilung
    bad = {**h, "players": {ME: {**h["players"][ME], "kills": 99}}}
    assert api._minute_player(bad, ME)["sides"] is None
    # wenig geworfen: kein "zu spät"
    few = {**h, "players": {ME: {**h["players"][ME], "utility": {"flash": 10}}}}
    assert api._minute_player(few, ME)["lesson"]["util_late"] is None


def test_minute_story_page_shows_plain_numbers():
    pipeline.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    history.save({**_story_entry(), "id": "s1", "map": "de_mirage", "analyzed_at": "2026-10-01T10:00"},
                 pipeline.HISTORY_DIR)
    page = TestClient(api.app).get("/m/s.html").text
    assert "15/20" in page and "Kills/Tode" in page and "41 %" in page
    assert "T-Seite</i>3:9 Runden" in page and "Overtime</i>2:4 Runden" in page
    assert "In der Tasche beim Tod: Flash, Molotov." in page and "Du wirfst viel, aber zu spät" in page
    assert "Ab dem nächsten Match ist dein Ziel höchstens 6 in so vielen Runden." in page
    assert "pro 10 Runden" not in page


def test_seen_first_sentence_does_not_contradict_the_shot():
    from cstaktik.coach_voice import _duel_sentence

    shot = _duel_sentence({"attacker": "g1", "duel": {"seen": "gegner", "seen_ms": None, "react": 203}})
    assert "G1 hat dich zuerst gesehen." in shot and "gar nicht" not in shot and "203 ms nach seinem" in shot
    never = _duel_sentence({"attacker": "g1", "duel": {"seen": "gegner", "seen_ms": None}})
    assert "du ihn gar nicht" in never


def test_report_rounds_tab_and_one_definition():
    import tempfile
    from pathlib import Path

    from cstaktik.report.render import render_report

    m, result = _match_with_lessons()
    html = render_report(m, result, maps_dirs=[Path(tempfile.mkdtemp())])
    data = json.loads(re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S).group(1))
    own = [r for r in data["rounds"] if not r.get("pro")]
    # Runden-Reiter: Kauf je Seite und je Fokus-Spieler Kills, Tod, Schaden (gleich gezählt wie K/D)
    assert set(own[0]["buy"]) == {"t", "ct"} and own[0]["buy"]["t"] in ("pistol", "eco", "force", "full", None)
    for st in result.stats:
        assert sum((r.get("me") or {}).get(st.steamid, [0, 0, 0])[0] for r in own) == st.kills
        assert sum((r.get("me") or {}).get(st.steamid, [0, 0, 0])[1] for r in own) == st.deaths
    assert "(deaktiviert)" not in html and "<span class=\"t\">Tod ohne Schaden" not in html  # aus bzw. doppelt
    assert '<details class="tech"><summary>Technik</summary>Werte aus der Demo, geparst mit awpy' in html
    assert "function callout(" in html and "function gclock(" in html  # Callouts und Spieluhr im Replay
