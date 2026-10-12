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
    assert st["untraded_death"].evaluated is True


def test_analyze_requires_focus():
    with pytest.raises(ValueError):
        analyze(build_match(focus=()), CFG)


def test_only_focus_players_are_judged():
    res = analyze(build_match(focus=(BRO,)), CFG)
    assert not any(f.steamid == ME for f in res.findings)
