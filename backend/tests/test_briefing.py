from fastapi.testclient import TestClient
from synth import ME, build_match

from cstaktik import briefing, goals, history, pipeline
from cstaktik.config import load_rules_config
from cstaktik.rules import analyze


def _hist(n=2):
    m = build_match()
    hs = []
    for i in range(n):
        s = history.summarize(m, analyze(m, load_rules_config()), "r.html")
        s["id"] = str(i)
        hs.append(s)
    return hs


def test_briefing_from_history():
    hs = _hist()
    b = briefing.build("de_mirage", hs, {"active": [{"title": "Z", "tip": "T", "target_pct": 10}]})
    assert b["matches"] == 2 and b["goals"][0]["title"] == "Z"
    # Ich stirbt 3x pro Match in SynthMid als CT -> 6x, alle als Erster
    assert any("Ich: 6x in SynthMid gestorben (von " in n["text"] and "davon 6x als Erster" in n["text"]
               and n["side"] == "CT" and "meist ohne Trade" in n["tip"] for n in b["notes"])
    empty = briefing.build("de_inferno", hs, {"active": []})
    assert empty["matches"] == 0 and empty["notes"] == [] and empty["watch"] == []


def test_start_page_and_briefing_route():
    from cstaktik import api

    c = TestClient(api.app)
    assert "Lade dein erstes Match hoch" in c.get("/").text
    for s in _hist(1):
        history.save(s, pipeline.HISTORY_DIR)
    st = {"active": [], "done": []}
    goals.update(st, history.load_all(pipeline.HISTORY_DIR)[0], load_rules_config()["goals"])
    goals.save(st, pipeline.GOALS_FILE)
    home = c.get("/").text
    assert "/briefing/de_mirage" in home and "Letztes Match" in home and 'class="gnav"' in home
    b = c.get("/briefing/de_mirage")
    assert b.status_code == 200 and "Kabine Mirage" in b.text and "SynthMid" in b.text
    assert c.get("/briefing/..%2Fetc").status_code in (400, 404)


def test_briefing_pro_utility():
    from cstaktik import briefing

    nades = [{"r": r, "side": "t", "won": True, "kind": "smoke", "t": 10.0, "from": "SynthT", "to": "SynthB",
              "fx": 0, "fy": 0, "tx": 1, "ty": 1} for r in range(1, 5)]
    tl = [{"round": r, "sid": "p", "side": "t", "won": True, "places": []} for r in range(1, 7)]
    b = briefing.build("de_mirage", [], {"active": []}, pro=[{"id": "x", "map": "de_mirage", "nades": nades, "timeline": tl}])
    assert b["pro_util"] == [{"side": "T", "items": [{"kind": "Smoke", "from": "SynthT", "to": "SynthB", "n": 4, "rounds": 6}]}]
