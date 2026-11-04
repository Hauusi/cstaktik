"""Stats-Seite: Vergleich mit dem Zeitraum davor, Verlauf, T gegen CT, Maps."""

from cstaktik import stats_view

ME = "1"


def _board(kills, deaths, rounds=20, dmg=None):
    return {"rounds": rounds, "kills": kills, "deaths": deaths, "assists": 2, "dmg": dmg if dmg is not None else 80 * rounds,
            "hs": kills // 2, "kast": 14, "survived": rounds - deaths, "k1": kills, "k2": 0, "k3": 0, "k4": 0, "k5": 0,
            "ok": 2, "od": 2, "traded": 1, "assists_known": True, "dmg_known": True}


def _h(i, kills, deaths, m="de_mirage", by_round=None):
    return {"id": f"m{i}", "map": m, "analyzed_at": f"2026-01-{i + 1:02d}T10:00", "report_file": f"m{i}.html",
            "board": {ME: _board(kills, deaths)}, "score_by": {ME: [13, 7] if kills > deaths else [7, 13]},
            "players": {ME: {"name": "Ich"}}, "by_round": {ME: by_round or []}}


def test_compare_needs_clear_gap_and_three_matches():
    hist = [_h(i, 10, 20) for i in range(10)] + [_h(10 + i, 25, 12) for i in range(10)]
    v = stats_view.build(hist, ME, "10")
    tiles = {t["key"]: t for t in v["tiles"]}
    assert v["sel_n"] == 10 and v["prev_n"] == 10 and v["has_prev"]
    assert tiles["kd"]["cmp"] == "up" and tiles["kd"]["delta"].startswith("+")
    assert tiles["adr"]["cmp"] == "same"  # gleicher Schaden: kein Grün ohne klaren Abstand
    assert v["won"] == 10 and v["lost"] == 0 and v["form"] == ["w"] * 5
    assert len(v["chart"]["points"]) == 10 and tiles["kd"]["spark"] is not None
    few = stats_view.build(hist[:12], ME, "10")  # nur 2 Matches davor
    assert not few["has_prev"] and all(t["cmp"] is None for t in few["tiles"])
    allv = stats_view.build(hist, ME, "all")
    assert len(allv["chart"]["points"]) == 20 and not allv["has_prev"]


def test_map_filter_and_cards():
    hist = [_h(0, 20, 10), _h(1, 10, 20, "de_inferno"), _h(2, 22, 10)]
    v = stats_view.build(hist, ME, "10", "de_inferno")
    assert v["sel_n"] == 1 and [m["label"] for m in v["by_map"]] == ["Mirage", "Inferno"]
    assert v["by_map"][0]["won"] == 2 and v["by_map"][0]["win_pct"] == 100


def test_side_split_only_with_enough_rounds():
    rows = [[r, "t" if r <= 12 else "ct", r % 2 == 0, 1 if r <= 12 else 0, r % 3 == 0, 50] for r in range(1, 25)]
    v = stats_view.build([_h(0, 12, 8, by_round=rows)], ME)
    s = {x["key"]: x for x in v["sides"][1:]}
    assert v["sides"][0] == {"rounds_t": 12, "rounds_ct": 12}
    assert s["kpr"]["t_s"] == "1,00" and s["kpr"]["ct_s"] == "0,00" and s["adr"]["t_s"] == "50"
    assert stats_view.build([_h(0, 12, 8, by_round=rows[:15])], ME)["sides"] is None  # nur 3 CT-Runden
