"""Erinnerung vor dem Match: einmal am Tag, im Fenster vor der Spielzeit, nicht nach dem Warm-up."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from synth import ME

from cstaktik import accounts, api, drills, notify, reminder

O = {"Origin": "http://testserver"}


def _setup(monkeypatch):
    accounts.add_user("Hausi", "Geheim-12345")
    accounts.link_steamid("Hausi", ME)
    monkeypatch.setattr(notify, "subs", lambda user: [{"endpoint": "x"}])
    sent = []
    monkeypatch.setattr(notify, "send_user", lambda user, msg, post=None: sent.append((user, msg)) or 1)
    return sent


def test_window_once_per_day_and_not_after_warmup(monkeypatch):
    sent = _setup(monkeypatch)
    reminder.set_time("Hausi", "20:00")
    assert reminder.check(datetime(2026, 3, 5, 19, 40)) == []  # zu früh
    assert reminder.check(datetime(2026, 3, 5, 19, 46)) == ["Hausi"]
    assert sent[0][1]["url"] == "/warmup" and sent[0][1]["title"].startswith("Gleich geht's los")
    assert reminder.check(datetime(2026, 3, 5, 19, 50)) == []  # nur einmal am Tag
    d = drills.load(ME)
    d["warmups"] = ["2026-03-06T19:30:00"]
    drills._save(ME, d)
    assert reminder.check(datetime(2026, 3, 6, 19, 50)) == []  # heute schon aufgewärmt


def test_message_has_plan_and_cue():
    drills.set_plan(ME, "alone", "Wenn ich peeken will, dann warte ich auf den Trade.", "m1.html", "2026-01-01T10:00")
    m = reminder.message(ME)
    assert "Wenn ich peeken will" in m["body"] and "„Nie ohne Partner“" in m["body"]
    assert "Zwei Minuten Warm-up" in reminder.message(None)["body"]


def test_set_time_validates_and_page(monkeypatch):
    _setup(monkeypatch)
    with pytest.raises(ValueError):
        reminder.set_time("Hausi", "25:00")
    a = TestClient(api.app)
    a.post("/login", data={"name": "Hausi", "password": "Geheim-12345"}, headers=O)
    a.post("/konto/erinnerung", data={"time": "21:30"}, headers=O)
    assert reminder.get("Hausi") == "21:30" and 'value="21:30"' in a.get("/konto").text
    a.post("/konto/erinnerung", data={"time": ""}, headers=O)
    assert reminder.get("Hausi") is None
