from cstaktik import goals
from cstaktik.config import load_rules_config

CFG = load_rules_config()["goals"]


def S(mid, alone, opening=0, rounds=24, order=("alone", "opening")):
    return {"id": mid, "rounds": rounds, "analyzed_at": f"2026-10-1{mid}T20:00",
            "cause_rounds": {"alone": alone, "opening": opening}, "cause_order": list(order)}


def test_goal_created_checked_done_and_replaced():
    st = {"active": [], "done": []}
    r1 = goals.update(st, S("1", alone=6, opening=4), CFG)
    assert [g["cause"] for g in st["active"]] == ["alone", "opening"]
    g = st["active"][0]
    assert (g["baseline_pct"], g["target_pct"]) == (25.0, 15.0) and g["drills"]
    assert r1["checks"] == [] and r1["new"] == ["Nicht mehr allein sterben", "Weniger als Erster sterben"]

    r2 = goals.update(st, S("2", alone=3, opening=6, order=()), CFG)  # 12.5 % <= 15 % erreicht
    alone = next(c for c in r2["checks"] if c["title"] == "Nicht mehr allein sterben")
    assert alone["met"] and alone["streak"] == 1 and alone["status"] == "aktiv"
    assert not next(c for c in r2["checks"] if c["title"] == "Weniger als Erster sterben")["met"]

    r3 = goals.update(st, S("3", alone=2, opening=5, order=("blind",)) | {"cause_rounds": {"alone": 2, "opening": 5, "blind": 4}}, CFG)
    assert next(c for c in r3["checks"] if c["title"] == "Nicht mehr allein sterben")["status"] == "geschafft"
    assert [g["cause"] for g in st["done"]] == ["alone"]
    assert {g["cause"] for g in st["active"]} == {"opening", "blind"}  # freier Platz neu besetzt


def test_same_match_twice_is_not_counted_twice():
    st = {"active": [], "done": []}
    goals.update(st, S("1", alone=6), CFG)
    goals.update(st, S("2", alone=3, order=()), CFG)
    goals.update(st, S("2", alone=3, order=()), CFG)  # erneut ausgewertet
    assert len(st["active"][0]["checks"]) == 1
    goals.update(st, S("1", alone=6), CFG)  # Ursprungs-Match prüft sich nicht selbst
    assert len(st["active"][0]["checks"]) == 1


def test_pipeline_writes_goals_and_report_shows_check(tmp_path):
    from synth import BRO, ME, build_match

    from cstaktik import pipeline
    from cstaktik.parser.loader import save_match

    src = tmp_path / "match.json"
    save_match(build_match(focus=()), src)
    out = pipeline.run(src, {ME, BRO}, tmp_path / "out")
    state = goals.load(pipeline.GOALS_FILE)
    assert state["active"]  # Economy-Ursache -> Ziel
    assert "Ziel-Check" in out.read_text()  # "Neue Ziele" werden angezeigt
