"""Duo über Matches: zusammen gegen getrennt, Trades, erste Tode; Aussage nur bei klarer Datenlage."""

from fastapi.testclient import TestClient
from synth import BRO, ME

from cstaktik import accounts, ai_coach, api, duo, history, pipeline
from cstaktik.coach import duo as duo_match

O = {"Origin": "http://testserver"}


def _h(i, tog=(10, 7), apart=(10, 3), mate=BRO):
    return {"id": f"d{i}", "map": "de_mirage", "rounds": 20, "analyzed_at": f"2026-02-{i + 1:02d}T10:00",
            "report_file": f"d{i}.html", "players": {ME: {"name": "Hausi"}, mate: {"name": "Bruder"}},
            "duo": {"sids": [ME, mate], "avg_distance": 900, "together": {"rounds": tog[0], "won": tog[1]},
                    "apart": {"rounds": apart[0], "won": apart[1]}, "trades_by": {ME: 2, mate: 1}, "first_by": {ME: 3, mate: 1}}}


def test_summary_clear_difference():
    s = duo.summary([_h(i) for i in range(3)], ME, {ME: "Hausi", BRO: "Bruder"})
    assert s["together"] == {"rounds": 30, "won": 21, "pct": 70} and s["apart"]["pct"] == 30
    assert s["tone"] == "good" and "Zusammen gewinnt ihr 70 %" in s["reading"]
    assert s["trades_me"] == 6 and s["trades_mate"] == 3 and s["first_me"] == 9 and s["together_share"] == 50
    assert s["avg_m"] == 23 and s["mate_name"] == "Bruder" and len(s["series"]) == 3


def test_summary_needs_rounds_and_ignores_other_partner():
    s = duo.summary([_h(0)], ME)
    assert not s["enough"] and "mindestens 20 Runden" in s["reading"] and s["tone"] == ""
    s = duo.summary([_h(0), _h(1), _h(2, mate="999")], ME)
    assert s["matches"] == 2 and s["mate"] == BRO
    assert duo.summary([{"id": "x"}], ME) is None


def test_coach_duo_has_sid_keys():
    from test_coach import C, build_match

    d = duo_match(build_match(), C)
    assert set(d["sids"]) == set(d["trades_by"]) == set(d["first_by"])


def test_stats_page_and_ai_facts_show_duo():
    pipeline.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    board = {"rounds": 20, "kills": 15, "deaths": 10, "assists": 2, "dmg": 1500, "hs": 6, "kast": 14, "survived": 10,
             "k1": 5, "k2": 2, "k3": 0, "k4": 0, "k5": 0, "ok": 2, "od": 2, "traded": 1, "assists_known": True, "dmg_known": True}
    for i in range(3):
        history.save({**_h(i), "board": {ME: board}, "score_by": {ME: [13, 7]}}, pipeline.HISTORY_DIR)
    accounts.add_user("Hausi", "Geheim-12345")
    accounts.link_steamid("Hausi", ME)
    c = TestClient(api.app)
    c.post("/login", data={"name": "Hausi", "password": "Geheim-12345"}, headers=O)
    page = c.get("/stats").text
    assert 'data-block="duo"' in page and "Zusammen gewinnt ihr 70 %" in page
    f = ai_coach.facts(_h(0), ME)
    assert "## Duo mit Bruder" in f and "Zusammen: 7 von 10" in f


def test_shared_plan_recommend_and_check():
    s = duo.summary([_h(i) for i in range(3)], ME)
    assert duo.recommend(s) == "together"  # zusammen 70 %, getrennt 30 %
    assert duo.recommend(None) == "trade"
    p = duo.set_plan(ME, BRO, "together", ME, "2026-02-02T12:00")
    assert duo.get_plan(BRO, ME) == p and p["text"].startswith("Wenn wir auf T")  # gilt für beide
    hist = [_h(0, tog=(5, 3), apart=(15, 5)), _h(1, tog=(5, 3), apart=(15, 5)), _h(2, tog=(15, 9), apart=(5, 2))]
    c = duo.plan_check(hist, ME, BRO, p)
    assert c.startswith("Seit eurer Abmachung (1 Match): zusammen in 75 % der Runden, davor 25 %.")
    assert "Trades je Match: 3,0 statt 3,0." in c


def test_warmup_duo_box_and_endpoint():
    pipeline.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        history.save(_h(i), pipeline.HISTORY_DIR)
    accounts.add_user("Hausi", "Geheim-12345")
    accounts.link_steamid("Hausi", ME)
    c = TestClient(api.app)
    c.post("/login", data={"name": "Hausi", "password": "Geheim-12345"}, headers=O)
    w = c.get("/warmup").text
    assert "Zu zweit mit Bruder" in w and "Mein Vorschlag für euch beide" in w and 'data-duokey="together"' in w
    assert c.post("/duo/plan", json={"key": "call"}, headers=O).json()["ok"]
    assert c.post("/duo/plan", json={"key": "xx"}, headers=O).status_code == 400
    w = c.get("/warmup").text
    assert "„Wenn einer von uns stirbt" in w and "Abmachung ändern" in w
