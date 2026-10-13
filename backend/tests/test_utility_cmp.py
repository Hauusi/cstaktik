"""Utility gegen Pros: Lineup-Abstand, Flash-Wirkung, Utility vor dem ersten Duell. Synthetische Daten."""

from synth import ENEMIES, MATES, ME, build_match

from cstaktik import utility_cmp
from cstaktik.model import Blind, GrenadeThrow, PositionSample, UtilityArea, Vec


def _match():
    m = build_match()
    r = m.rounds[1]
    f0 = r.freeze_end_tick
    for p in m.positions:  # Orte für die Landepunkt-Bestimmung
        p.place = "SynthJungle" if p.pos.x > 2000 else "SynthMid"
    m.grenades.append(GrenadeThrow(round=r.num, entity_id=1, thrower_steamid=ME, grenade_type="Smoke", kind="smoke",
                                   points=[(f0 + 64, 0, 0, 0), (f0 + 200, 3400, 3000, 0)]))
    m.utility.append(UtilityArea(round=r.num, kind="flash", start_tick=f0 + 300, thrower_steamid=ME, pos=Vec(x=0, y=0)))
    m.blinds += [Blind(round=r.num, tick=f0 + 300, victim_steamid=ENEMIES[0], attacker_steamid=ME, duration=2.4),
                 Blind(round=r.num, tick=f0 + 301, victim_steamid=MATES[1], attacker_steamid=ME, duration=1.2)]
    return m


def test_lineup_vs_pro_spot():
    m = _match()
    pro = [{"map": "de_mirage", "nades": [{"kind": "smoke", "side": "ct", "to": "SynthJungle", "from": "SynthCT",
                                            "tx": 3100 + i, "ty": 3000, "won": True, "r": 1, "t": 5, "fx": 0, "fy": 0}
                                           for i in range(4)]}]
    ln = utility_cmp.lineups(m, pro)
    assert len(ln) == 1 and ln[0]["to"] == "SynthJungle" and ln[0]["pro_from"] == "SynthCT"
    assert 290 <= ln[0]["dist"] <= 300 and ln[0]["ok"] is False


def test_flash_effect_and_pre_contact():
    m = _match()
    fl = utility_cmp.flash_effect(m, {ME})
    assert fl == [{"r": m.rounds[1].num, "tick": m.rounds[1].freeze_end_tick + 300, "sid": ME, "enemy_s": 2.4,
                   "team_s": 1.2}]
    st = utility_cmp.flash_stats(fl)
    assert st["good"] == 1 and st["team"] == 1
    n, pr = utility_cmp.pre_contact(m, {ME})
    assert n == 1 and pr >= 1
