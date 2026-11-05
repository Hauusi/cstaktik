"""Wochenrückblick: letzte 7 Tage gegen die 4 Wochen davor, Push sonntags einmal je Woche."""

from datetime import datetime

from fastapi.testclient import TestClient
from synth import ME

from cstaktik import accounts, api, drills, history, notify, pipeline, reminder, weekly

O = {"Origin": "http://testserver"}


def _h(day, kills, traded, won=True):
    b = {"rounds": 20, "kills": kills, "deaths": 15, "hs": 5, "ok": 2, "od": 2, "k1": kills, "k2": 0, "k3": 0, "k4": 0,
         "k5": 0, "assists": 2, "kast": 12, "survived": 5, "dmg": 1500, "traded": 2, "assists_known": True, "dmg_known": True}
    return {"id": f"w{day}", "map": "de_mirage", "rounds": 20, "analyzed_at": f"2026-03-{day:02d}T20:00",
            "report_file": f"w{day}.html", "players": {ME: {"name": "Hausi", "rounds": 20}}, "board": {ME: b},
            "score_by": {ME: [13, 7] if won else [7, 13]},
            "deaths": [{"sid": ME, "traded": k < traded} for k in range(10)]}


def test_week_against_weeks_before():
    hist = [_h(d, 10, 1, won=False) for d in (2, 5, 8, 10)] + [_h(d, 25, 6) for d in (16, 18, 20)]
    slot = {"focus": {"lesson": "alone", "matches": [{"date": "2026-03-18T20:00", "met": True},
                                                       {"date": "2026-03-20T20:00", "met": False}]},
            "done": [{"lesson": "utility", "done_at": "2026-03-19T20:00"}]}
    d = drills.load(ME)
    d["warmups"] = ["2026-03-16T19:50:00", "2026-03-18T19:50:00", "2026-03-20T19:50:00"]
    drills._save(ME, d)
    r = weekly.build(hist, ME, datetime(2026, 3, 22, 19, 30), slot)
    text = " ".join(r["lines"])
    assert r["lines"][0] == "Diese Woche: 3 Matches, 3 Siege, 0 Niederlagen."
    assert "besser als in den Wochen davor" in r["lines"][1]
    assert "Besser geworden:" in text and "Deine Tode getradet (10 % auf 60 %)" in text
    assert "An „Nicht ohne Trade-Partner peeken“: 1 von 2 Matches im Ziel." in text
    assert "Geschafft diese Woche: „Erst Utility, dann Duell“." in text
    assert "Warm-up an 3 Tagen" in text and r["lines"][-1].startswith("Nächste Woche bleiben wir bei")
    empty = weekly.build([], ME, datetime(2026, 3, 22), None)
    assert empty["matches"] == 0 and empty["lines"][0].startswith("Diese Woche gab es kein Match")


def test_weekly_push_once_on_sunday(monkeypatch):
    accounts.add_user("Hausi", "Geheim-12345")
    accounts.link_steamid("Hausi", ME)
    monkeypatch.setattr(notify, "subs", lambda user: [{"endpoint": "x"}])
    sent = []
    monkeypatch.setattr(notify, "send_user", lambda user, msg, post=None: sent.append(msg) or 1)
    hist = [_h(20, 15, 3)]
    assert reminder.weekly_check(datetime(2026, 3, 21, 20, 0), hist=hist) == []  # Samstag
    assert reminder.weekly_check(datetime(2026, 3, 22, 18, 0), hist=hist) == []  # zu früh
    assert reminder.weekly_check(datetime(2026, 3, 22, 19, 5), hist=hist) == ["Hausi"]
    assert sent[0]["url"] == "/woche" and sent[0]["body"].startswith("Diese Woche: 1 Match")
    assert reminder.weekly_check(datetime(2026, 3, 22, 21, 0), hist=hist) == []  # einmal je Woche
    assert reminder.weekly_check(datetime(2026, 3, 29, 19, 5), hist=hist) == []  # Woche ohne Match


def test_week_page():
    history.save(_h(1, 15, 3), pipeline.HISTORY_DIR)
    accounts.add_user("Hausi", "Geheim-12345")
    accounts.link_steamid("Hausi", ME)
    c = TestClient(api.app)
    c.post("/login", data={"name": "Hausi", "password": "Geheim-12345"}, headers=O)
    page = c.get("/woche").text
    assert 'data-block="woche"' in page and "Wochenrückblick" in page
