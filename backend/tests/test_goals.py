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
    assert r1["checks"] == [] and r1["new"] == ["Nicht ohne Trade-Partner peeken", "Weniger als Erster sterben"]

    r2 = goals.update(st, S("2", alone=3, opening=6, order=()), CFG)  # 12.5 % <= 15 % erreicht
    alone = next(c for c in r2["checks"] if c["title"] == "Nicht ohne Trade-Partner peeken")
    assert alone["met"] and alone["streak"] == 1 and alone["status"] == "aktiv"
    assert not next(c for c in r2["checks"] if c["title"] == "Weniger als Erster sterben")["met"]

    r3 = goals.update(st, S("3", alone=2, opening=5, order=("blind",)) | {"cause_rounds": {"alone": 2, "opening": 5, "blind": 4}}, CFG)
    assert next(c for c in r3["checks"] if c["title"] == "Nicht ohne Trade-Partner peeken")["status"] == "geschafft"
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
    assert state["active"] == []  # 6 Runden: unter min_check_rounds, aus so wenig entsteht kein Ziel
    html = out.read_text()
    assert 'data-tab="coach"' in html and 'data-tab="runden"' in html and 'class="gnav"' in html


def test_reanalysed_old_match_keeps_chronological_streak():
    from cstaktik import goals

    cfg = {"done_after": 2, "max_active": 3, "target_factor": 0.6}
    st = {"active": [], "done": []}

    def s(i, pct, date):
        return {"id": i, "rounds": 20, "cause_rounds": {"alone": pct // 5}, "cause_order": ["alone"],
                "analyzed_at": date}

    goals.update(st, s("A0", 50, "2026-10-01T10:00"), cfg)
    for i, pct, d in (("A", 20, "2026-10-02T10:00"), ("B", 50, "2026-10-03T10:00"), ("C", 20, "2026-10-04T10:00")):
        goals.update(st, s(i, pct, d), cfg)
    r = goals.update(st, s("A", 20, "2026-10-02T10:00"), cfg)  # altes Match erneut ausgewertet
    assert r["checks"][0]["streak"] == 1 and not st["done"]
    goals.update(st, s("D", 20, "2026-10-05T10:00"), cfg)  # jetzt wirklich 2 in Folge
    assert st["done"] and not any(g["cause"] == "alone" for g in st["active"])  # nicht sofort neu angelegt


def test_small_samples_create_and_finish_nothing():
    st = {"active": [], "done": []}
    goals.update(st, S("1", alone=3, rounds=10), CFG)  # unter min_check_rounds
    assert st["active"] == []
    goals.update(st, S("2", alone=2, opening=6), CFG)  # alone nur 2 Runden: unter min_count
    assert [g["cause"] for g in st["active"]] == ["opening"]

    # geschafft erst mit genug Runden in der Serie (min_master_rounds)
    st = {"active": [], "done": []}
    goals.update(st, S("1", alone=6, order=("alone",)), CFG)
    goals.update(st, S("2", alone=0, rounds=13, order=()), CFG)
    r = goals.update(st, S("3", alone=0, rounds=13, order=()), CFG)
    assert r["checks"][0]["streak"] == 2 and r["checks"][0]["status"] == "aktiv" and not st["done"]


def test_mech_goal_needs_enough_shots_and_deaths():
    mech_cfg = load_rules_config()["mechanics"]

    def s(mid, shots, deaths):
        return {"id": mid, "rounds": 24, "analyzed_at": f"2026-10-1{mid}T20:00", "cause_rounds": {},
                "cause_order": [], "mech": {"a": {"moving_pct": 80.0, "deaths_no_shot_pct": 80.0, "shots": shots}},
                "players": {"a": {"name": "A", "deaths": deaths}}}

    st = {"active": [], "done": []}
    goals.update(st, s("1", 5, 3), CFG, mech_cfg)
    assert st["active"] == []
    goals.update(st, s("2", 40, 3), CFG, mech_cfg)
    assert [g["metric"] for g in st["active"]] == ["moving_pct"]
