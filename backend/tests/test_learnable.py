"""Training, Playbook, Lineups, Map-Buch: konkret, kurz, mit Callouts und Spieluhr."""

import json
from datetime import date

from fastapi.testclient import TestClient

from cstaktik import lineups, mapbook, playbook, weekplan
from cstaktik.config import load_rules_config


def test_style_mix_counts_group_and_sums_to_100():
    def play(r, style_paths):
        return {"r": r, "won": r % 2 == 0, "site": "B", **style_paths}

    # 3 gleiche Arten: ohne Ausgleich 33 + 33 + 33 = 99
    groups = {"paths": {f"t{i}": [[i * 50, 0]] * 30 for i in range(5)},
              "places": {f"t{i}": ["Mid"] * 30 for i in range(5)}, "arrive": 70, "approach": {}}
    rush = {"arrive": 10, "approach": {"t1": "Apartments"}}
    exe = {"arrive": 40, "approach": {"t1": "Apartments"}}
    src = [{"map": "de_mirage", "plays": [play(1 + 0, groups), play(4, rush), play(5, exe)]}]
    for p in src[0]["plays"]:
        p["t_eq"] = 20000
    mix = playbook.style_mix(src, "de_mirage")
    assert set(mix["styles"]) == {"group", "rush", "execute"}
    assert mix["styles"]["group"]["label"] == "Gemeinsam"
    assert sum(v["share"] for v in mix["styles"].values()) == 100
    assert playbook.shares_100({"a": 1, "b": 1, "c": 1}) in ({"a": 34, "b": 33, "c": 33}, {"a": 33, "b": 34, "c": 33},
                                                             {"a": 33, "b": 33, "c": 34})
    assert playbook.shares_100({"a": 0}) == {"a": 0}


def test_roles_route_thrower_clock_and_lineup():
    ex = {"plant_t": 50,
          "paths": {"a": [[0, 0], [100, 0], [200, 0], [300, 0], [400, 0]], "b": [[0, 2000], [0, 2100], [0, 2200]]},
          "places": {"a": ["TSpawn", "TSpawn", "PalaceInterior", "PalaceInterior", "BombsiteA"],
                     "b": ["TSpawn", "TopofMid", "TopofMid"]},
          "nades": [], "round_nades": [
              {"kind": "smoke", "t": 4, "side": "t", "from": "PalaceInterior", "to": "CTSpawn",
               "p": [210, 5, 0, 90, -10, 0, 0], "tx": 900, "ty": 900},
              {"kind": "flash", "t": 2.5, "side": "t", "to": "TopofMid", "fx": 5, "fy": 2110, "tx": 10, "ty": 2500},
              {"kind": "he", "t": 3, "side": "t", "to": "X", "fx": 0, "fy": 0, "tx": 0, "ty": 0},
              {"kind": "molotov", "t": 6, "side": "t", "to": "Jungle", "fx": 5000, "fy": 5000, "tx": 0, "ty": 0}],
          "deaths": [{"t": 7, "side": "t", "sid": "b", "place": "TopofMid"}]}
    assert playbook.route(ex["places"]["a"]) == "Palace → A-Site"
    assert playbook.route([None, "TSpawn"]) == "T-Spawn"
    lines = [{"id": "lu1", "kind": "smoke", "side": "t", "x": 230, "y": 0, "tx": 950, "ty": 900}]
    roles = playbook.roles(ex, lines)
    assert [r["route"] for r in roles] == ["Palace → A-Site", "Top Mid"]
    assert roles[0]["nades"] == [{"idx": 0, "kind": "smoke", "kind_de": "Smoke", "to": "CT-Spawn", "clock": "1:51",
                                  "lineup": "lu1", "t": 4}]
    assert roles[1]["nades"][0]["kind_de"] == "Flash" and roles[1]["nades"][0]["lineup"] is None  # ohne Wurfstelle
    assert roles[1]["died"] == {"clock": "1:48", "place": "Top Mid"}
    # HE nicht gezeichnet, Molotov weit weg von allen Wegen: keinem Spieler zugeordnet
    assert len(playbook.drawn_nades(ex)) == 3 and all(len(r["nades"]) == 1 for r in roles)
    texts = [i["text"] for e in playbook.events(ex) for i in e["items"]]
    assert "Spieler 1: Smoke von Palace auf CT-Spawn" in texts and "Spieler 2 fällt in Top Mid" in texts


def test_playbook_without_radar_draws_on_blank(tmp_path, monkeypatch):
    from test_playbook import _match, _split_route

    from cstaktik import api, pipeline

    monkeypatch.setattr(pipeline, "PRO_DIR", tmp_path)
    p1 = playbook.plays(_match(5, _split_route(), plant_s=48))[0]
    (tmp_path / "a.json").write_text(json.dumps({"map": "de_inferno", "plays": [p1, {**p1, "r": 6}], "nades": []}))
    t = TestClient(api.app).get("/playbook/de_inferno").text  # kein Radarbild, Download im Test aus
    assert "Keine Karte für diese Map" in t and 'class="pmap blank"' in t and "Rollen: wer läuft wo" in t
    assert "auf der Site meist bei 1:15" in t and "Plant, meist bei 1:07" in t  # Uhr im Spiel statt Sekunden


def _lu(i, n, frm="TSpawn", to="TopofMid", kind="smoke", side="t"):
    return {"id": f"l{i}", "kind": kind, "kind_de": lineups.KIND_DE[kind], "side": side, "from": frm, "to": to,
            "from_c": frm, "to_c": to, "n": n, "demos": 1}


def test_lineups_dedupe_and_core_first():
    items = [_lu(1, 5), _lu(2, 3), _lu(3, 7, to="Jungle")] + [_lu(10 + i, 2, to=f"Ziel{i}") for i in range(6)]
    d = lineups.dedupe(items)
    top = next(x for x in d if x["to"] == "TopofMid")
    assert top["id"] == "l1" and top["alt_ids"] == ["l2"] and top["alt_n"] == 3 and len(d) == 8
    sides = lineups.organize(items)
    assert [s["side"] for s in sides] == ["t"]
    assert [x["id"] for x in sides[0]["core"]][:2] == ["l3", "l1"] and len(sides[0]["core"]) == 5
    assert sum(len(g["rows"]) for g in sides[0]["groups"]) == 3


def test_lineup_page_short_and_alt_link(tmp_path, monkeypatch):
    from cstaktik import api

    full = [{**_lu(1, 5), "x": 0, "y": 0, "z": 0, "yaw": 0, "pitch": 0, "tx": 500, "ty": 0, "spread": 40, "t": 11,
             "clock": "1:44", "tech": {"label": "Sprungwurf"}, "cmd": "setpos 0 0 0;setang 0 0 0", "won": 0},
            {**_lu(2, 2), "x": 60, "y": 0, "z": 0, "yaw": 0, "pitch": 0, "tx": 500, "ty": 0, "spread": 10, "t": 11,
             "clock": "1:44", "tech": {"label": "im Stehen"}, "cmd": "setpos 60 0 0;setang 0 0 0", "won": 0}]
    monkeypatch.setattr(lineups, "build", lambda pro, m: [dict(x) for x in full])
    t = TestClient(api.app).get("/lineups/de_mirage?l=l2").text
    assert 'class="lu sel" id="l1"' in t  # Link auf den zusammengelegten Wurf zeigt den gezeigten
    assert "bei 1:44 auf der Uhr" in t and "Sprungwurf" in t and "innerhalb 1,0 m" in t and "Wurf: TSpawn" in t
    assert "gewonnen" not in t and "Varianten" in t and t.count('class="lu ') == 1


def test_mapbook_rare_spots_aim_spot_and_pro_n():
    from test_mapbook_lineups import _hist, _pro

    h = _hist()
    for d in h[0]["deaths"]:
        d.update(ax=500, ay=200, aplace="BombsiteA", x=0, y=0)
    book = mapbook.build(h, _pro(), "de_mirage", "me", load_rules_config()["mapbook"])
    ct = book["sides"]["ct"]
    assert ct["killer_top"] == [] and ct["spots"][0]["killer_places"] == []  # ganzer Bombsite: kein Vorziel-Tipp
    assert mapbook.aim_spot("Palace") and not mapbook.aim_spot("BombsiteB") and not mapbook.aim_spot(None)
    assert ct["spots"][0]["pro"]["total"] == 12 and ct["spots"][0]["pro"]["n"] == 4
    assert book["at"] == "1:35"  # Spieluhr, nicht verstrichene Zeit


def test_weekplan_routine_concrete_and_once():
    from cstaktik.curriculum import TEACH

    lu = {"id": "f1", "kind": "flash", "kind_de": "Flash", "from_c": "Connector", "to_c": "Mid", "from": "Connector",
          "to": "Middle", "cmd": "setpos 1 2 3;setang 0 0 0", "tech": {"label": "im Stehen"}, "clock": "1:40", "n": 4,
          "spread": 50, "t": 15}
    ctx = {"sid": "me", "lesson": "utility", "routine": TEACH["utility"]["routine"], "map": "de_mirage",
           "map_label": "Mirage", "spot": None, "lineup": lu, "scenes": 3, "tactic": None,
           "positions": [{"side": "ct", "place": "Connector", "n": 8}, {"side": "t", "place": "TopofMid", "n": 5}],
           "pos_lineups": [lu], "fault": TEACH["utility"]["fault"], "in_game": TEACH["utility"]["in_game"]}
    tasks = weekplan.tasks_for(ctx)
    assert [t["kind"] for t in tasks] == ["Übung", "Map-Buch", "Situationen"]  # Lineup steckt schon in der Übung
    r = tasks[0]
    assert r["positions"][1] == {"side": "T", "place": "Top Mid", "n": 5,
                                 "link": "/mapbook/de_mirage?p=me#spot-t-TopofMid"}
    assert r["lineups"][0]["cmd"] == lu["cmd"] and r["lineups"][0]["label"] == "Flash von Connector auf Mid"
    assert r["fault"].startswith("Ein Tod") and any("Top Mid" in s for s in r["steps"])
    assert not any("Wiederholung" in t["title"] for t in tasks) and tasks[2]["auto"]
    # alter Plan derselben Woche (mit Wiederholung): neu gebaut, Häkchen bleiben
    slot = {"weeks": {"2026-W42": {"lesson": "utility", "created": "x", "done": {"quiz": "t", "routine2:utility": "t"},
                                   "tasks": [{"id": "quiz"}, {"id": "routine2:utility"}]}}}
    _key, plan, changed = weekplan.ensure(slot, ctx, date(2026, 10, 13))
    assert changed and plan["v"] == weekplan.PLAN_V and plan["done"] == {"quiz": "t"}
    assert weekplan.ensure(slot, ctx, date(2026, 10, 13))[2] is False
