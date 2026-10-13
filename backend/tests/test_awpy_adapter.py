"""parse_demo mit einem nachgebauten awpy-Demo-Objekt (Spaltennamen wie awpy 2.0.2).

Fängt Fehler im Adapter ab, ohne eine echte .dem zu brauchen.
"""

import pandas as pd
import pytest

pl = pytest.importorskip("polars")
awpy = pytest.importorskip("awpy")

from cstaktik.parser.awpy_adapter import parse_demo  # noqa: E402

A, B = 76561190000000001, 76561190000000011


class FakeParser:
    def parse_event(self, name, **_):
        assert name == "player_blind"
        return pd.DataFrame([{"tick": 850, "user_steamid": A, "attacker_steamid": B, "blind_duration": 1.734}])

    def parse_ticks(self, props, ticks=None):
        rows = []
        for t in ticks or []:
            for sid, team in ((A, "CT"), (B, "TERRORIST")):
                r = {"tick": t, "steamid": sid, "name": str(sid)}
                if "inventory" in props:
                    r["inventory"] = ["Glock-18", "Flashbang"]
                if "velocity_X" in props:
                    r.update(velocity_X=30.0 if sid == A else 0.0, velocity_Y=40.0 if sid == A else 0.0)
                if "pitch" in props:  # Kontakt-Tick: A schaut nach +y zu B, B nach -y zu A
                    r.update(X=float(t), Y=0.0 if sid == A else 500.0, Z=0.0, yaw=90.0 if sid == A else 270.0,
                             pitch=0.0)
                if "balance" in props:
                    r.update(balance=800, current_equip_value=4200, cash_spent_this_round=3500, team_name=team)
                rows.append(r)
        return pd.DataFrame(rows)


class FakeDemo:
    def __init__(self, path, tickrate=64, **_):
        self.header = {"map_name": "de_mirage"}
        self.parser = FakeParser()

    def parse(self, player_props=None):
        self.rounds = pl.DataFrame({
            "round_num": [1], "start": [100], "freeze_end": [200], "end": [2000], "official_end": [2100],
            "winner": ["t"], "reason": ["t_killed"], "bomb_plant": [None], "bomb_site": ["not_planted"],
        })
        ticks = []
        for t in range(200, 1000, 8):
            ticks.append({"tick": t, "steamid": A, "name": "Ich", "side": "ct", "round_num": 1,
                          "X": float(t), "Y": 0.0, "Z": 0.0, "place": "Mid", "health": 100, "yaw": 90.0,
                          "active_weapon_name": "M4A1-S", "spotted": False})
            ticks.append({"tick": t, "steamid": B, "name": "Gegner", "side": "t", "round_num": 1,
                          "X": float(t), "Y": 500.0, "Z": 0.0, "place": "Top", "health": 100, "yaw": 270.0,
                          "active_weapon_name": "AK-47", "spotted": t > 32})
        self.ticks = pl.DataFrame(ticks).with_columns(pl.col("steamid").cast(pl.UInt64))
        self.kills = pl.DataFrame([{
            "tick": 900, "round_num": 1, "attacker_steamid": B, "attacker_name": "Gegner", "attacker_side": "t",
            "attacker_X": 900.0, "attacker_Y": 500.0, "attacker_Z": 0.0, "attacker_place": "Top",
            "victim_steamid": A, "victim_name": "Ich", "victim_side": "ct", "victim_X": 900.0, "victim_Y": 0.0,
            "victim_Z": 0.0, "victim_place": "Mid", "weapon": "ak47", "headshot": True,
        }])
        self.grenades = pl.DataFrame([
            {"thrower_steamid": A, "thrower": "Ich", "grenade_type": "smokegrenade", "tick": t,
             "X": float(t), "Y": 100.0, "Z": 10.0, "entity_id": 55, "round_num": 1}
            for t in range(300, 400, 2)
        ])
        self.smokes = pl.DataFrame([{"entity_id": 55, "start_tick": 400, "end_tick": 1500, "thrower_steamid": A,
                                     "thrower_name": "Ich", "X": 398.0, "Y": 100.0, "Z": 0.0, "round_num": 1}])
        self.infernos = pl.DataFrame(schema={"entity_id": pl.Int64, "start_tick": pl.Int64, "end_tick": pl.Int64,
                                             "thrower_steamid": pl.UInt64, "X": pl.Float64, "Y": pl.Float64,
                                             "Z": pl.Float64, "round_num": pl.Int64})
        self.bomb = pl.DataFrame(schema={"tick": pl.Int64, "event": pl.Utf8, "X": pl.Float64, "Y": pl.Float64,
                                         "Z": pl.Float64, "steamid": pl.UInt64, "round_num": pl.Int64})
        self.shots = pl.DataFrame([{"tick": 870, "round_num": 1, "player_steamid": A, "weapon": "weapon_m4a1"}])
        self.damages = pl.DataFrame([{"tick": 880, "round_num": 1, "attacker_steamid": A, "victim_steamid": B,
                                      "dmg_health_real": 27, "weapon": "m4a1"}])
        self.events = {
            "flashbang_detonate": pl.DataFrame([{"tick": 500, "x": 1.0, "y": 2.0, "z": 3.0, "user_steamid": A}]),
            # Smoke 1400 Ticks (> 20 s bei 64 Tick): awpy würde das Ende verwerfen
            "smokegrenade_detonate": pl.DataFrame([{"entityid": 55, "tick": 400, "x": 398.0, "y": 100.0, "z": 0.0, "user_steamid": A}]),
            "smokegrenade_expired": pl.DataFrame([{"entityid": 55, "tick": 1800}]),
        }


def test_parse_demo_with_fake_awpy(tmp_path, monkeypatch):
    monkeypatch.setattr(awpy, "Demo", FakeDemo)
    demo = tmp_path / "x.dem"
    demo.write_bytes(b"fake")
    stages = []
    cfg = {"tickrate": 64, "position_samples_per_second": 4, "economy_sample_offset_s": 5, "grenade_sample_ticks": 4}
    m = parse_demo(demo, {str(A)}, cfg, progress=lambda st, f: stages.append((st, f)))

    assert m.map_name == "de_mirage" and [r.num for r in m.rounds] == [1]
    assert {p.steamid for p in m.players if p.is_focus} == {str(A)}
    assert m.rounds[0].sides == {str(A): "ct", str(B): "t"}
    assert m.positions and all(p.tick % 16 == 0 for p in m.positions) and m.positions[0].yaw is not None
    assert {p.spotted for p in m.positions} == {True, False}
    assert m.kills[0].victim_inventory == ["Glock-18", "Flashbang"]
    assert m.rounds[0].economy and m.rounds[0].economy[0].equip_value == 4200
    assert len(m.grenades) == 1 and m.grenades[0].kind == "smoke" and len(m.grenades[0].points) < 50
    assert {u.kind for u in m.utility} == {"smoke", "flash"}
    smoke = next(u for u in m.utility if u.kind == "smoke")
    assert (smoke.end_tick, smoke.end_known) == (1800, True)
    assert {p.weapon for p in m.positions} == {"M4A1-S", "AK-47"}
    assert m.shots[0].speed == 50.0 and m.shots[0].weapon == "weapon_m4a1"
    assert m.blinds[0].victim_steamid == str(A) and m.blinds[0].duration == 1.73
    assert m.damages[0].dmg == 27 and m.damages[0].attacker_steamid == str(A)
    assert m.missing == []
    fr = [f for _, f in stages]
    assert fr == sorted(fr) and stages[-1][0] == "Duelle"
    d = m.duels[0]
    assert (d.contact, d.winner, d.loser) == (870, str(B), str(A))
    assert d.l_err == 0.0 and d.w_err == 0.0 and d.l_react_ms == 0 and d.w_react_ms is None


def test_match_timed_long_missing_and_reused_entity():
    from cstaktik.parser.awpy_adapter import match_timed

    bounds = [(1, 0, 1000), (2, 1100, 3000)]
    starts = [{"entityid": 5, "tick": 100}, {"entityid": 5, "tick": 1200}, {"entityid": 9, "tick": 200}]
    ends = [{"entityid": 5, "tick": 900}, {"entityid": 5, "tick": 2700}]
    res = {(row["entityid"], rnd): (end, known) for row, rnd, end, known in match_timed(starts, ends, bounds)}
    assert res[(5, 1)] == (900, True)  # 800 Ticks, keine Obergrenze
    assert res[(5, 2)] == (2700, True)  # gleiche entityid in neuer Runde
    assert res[(9, 1)] == (1000, False)  # kein Ende -> Rundenende, markiert
