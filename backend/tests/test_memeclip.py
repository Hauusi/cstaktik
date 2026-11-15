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
