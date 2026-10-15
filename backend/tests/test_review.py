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


def test_review_page_shows_chain_metrics_and_seen_trend(tmp_path, monkeypatch):
    hs = [_h(i, 4, 20, 25.0) for i in range(5)] + [_h(i, 2, 30, 18.0) for i in range(5, 10)]
    for i, h in enumerate(hs):
        h["duel_stats"]["a"].update(seen_n=20, seen_opp=45 if i < 5 else 25, tts=500, tts_n=5)
    r = review.build(hs, 5)
    assert r["players"][0]["duels"]["seen_opp"] == 25 and "du stehst" not in r["say"][0]
    assert "zuerst, vorher 45 % – deine Positionen werden besser." in r["say"][0]
    from cstaktik import api

    html = api._env.get_template("review.html").render(r=r, nav_active="matches")
    assert "Er sah dich zuerst" in html and "vorher 45 %" in html and "Sehen → Schuss" in html


def test_review_team_trends():
    def m(won_after_first_kill):
        plays = [{"won": won_after_first_kill, "kills": [{"t": 5, "side": "ct"}], "t_eq": 25000, "plant_t": None}] * 4
        return {"players": {"a": {"name": "A"}}, "plays": plays, "won": 13, "lost": 5, "rounds": 18}
    hs = [m(False)] * 5 + [m(True)] * 5
    r = review.build(hs, 5)
    row = next(t for t in r["team"] if t["label"] == "T: nach eurem ersten Kill")
    assert row["now"]["won_pct"] == 100 and row["before"]["won_pct"] == 0 and row["trend"] == "besser"
    assert any(s.startswith("Als Team: T: nach eurem ersten Kill 100 % statt 0 %") for s in r["say"])
