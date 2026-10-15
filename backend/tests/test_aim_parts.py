"""Fadenkreuz-Fehler zerlegt: seitlich und Höhe."""

from cstaktik.coach_voice import duel_reading
from cstaktik.duels import aim_parts, angle_parts, angle_error


def test_angle_parts_side_and_height():
    target = (1000.0, 0.0, 0.0)
    # Blick genau auf den Kopf
    assert angle_parts((0.0, 0.0, 0.0, 0.0, 0.0), target) == (0.0, 0.0)
    # 5 Grad nach unten geschaut = zu tief, 4 Grad seitlich (yaw über 360 gewickelt)
    side, height = angle_parts((0.0, 0.0, 0.0, 356.0, 5.0), target)
    assert (side, height) == (4.0, 5.0)
    assert abs(angle_error((0.0, 0.0, 0.0, 356.0, 5.0), target) - 6.4) < 0.1
    # Gegner höher (Treppe): Blick geradeaus liegt unter dem Kopf
    assert angle_parts((0.0, 0.0, 0.0, 0.0, 0.0), (1000.0, 0.0, 100.0))[1] > 5


def test_aim_parts_only_near_duels():
    rows = [{"err": 5, "side": 1, "height": 4}, {"err": 6, "side": 2, "height": 3}, {"err": 3, "side": 3, "height": 0},
            {"err": 90, "side": 90, "height": 0}]
    p = aim_parts(rows)
    assert p == {"aim_n": 3, "err_side": 2.0, "err_height": 3.0, "low_pct": 67}


def test_reading_names_low_crosshair():
    pro = {"err": 3.0, "aim_n": 300, "low_pct": 30, "err_side": 2.0}
    me = {"n": 30, "err": 5.1, "aim_n": 20, "low_pct": 55, "err_side": 2.2}
    assert "zu tief" in duel_reading(me, pro) and "55 %" in duel_reading(me, pro)
    me2 = {**me, "low_pct": 32, "err_side": 4.0}
    assert "seitlich" in duel_reading(me2, pro)
    assert "Kopfhöhe ist hier" in duel_reading({**me, "aim_n": 3}, pro)


def test_death_sentence_mentions_height():
    from cstaktik.coach_voice import _duel_sentence

    s = _duel_sentence({"attacker": "x", "duel": {"err": 6.0, "height": 5.0}})
    assert "6° neben x, 5° unter dem Kopf" in s
