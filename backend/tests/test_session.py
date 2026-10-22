"""Spielabend ("Heute"), Übungs-Vergleich und die Abmachung aus dem Report."""

from datetime import date, timedelta

from fastapi.testclient import TestClient
from synth import BRO, ME

from cstaktik import accounts, api, coaching, history, notify, pipeline, session, weekplan
from cstaktik.coach_voice import LESSONS

O = {"Origin": "http://testserver"}
DAY = date(2026, 10, 16)


def _h(mid, at, score, sid=ME, rounds=22, count=1, imp=100, lesson="utility", target=1.0):
    """Verlaufs-Eintrag eines Spielers mit Auftrag-Check (Lektion, Ziel) und Impact."""
    check = {"lesson": lesson, "title": LESSONS[lesson][0], "target": target, "rate": 0.5, "count": count,
             "rounds": rounds, "met": True}
    return {"id": mid, "map": "de_mirage", "analyzed_at": at, "report_file": f"{mid}.html", "rounds": rounds,
            "players": {sid: {"name": "Ich" if sid == ME else "Bruder", "rounds": rounds}},
            "score_by": {sid: list(score)}, "lessons": {sid: {lesson: count}},
            "impact": {sid: {"total": imp}} if imp is not None else {},
            "focus_check": {sid: {"check": check, "focus": {"lesson": lesson, "target": target}}}}


def _evening():
    d = DAY.isoformat()
    return [_h("y1", f"{(DAY - timedelta(days=1)).isoformat()}T22:00:00", (13, 2)),  # gestern
            _h("a1", f"{d}T19:00:00", (13, 9)),
            _h("b1", f"{d}T19:30:00", (4, 13), sid=BRO),  # nur der Bruder
            _h("a2", f"{d}T20:10:00", (12, 12), imp=-40)]


def test_session_counts_own_matches_of_the_day_with_draw():
    s = session.session(_evening(), ME, DAY)
    assert s["n"] == 2 and (s["won"], s["lost"], s["draw"]) == (1, 0, 1)
    assert s["line"] == "Heute 2 Matches: 1 Sieg, 0 Niederlagen, 1 Unentschieden."
    assert s["impact"] == {"total": "+0,6", "pos": True}
    a = s["auftrag"]  # 2x in 44 Runden: genug Runden, Rate 0,5 unter dem Ziel 1,0
    assert a["count"] == 2 and a["rounds"] == 44 and a["met"] and "Im Ziel." in a["text"]
    assert s["tilt"] is None  # ein Abend reicht nicht für die Tilt-Schwellen
    assert session.session(_evening(), BRO, DAY) is None  # nur ein Match: kein Spielabend
    assert session.session(_evening(), ME, DAY, until=f"{DAY.isoformat()}T19:00:00") is None


def test_session_hides_weak_parts():
    hs = _evening()
    for h in hs:
        h["players"][ME if ME in h["players"] else BRO]["rounds"] = 15  # zusammen nur 30 Runden
    hs[3]["impact"] = {}  # ein Match ohne Impact: keine Summe
    s = session.session(hs, ME, DAY)
    assert s["n"] == 2 and s["auftrag"] is None and s["impact"] is None
    assert session.session([], ME, DAY) is None


def test_push_line_from_second_match_of_the_day():
    hs = _evening()
    first = notify.match_message(hs[1], ME, hs)
    second = notify.match_message(hs[3], ME, hs)
    assert "Heute" not in first["body"]
    assert second["body"].endswith("Heute 2 Matches: 1 Sieg, 0 Niederlagen, 1 Unentschieden.")
    assert "Heute" not in notify.match_message(hs[2], BRO, hs)["body"]
    assert "Heute" not in notify.match_message(hs[3], ME)["body"]  # ohne Verlauf wie bisher


def _slot(with_rounds=45, without_rounds=45, with_n=2, without_n=9):
    m = lambda i, drills, n, r: {"match": f"m{i}", "date": f"2026-01-0{i}T10:00:00", "rate": round(10 * n / r, 1),  # noqa: E731
                                 "met": None, "count": n, "rounds": r, "drills": drills}
    return {"focus": {"lesson": "utility", "matches": [m(1, 1, with_n, with_rounds), m(2, 0, without_n, without_rounds),
                                                       {"match": "alt", "date": "2026-01-03T10:00:00", "rate": 6.0, "met": None, "count": 30, "rounds": 50}]},
            "done": [{"lesson": "alone", "matches": []}]}


def test_practice_needs_rounds_on_both_sides():
    p = session.practice(_slot())
    assert p["state"] == "besser"
    assert p["text"].startswith("In Matches nach einer Übung: 0,4 Fokus-Fehler pro 10 Runden (2x in 45 Runden). "
                                "Ohne: 2,0 (9x in 45 Runden).")
    assert "kein Beweis" in p["text"]
    assert session.practice(_slot(with_rounds=30)) is None  # zu wenig Runden nach Übungen
    assert session.practice(_slot(without_rounds=30)) is None
    assert session.practice(_slot(with_n=8, without_n=9))["text"].endswith("Kein klarer Unterschied.")
    assert session.practice(None) is None and session.practice({}) is None


def _today(hh):
    return f"{weekplan.local_today().isoformat()}T{hh}:00:00"


def _save(h):
    pipeline.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    history.save(h, pipeline.HISTORY_DIR)
    (pipeline.REPORTS_DIR / h["report_file"]).write_text("<html><head><title>x</title></head><body></body></html>")


def _login(name):
    c = TestClient(api.app)
    c.post("/login", data={"name": name, "password": "Geheim-12345"}, headers=O)
    return c


def test_today_block_on_home_and_minute_page():
    _save(_h("t1", _today("00"), (13, 9)))
    c = TestClient(api.app)
    _save(_h("t2", _today("00").replace(":00:00", ":05:00"), (5, 13)))
    assert "Heute 2 Matches" not in c.get("/").text  # Startseite: nur neues Match und Fokus, der Abend steht im Match
    assert "Heute 2 Matches: 1 Sieg, 1 Niederlage." in c.get("/m/t2.html").text  # Story: eine Zeile im Ergebnis
    assert "Heute 2 Matches" not in c.get("/m/t1.html").text  # bis zu diesem Match: erst eins
    slot = _slot()
    slot["focus"].update({"target": 1.0, "baseline": 2.0, "created_at": "2026-01-01T00:00:00", "status": "aktiv"})
    coaching.save({"players": {ME: {**slot, "drills": []}}}, pipeline.COACHING_FILE)
    assert "In Matches nach einer Übung" in c.get(f"/progress?p={ME}").text  # Fortschritt


def test_deal_saved_for_own_player_shown_until_next_match():
    _save(_h("d1", "2026-01-01T10:00:00", (13, 7)))
    coaching.save({"players": {ME: {"focus": {"lesson": "utility", "target": 1.0, "baseline": 2.0, "matches": []},
                                    "done": [], "drills": []}}}, pipeline.COACHING_FILE)
    for u, sid in (("Hausi", ME), ("Bruder", BRO)):
        accounts.add_user(u, "Geheim-12345")
        accounts.link_steamid(u, sid)
    a, b = _login("Hausi"), _login("Bruder")
    body = {"sid": ME, "lesson": "utility", "report": "d1.html"}
    assert a.post("/training/deal", json={**body, "sid": BRO}, headers=O).status_code == 403
    assert b.post("/training/deal", json=body, headers=O).status_code == 403  # nicht sein Spieler
    assert b.post("/training/deal", json={**body, "sid": BRO}, headers=O).status_code == 404  # nicht sein Match
    assert a.post("/training/deal", json=body, headers={"Origin": "https://fremd.example"}).status_code == 403
    assert a.post("/training/deal", json=body, headers=O).json() == {"ok": True}
    home = a.get("/kurs").text
    assert ("Nach dem Match auf Mirage (13:7) hast du dir vorgenommen: "
            f"{LESSONS['utility'][0]}: höchstens 1,0x pro 10 Runden.") in home  # in der Karte der aktuellen Lektion
    assert "vorgenommen" not in b.get("/kurs").text  # nur beim eigenen Nutzer
    _save(_h("d2", "2026-01-02T10:00:00", (10, 13)))  # nächstes Match ausgewertet
    assert "vorgenommen" not in a.get("/kurs").text


def test_deal_without_accounts_stays_in_browser():
    _save(_h("d1", "2026-01-01T10:00:00", (13, 7)))
    c = TestClient(api.app)
    assert c.post("/training/deal", json={"sid": ME, "lesson": "utility", "report": "d1.html"},
                  headers=O).status_code == 400
    assert "vorgenommen" not in c.get("/").text
