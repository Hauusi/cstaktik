import pytest
from synth import BRO, ME, build_match

from cstaktik.config import load_rules_config
from cstaktik.rules import analyze, economy, repeated_death_spot, untraded_death, unused_utility
from cstaktik.rules.base import NotEvaluable

CFG = load_rules_config()


def rule_cfg(rule):
    return CFG["rules"][rule.RULE_ID]


def test_untraded_only_isolated_untraded_death():
    f = untraded_death.run(build_match(), rule_cfg(untraded_death))
    assert [(x.round, x.steamid) for x in f] == [(2, ME)]
    assert f[0].severity == "hoch"  # erster Tod der Runde
    assert f[0].evidence["abstand_units"] > CFG["rules"]["untraded_death"]["trade_distance_units"]
    assert f[0].tick is not None and "SynthMid" in f[0].text


def test_untraded_needs_positions():
    m = build_match()
    m.positions = []
    with pytest.raises(NotEvaluable):
        untraded_death.run(m, rule_cfg(untraded_death))


def test_repeated_death_spot():
    f = repeated_death_spot.run(build_match(), rule_cfg(repeated_death_spot))
    assert len(f) == 1
    assert f[0].rounds == [2, 3, 4] and f[0].severity == "hoch"
    assert f[0].evidence["ort"] == "SynthMid"


def test_repeated_death_spot_radius_fallback_without_place():
    m = build_match()
    for k in m.kills:
        k.victim_place = None
    f = repeated_death_spot.run(m, rule_cfg(repeated_death_spot))
    assert len(f) == 1 and f[0].evidence["tode"] == 3


def test_unused_utility():
    f = unused_utility.run(build_match(), rule_cfg(unused_utility))
    assert [x.round for x in f] == [2]
    assert f[0].evidence["ungenutzt"] == ["Flashbang", "Smoke Grenade"]


def test_unused_utility_not_evaluable_without_inventory():
    m = build_match()
    for k in m.kills:
        k.victim_inventory = None
    with pytest.raises(NotEvaluable):
        unused_utility.run(m, rule_cfg(unused_utility))


def test_economy():
    f = economy.run(build_match(), rule_cfg(economy))
    titles = {(x.round, x.title) for x in f}
    assert (2, "Uneinheitlicher Kauf") in titles
    assert (5, "Force-Buy kostet Folgerunde") in titles
    assert not any(x.round == 1 for x in f)  # Pistolrunde ignoriert
    force = next(x for x in f if x.round == 5)
    assert force.evidence["folgerunde_equip_avg"] == 1000


def test_economy_not_evaluable_without_data():
    m = build_match()
    for r in m.rounds:
        r.economy = []
    with pytest.raises(NotEvaluable):
        economy.run(m, rule_cfg(economy))


def test_analyze_reports_unevaluable_rules():
    m = build_match()
    for r in m.rounds:
        r.economy = []
    res = analyze(m, CFG)
    st = {s.rule_id: s for s in res.rule_status}
    assert st["economy"].evaluated is False and st["economy"].reason
    assert st["death_review"].evaluated is True
    assert st["untraded_death"].reason == "deaktiviert"  # in death_review zusammengefasst


def test_analyze_requires_focus():
    with pytest.raises(ValueError):
        analyze(build_match(focus=()), CFG)


def test_only_focus_players_are_judged():
    res = analyze(build_match(focus=(BRO,)), CFG)
    assert not any(f.steamid == ME for f in res.findings)


def test_entry_deaths_pattern():
    from cstaktik.rules import entry_deaths

    f = entry_deaths.run(build_match(), CFG["rules"]["entry_deaths"])
    assert len(f) == 1 and f[0].rounds == [2, 3, 4] and f[0].steamid == ME


def test_no_damage_death_needs_damage_data_and_counts():
    from cstaktik.model import Damage
    from cstaktik.rules import no_damage_death

    m = build_match()
    with pytest.raises(NotEvaluable):
        no_damage_death.run(m, CFG["rules"]["no_damage_death"])
    # Runde 3: ME hat vorher Schaden gemacht -> zählt nicht
    k3 = next(k for k in m.kills if k.round == 3)
    m.damages = [Damage(round=3, tick=k3.tick - 10, attacker_steamid=ME, victim_steamid=k3.attacker_steamid, dmg=40)]
    cfg = {**CFG["rules"]["no_damage_death"], "min_count": 2}
    f = no_damage_death.run(m, cfg)
    assert f[0].rounds == [2, 4] and "2 von 3" in f[0].text


def test_positives_trade_and_untraded_overlay():
    from cstaktik.rules import positives

    f = positives.run(build_match(), CFG["rules"]["positives"])
    trade = [x for x in f if x.title == "Trade gegeben"]
    assert len(trade) == 1 and trade[0].steamid == BRO and trade[0].round == 4 and trade[0].severity == "gut"
    u = untraded_death.run(build_match(), rule_cfg(untraded_death))[0]
    assert len(u.overlay["line"]) == 2 and "Units" in u.overlay["label"]


def test_stats_and_good_findings_not_in_top_issues():
    res = analyze(build_match(), CFG)
    me = next(s for s in res.stats if s.steamid == ME)
    assert (me.deaths, me.opening_deaths, me.traded_deaths) == (3, 3, 1)
    assert me.adr is None  # keine Schadensdaten -> keine Zahl erfinden
    from cstaktik.report.render import _homework, _top_issues

    assert all(t["title"] != "Trade gegeben" for t in _top_issues(res))
    hw = {h["name"]: h for h in _homework(res)}
    assert hw["Ich"]["items"]


def test_death_review_facts_and_tip_priority():
    from cstaktik.model import Blind, Damage
    from cstaktik.rules import death_review

    m = build_match()
    k2 = next(k for k in m.kills if k.round == 2)
    m.damages = [Damage(round=2, tick=k2.tick - 200, attacker_steamid=k2.attacker_steamid, victim_steamid=ME, dmg=63,
                        weapon="inferno")]
    m.blinds = [Blind(round=2, tick=k2.tick - 32, victim_steamid=ME, attacker_steamid=k2.attacker_steamid, duration=1.8)]
    f = {x.round: x for x in death_review.run(m, CFG["rules"]["death_review"])}
    assert set(f) == {2, 3, 4}  # jeder Tod von ME
    r2 = f[2]
    lage = " | ".join(r2.evidence["lage"])
    assert "5 gegen 5 (erstes Duell der Runde)" in lage and "geblendet 1.8s von Gegner1, 0.5s vor dem Tod" in lage
    assert "37 HP vor dem Duell (vorher 63 durch Molotov von Gegner1)" in lage
    assert r2.title == "Tod: Geblendet" and r2.severity == "hoch"  # Blendung hat Vorrang
    assert r2.text.startswith("Ich stirbt bei 0:20 in SynthMid mit 37 HP, geblendet, gegen Gegner1 (ak47)")
    assert "Allein, kein Trade" in r2.evidence["weitere_punkte"] and "Utility nicht genutzt" in r2.evidence["weitere_punkte"]
    assert r2.overlay["line"] and "Units zu" in r2.overlay["label"]
    # Runde 3: Bruder 200 Units daneben -> nicht allein
    assert all("Allein" not in p for p in f[3].evidence["weitere_punkte"]) and "Allein" not in f[3].title
    # Runde 4: allein, aber Bruder tradet -> kein "Allein, kein Trade"
    assert "wurde getradet" in f[4].evidence["lage"] and "Allein" not in f[4].title


def test_death_review_concrete_tips_and_no_fake_outnumbered():
    from synth import MATES

    from cstaktik.rules import death_review

    m = build_match()
    # Team startet nur mit 4 Spielern (wie im echten Match): Opening-Tod ist KEINE "Unterzahl"
    r2 = m.round_by_num(2)
    del r2.sides[MATES[4]]
    f = {x.round: x for x in death_review.run(m, CFG["rules"]["death_review"])}[2]
    assert "Unterzahl" not in [f.title.removeprefix("Tod: ")] + f.evidence["weitere_punkte"]
    assert "Teams 4 gegen 5 von Anfang an" in f.evidence["lage"][0]
    # Haupttipp nennt die echte Person/Entfernung statt Standardsatz
    assert f.title == "Tod: Allein, kein Trade" and "Units weg" in f.tip and "Bruder" in f.tip
    assert "Utility nicht genutzt" in f.evidence["weitere_punkte"]
