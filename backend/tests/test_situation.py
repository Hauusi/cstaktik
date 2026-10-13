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


def test_pro_decisions_and_compare_by_situation():
    from synth import build_match

    from cstaktik.situation import compare, compare_text, enrich_pro, pro_decisions

    rows = pro_decisions(build_match(focus=()))
    assert rows and all(r[4] in ("gehalten", "zurückgezogen", "Richtung Gegner") for r in rows)
    assert all(len(r) == 9 and r[0] in ("ct", "t") for r in rows)

    # handgebaut: CT 4 gegen 5 ohne Bombe: 6x gehalten (4 Siege), 4x Richtung Gegner (1 Sieg)
    dec = [["ct", 4, 5, 0, "gehalten", i < 4, 1, 0, "p"] for i in range(6)] + \
          [["ct", 4, 5, 0, "Richtung Gegner", i < 1, 1, 0, "p"] for i in range(4)]
    pro = [{"id": "a", "map": "de_synth", "decisions": dec}]
    cmp = compare(pro, "de_synth", "ct", 4, 5, False, min_n=8)
    assert cmp["best"] == "gehalten" and cmp["n"] == 10 and not cmp["coarse"]
    assert compare_text(cmp, "ct", 4, 5, False, "Richtung Gegner") == (
        "Pros in dieser Lage (CT, 4 gegen 5, Bombe nicht gelegt), 10 Fälle aus 1 Demo: Position gehalten 6x "
        "(67 % Siege), Richtung Gegner 4x (25 % Siege). Du: Richtung Gegner.")
    assert compare(pro, "de_other", "ct", 4, 5, False) is None

    m = _match(moving_at_death=True)
    m.map_name = "de_synth"
    f = _finding(m)
    enrich(m, [f], None, CFG)
    enrich_pro(m, [f], pro)
    assert f.evidence["pro_best"] == "gehalten" and "Du: Richtung Gegner" in f.evidence["pro_lage"]


def test_pro_tip_and_situation_clip():
    from synth import build_match

    from cstaktik.reference import pro_clips
    from cstaktik.situation import enrich_pro

    pm = build_match(focus=())
    pm.source_sha256 = "pm1"
    rnd = next(r for r in pm.rounds if r.winner == "ct")
    dec = [["ct", 4, 5, 0, "gehalten", True, rnd.num, rnd.freeze_end_tick + 15 * TR, MATES[2]] for _ in range(6)] + \
          [["ct", 4, 5, 0, "Richtung Gegner", i < 1, 1, 0, "p"] for i in range(4)]
    pro = [{"id": "pm1", "map": "de_synth", "decisions": dec}]
    m = _match(moving_at_death=True)
    m.map_name = pm.map_name = "de_synth"
    f = _finding(m)
    enrich(m, [f], None, CFG)
    enrich_pro(m, [f], pro)
    assert f.evidence["pro_tip"] == ('In dieser Lage gewinnen Pros am häufigsten mit "Position gehalten" '
                                     '(100 % Siege), bei dir: Richtung Gegner (25 %).')
    clips = pro_clips(m, [f], [pm], pro)  # kein Pro am selben Ort -> Szene nach Lage
    assert len(clips) == 1 and clips[0]["sid"] == MATES[2]
    assert f.evidence["pro_clip"].startswith("Gleiche Lage (CT, 4 gegen 5, Bombe nicht gelegt): Mate3 hat "
                                             "Position gehalten und die Runde gewonnen.")


def test_no_best_action_with_single_option():
    from cstaktik.situation import compare

    dec = [["ct", 4, 5, 0, "gehalten", True, 1, 0, "p"] for _ in range(10)]
    cmp = compare([{"id": "a", "map": "m", "decisions": dec}], "m", "ct", 4, 5, False)
    assert cmp["n"] == 10 and cmp["best"] is None


def test_coach_voice_scene_and_focus():
    from cstaktik import coach_voice
    from cstaktik.config import load_rules_config
    from cstaktik.rules import death_review

    m = _match(moving_at_death=True)
    m.kills[-1].attacker_name = "Gegner1"
    cfg = load_rules_config()["rules"]["death_review"]
    fs = death_review.run(m, {**cfg, "mech": load_rules_config()["mechanics"]})
    f = fs[-1]
    enrich(m, [f], None, CFG)
    coach_voice.apply([f])
    v = f.evidence["coach"]
    assert v["id"] in coach_voice.LESSONS and v["lesson"] == coach_voice.LESSONS[v["id"]][0]
    assert v["happened"].startswith("Bei 0:14 gehst du in SynthA los: 4 gegen 5, nur 20 HP, Bruder 2000 Units weg.")
    assert "Gegner1 aus SynthPalace" in v["happened"]
    foc = coach_voice.focus([f, f])
    assert foc[0]["count"] == 2 and foc[0]["lesson"] == v["lesson"]
    assert coach_voice.headline(foc).startswith("Was euch heute Runden gekostet hat: ")
