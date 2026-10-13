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

    coaching.save({"focus": {"lesson": "alone", "target": 1.0, "baseline": 2.0, "created_at": "2026-10-01T10:00",
                             "matches": [], "status": "aktiv"}, "done": [], "drills": []}, pipeline.COACHING_FILE)
    sc = {"lesson": "alone", "who": "Ich", "round": 3, "tick": 500, "from": 400, "report": "x.html", "map": "de_mirage",
          "snap": {"own": 4, "enemy": 5, "planted": False, "hp": 100, "mate_d": 1300, "mate": "Bruder", "secs": 20,
                   "place": "Mid", "kind": "bewegt"}, "aktion": "Richtung Gegner", "pro_rates": None,
          "pro_best": None, "cost": 12, "happened": "h", "next": "n"}
    history.save({"id": "a1", "map": "de_mirage", "rounds": 20, "analyzed_at": "2026-10-02T10:00",
                  "players": {}, "scenes": [sc, sc]}, pipeline.HISTORY_DIR)
    c = TestClient(api.app)
    home = c.get("/").text
    assert "Dein Auftrag" in home and "Nie allein in ein Duell" in home and "1 eigene Situationen" in home
    t = c.get("/training").text
    assert "Nicht ohne Trade-Partner peeken" in t and "1 echte Situationen" in t
    assert c.post("/training/done", follow_redirects=False).status_code == 303
    assert len(coaching.load(pipeline.COACHING_FILE)["drills"]) == 1
    assert "(1x bisher)" in c.get("/").text
