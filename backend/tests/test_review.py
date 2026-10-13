"""Review über mehrere Matches."""

from cstaktik import review


def _h(i, alone, cost, err):
    return {"id": str(i), "analyzed_at": f"2026-10-{i + 1:02d}", "rounds": 20, "won": 13, "lost": 9,
            "players": {"a": {"name": "Satoru"}}, "lessons": {"a": {"alone": alone}},
            "scenes": [{"sid": "a", "lesson": "alone", "cost": cost}], "duel_stats": {"a": {"err": err, "react": 300,
                                                                                         "first_hit": 20, "n": 4}}}


def test_review_window_vs_before():
    hs = [_h(i, 4, 20, 25.0) for i in range(5)] + [_h(i, 2, 30, 18.0) for i in range(5, 10)]
    r = review.build(hs, 5)
    p = r["players"][0]
    top = p["lessons"][0]
    assert top["id"] == "alone" and top["count"] == 10 and top["rounds_lost"] == 1.5
    assert top["rate"] == 1.0 and top["rate_before"] == 2.0 and top["trend"] == "besser"
    assert p["duels"]["err"] == 18.0 and p["duels_before"]["err"] == 25.0
    assert r["say"][0].startswith("Satoru: In den letzten 5 Matches hat dich „Nicht ohne Trade-Partner peeken“")
    assert "Weniger als davor" in r["say"][0] and "jetzt 18° daneben, vorher 25° – besser." in r["say"][0]
