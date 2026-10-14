"""Coaching-Kreislauf: Auftrag setzen, prüfen, meistern; gute Szenen finden. Synthetische Daten."""

from synth import ENEMIES, MATES, ME, TR, build_match

from cstaktik import coaching
from cstaktik.model import GrenadeThrow, Kill, PositionSample, Vec


def _sum(mid, n, rounds=20, lid="alone"):
    return {"id": mid, "rounds": rounds, "analyzed_at": f"2026-10-0{mid}T20:00", "lessons": {"a": {lid: n}},
            "report_file": f"{mid}.html", "map": "de_mirage"}


def test_focus_set_checked_and_mastered():
    st = {"focus": None, "done": [], "drills": []}
    r1 = coaching.update(st, _sum("1", 4), ["alone"])  # 2,0 pro 10 Runden -> Ziel 1,2
    assert r1["new"] and r1["check"] is None and r1["focus"]["target"] == 1.2 and r1["focus"]["baseline"] == 2.0
    r2 = coaching.update(st, _sum("2", 3), ["alone"])  # 1,5 > 1,2: nicht geschafft
    assert r2["check"]["met"] is False and r2["check"]["streak"] == 0 and not r2["new"]
    assert coaching.update(st, _sum("2", 3), ["alone"])["check"]["streak"] == 0  # gleiche Demo zählt nicht doppelt
    assert len(st["focus"]["matches"]) == 1
    r3 = coaching.update(st, _sum("3", 2), ["alone"])
    assert r3["check"]["met"] and r3["check"]["streak"] == 1 and r3["mastered"] is None
    s4 = _sum("4", 1)
    s4["lessons"]["a"]["utility"] = 3
    r4 = coaching.update(st, s4, ["utility", "alone"])
    assert r4["mastered"] == "alone" and r4["new"] and r4["focus"]["lesson"] == "utility"
    assert st["done"][0]["lesson"] == "alone"


def test_bright_spots_trade_range_and_flash_kill():
    m = build_match()
    r = m.rounds[0]
    t = r.freeze_end_tick + 10 * TR
    for sid, x in ((ME, 0), (MATES[1], 300)):
        m.positions.append(PositionSample(round=r.num, tick=t, steamid=sid, side="ct", pos=Vec(x=x, y=0)))
    m.kills.append(Kill(tick=t, round=r.num, attacker_steamid=ME, attacker_name="Ich", attacker_side="ct",
                        victim_steamid=ENEMIES[3], victim_name="Gegner4", victim_side="t", victim_place="SynthA"))
    spots = coaching.bright_spots(m, "alone")
    assert spots and spots[0]["round"] == r.num and "mit Bruder 300 Units daneben" in spots[0]["text"]

    m.grenades.append(GrenadeThrow(round=r.num, entity_id=5, thrower_steamid=ME, grenade_type="Flashbang", kind="flash",
                                   points=[(t - 2 * TR, 0, 0, 0), (t - TR, 100, 0, 0)]))
    assert "wirft eine Flash und holt 2,0 s später den Kill" in coaching.bright_spots(m, "utility")[0]["text"]


def test_training_pages_and_drill_done():
    from fastapi.testclient import TestClient

    from cstaktik import api, history, pipeline

    coaching.save({"players": {"s1": {"focus": {"lesson": "alone", "target": 1.0, "baseline": 2.0,
                                                "created_at": "2026-10-01T10:00", "matches": [], "status": "aktiv"},
                                      "done": [], "drills": []}}}, pipeline.COACHING_FILE)
    sc = {"lesson": "alone", "who": "Ich", "round": 3, "tick": 500, "from": 400, "report": "x.html", "map": "de_mirage",
          "snap": {"own": 4, "enemy": 5, "planted": False, "hp": 100, "mate_d": 1300, "mate": "Bruder", "secs": 20,
                   "place": "Mid", "kind": "bewegt"}, "aktion": "Richtung Gegner", "pro_rates": None,
          "pro_best": None, "cost": 12, "happened": "h", "next": "n"}
    sc["sid"] = "s1"
    history.save({"id": "a1", "map": "de_mirage", "rounds": 20, "analyzed_at": "2026-10-02T10:00",
                  "players": {"s1": {"name": "Ich"}}, "scenes": [sc, sc]}, pipeline.HISTORY_DIR)
    c = TestClient(api.app)
    home = c.get("/").text
    assert "Eure Aufträge" in home and "Nie allein in ein Duell" in home and "1 eigene Situationen" in home
    t = c.get("/training/situationen").text
    assert "Nicht ohne Trade-Partner peeken" in t and "1 echte Situationen" in t
    hub = c.get("/training").text  # Wochenplan wird beim ersten Aufruf angelegt
    assert "Wochenplan" in hub and "Zu zweit peeken" in hub and "Situations-Training" in hub
    st = coaching.load(pipeline.COACHING_FILE)["players"]["s1"]
    (week, plan), = st["weeks"].items()
    tid = plan["tasks"][0]["id"]
    assert c.post(f"/training/plan?p=s1&week={week}&task={tid}", follow_redirects=False).status_code == 303
    st = coaching.load(pipeline.COACHING_FILE)["players"]["s1"]
    assert tid in st["weeks"][week]["done"] and len(st["drills"]) == 1  # Übung zählt auch als Drill
    c.post(f"/training/plan?p=s1&week={week}&task={tid}")  # Haken wieder weg: Übung zurückgenommen
    st = coaching.load(pipeline.COACHING_FILE)["players"]["s1"]
    assert tid not in st["weeks"][week]["done"] and st["drills"] == []
    # Start-Button: zählt einmal und hakt dieselbe Übung im Wochenplan ab
    assert c.post("/training/done?p=s1", follow_redirects=False).status_code == 303
    st = coaching.load(pipeline.COACHING_FILE)["players"]["s1"]
    assert len(st["drills"]) == 1 and tid in st["weeks"][week]["done"]
    assert "(1x bisher)" in c.get("/").text
    # Formular von fremder Seite wird abgelehnt
    assert c.post("/training/done?p=s1", headers={"origin": "https://evil.example"}).status_code == 403
    # hinter einem Proxy: Origin = öffentliche Adresse, Host = intern
    assert c.post("/training/done?p=s1", headers={"origin": "https://coach.example", "host": "127.0.0.1:8000",
                                                   "x-forwarded-host": "coach.example"},
                  follow_redirects=False).status_code == 303


def test_update_all_per_player_and_legacy_migration():
    st = {"focus": {"lesson": "alone", "target": 1.0, "baseline": 2.0, "created_from": "0", "matches": [],
                    "status": "aktiv"}, "done": [], "drills": []}
    summ = {"id": "1", "rounds": 20, "analyzed_at": "2026-10-05", "players": {"a": {"name": "A"}, "b": {"name": "B"}},
            "lessons": {"a": {"alone": 0, "utility": 4}, "b": {"alone": 5}}}
    res = coaching.update_all(st, summ, {"a": ["utility"], "b": ["alone"]})
    assert "focus" not in st and set(st["players"]) == {"a", "b"}  # alter gemeinsamer Auftrag übernommen
    assert res["a"]["check"]["met"] and res["b"]["check"]["met"] is False and res["a"]["name"] == "A"


def test_kabine_in_briefing():
    from fastapi.testclient import TestClient

    from cstaktik import api, history, pipeline

    coaching.save({"players": {"s1": {"focus": {"lesson": "alone", "target": 1.0, "baseline": 2.0,
                                                "created_at": "2026-10-01T10:00", "matches": [], "status": "aktiv"},
                                      "done": [], "drills": []}}}, pipeline.COACHING_FILE)
    sc = {"lesson": "alone", "who": "Ich", "sid": "s1", "round": 3, "tick": 500, "from": 400, "report": "x.html",
          "map": "de_mirage", "pos": [100, 200], "snap": {}, "aktion": "gehalten", "happened": "", "next": ""}
    history.save({"id": "a1", "map": "de_mirage", "rounds": 20, "analyzed_at": "2026-10-02T10:00",
                  "players": {"s1": {"name": "Ich"}}, "scenes": [sc]}, pipeline.HISTORY_DIR)
    html = TestClient(api.app).get("/briefing/de_mirage").text
    assert "Kabine" in html and "Nie allein in ein Duell" in html and "/reports/x.html#s3-400" in html


def _ps(mid, n, rounds=20, lid="alone", played=None):
    s = _sum(mid, n, rounds, lid)
    s["players"] = {"a": {"name": "A", "rounds": played if played is not None else rounds}}
    return s


def test_baseline_pooled_over_recent_matches_and_min_count():
    past = [_ps("1", 1), _ps("2", 1)]
    st = {"focus": None, "done": [], "drills": []}
    r = coaching.update(st, _ps("3", 4), ["alone"], sid="a", past=past)
    # nicht nur das schlechte Match (2,0), sondern 6 in 60 Runden = 1,0 pro 10 Runden
    assert r["focus"]["baseline"] == 1.0 and r["focus"]["baseline_n"] == 6 and r["focus"]["baseline_rounds"] == 60
    st2 = {"focus": None, "done": [], "drills": []}
    assert coaching.update(st2, _ps("1", 2), ["alone"], sid="a")["focus"] is None  # 2 Vorkommen: zu wenig


def test_short_match_does_not_count_and_mastery_needs_rounds():
    st = {"focus": None, "done": [], "drills": []}
    coaching.update(st, _ps("1", 4), ["alone"], sid="a")  # Ziel 1,2
    short = coaching.update(st, _ps("2", 0, played=8), ["alone"], sid="a")
    assert short["check"]["met"] is None and short["check"]["streak"] == 0  # 8 Runden: weder für noch gegen
    r3 = coaching.update(st, _ps("3", 0, rounds=13), ["alone"], sid="a")
    r4 = coaching.update(st, _ps("4", 0, rounds=13), ["alone"], sid="a")
    assert r4["check"]["streak"] == 2 and r4["mastered"] is None  # 2x geschafft, aber nur 26 Runden
    r5 = coaching.update(st, _ps("5", 1, rounds=20), ["alone"], sid="a")
    assert r5["mastered"] == "alone" and r5["check"]["streak_rounds"] == 46
    assert r3["check"]["rounds"] == 13


def test_relapse_brings_mastered_lesson_back():
    st = {"focus": None, "done": [{"lesson": "alone", "baseline": 1.5, "done_at": "2026-10-02T20:00"}], "drills": []}
    hist = [_ps("1", 1), _ps("2", 1)]
    assert coaching.update(st, _ps("3", 3), ["alone"], sid="a", past=hist)["focus"] is None  # 5/60 < 1,5
    hist = [_ps("1", 4), _ps("2", 3)]
    r = coaching.update(st, _ps("4", 4), ["alone"], sid="a", past=hist)
    assert r["focus"]["lesson"] == "alone" and r["focus"]["rueckfall"] == "2026-10-02T20:00"


def test_compare_rates_only_claims_clear_differences():
    assert coaching.compare_rates(8, 48, 2, 48)["state"] == "besser"
    assert coaching.compare_rates(3, 40, 9, 40)["state"] == "schlechter"
    assert coaching.compare_rates(4, 40, 2, 40)["state"] == "gleich"
    assert coaching.compare_rates(2, 20, 0, 20)["state"] == "wenig"  # zu wenig Runden


def test_bright_spots_from_duels_and_honest_none():
    from cstaktik.model import Duel

    m = build_match()
    k = next(k for k in m.kills if k.attacker_steamid == MATES[1])
    m.duels = [Duel(round=k.round, tick=k.tick, contact=k.tick - 20, winner=MATES[1], loser=k.victim_steamid,
                    w_err=3.5, l_err=30.0, w_react_ms=0, l_react_ms=200, w_first_hit=True, l_first_hit=False,
                    w_speed=10, l_speed=200, w_shots=2, l_shots=3)]
    spots = coaching.bright_spots(m, "crosshair")
    assert spots and "Fadenkreuz 3,5° neben dem Gegner, zuerst geschossen" in spots[0]["text"]
    assert "steht beim ersten Schuss (10 Units/s)" in coaching.bright_spots(m, "moving")[0]["text"]
    assert coaching.bright_spots(m, "blind") is None  # keine Suche für diese Lektion
    assert coaching.bright_spots(m, "crosshair", sid=ME) == []  # nur Szenen dieses Spielers


def test_check_counts_drills_before_match():
    st = {"focus": None, "done": [], "drills": []}
    coaching.update(st, _ps("1", 4), ["alone"], sid="a")  # Auftrag seit 2026-10-01T20:00
    coaching.drill_done(st, "alone", "2026-10-01T21:00")
    coaching.drill_done(st, "alone", "2026-10-02T10:00")
    coaching.drill_done(st, "utility", "2026-10-02T10:00")  # andere Lektion zählt nicht
    r = coaching.update(st, _ps("2", 1), ["alone"], sid="a")
    assert r["check"]["drills"] == 2
    coaching.drill_done(st, "alone", "2026-10-03T10:00")
    assert coaching.update(st, _ps("3", 1), ["alone"], sid="a")["check"]["drills"] == 1  # nur seit dem letzten Match


def test_old_counting_is_recomputed_on_next_upload(tmp_path, monkeypatch):
    """Alte coaching.json (andere Zählweise): beim nächsten Upload werden die Aufträge neu berechnet."""
    from synth import BRO

    from cstaktik import pipeline
    from cstaktik.parser.loader import save_match

    monkeypatch.setattr(pipeline, "REPORTS_DIR", tmp_path / "reports")
    for i in range(2):
        m = build_match()
        m.source_sha256 = f"match{i}"
        src = tmp_path / f"m{i}.json"
        save_match(m, src)
        pipeline.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        save_match(m, pipeline.CACHE_DIR / f"match{i}.v{pipeline.CACHE_SCHEMA}.json")
        if i == 1:  # Zustand wie vor dem Update: alte Zählweise, unpassender Ausgangswert
            st = coaching.load(pipeline.COACHING_FILE)
            st.pop("count_version", None)
            for slot in st["players"].values():
                if slot.get("focus"):
                    slot["focus"]["baseline"] = 99.0
            coaching.save(st, pipeline.COACHING_FILE)
        pipeline.run(src, {ME, BRO}, tmp_path / "reports")
    st = coaching.load(pipeline.COACHING_FILE)
    assert st["count_version"] == coaching.COUNT_VERSION
    assert all((s.get("focus") or {}).get("baseline") != 99.0 for s in st["players"].values())
