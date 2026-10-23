"""Szenen-Clip: letzte Sekunden vor dem Tod aus Demo-Positionen, im Coach und in der Story abspielbar."""

from cstaktik import api, scene_clip
from cstaktik.model import Kill, MatchData, Player, PositionSample, Round, UtilityArea, Vec

ME, MATE, EN = "1", "2", "9"


def _match():
    sides = {ME: "t", MATE: "t", EN: "ct"}
    pos = []
    for k in range(0, 13 * 64, 16):  # 4 Abtastpunkte je Sekunde
        tick = 1000 + k
        pos += [PositionSample(round=1, tick=tick, steamid=ME, side="t", pos=Vec(x=k, y=0), alive=True),
                PositionSample(round=1, tick=tick, steamid=MATE, side="t", pos=Vec(x=0, y=k), alive=True),
                PositionSample(round=1, tick=tick, steamid=EN, side="ct", pos=Vec(x=500, y=500), alive=True)]
    return MatchData(
        map_name="de_mirage", tickrate=64, tickrate_source="t",
        players=[Player(steamid=ME, name="Ich", is_focus=True), Player(steamid=MATE, name="Mate"),
                 Player(steamid=EN, name="Gegner")],
        rounds=[Round(num=1, start_tick=0, freeze_end_tick=1000, end_tick=3000, sides=sides)],
        positions=pos,
        kills=[Kill(tick=1640, round=1, attacker_steamid=EN, victim_steamid=ME, victim_name="Ich", weapon="ak47")],
        utility=[UtilityArea(round=1, kind="smoke", start_tick=1100, end_tick=2000, thrower_steamid=MATE,
                             pos=Vec(x=100, y=100))])


def test_clip_window_teams_and_events():
    c = scene_clip.clip(_match(), ME, 1, 1640, from_tick=1500)
    assert [p["t"] for p in c["ids"]] == [0, 1, 2] and c["ids"][0]["n"] == "Ich"
    assert c["frames"][0][0] == -8.0  # Start: 8 s vor dem Tod (Entscheidung lag später)
    assert scene_clip.clip(_match(), ME, 1, 1640, from_tick=1050)["frames"][0][0] == -10.0  # nie vor der Kaufzeit
    assert c["frames"][-1][0] <= 1.0 and any(t == 0 for t, _ in c["frames"])
    assert c["kills"] == [[0.0, 2, 0]]
    assert c["nades"] == [[-8.44, 5.62, "smoke", 100, 100, 1]]
    assert scene_clip.clip(_match(), ME, 2, 1640) is None  # Runde ohne Daten: kein Clip


def test_clip_px_frames_and_view():
    class R:
        scale = 5.0

        def to_px(self, x, y):
            return x / 5, y / 5

    v = api._clip_px(scene_clip.clip(_match(), ME, 1, 1640), R())
    assert v["frames"][0][1][0][:1] == [0] and v["nades"][0][5] == 28.0  # Smoke-Radius 140 Units / Maßstab
    assert len(v["vb"]) == 3 and v["vb"][2] >= 380  # Ausschnitt um dich und deinen Killer
