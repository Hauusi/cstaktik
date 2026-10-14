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


def test_main_via_ignores_single_side_paths():
    assert playbook.main_via({"a": "Palace", "b": "Palace", "c": "Ramp", "d": "Ramp", "e": "Underpass"}, "split") \
        == ["Palace", "Ramp"]
    # nur ein Ort mit 2+: auf zwei auffüllen (meiste Spieler, dann alphabetisch)
    assert playbook.main_via({"a": "Ramp", "b": "Ramp", "c": "Ramp", "d": "Palace", "e": "Underpass"}, "split") \
        == ["Palace", "Ramp"]
    assert playbook.main_via({"a": "Ramp", "b": "Ramp", "c": "Palace"}, "execute") == ["Ramp"]


def test_variant_with_one_other_path_joins_same_tactic():
    p1 = playbook.plays(_match(5, _split_route(), plant_s=48))[0]
    route = _split_route()
    route["t5"] = [(0, "TSpawn", 0, 0), (20, "Underpass", 10, 10), (40, "BombsiteA", 20, 20)]
    p2 = {**playbook.plays(_match(6, route, plant_s=48))[0], "won": False}
    t = playbook.build([{"map": "de_mirage", "plays": [p1, p2]}], "de_mirage")["tactics"]
    assert len(t) == 1 and t[0]["name"] == "A-Split über Palace + Ramp" and t[0]["n"] == 2
    assert [r["r"] for r in t[0]["rounds"]] == [5, 6]  # Beispielrunde (gewonnen) zuerst
    assert t[0]["rounds"][1]["via_all"] == ["Palace", "Ramp", "Underpass"]


def _ct_match(rnd, spots, plant_site_place=None):
    """spots: CT-sid -> (x, y, Ort) nach 20 s."""
    tr, start = 64, 1000
    r = Round(num=rnd, start_tick=0, freeze_end_tick=start, end_tick=start + 120 * tr, winner="ct",
              sides={**{s: "t" for s in T}, **{s: "ct" for s in CT}})
    pos = [PositionSample(round=rnd, tick=start + 20 * tr, steamid=s, side="ct", pos=Vec(x=x, y=y), place=pl)
           for s, (x, y, pl) in spots.items()]
    return MatchData(map_name="de_mirage", tickrate=tr, tickrate_source="t", players=[], rounds=[r], positions=pos)


def test_ct_setups_zones_from_plants():
    std = {"c1": (0, 0, "BombsiteA"), "c2": (100, 0, "Jungle"), "c3": (2500, 0, "Window"),
           "c4": (5000, 0, "BombsiteB"), "c5": (5100, 0, "Market")}
    p = playbook.ct_plays(_ct_match(3, std))[0]
    assert p["won"] and p["pos"]["c3"] == [2500, 0, "Window"]
    assert playbook.ct_plays(_ct_match(3, std), team={"t1"}) == []
    src = [{"map": "de_mirage", "ct_plays": [p, {**p, "r": 4, "won": False}],
            "plays": [{"site": "A", "plant": [0, 0]}, {"site": "A", "plant": [50, 0]},
                      {"site": "B", "plant": [5000, 0]}, {"site": "B", "plant": [5050, 0]}]}]
    centers = playbook.site_centers(src, "de_mirage")
    assert centers == {"A": [25, 0], "B": [5025, 0]}
    assert playbook.zone(2500, 0, centers, 1300) == "M"
    book = playbook.ct_build(src, "de_mirage", centers)
    s = book["setups"][0]
    assert (s["name"], s["n"], s["won_pct"], (s["a"], s["m"], s["b"])) == ("2-1-2", 2, 50, (2, 1, 2))
    stack = {k: (i * 50, 0, "BombsiteA") for i, k in enumerate(CT[:4])} | {"c5": (5000, 0, "BombsiteB")}
    q = playbook.ct_plays(_ct_match(5, stack))[0]
    book = playbook.ct_build([{**src[0], "ct_plays": [q, q]}], "de_mirage", centers)
    assert book["setups"][0]["name"] == "Stack auf A"
    # ohne zwei Bombsites keine Zonen
    assert playbook.ct_build(src, "de_mirage", {"A": [0, 0]})["setups"] == []


def test_gameplan_picks_best_with_enough_rounds():
    p = playbook.plays(_match(5, _split_route(), plant_s=48))[0]
    rush = {s: [(0, "TSpawn", 0, 0), (8, "Apartments", 5, 5), (16, "BombsiteB", 9, 9)] for s in T}
    q = playbook.plays(_match(8, rush, plant_s=22, equip=5000))[0]
    pro = [{"map": "de_mirage", "plays": [p, p, {**p, "won": False}, q, q]}]  # Rush nur 2x: zu wenig
    own = [{"map": "de_mirage", "plays": [{**q, "won": False}] * 4 + [p] * 3}]
    plan = playbook.gameplan(pro, own, "de_mirage")
    assert plan["t_pro"]["name"] == "A-Split über Palace + Ramp" and plan["t_pro"]["won_pct"] == 67
    assert plan["t_pro"]["why"] == "best"
    weak_pro = [{"map": "de_mirage", "plays": [p, {**p, "won": False}, {**p, "won": False}]}]
    assert playbook.gameplan(weak_pro, [], "de_mirage")["t_pro"]["why"] == "often"  # 33 %: keine Empfehlung
    assert plan["t_own"]["name"] == "A-Split über Palace + Ramp"
    assert plan["t_weak"]["label"] == "Rush" and plan["t_weak"]["won_pct"] == 0
    assert playbook.gameplan([], [], "de_mirage") is None


def test_nade_set_links_to_lineup(tmp_path, monkeypatch):
    import json

    from fastapi.testclient import TestClient

    from cstaktik import api, lineups, pipeline

    monkeypatch.setattr(pipeline, "PRO_DIR", tmp_path)
    monkeypatch.setattr(lineups, "build", lambda pro, m: [{"id": "lu7", "side": "t", "kind": "smoke", "to": "CT"}])
    p1 = {k: v for k, v in playbook.plays(_match(5, _split_route(), plant_s=48))[0].items() if k not in ("nades", "kills")}
    nades = [{"r": r, "side": "t", "kind": "smoke", "t": 30, "to": "CT", "from": "TSpawn", "fx": 0, "fy": 0, "tx": 1, "ty": 1}
             for r in (5, 6)]
    (tmp_path / "a.json").write_text(json.dumps({"map": "de_mirage", "plays": [p1, {**p1, "r": 6}], "nades": nades}))
    t = TestClient(api.app).get("/playbook/de_mirage").text
    assert 'href="/lineups/de_mirage?l=lu7"' in t


def test_report_tactics_of_this_match(tmp_path, monkeypatch):
    from cstaktik import pipeline
    from cstaktik.model import Player
    from cstaktik.report import render

    monkeypatch.setattr(pipeline, "PRO_DIR", tmp_path)
    m = _match(5, _split_route(), plant_s=48)
    m = m.model_copy(update={"players": [Player(steamid="t1", name="Ich", is_focus=True)]})
    tac = render._tactics(m)
    assert tac["t"][0]["name"] == "A-Split über Palace + Ramp" and tac["t"][0]["won_pct"] == 100
    assert tac["t"][0]["pro"] is None and tac["tags"] == {5: "A-Split über Palace + Ramp"} and tac["ct"] == []


def test_report_renders_tactics_section(tmp_path, monkeypatch):
    from synth import build_match

    from cstaktik.config import load_rules_config
    from cstaktik.report import render
    from cstaktik.rules import analyze

    m = build_match()
    fake = {"t": [{"name": "B-Rush über Apartments", "n": 3, "won": 1, "won_pct": 33, "rounds": [2, 4, 6],
                   "pro": {"n": 5, "won_pct": 60, "id": "rush-B-Apartments"}}],
            "ct": [], "tags": {2: "B-Rush über Apartments"}, "map": "de_mirage", "zones": False}
    monkeypatch.setattr(render, "_tactics", lambda match: fake)
    html = render.render_report(m, analyze(m, load_rules_config()), maps_dirs=[tmp_path])
    assert "Eure Taktiken heute" in html and "Pros 60 % (5 Runden)" in html and '"tac":"B-Rush über Apartments"' in html
