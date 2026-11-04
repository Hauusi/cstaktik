"""Tagesplan: Schritte und erledigt nur aus gespeicherten Daten."""

from datetime import datetime

from cstaktik import academy, dayplan, drills

ME = "1"


def test_steps_and_done_state(monkeypatch):
    now = datetime(2026, 3, 5, 18)
    monkeypatch.setattr(dayplan, "_today_local", lambda: "2026-03-05")
    coach = {"file": "m1.html", "map_label": "Mirage", "done": False}
    slot = {"focus": {"lesson": "alone"}, "drills": [{"lesson": "alone", "date": "2026-03-04T20:00"}]}
    p = dayplan.build(ME, coach, slot, now=now)
    assert [s["id"] for s in p["steps"]] == ["session", "drill", "wissen", "warmup"] and p["done"] == 0
    assert p["next"] == "session" and p["steps"][2]["href"] == "/wissen/trading"  # Thema zur Lektion
    slot["drills"].append({"lesson": "alone", "date": "2026-03-05T17:00"})
    d = drills.load(ME)
    d["warmups"] = ["2026-03-05T17:30:00"]
    d["read"] = {"trading": "2026-03-05T17:10:00"}
    drills._save(ME, d)
    p = dayplan.build(ME, {**coach, "done": True}, slot, now=now)
    assert p["done"] == 4 and p["next"] is None


def test_without_lesson_or_match():
    p = dayplan.build(ME, None, None, now=datetime(2026, 3, 5))
    assert [s["id"] for s in p["steps"]] == ["wissen", "warmup"]
    assert p["steps"][0]["href"] == f"/wissen/{next(iter(academy.TOPICS))}"
    assert dayplan.build("", None, None) is None
