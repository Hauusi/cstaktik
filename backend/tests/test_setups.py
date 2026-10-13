"""Positionen und Ausführungen: CT-Orte mit Toden/Siegen, T-Ausführungen aus Timeline und Granaten."""

from synth import build_match

from cstaktik import setups


def test_ct_positions_with_pro_share():
    m = build_match()
    for p in m.positions:
        p.place = "SynthB"
    pro = [{"map": "de_mirage", "timeline": [{"round": r, "sid": "p", "side": "ct", "won": r % 2 == 0,
                                              "places": [None] * 4 + ["SynthB"]} for r in range(12)]}]
    rows, top = setups.ct_positions(m, pro)
    me = next(r for r in rows if r["who"] == "Ich")
    assert me["place"] == "SynthB" and me["rounds"] >= 1 and me["pro_share"] == 100 and me["pro_won"] == 50
    assert top[0]["place"] == "SynthB"


def test_executes_from_timeline():
    tl = [{"round": 1, "sid": s, "side": "t", "won": True,
           "places": ["TSpawn", "TSpawn", "BombsiteA" if s in "ab" else "Mid", "BombsiteA"]} for s in "abc"]
    nades = [{"r": 1, "side": "t", "to": "BombsiteA", "t": 5.0}, {"r": 1, "side": "t", "to": "Mid", "t": 5.0}]
    ex = setups.executes_from(tl, nades)
    assert ex == [{"round": 1, "site": "BombsiteA", "at": 10, "players": 3, "util": 1, "won": True}]
