"""Größte Hebel: Rangliste in Runden pro Match."""

from cstaktik import levers


def test_levers_rank_lessons_and_round_gaps():
    def play(eq, won):
        return {"r": 1, "t_eq": eq, "won": won, "site": "A", "arrive": 30, "approach": {}}

    hs = [{"players": {"a": {}}, "map": "de_mirage",
           "scenes": [{"sid": "a", "lesson": "alone", "cost": 30}, {"sid": "a", "lesson": "utility", "cost": 5},
                      {"sid": "b", "lesson": "alone", "cost": 90}],
           "plays": [play(10000, False)] * 4 + [play(25000, True)]} for _ in range(4)]
    pro = [{"map": "de_mirage", "plays": [play(10000, True)] * 6 + [play(10000, False)] * 4}]
    lv = levers.build(hs, pro, "a")
    assert [x["title"] for x in lv][:2] == ["Force Buy auf T", "Nicht ohne Trade-Partner peeken"]
    force = lv[0]
    assert round(force["gain"], 1) == 2.4 and force["gain_s"] == "2,4"  # 4 Force/Match x 60 % Abstand
    assert round(lv[1]["gain"], 2) == 0.3  # 30 Prozentpunkte je Match, nur Spieler a
    assert all(x["title"] != "Erst Utility, dann Duell" for x in lv)  # 0,05 Runden: Rauschen
    assert levers.build([], pro, "a") == []
