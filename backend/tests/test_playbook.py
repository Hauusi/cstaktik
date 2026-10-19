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
    # spät und verteilt: Default
    spots = {"t1": ("Apartments", -2000, 0), "t2": ("Mid", 0, 0), "t3": ("Palace", 2000, 0), "t4": ("Mid", 0, 1500),
             "t5": ("Underpass", -1500, 1500)}
    spread = {s: [(0, "TSpawn", 0, 0), (10, pl, x, y), (70, "BombsiteB", 9, 9)] for s, (pl, x, y) in spots.items()}
    p = playbook.plays(_match(9, spread, plant_s=80, equip=5000))[0]
    k = playbook.classify(p, {})
    assert k["style"] == "default" and k["name"] == "Default, spät auf B"
    # spät, aber alle 5 früh Mitte: kein Default
    slow = {s: [(0, "TSpawn", 0, 0), (10, "Mid", 5 + 50 * i, 5), (70, "BombsiteB", 9, 9)] for i, s in enumerate(T)}
    p = playbook.plays(_match(10, slow, plant_s=80, equip=5000))[0]
    k = playbook.classify(p, {})
    assert k["style"] == "group" and k["name"] == "Gemeinsam über Mid, spät auf B" and k["via"] == ["Mid"]
    # erst nach 20 s verteilt, nach 30 s laufen 4 gemeinsam über Palace: auch kein Default
    late = {s: [(0, "TSpawn", 0, 0), (10, pl, x, y), (28, "Palace", 3000 + 40 * i, 0), (70, "BombsiteB", 9, 9)]
            for i, (s, (pl, x, y)) in enumerate(spots.items())}
    late["t5"] = [(0, "TSpawn", 0, 0), (10, "Mid", 0, 0), (70, "BombsiteB", 9, 9)]
    p2 = playbook.plays(_match(11, late, plant_s=80, equip=5000))[0]
    assert playbook.classify(p2, {})["name"] == "Gemeinsam über Palace, spät auf B"
    # hintereinander denselben Weg (nie 4 im Umkreis), einer Mitte: kein Default
    line = {s: [(0, "TSpawn", 0, 0), (10, "TRamp", 400 * i, 0), (25, "Palace", 4000 + 400 * i, 0),
                (45, "PalaceInterior", 9000 + 400 * i, 0), (70, "BombsiteA", 9, 9)] for i, s in enumerate(T[:4])}
    line["t5"] = [(0, "TSpawn", 0, 0), (10, "Mid", -3000, 3000), (70, "BombsiteA", 9, 9)]
    p3 = playbook.plays(_match(12, line, plant_s=80, equip=5000))[0]
    k3 = playbook.classify(p3, {})
    assert k3["style"] == "group" and k3["name"] == "Gemeinsam über Palace, spät auf A"
    # ältere Daten ohne Orte: Name ohne Ort
    p.pop("places")
    assert playbook.classify(p, {})["name"] == "Gemeinsam, spät auf B"


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
    assert [i["text"] for i in ev[0]["items"]] == ["Smoke von T-Spawn auf CT", "Smoke auf Jungle"]
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
    assert s.startswith("Ihr spielt Split deutlich öfter als Pros. Das sind 100 % eurer T-Runden, bei Pros 33 %.")
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
    assert "Zum Mitnehmen" in html and "Nicht wiederholen" not in html  # 1 von 3 Runden: zu wenig für ein Urteil


def test_weekplan_gets_pro_tactic_task():
    from cstaktik import weekplan

    ctx = {"sid": "a", "lesson": "utility", "routine": {"title": "R", "minutes": 10, "steps": ["x"]}, "map": "de_mirage",
           "map_label": "Mirage", "spot": None, "lineup": None, "scenes": 0,
           "tactic": {"id": "split-A-Palace-Ramp", "name": "A-Split über Palace + Ramp", "won_pct": 67, "won": 2, "n": 3,
                      "common": [{"kind": "smoke", "to": "CT", "n": 3}]}}
    task = next(t for t in weekplan.tasks_for(ctx) if t["kind"] == "Playbook")
    assert task["title"] == "Pro-Taktik: A-Split über Palace + Ramp" and task["link"] == "/playbook/de_mirage#split-A-Palace-Ramp"
    assert "Smoke auf CT" in task["steps"][1]
    assert not any(t["kind"] == "Playbook" for t in weekplan.tasks_for({**ctx, "tactic": None}))


def test_eco_name_without_route_and_nuke_without_zones():
    via = {s: "Apartments" if s in ("t1", "t2", "t3") else "Market" for s in T}
    route = {s: [(0, "TSpawn", 0, 0), (8, v, 5, 5), (16, "BombsiteB", 9, 9)] for s, v in via.items()}
    p = playbook.plays(_match(7, route, plant_s=22, equip=1000))[0]
    assert playbook.classify(p, {})["name"] == "B-Eco-Push"
    src = [{"map": "de_nuke", "plays": [{"site": "A", "plant": [0, 0]}] * 2 + [{"site": "B", "plant": [0, 10]}] * 2}]
    assert playbook.site_centers(src, "de_nuke") == {}


def test_upgrade_history_survives_broken_cache(tmp_path, monkeypatch):
    from cstaktik import history, pipeline

    monkeypatch.setattr(pipeline, "HISTORY_DIR", tmp_path / "h")
    monkeypatch.setattr(pipeline, "CACHE_DIR", tmp_path / "c")
    (tmp_path / "c").mkdir()
    history.save({"id": "abc", "map": "de_mirage"}, tmp_path / "h")
    monkeypatch.setattr(pipeline, "cache_file", lambda i: tmp_path / "c" / "abc.json")
    (tmp_path / "c" / "abc.json").write_text("{kaputt")
    assert pipeline.upgrade_history() == 0  # kein Absturz, Eintrag bleibt für später


def test_tactic_task_ticks_itself_when_played():
    from cstaktik import weekplan

    p = playbook.plays(_match(5, _split_route(), plant_s=48))[0]
    tid = playbook.tactic_id(p)
    assert tid == "split-A-Palace-Ramp"
    key = "2026-W42"
    plan = {"lesson": "utility", "done": {}, "tasks": [{"id": f"tactic:de_mirage:{tid}", "kind": "Playbook"}]}
    hist = [{"map": "de_mirage", "analyzed_at": "2026-10-14T20:00", "plays": [p, {**p, "won": False}]},
            {"map": "de_mirage", "analyzed_at": "2026-10-01T20:00", "plays": [p]}]  # andere Woche zählt nicht
    assert weekplan.tactic_progress(key, plan, hist) is True
    assert plan["tasks"][0]["played"] == {"n": 2, "won": 1} and f"tactic:de_mirage:{tid}" in plan["done"]
    assert weekplan.tactic_progress(key, plan, hist) is False  # nichts Neues


def test_buy_mix_and_reading():
    def r(eq, won):
        return {"t_eq": eq, "won": won, "site": "A", "arrive": 30, "approach": {}}
    own = playbook.buy_mix([{"plays": [r(10000, False)] * 9 + [r(10000, True)] + [r(25000, True)] * 5 + [{**r(800, True), "pistol": True}]}])
    assert own["total"] == 15 and own["buys"]["force"] == {"label": "Force Buy", "n": 10, "share": 67, "won": 1, "won_pct": 10}
    pro = playbook.buy_mix([{"plays": [r(10000, True)] * 4 + [r(10000, False)] * 6 + [r(25000, True)] * 10}])
    assert "Ihr gewinnt 10 %, 1 von 10. Pros: 40 %" in playbook.buy_reading(own, pro)


def test_postplant_by_numbers():
    def p(won, t_dead, ct_dead):
        kills = [{"t": 10, "side": "t"}] * t_dead + [{"t": 12, "side": "ct"}] * ct_dead + [{"t": 99, "side": "t"}]
        return {"plant_t": 40, "won": won, "kills": kills}
    own = playbook.postplant_mix([{"plays": [p(False, 0, 2)] * 6 + [p(True, 0, 2)] * 2 + [p(True, 1, 1)] + [{"plant_t": None}]}])
    assert own["total"] == 9 and own["rows"]["up"] == {"label": "Überzahl", "n": 8, "won": 2, "won_pct": 25}
    assert own["rows"]["even"]["n"] == 1  # Kill nach dem Plant zählt nicht
    pro = playbook.postplant_mix([{"plays": [p(True, 0, 2)] * 7 + [p(False, 0, 2)]}])
    assert playbook.postplant_reading(own, pro).startswith("Nach dem Plant in Überzahl gewinnt ihr klar seltener als Pros. Bei euch sind es 25 %, 2 von 8. Pros: 88 %.")


def test_tactic_task_respects_manual_untick_and_player():
    from cstaktik import weekplan

    p = playbook.plays(_match(5, _split_route(), plant_s=48))[0]
    tid = playbook.tactic_id(p)
    task_id = f"tactic:de_mirage:{tid}"
    plan = {"lesson": "utility", "done": {}, "tasks": [{"id": task_id, "kind": "Playbook"}]}
    hist = [{"map": "de_mirage", "analyzed_at": "2026-10-14T20:00", "plays": [p], "players": {"b": {}}}]
    assert weekplan.tactic_progress("2026-W42", plan, hist, sid="a") is True  # Match ohne Spieler a: nur played=0
    assert plan["tasks"][0]["played"]["n"] == 0 and task_id not in plan["done"]
    hist[0]["players"]["a"] = {}
    weekplan.tactic_progress("2026-W42", plan, hist, sid="a")
    assert task_id in plan["done"]
    weekplan.toggle({"weeks": {"2026-W42": plan}}, "2026-W42", task_id)  # Haken von Hand raus
    weekplan.tactic_progress("2026-W42", plan, hist, sid="a")
    assert task_id not in plan["done"]  # bleibt draußen


def test_no_site_rounds_are_not_a_tactic_and_missing_equip_is_not_eco():
    lost = {"r": 3, "won": False, "site": None, "arrive": None, "approach": {}, "t_eq": 25000}
    mix = playbook.style_mix([{"map": "de_mirage", "plays": [lost] * 5}], "de_mirage")
    assert mix["total"] == 0
    m = _match(5, _split_route(), plant_s=48)
    for e in m.rounds[0].economy:
        e.equip_value = None
    p = playbook.plays(m)[0]
    assert p["t_eq"] is None and playbook.classify(p, {})["buy"] is None


def test_ct_retake_and_ct_buys():
    def p(won, t_dead, ct_dead, eq=25000):
        kills = [{"t": 10, "side": "t"}] * t_dead + [{"t": 12, "side": "ct"}] * ct_dead
        return {"r": 3, "plant_t": 40, "won": won, "kills": kills, "ct_eq": eq}
    own = [{"ct_plays": [p(False, 2, 0)] * 6 + [p(True, 2, 0)] + [p(False, 0, 0, 10000)] * 8}]
    pp = playbook.postplant_mix(own, "ct")
    assert pp["rows"]["up"] == {"label": "Überzahl", "n": 7, "won": 1, "won_pct": 14}  # 5 CT gegen 3 T
    pro = [{"ct_plays": [p(True, 2, 0)] * 6 + [p(False, 2, 0)] + [p(True, 0, 0, 10000)] * 4 + [p(False, 0, 0, 10000)] * 4}]
    r = playbook.postplant_reading(pp, playbook.postplant_mix(pro, "ct"), side="ct")
    assert r.startswith("Im Retake in Überzahl gewinnt ihr klar seltener als Pros. Bei euch sind es 14 %, 1 von 7. Pros: 86 %.") and "Retaket in Überzahl gemeinsam" in r
    b = playbook.buy_reading(playbook.buy_mix(own, side="ct"), playbook.buy_mix(pro, side="ct"), side="ct")
    assert b.startswith("Force-Buys auf CT lohnen sich bei euch selten. Ihr gewinnt 0 %, 0 von 8. Pros: 50 %.")


def test_ct_plays_store_kills_plant_and_equip():
    from cstaktik.model import BombEvent, PlayerEconomy

    std = {"c1": (0, 0, "BombsiteA"), "c2": (100, 0, "Jungle"), "c3": (2500, 0, "Window"),
           "c4": (5000, 0, "BombsiteB"), "c5": (5100, 0, "Market")}
    m = _ct_match(3, std)
    m.rounds[0].economy = [PlayerEconomy(steamid=s, side="ct", equip_value=5000) for s in CT]
    m.bomb = [BombEvent(round=3, tick=1000 + 50 * 64, event="plant", steamid="t1", pos=Vec(x=0, y=0))]
    p = playbook.ct_plays(m)[0]
    assert p["plant_t"] == 50.0 and p["ct_eq"] == 25000 and p["kills"] == [] and p["pistol"] is False


def test_firstblood_conversion():
    def p(first_side, won):
        return {"won": won, "kills": [{"t": 30, "side": "ct"}, {"t": 12, "side": first_side}]}
    own = playbook.firstblood_mix([{"plays": [p("ct", False)] * 7 + [p("ct", True)] * 3 + [p("t", False)] * 4}], "t")
    assert own["rows"]["for"] == {"label": "Erster Kill für euch (5 gegen 4)", "n": 10, "won": 3, "won_pct": 30}
    assert own["rows"]["against"]["n"] == 4
    pro = playbook.firstblood_mix([{"plays": [p("ct", True)] * 8 + [p("ct", False)] * 2}], "t")
    r = playbook.firstblood_reading(own, pro, "t")
    assert r.startswith("Auf T verschenkt ihr den Vorteil nach eurem ersten Kill öfter als Pros. Ihr gewinnt 30 % dieser Runden, 3 von 10. Pros: 80 %.")
    ct = playbook.firstblood_mix([{"ct_plays": [p("t", True)]}], "ct")
    assert ct["rows"]["for"]["n"] == 1  # erster Tod auf T-Seite = Kill für die CT
