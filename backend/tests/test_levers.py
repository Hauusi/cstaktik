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


def test_levers_need_enough_scenes():
    hs = [{"players": {"a": {}}, "scenes": [{"sid": "a", "lesson": "alone", "cost": 90}]}]
    assert levers.build(hs, [], "a") == []  # eine Szene in einem Match: keine Zahl
    lv = levers.build(hs * 4, [], "a")
    assert lv and lv[0]["text"].startswith("Verlorene Rundenchance bei diesen Toden") and "4 Szenen in 4 Matches" in lv[0]["text"]


def test_levers_overlap_counted_once_and_thin_data():
    # Ein Match: dieselben 11 T-Runden sind Full Buy UND "erster Tod" -> nicht zweimal addieren, nur ein Hebel
    def play(r, won, first):
        return {"r": r, "t_eq": 25000, "won": won, "site": "A", "arrive": 30, "approach": {},
                "kills": [{"t": 10, "side": first}]}

    own = [play(r, r == 0, "t") for r in range(11)]
    pro = [{"map": "de_mirage", "plays": [play(r, r % 2 == 0, "t") for r in range(20)]}]
    one = [{"players": {"a": {}}, "map": "de_mirage", "plays": own}]
    lv = levers.build(one, pro, "a")
    assert len(lv) == 1 and lv[0].get("thin") and "Tendenz" in lv[0]["text"]
    assert "Runden aus 1 Demo)" in lv[0]["text"]  # Pro-Basis steht dabei
    lv = levers.build([dict(one[0]), dict(one[0])], pro, "a")
    assert len(lv) == 1  # Kauf, erster Tod und Taktik sind dieselben Runden: nur der größte Hebel zählt
    assert not lv[0].get("thin")


def test_levers_dedupe_scales_partial_overlap():
    a = {"gain": 2.0, "rounds": {1, 2, 3, 4}, "text": "A."}
    b = {"gain": 1.0, "rounds": {3, 4, 5, 6, 7, 8}, "text": "B."}
    c = {"gain": 0.9, "rounds": {1, 2, 3, 9}, "text": "C."}
    out = levers.dedupe([b, a, c])
    assert [x["text"][:2] for x in out] == ["A.", "B."]
    assert round(out[1]["gain"], 2) == 0.67 and "2 dieser Runden" in out[1]["text"]
