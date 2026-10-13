from datetime import date

from cstaktik import lineups, mapbook, weekplan
from cstaktik.config import load_rules_config

CFG = load_rules_config()["mapbook"]


def nade(x, yaw, sz=0.0, sxy=0.0, tx=1000, won=True, kind="smoke", side="t", frm="TSpawn", to="Window"):
    return {"r": 1, "side": side, "won": won, "kind": kind, "t": 20.0, "from": frm, "to": to,
            "tx": tx, "ty": 0, "p": [x, 0.0, 10.0, yaw, -40.0, sxy, sz, None]}


def pro_demo(i, nades, timeline=(), deaths=()):
    return {"id": f"p{i}", "map": "de_mirage", "nades": nades, "timeline": list(timeline), "deaths": list(deaths)}


def test_lineups_cluster_repeated_throws_only():
    pro = [pro_demo(1, [nade(0, 90, sz=290), nade(10, 91, sz=280), nade(500, 90)]),
           pro_demo(2, [nade(5, 90.5), nade(0, 110), nade(0, 90, tx=3000)])]
    ls = lineups.build(pro, "de_mirage")
    assert len(ls) == 1  # andere Stelle, anderer Blick, andere Landung: kein Lineup
    lu = ls[0]
    assert lu["n"] == 3 and lu["demos"] == 2 and lu["kind_de"] == "Smoke" and lu["to"] == "Window"
    assert lu["tech"]["label"] == "Sprungwurf" and lu["tech"]["duck"] is None  # 2 von 3 in der Luft
    assert lu["cmd"].startswith("setpos ") and ";setang -40.00 " in lu["cmd"]
    assert lineups.build(pro, "de_dust2") == []


def test_lineup_technique_standing_and_running():
    assert lineups.technique([nade(0, 0), nade(0, 0)])["label"] == "im Stehen"
    assert lineups.technique([nade(0, 0, sxy=200), nade(0, 0, sxy=210)])["label"] == "im Laufen"


def _hist():
    tl, deaths = [], []
    for r in range(1, 6):  # 5 CT-Runden in Connector, 3x als Erster tot, ohne Trade
        tl.append({"round": r, "sid": "me", "side": "ct", "won": r > 3, "places": ["CTSpawn"] * 4 + ["Connector"]})
        if r <= 3:
            deaths.append({"sid": "me", "round": r, "side": "ct", "first": True, "traded": False, "place": "Connector"})
    tl.append({"round": 6, "sid": "me", "side": "ct", "won": True, "places": ["CTSpawn"] * 4 + ["Jungle"]})
    return [{"id": "m1", "map": "de_mirage", "report_file": "m1.html", "analyzed_at": "2026-10-12T20:00",
             "rounds": 20, "players": {"me": {"name": "Ich"}}, "timeline": tl, "deaths": deaths,
             "lessons": {"me": {"alone": 2}}}]


def _pro():
    tl = [{"round": r, "sid": f"p{r % 5}", "side": "ct", "won": r % 2 == 0,
           "places": ["CTSpawn"] * 4 + (["Connector"] if r < 4 else ["Jungle"])} for r in range(12)]
    return [pro_demo(1, [nade(0, 90, side="ct", frm="Connector", to="Mid"), nade(4, 90, side="ct", frm="Connector", to="Mid")],
                     tl, [{"r": 1, "sid": "p1", "first": True}])]


def test_mapbook_rates_spots_and_compares_with_pros():
    book = mapbook.build(_hist(), _pro(), "de_mirage", "me", CFG)
    ct = book["sides"]["ct"]
    con = ct["spots"][0]
    assert con["place"] == "Connector" and con["n"] == 5 and con["first"] == 3 and con["untraded"] == 3
    assert con["verdict"] == "problem" and "In 3 von 5 Runden hier als Erster gestorben." in con["why"]
    assert con["pro"]["share"] == 33 and con["pro"]["n"] == 4  # 4 von 12 Pro-Runden
    assert con["lineups"] and con["lineups"][0]["to"] == "Mid"
    assert ct["spots"][1]["verdict"] == "offen"  # Jungle: nur 1 Runde
    assert ct["pro_spots"][0]["place"] == "Jungle"
    assert mapbook.worst_spot(book)["place"] == "Connector"
    assert book["sides"]["t"]["spots"] == []


def test_weekplan_tasks_toggle_and_check():
    from cstaktik.curriculum import TEACH

    book = mapbook.build(_hist(), _pro(), "de_mirage", "me", CFG)
    spot = mapbook.worst_spot(book)
    ctx = {"sid": "me", "lesson": "alone", "routine": TEACH["alone"]["routine"], "map": "de_mirage",
           "map_label": "Mirage", "spot": spot, "lineup": spot["lineups"][0], "scenes": 2}
    slot = {}
    day = date(2026, 10, 13)
    key, plan, changed = weekplan.ensure(slot, ctx, day)
    assert key == "2026-W42" and changed
    kinds = [t["kind"] for t in plan["tasks"]]
    assert kinds == ["Übung", "Map-Buch", "Lineup", "Situationen", "Übung"]
    assert "Connector" in plan["tasks"][1]["title"] and plan["tasks"][1]["link"].startswith("/mapbook/de_mirage?p=me")
    assert weekplan.toggle(slot, key, plan["tasks"][0]["id"]) is True
    assert weekplan.ensure(slot, ctx, day)[2] is False  # gleiche Woche, gleicher Auftrag: bleibt
    ctx2 = {**ctx, "lesson": "utility", "routine": TEACH["utility"]["routine"]}
    _, plan2, changed2 = weekplan.ensure(slot, ctx2, day)
    assert changed2 and len(plan2["done"]) == 0  # Übung des alten Auftrags zählt nicht
    weekplan.toggle(slot, key, plan2["tasks"][1]["id"])  # Map-Buch-Aufgabe bleibt bei Wechsel erhalten
    _, plan3, _ = weekplan.ensure(slot, ctx, day)
    assert plan2["tasks"][1]["id"] in plan3["done"]
    chk = weekplan.check(key, plan3, _hist(), "me", {"lesson": "alone", "target": 0.6, "baseline": 2.0})
    assert chk["matches"] == 1 and chk["rate"] == 1.0 and chk["met"] is False and chk["from"] == "12.10."


def test_mapbook_and_lineup_pages():
    from fastapi.testclient import TestClient

    from cstaktik import api, history, pipeline, pro

    for h in _hist():
        history.save(h, pipeline.HISTORY_DIR)
    for d in _pro():
        pro.save({**d, "version": pro.VERSION}, pipeline.PRO_DIR)
    c = TestClient(api.app)
    mb = c.get("/mapbook/de_mirage?p=me").text
    assert "Map-Buch Mirage" in mb and "Connector" in mb and "Anpassen" in mb and "/lineups/de_mirage?l=" in mb
    lp = c.get("/lineups/de_mirage").text
    assert "Connector → Mid" in lp and "setpos " in lp and "Kopieren" in lp
    assert "Kein Lineup" in c.get("/lineups/de_mirage?side=t").text
    assert c.get("/mapbook/..%2Fx").status_code in (400, 404)
