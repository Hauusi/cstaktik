"""Meme-Clip: Kill-Zeitpunkte aus Rahmen-Zählung und Schnittplan (ohne ffmpeg)."""

from cstaktik import memeclip


def test_kills_bridge_short_dropouts_and_count_double_kills():
    cnt = [0] * 20 + [1] * 30 + [0] * 10 + [1] * 20 + [0] * 80 + [1] * 10 + [2] * 20 + [0] * 10
    ks = [t for t, _ in memeclip.kills_from_counts(cnt, fps=20)]
    assert ks == [1.0, 8.0, 8.5]  # Aussetzer von 0,5 s ist kein neuer Kill; 1 -> 2 ist ein zweiter
    assert memeclip.kills_from_counts([0] * 10 + [1] * 2 + [0] * 30) == []  # einzelnes Aufblitzen unter 0,2 s zählt nicht


def test_plan_cuts_dead_time_and_ends_on_freeze():
    box = (1100, 80, 1270, 105)
    segs = memeclip.plan([{"t": 4.15, "box": box}, {"t": 10.1, "box": box}], 18.0)
    kinds = [s["kind"] for s in segs]
    assert kinds == ["lead", "hit", "lead", "hit", "hold"]
    assert [s["text"] for s in segs if s["kind"] != "lead"] == ["+1", "+2", "2 KILLS"]
    assert segs[2]["ss"] > segs[1]["ss"] + segs[1]["d"] + 2  # Totzeit zwischen den Kills fällt weg
    assert segs[1]["ss"] < 4.05 < segs[1]["ss"] + segs[1]["d"]  # der Kill liegt in der Zeitlupe, nicht davor
    assert all(s["d"] > 0 for s in segs) and segs[-1]["d"] == memeclip.LAST_HOLD_S
    one = memeclip.plan([{"t": 0.2, "box": box}], 3.0)
    assert one[-1]["text"] == "KILL" and one[0]["ss"] >= 0


def test_beat_grid_finds_tempo_and_plan_puts_kills_on_beats():
    import numpy as np

    from cstaktik import beats

    env = np.zeros(1500)
    env[5::50] = 1.0  # ein Schlag alle 0,5 s (10 ms Raster) = 120 Schläge pro Minute
    g = beats.beat_grid(env)
    assert abs(g["bpm"] - 120) < 2 and abs(g["beats"][1] - g["beats"][0] - 0.5) < 0.02
    box = (1100, 80, 1270, 105)
    bt = [round(0.1 + 0.5 * i, 3) for i in range(27)]
    pl = memeclip.plan_beat([{"t": 4.15, "box": box}, {"t": 10.1, "box": box}, {"t": 16.15, "box": box}], 18.2, bt)
    hits = [s for s in pl["segments"] if s["kind"] == "hit"]
    assert len(hits) == 3 and all(any(abs(h["o0"] - b) < 0.001 for b in bt) for h in hits)  # Kill genau auf dem Schlag
    o = 0.0
    for s in pl["segments"]:  # lückenlos: jedes Segment beginnt, wo das vorige endet
        assert abs(s["o0"] - o) < 0.002, s
        o += s["out"]
    assert abs(o - pl["seconds"]) < 0.01
    assert memeclip.word_times(["A", "B", "1.45:C"], bt)[:3] == [(0.1, 0.6, "A"), (0.6, 1.45, "B"), (1.45, 1.95, "C")]
