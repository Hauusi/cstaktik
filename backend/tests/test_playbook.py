"""Playbook: T-Runden erkennen (Ziel, Tempo, Split, Kauf) und zu Taktiken gruppieren."""

from cstaktik import playbook
from cstaktik.model import BombEvent, MatchData, PlayerEconomy, PositionSample, Round, Vec

T = ["t1", "t2", "t3", "t4", "t5"]
CT = ["c1", "c2", "c3", "c4", "c5"]


def _match(rnd: int, route: dict, plant_s: float | None, equip: int = 4500) -> MatchData:
    """route: sid -> Liste (Sekunde, Ort, x, y). Positionen jede Sekunde mit dem letzten Ort."""
    tr, start = 64, 1000
    r = Round(num=rnd, start_tick=0, freeze_end_tick=start, end_tick=start + 120 * tr, winner="t",
              sides={**{s: "t" for s in T}, **{s: "ct" for s in CT}},
              economy=[PlayerEconomy(steamid=s, side="t", equip_value=equip) for s in T])
    pos = []
    for sid, steps in route.items():
        for sec in range(0, 100):
            cur = [st for st in steps if st[0] <= sec][-1]
            pos.append(PositionSample(round=rnd, tick=start + sec * tr, steamid=sid, side="t",
                                      pos=Vec(x=cur[2], y=cur[3]), place=cur[1]))
    bomb = ([BombEvent(round=rnd, tick=start + int(plant_s * tr), event="plant", steamid="t1", pos=Vec(x=0, y=0))]
            if plant_s else [])
    return MatchData(map_name="de_mirage", tickrate=tr, tickrate_source="t", players=[], rounds=[r],
                     positions=pos, bomb=bomb)


def _split_route():
    via = {"t1": "Palace", "t2": "Palace", "t3": "Ramp", "t4": "Ramp", "t5": "Ramp"}
    return {s: [(0, "TSpawn", 0, 0), (20, v, 10, 10), (40, "BombsiteA", 20, 20)] for s, v in via.items()}


def test_plays_and_classify_split_execute():
    p = playbook.plays(_match(5, _split_route(), plant_s=48))[0]
    assert p["site"] == "A" and p["arrive"] == 40 and p["plant_t"] == 48.0
    assert set(p["approach"].values()) == {"Palace", "Ramp"} and p["paths"]["t1"][0] == [0, 0]
    k = playbook.classify(p, {})
    assert k["style"] == "split" and k["buy"] == "full" and k["name"] == "A-Split über Palace + Ramp"


def test_rush_eco_pistol_default():
    rush = {s: [(0, "TSpawn", 0, 0), (8, "Apartments", 5, 5), (16, "BombsiteB", 9, 9)] for s in T}
    p = playbook.plays(_match(7, rush, plant_s=22, equip=1000))[0]
    assert playbook.classify(p, {})["style"] == "eco"  # wenig Geld, schnell: Eco-Push
    p = playbook.plays(_match(1, rush, plant_s=22, equip=800))[0]
    assert playbook.classify(p, {})["style"] == "pistol"
    p = playbook.plays(_match(8, rush, plant_s=22, equip=5000))[0]
    assert playbook.classify(p, {})["name"] == "B-Rush über Apartments"
    slow = {s: [(0, "TSpawn", 0, 0), (10, "Mid", 5, 5), (70, "BombsiteB", 9, 9)] for s in T}
    p = playbook.plays(_match(9, slow, plant_s=80, equip=5000))[0]
    assert playbook.classify(p, {})["name"] == "Default, spät auf B"


def test_build_groups_rounds_and_finds_common_nades():
    # ältere Pro-Daten: Granaten auf Demo-Ebene, nicht je Runde
    p1 = {k: v for k, v in playbook.plays(_match(5, _split_route(), plant_s=48))[0].items() if k not in ("nades", "kills")}
    p2 = {**p1, "r": 6, "won": False}
    nades = [{"r": 5, "side": "t", "kind": "smoke", "t": 30, "to": "CT", "from": "TSpawn"},
             {"r": 6, "side": "t", "kind": "smoke", "t": 31, "to": "CT", "from": "TSpawn"},
             {"r": 6, "side": "t", "kind": "flash", "t": 38, "to": "BombsiteA", "from": "Ramp"}]
    book = playbook.build([{"map": "de_mirage", "plays": [p1, p2], "nades": nades}], "de_mirage")
    t = book["tactics"][0]
    assert (t["name"], t["n"], t["won"], t["won_pct"]) == ("A-Split über Palace + Ramp", 2, 1, 50)
    assert t["common"] == [{"kind": "smoke", "to": "CT", "n": 2}, {"kind": "flash", "to": "BombsiteA", "n": 1}]
    assert t["example"]["r"] == 5 and t["plant_t"] == 48
    # eine einzelne Runde ist noch keine Taktik
    assert playbook.build([{"map": "de_mirage", "plays": [p1], "nades": []}], "de_mirage")["tactics"] == []


def test_playbook_page_renders(tmp_path, monkeypatch):
    import json

    from fastapi.testclient import TestClient

    from cstaktik import api, pipeline

    monkeypatch.setattr(pipeline, "PRO_DIR", tmp_path)
    p1 = playbook.plays(_match(5, _split_route(), plant_s=48))[0]
    (tmp_path / "a.json").write_text(json.dumps({"map": "de_mirage", "plays": [p1, {**p1, "r": 6}], "nades": []}))
    t = TestClient(api.app).get("/playbook/de_mirage").text
    assert "A-Split über Palace + Ramp" in t and "Was ist ein Split?" in t
    (tmp_path / "a.json").write_text(json.dumps({"map": "de_mirage", "nades": []}))  # alte Pro-Daten ohne Laufwege
    assert "pro-update" in TestClient(api.app).get("/playbook/de_mirage").text


def test_events_merge_close_moments():
    ex = {"site": "A", "arrive": 36, "plant_t": 46,
          "nades": [{"kind": "smoke", "t": 28, "from": "TSpawn", "to": "CT"}, {"kind": "smoke", "t": 29, "to": "Jungle"}],
          "deaths": [{"t": 31, "side": "ct", "place": "Jungle", "first": True}]}
    ev = playbook.events(ex)
    assert [e["t"] for e in ev] == [28, 31, 36, 46]
    assert [i["text"] for i in ev[0]["items"]] == ["Smoke von TSpawn auf CT", "Smoke auf Jungle"]
    assert ev[1]["items"][0]["text"] == "CT fällt in Jungle (Opening)" and ev[3]["items"][0]["text"] == "Bombe liegt"


def test_own_plays_only_with_team_and_compare_to_pros():
    m = _match(5, _split_route(), plant_s=48)
    assert playbook.plays(m, team={"c1"}) == [] and len(playbook.plays(m, team={"t1"})) == 1
    p = playbook.plays(m, team={"t1"})[0]
    own = playbook.style_mix([{"map": "de_mirage", "plays": [p] * 12}], "de_mirage")
    assert own["total"] == 12 and own["styles"]["split"]["share"] == 100
    slow = {s: [(0, "TSpawn", 0, 0), (10, "Mid", 5, 5), (70, "BombsiteB", 9, 9)] for s in T}
    q = playbook.plays(_match(9, slow, plant_s=80, equip=5000))[0]
    pro = playbook.style_mix([{"map": "de_mirage", "plays": [q] * 8 + [p] * 4}], "de_mirage")
    s = playbook.compare(own, pro)
    assert s.startswith("Ihr spielt Split deutlich öfter als Pros: 100 % eurer T-Runden, Pros 33 %.")
    assert playbook.compare({**own, "total": 5}, pro) is None  # zu wenig eigene Runden
