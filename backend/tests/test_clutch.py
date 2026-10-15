from cstaktik import clutch
from cstaktik.model import BombEvent, Kill, MatchData, Player, Round


def _kill(t, a, v, vside):
    return Kill(tick=t, round=1, attacker_steamid=a, victim_steamid=v, victim_name=v, victim_side=vside)


def _match(kills, bomb=(), winner="t"):
    sides = {"me": "t", "m2": "t", "e1": "ct", "e2": "ct"}
    return MatchData(tickrate=64, tickrate_source="t", players=[Player(steamid=s, name=s) for s in sides],
                     rounds=[Round(num=1, start_tick=0, end_tick=9000, winner=winner, sides=sides)],
                     kills=kills, bomb=list(bomb))


def test_clutch_detected_with_plant_and_kills():
    m = _match([_kill(100, "e1", "m2", "t"), _kill(800, "me", "e1", "ct"), _kill(1000, "me", "e2", "ct")],
               bomb=[BombEvent(round=1, tick=500, event="plant", steamid="me")])
    rows = clutch.clutches(m, team={"me", "m2"})
    assert rows == [{"sid": "me", "round": 1, "side": "t", "vs": 2, "planted": False, "won": True, "kills": 2,
                     "alive": True, "plant": True}]


def test_simultaneous_deaths_counted_together():
    # m2 und e1 sterben im selben Tick: Lage ist 1 gegen 1, nicht 1 gegen 2
    m = _match([_kill(100, "e2", "m2", "t"), _kill(100, "me", "e1", "ct"), _kill(400, "e2", "me", "t")],
               winner="ct")
    rows = {r["sid"]: r for r in clutch.clutches(m)}
    assert rows["me"]["vs"] == 1 and rows["e2"]["vs"] == 1
    assert rows["me"]["won"] is False and rows["me"]["life_s"] == round(300 / 64, 1)
    assert clutch.clutches(m, team={"me"})[0]["sid"] == "me"


def test_summary_compares_with_pro_expectation():
    pros = [{"states": [{"w": "ct", "s": [[2, 1, 0], [1, 1, 0]]}] * 8 + [{"w": "t", "s": [[1, 1, 0]]}] * 4}]
    rates = clutch.pro_rates(pros)
    assert rates["rates"][("ct", 1, False)] == [12, 8] and rates["rates"][("t", 2, False)] == [8, 0] and rates["rates"][("t", 1, False)] == [4, 4]
    own = [{"sid": "me", "side": "ct", "vs": 1, "planted": False, "won": False, "kills": 0, "alive": False}] * 6
    s = clutch.summary([{"clutch": own}], "me", pros)
    assert s["n"] == 6 and s["won"] == 0 and s["exp"] == 4.0 and s["exp_n"] == 6
    assert "lässt du Runden liegen" in s["reading"]
    assert clutch.summary([{"clutch": own}], "other", pros) is None


def test_clutch_lever():
    from cstaktik import levers

    pros = [{"states": [{"w": "ct", "s": [[1, 1, 0]]}] * 9 + [{"w": "t", "s": [[1, 1, 0]]}] * 3}]
    own = [{"sid": "me", "side": "ct", "vs": 1, "planted": False, "won": False, "kills": 0, "alive": False}] * 6
    hist = [{"players": {"me": {}}, "clutch": own}, {"players": {"me": {}}, "clutch": []}]
    lv = next(x for x in levers.build(hist, pros, "me", top=0) if x["kind"] == "Clutch")
    assert lv["gain"] == 6 * 0.75 / 2 and "0 von 6" in lv["text"]
