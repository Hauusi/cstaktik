"""Wer sah wen zuerst: Sichtungs-Läufe, Gleichstand, Kennzahlen."""

from cstaktik.duels import first_seen, seen_first, seen_stats


def test_first_seen_takes_start_of_last_continuous_run():
    ticks = list(range(0, 400, 4))
    # 0..40 gesehen, dann 1 s Pause (Lücke > 0,5 s), ab 120 wieder; kurze Lücke 200..220 wird überbrückt
    seen = {(t, "T"): frozenset({"V"}) for t in ticks if t <= 40 or (120 <= t < 200) or t >= 220}
    assert first_seen(seen, ticks, "V", "T", 64) == 120
    assert first_seen(seen, ticks, "X", "T", 64) is None


def test_seen_first_order_and_tie():
    assert seen_first(100, 200, True, 64) == "ich"
    assert seen_first(200, 100, True, 64) == "gegner"
    assert seen_first(100, 105, True, 64) == "gleich"  # unter 0,15 s
    assert seen_first(None, 100, True, 64) == "gegner"
    assert seen_first(100, None, True, 64) == "ich"
    assert seen_first(None, None, True, 64) is None
    assert seen_first(100, 200, False, 64) is None  # Demo ohne Sichtung: keine Aussage


def test_seen_stats_split_wins_by_who_saw_first():
    rows = ([{"seen": "ich", "won": True}] * 3 + [{"seen": "ich", "won": False}]
            + [{"seen": "gegner", "won": False}] * 4 + [{"seen": "gleich", "won": True}, {"seen": None, "won": True}])
    s = seen_stats(rows)
    assert (s["seen_n"], s["seen_me"], s["seen_opp"]) == (9, 44, 44)
    assert (s["won_seen_me"], s["won_seen_opp"], s["seen_me_n"], s["seen_opp_n"]) == (75, 0, 4, 4)


def test_reading_names_position_when_seen_first_more_than_pros():
    from cstaktik.coach_voice import duel_reading

    pro = {"err": 5.0, "shot_first": 59, "first_hit": 30, "seen_n": 400, "seen_me": 45, "seen_opp": 40,
           "won_seen_me": 70, "won_seen_opp": 35}
    me = {"n": 40, "err": 5.1, "shot_first": 50, "first_hit": 30, "seen_n": 30, "seen_me": 30, "seen_opp": 60,
          "seen_me_n": 9, "seen_opp_n": 18, "won_seen_me": 66, "won_seen_opp": 22}
    r = duel_reading(me, pro)
    assert "60 %" in r and "Pros 40 %" in r and "22 %" in r and "Position" in r
    # sieht oft zuerst, verliert aber: Umsetzung
    me2 = {**me, "seen_me": 50, "seen_opp": 40, "seen_me_n": 15, "won_seen_me": 45}
    assert "verpufft" in duel_reading(me2, pro)
    # zu wenig Sichtungen: alte Lesart
    assert "Position und Timing" in duel_reading({**me, "seen_n": 5}, pro)


def test_death_sentence_says_who_saw_first():
    from cstaktik.coach_voice import _duel_sentence

    s = _duel_sentence({"attacker": "der Gegner", "duel": {"seen": "gegner", "seen_ms": -800, "won": False}})
    assert s.startswith("Der Gegner hat dich zuerst gesehen, 0,8 s vor dir.")
    s = _duel_sentence({"attacker": "x", "duel": {"seen": "ich", "seen_ms": 400, "won": False}})
    assert "Du hast ihn zuerst gesehen (0,4 s Vorsprung) und trotzdem verloren." in s


def test_lesson_seen_first_beats_crosshair_but_not_angle():
    from cstaktik.coach_voice import lesson_id

    lost = {"label": "Duell verloren"}
    assert lesson_id({**lost, "duel": {"err": 35.0, "seen": "gegner", "seen_ms": -600}}) == "seen_first"
    assert lesson_id({**lost, "duel": {"err": 35.0, "seen": "gegner", "seen_ms": None}}) == "seen_first"
    # knapp (unter 0,3 s) oder gleichzeitig: bleibt beim Fadenkreuz
    assert lesson_id({**lost, "duel": {"err": 35.0, "seen": "gegner", "seen_ms": -200}}) == "crosshair"
    assert lesson_id({**lost, "duel": {"err": 35.0, "seen": "gleich"}}) == "crosshair"
    # in eine ganz andere Richtung geschaut: Winkel-Problem
    assert lesson_id({**lost, "duel": {"err": 120.0, "seen": "gegner", "seen_ms": -900}}) == "angle"


def test_seen_first_why_and_next_name_the_lead():
    from cstaktik.coach_voice import _next, _why

    fx = {"attacker": "Gegner1", "aplace": "Palace", "duel": {"seen": "gegner", "seen_ms": -700}}
    snap = {"kind": "gehalten", "place": "Ramp"}
    assert "Gegner1 aus Palace hat dich gesehen, 0,7 s bevor du ihn gesehen hast" in _why("seen_first", fx, snap, "gehalten")
    assert _next("seen_first", fx, snap).startswith("In Ramp nicht an der offenen Kante warten")


def test_time_to_shot_from_sighting():
    from cstaktik.duels import side_of, tts_stats
    from cstaktik.model import Duel

    # Kontakt 1000, Sieger sah ab 936 (1 s vorher) und schoss 0 ms nach Kontakt; Verlierer sah ab 990, schoss 250 ms
    d = Duel(round=1, tick=1100, contact=1000, winner="w", loser="l", w_react_ms=0, l_react_ms=250,
             seen_known=True, w_seen=936, l_seen=990)
    assert side_of(d, "w", 64)["tts"] == 1000 and side_of(d, "l", 64)["tts"] == 406
    # Prefire (Schuss vor der Sichtung) und unbekannte Sichtung: kein Wert
    assert side_of(d.model_copy(update={"w_seen": 1010}), "w", 64)["tts"] is None
    assert side_of(d.model_copy(update={"seen_known": False}), "w", 64)["tts"] is None
    assert tts_stats([{"tts": 300}, {"tts": 500}, {"tts": None}]) == {"tts": 400, "tts_n": 2}


def test_reading_time_to_shot():
    from cstaktik.coach_voice import duel_reading

    pro = {"err": 3.0, "shot_first": 60, "first_hit": 30, "tts": 380, "tts_n": 500}
    me = {"n": 30, "err": 3.4, "shot_first": 55, "first_hit": 30, "tts": 520, "tts_n": 20}
    assert "520 ms" in duel_reading(me, pro) and "Pros 380 ms" in duel_reading(me, pro)
