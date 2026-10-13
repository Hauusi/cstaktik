from synth import BRO, ENEMIES, MATES, ME, build_match, _kill
from cstaktik.coach import advantage_throws, diagnose, duo, utility_impact
from cstaktik.config import load_rules_config
from cstaktik.model import Blind, Damage, GrenadeThrow, Vec
from cstaktik.rules import analyze

CFG = load_rules_config()
C = CFG["coach"]


def _with_throw():
    """Runde 5: CT tötet 3 Gegner (5 gegen 2) und verliert trotzdem."""
    m = build_match()
    r5 = m.round_by_num(5)
    for i, e in enumerate(ENEMIES[:3]):
        m.kills.append(_kill(r5, 10 + i, MATES[2 + i % 3], e, Vec(x=500, y=500), "SynthB"))
    m.kills.sort(key=lambda k: k.tick)
    return m


def test_advantage_throw_detected_from_kill_order():
    t = advantage_throws(_with_throw(), C["advantage_min_lead"])
    assert t == [{"round": 5, "tick": t[0]["tick"], "mine": 5, "theirs": 2}]
    assert advantage_throws(build_match(), C["advantage_min_lead"]) == []


def test_diagnose_ranks_causes_by_lost_rounds_and_builds_moments():
    m = _with_throw()
    d = diagnose(m, analyze(m, CFG), C)
    assert (d["won"], d["lost"]) == (3, 3)
    ids = [c["id"] for c in d["causes"]]
    assert ids[0] == "economy" and d["causes"][0]["lost_rounds"] == [2, 5]
    assert "Hauptgründe" in d["sentence"] and "2 von 3 verlorenen Runden" in d["sentence"]
    # Momente: Runde + Tick fürs Replay, inkl. verspielter Überzahl
    assert d["key_moments"] and all(mo["tick"] is not None for mo in d["key_moments"])
    assert any(mo["title"] == "Überzahl verspielt" and mo["round"] == 5 for mo in d["key_moments"])
    assert any(p["title"] == "Trade gegeben" for p in d["positives"])


def test_cause_needs_minimum_lost_rounds():
    m = build_match()
    d = diagnose(m, analyze(m, CFG), {**C, "cause_min_lost_rounds": 3})
    assert d["causes"] == [] and "Kein klares Muster" in d["sentence"]


def test_duo_together_vs_apart_trades_and_first_deaths():
    d = duo(build_match(), C)
    assert d["together"] == {"rounds": 1, "won": 1}  # R3: Bruder 200 Units daneben
    assert d["apart"] == {"rounds": 2, "won": 1}  # R2 verloren, R4 gewonnen
    assert d["trades"]["Bruder"] == 1 and d["died_first"]["Ich"] == 3
    assert duo(build_match(focus=(ME,)), C) is None


def test_utility_impact_counts_blinds_and_nade_damage():
    m = build_match()
    r2 = m.round_by_num(2)
    t = r2.freeze_end_tick
    m.grenades.append(GrenadeThrow(round=2, entity_id=1, thrower_steamid=ME, grenade_type="flashbang", kind="flash",
                                   points=[(t, 0, 0, 0)]))
    m.blinds = [
        Blind(round=2, tick=t + 5, victim_steamid=ENEMIES[0], attacker_steamid=ME, duration=2.0),
        Blind(round=2, tick=t + 5, victim_steamid=BRO, attacker_steamid=ME, duration=1.5),
        Blind(round=2, tick=t + 5, victim_steamid=ENEMIES[1], attacker_steamid=ME, duration=0.2),  # zu kurz
    ]
    m.damages = [Damage(round=2, tick=t + 9, attacker_steamid=ME, victim_steamid=ENEMIES[0], dmg=40, weapon="hegrenade")]
    u = {x["name"]: x for x in utility_impact(m, C)}["Ich"]
    assert (u["thrown"]["flash"], u["enemies_blinded"], u["team_blinded"], u["he_damage"]) == (1, 1, 1, 40)


def test_report_shows_verdict_causes_and_moment_tour(tmp_path):
    import json
    import re

    from cstaktik.report.render import render_report

    m = _with_throw()
    html = render_report(m, analyze(m, CFG), maps_dirs=[tmp_path])
    assert "3:3 auf Mirage. Ich hab es mir angesehen." in html and "Warum verloren" in html and "Economy-Fehler" in html
    assert "Ihr als Duo" in html and "Utility-Wirkung" in html
    data = json.loads(re.search(r'id="data">(.*?)</script>', html, re.S).group(1))
    assert data["moments"] and all({"round", "tick", "title"} <= set(mo) for mo in data["moments"])


def test_history_stores_causes():
    from cstaktik import history

    m = _with_throw()
    s = history.summarize(m, analyze(m, CFG))
    assert s["causes"]["economy"] == 2
