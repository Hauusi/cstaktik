"""Spielerprofil: Urteil je Bereich aus den Kurs-Lektionen, Kennzahlen mit Verlauf, Economy ohne Urteil."""

from cstaktik import spielerprofil

ME = "1"


def _h(i, alone=0, traded=1, deaths=4, won=50):
    return {"id": f"m{i}", "map": "de_mirage", "rounds": 20, "analyzed_at": f"2026-01-{i + 1:02d}T10:00",
            "players": {ME: {"name": "Ich", "rounds": 20}}, "lessons": {ME: {"alone": alone}},
            "deaths": [{"sid": ME, "traded": k < traded} for k in range(deaths)],
            "duel_stats": {ME: {"n": 10, "won": won}}, "cause_rounds": {"economy": 1, "advantage": 0},
            "board": {ME: {"rounds": 20, "kills": 15, "deaths": deaths, "hs": 6, "ok": 2, "od": 2, "k1": 5, "k2": 2, "k3": 0,
                           "k4": 0, "k5": 0, "assists": 3, "kast": 14, "survived": 16, "dmg": 1500, "traded": 1,
                           "assists_known": True, "dmg_known": True}}}


def test_area_verdicts_and_trends():
    hist = [_h(i, alone=0, traded=0, won=40) for i in range(10)] + [_h(10 + i, alone=4, traded=3, won=60) for i in range(10)]
    p = spielerprofil.build(hist, ME)
    a = {x["key"]: x for x in p["areas"]}
    assert a["team"]["verdict"] == "baustelle" and a["team"]["worst"] == "alone" and "Grenze" in a["team"]["why"]
    assert "Zusammenspiel" in p["weak"]
    m = {x["key"]: x for x in a["team"]["metrics"]}
    assert m["traded"]["value"] == "75 %" and m["traded"]["trend"] == "up"  # 75 % gegen 0 % davor
    d = {x["key"]: x for x in a["duel"]["metrics"]}
    assert d["duel_won"]["trend"] == "up" and d["duel_won"]["ref"] == 50 and d["duel_won"]["vs_ref"] == "über"
    assert a["eco"]["verdict"] is None and a["eco"]["metrics"][0]["value"] == "0,5 pro 10 R."
    assert p["has_prev"] and p["n"] == 10


def test_no_trend_without_three_earlier_matches_and_empty():
    p = spielerprofil.build([_h(i) for i in range(12)], ME)
    assert not p["has_prev"] and all(m["trend"] is None for a in p["areas"] for m in a["metrics"])
    assert spielerprofil.build([], ME) is None
