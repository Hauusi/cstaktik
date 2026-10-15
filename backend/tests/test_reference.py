from synth import ME, build_match

from cstaktik import history
from cstaktik.config import load_rules_config
from cstaktik.reference import enrich, timeline, winning_spots
from cstaktik.rules import analyze

CFG = load_rules_config()


def _match():
    """Siegrunden 3 und 4: Ich steht in SynthJungle. Verlorene Runde 2: Tod in SynthMid."""
    m = build_match()
    for p in m.positions:
        if p.steamid == ME:
            p.place = "SynthJungle" if p.round in (3, 4) else "SynthMid"
    return m


def test_timeline_places_every_5s():
    tl = [t for t in timeline(_match()) if t["sid"] == ME]
    r3 = next(t for t in tl if t["round"] == 3)
    assert r3["won"] and r3["side"] == "ct" and r3["places"][0] == "SynthJungle" and r3["places"][4] == "SynthJungle"


def test_enrich_adds_reference_and_ghost():
    m = _match()
    res = analyze(m, CFG)
    enrich(m, res.findings)
    f = next(f for f in res.findings if f.rule_id == "death_review" and f.round == 2)
    assert "In gewonnenen CT-Runden warst du nach 0:20 meist in SynthJungle, in 2 von 2. Hier bist du in SynthMid gestorben." == f.evidence["vorbild"]
    assert f.overlay["ghost_round"] in (3, 4) and f.overlay["ghost_offset_s"] == 20 and len(f.overlay["ghost"]) == 2


def test_no_reference_without_enough_won_rounds():
    m = _match()
    res = analyze(m, CFG)
    enrich(m, res.findings, min_samples=5)
    assert not any("vorbild" in f.evidence for f in res.findings)


def test_winning_spots_for_briefing_from_history():
    m = _match()
    s = history.summarize(m, analyze(m, CFG))
    spots = winning_spots([s, {**s, "id": "x"}], "de_mirage")
    me = next(w for w in spots if w["name"] == "Ich")
    assert (me["side"], me["place"], me["n"], me["total"]) == ("CT", "SynthJungle", 4, 4)  # je Match Runde 3+4 (Runde 1 ohne Positionen)
