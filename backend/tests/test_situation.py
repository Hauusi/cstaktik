"""Situations-Analyse: Entscheidungsmoment, Lagebild, Gewinnchance. Synthetische Daten (Präfix 'Synth')."""

from synth import ENEMIES, MATES, ME, NAMES, TR, _round

from cstaktik.config import load_rules_config
from cstaktik.model import BombEvent, Damage, Finding, Kill, MatchData, Player, PositionSample, Vec
from cstaktik.rules.base import PositionIndex
from cstaktik.situation import WinModel, decision_tick, enrich, round_states

CFG = load_rules_config()["situation"]


def _match(moving_at_death: bool) -> MatchData:
    """ME steht 0–14 s in SynthA; danach entweder stehen (gehalten) oder ab 14 s Richtung Gegner laufen."""
    r = _round(1, "t")
    f0 = r.freeze_end_tick
    pos = []
    for i in range(0, 20 * TR + 1, TR // 4):
        t = f0 + i
        if moving_at_death and i > 14 * TR:
            x = 200 * (i - 14 * TR) / TR  # 200 Units/s Richtung Gegner
        else:
            x = 0.0
        pos.append(PositionSample(round=1, tick=t, steamid=ME, side="ct", pos=Vec(x=x, y=0), place="SynthA"))
        pos.append(PositionSample(round=1, tick=t, steamid=MATES[1], side="ct", pos=Vec(x=-2000, y=0), place="SynthCT"))
        pos.append(PositionSample(round=1, tick=t, steamid=ENEMIES[0], side="t", pos=Vec(x=2500, y=0),
                                  place="SynthPalace"))
    kills = [
        Kill(tick=f0 + 5 * TR, round=1, attacker_steamid=ENEMIES[1], victim_steamid=MATES[2],
             victim_name=NAMES[MATES[2]], victim_side="ct", attacker_side="t"),
        Kill(tick=f0 + 20 * TR, round=1, attacker_steamid=ENEMIES[0], attacker_side="t", attacker_place="SynthPalace",
             victim_steamid=ME, victim_name="Ich", victim_side="ct", victim_place="SynthA",
             victim_pos=Vec(x=0, y=0), victim_inventory=["USP-S", "Smoke Grenade", "Flashbang"]),
    ]
    dmg = [Damage(round=1, tick=f0 + 3 * TR, attacker_steamid=ENEMIES[0], victim_steamid=ME, dmg=80, weapon="ak47")]
    return MatchData(map_name="de_synth", tickrate=TR, tickrate_source="test",
                     players=[Player(steamid=s, name=NAMES[s], is_focus=s == ME) for s in MATES + ENEMIES],
                     rounds=[r], kills=kills, damages=dmg, positions=pos)


def _finding(m: MatchData) -> Finding:
    k = m.kills[-1]
    return Finding(rule_id="death_review", title="Tod", round=1, tick=k.tick, severity="hoch", steamid=ME,
                   player_name="Ich", text="", tip="")


def test_decision_moment_moving_and_holding():
    m = _match(moving_at_death=True)
    r = m.rounds[0]
    tick, kind = decision_tick(PositionIndex(m.positions), r, ME, m.kills[-1].tick, TR, CFG)
    assert kind == "bewegt" and abs(tick - (r.freeze_end_tick + 14 * TR)) <= TR // 4 + 1  # Beginn der Bewegung

    m = _match(moving_at_death=False)
    tick, kind = decision_tick(PositionIndex(m.positions), m.rounds[0], ME, m.kills[-1].tick, TR, CFG)
    assert kind == "gehalten" and tick == r.freeze_end_tick + 12 * TR  # Rückblick max. 8 s


def test_snapshot_text_category_and_action():
    m = _match(moving_at_death=True)
    f = _finding(m)
    enrich(m, [f], None, CFG)
    e = f.evidence
    assert e["entscheidung"].startswith("0:14: Du gehst los in SynthA. Lage: 4 gegen 5, du 20 HP, Bombe nicht gelegt")
    assert "Bruder 2000 Units weg" in e["entscheidung"] and "du hattest Smoke, Flash" in e["entscheidung"]
    assert e["situation"] == "Allein vorrücken (CT)" and e["aktion"] == "Richtung Gegner"
    assert f.overlay["decision"][2] == m.rounds[0].freeze_end_tick + 14 * TR


def test_win_model_counts_and_cost():
    # 10 Runden: aus 4v5 gewinnt CT 4x, aus 3v5 nie
    rounds = [{"w": "ct" if i < 4 else "t", "s": [[5, 5, 0], [4, 5, 0]] + ([[3, 5, 0]] if i >= 4 else [])}
              for i in range(10)]
    model = WinModel(rounds, min_n=5)
    assert model.prob("ct", 4, 5, False)[0] == 0.4
    assert model.prob("ct", 3, 5, False) == (0.0, 6, False)
    assert model.prob("ct", 2, 5, False) is None or model.prob("ct", 2, 5, False)[2]  # nur grob
    assert model.prob("t", 0, 3, False)[0] == 1.0

    m = _match(moving_at_death=True)
    f = _finding(m)
    enrich(m, [f], model, CFG)
    assert f.evidence["cost_pct"] == 40 and "vorher 40 %, danach 0 %" in f.evidence["chance"]


def test_round_states_with_plant():
    m = _match(moving_at_death=False)
    m.bomb.append(BombEvent(round=1, tick=m.rounds[0].freeze_end_tick + 15 * TR, event="plant"))
    assert round_states(m) == [{"w": "t", "s": [[5, 5, 0], [4, 5, 0], [4, 5, 1], [3, 5, 1]]}]


def test_info_from_spotted():
    m = _match(moving_at_death=True)
    f0 = m.rounds[0].freeze_end_tick
    for p in m.positions:
        if p.steamid == ENEMIES[0]:
            p.spotted = p.tick >= f0 + 16 * TR  # Killer ab 0:16 auf dem Radar
        elif p.steamid in ENEMIES:
            p.spotted = False
    m.kills[-1].attacker_name = "Gegner1"
    f = _finding(m)
    enrich(m, [f], None, CFG)
    assert f.evidence["info"] == "Info: kein Gegner auf dem Radar, Gegner1 war ab 0:16 sichtbar."

    for p in m.positions:
        p.spotted = None
    f = _finding(m)
    enrich(m, [f], None, CFG)
    assert "info" not in f.evidence  # Feld fehlt in der Demo: keine Aussage
