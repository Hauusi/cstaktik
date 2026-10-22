"""Granaten-Wirkung aus Demo-Ereignissen: Schaden, Blendzeit, Flash-Assist, ungenutzte Granaten beim Tod."""

from cstaktik import ai_coach, nade_effect
from cstaktik.model import (Blind, Damage, GrenadeThrow, Kill, MatchData, Player, Round, UtilityArea, Vec)

ME, MATE, EN = "1", "2", "9"


def _match():
    sides = {ME: "t", MATE: "t", EN: "ct"}
    g = lambda kind, r: GrenadeThrow(round=r, entity_id=r, thrower_steamid=ME, grenade_type=kind, kind=kind,  # noqa: E731
                                     points=[])
    return MatchData(
        map_name="de_mirage", tickrate=64, tickrate_source="t",
        players=[Player(steamid=ME, name="Ich", is_focus=True), Player(steamid=MATE, name="Mate"),
                 Player(steamid=EN, name="Gegner")],
        rounds=[Round(num=1, start_tick=0, end_tick=5000, sides=sides), Round(num=2, start_tick=5000, end_tick=9000, sides=sides)],
        grenades=[g("flash", 1), g("he", 1), g("molotov", 2), g("smoke", 2)],
        utility=[UtilityArea(round=1, kind="flash", start_tick=1000, thrower_steamid=ME, pos=Vec(x=0, y=0))],
        blinds=[Blind(round=1, tick=1005, victim_steamid=EN, attacker_steamid=ME, duration=2.5),
                Blind(round=1, tick=1005, victim_steamid=MATE, attacker_steamid=ME, duration=1.2)],
        damages=[Damage(round=1, tick=1200, attacker_steamid=ME, victim_steamid=EN, dmg=40, weapon="hegrenade"),
                 Damage(round=1, tick=1200, attacker_steamid=ME, victim_steamid=MATE, dmg=10, weapon="hegrenade"),
                 Damage(round=2, tick=6000, attacker_steamid=ME, victim_steamid=EN, dmg=30, weapon="inferno")],
        kills=[Kill(tick=1100, round=1, attacker_steamid=MATE, victim_steamid=EN, victim_name="Gegner", weapon="ak47"),
               Kill(tick=7000, round=2, attacker_steamid=EN, victim_steamid=ME, victim_name="Ich", weapon="m4a1",
                    victim_inventory=["Glock-18", "Flashbang", "HE Grenade"])],
    )


def test_stats():
    s = nade_effect.stats(_match(), ME)
    assert s["flash"] == {"n": 1, "good": 1, "team": 1, "assists": 1, "enemies": 1, "avg_blind_s": 2.5}
    assert s["he"] == {"n": 1, "enemy_dmg": 40, "team_dmg": 10, "kills": 0}
    assert s["molotov"] == {"n": 1, "enemy_dmg": 30, "team_dmg": 0, "kills": 0} and s["smoke"] == {"n": 1}
    assert s["unused"] == [{"r": 2, "nades": ["Flash", "HE"]}] and s["deaths_known"] == 1
    r1 = s["rounds"][0]
    assert r1["thrown"] == {"flash": 1, "he": 1} and r1["he_dmg"] == 40 and r1["assists"] == 1 and r1["team_blind"] == 1


def test_coach_facts_show_effect():
    h = {"map": "de_mirage", "players": {ME: {"name": "Ich"}}, "nade_eff": nade_effect.by_player(_match())}
    t = ai_coach.facts(h, ME)
    assert "Flash-Assist): 1" in t and "HE: 1 geworfen, 40 Schaden an Gegnern, 10 an Mitspielern." in t
    assert "Smokes: 1 geworfen. Ihre Wirkung (Sicht blockiert) misst die App nicht." in t
    assert "Gestorben mit Granaten in der Tasche: 1 von 1 Toden: Runde 2 (Flash, HE)" in t
    assert "Runde 1: 1x Flash, 1x HE; 1 Gegner geblendet (zusammen 2.5 s); 1 geblendete Gegner getötet; " \
           "eigenes Team geblendet; HE 40 Schaden" in t
