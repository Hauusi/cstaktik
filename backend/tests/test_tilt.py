from cstaktik import tilt


def _hist(n_matches=4):
    hs = []
    for m in range(n_matches):
        seq, deaths, rounds = [], [], {}
        # Muster: L L L W W L L L W W ... (Runde 1 = Pistole)
        for num in range(1, 25):
            won = (num - 1) % 5 >= 3
            seq.append([num, "ct" if num <= 12 else "t", won])
            prev_lost_twice = num > 2 and not seq[-2][2] and not seq[-3][2]
            if prev_lost_twice:
                deaths.append({"sid": "a", "round": num, "first": True, "traded": False})
                rounds[str(num)] = -20.0
            else:
                rounds[str(num)] = 10.0
        hs.append({"players": {"a": {}}, "seq": seq, "deaths": deaths,
                   "impact": {"a": {"total": 0, "rounds": rounds}}})
    return hs


def test_tilt_detected_after_losing_streak():
    s = tilt.summary(_hist(), "a")
    g = s["groups"]
    assert g["serie"]["n"] >= 25 and g["sieg"]["n"] >= 25
    assert g["serie"]["first"] == 100 and g["sieg"]["first"] == 0
    assert g["serie"]["impact"] == -20.0 and g["sieg"]["impact"] == 10.0
    assert s["enough"] and "messbar schlechter" in s["reading"]


def test_pistol_rounds_skipped_and_few_rounds():
    rs = tilt.rows(_hist(1), "a")
    assert len(rs) == 22  # 24 Runden minus zwei Pistolen
    s = tilt.summary(_hist(1), "a")
    assert not s["enough"] and s["reading"] is None
    assert tilt.summary(_hist(1), "zz") is None


def test_no_impact_no_verdict():
    hs = _hist()
    for h in hs:
        h["impact"] = {}
    assert tilt.summary(hs, "a") is None  # z. B. Gegner oder alte Matches: keine "kein Tilt"-Aussage
    hs = _hist()
    for h in hs:
        h["seq"] = {"a": h["seq"]}  # neues Format je Spieler
    assert tilt.summary(hs, "a")["enough"]


def test_unscored_death_round_is_unknown_not_zero():
    hs = _hist(1)
    r = next(d["round"] for d in hs[0]["deaths"])
    del hs[0]["impact"]["a"]["rounds"][str(r)]  # Tod nicht bewertbar
    del hs[0]["impact"]["a"]["rounds"]["5"]  # Runde ohne Tod und ohne Wert: bleibt 0
    rows = {i: x for i, x in enumerate(tilt.rows(hs, "a"))}
    vals = [x["impact"] for x in rows.values()]
    assert vals.count(None) == 1 and 0.0 in vals
