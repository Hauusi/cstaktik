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
    k2 = [{"t": 4.15, "box": box, "src": "a.mp4", "dur": 18.2}, {"t": 10.1, "box": box, "src": "a.mp4", "dur": 18.2},
          {"t": 3.0, "box": box, "src": "b.mp4", "dur": 9.0}]
    pl = memeclip.plan_beat(k2, 18.2, bt)
    hits = [s for s in pl["segments"] if s["kind"] == "hit"]
    assert len(hits) == 3 and all(any(abs(h["o0"] - b) < 0.001 for b in bt) for h in hits)  # Kill genau auf dem Schlag
    kinds = [s["kind"] for s in pl["segments"]]
    assert kinds[:6] == ["shot", "ramp", "hit", "shot", "ramp", "hit"]  # je Takt: Schnitt, Anlauf, Kill
    cuts = [s["o0"] for s in pl["segments"]]
    assert all(any(abs(c - b) < 0.002 for b in bt + [0.0]) or c < 0.11 for c in cuts)  # jeder Bildwechsel auf einem Schlag
    sh = pl["segments"][3]
    assert sh["ss"] + sh["d"] <= pl["segments"][4]["ss"] + 0.001  # der Schnitt zeigt die Szene vor dem Anlauf
    assert [round(hits[i + 1]["o0"] - hits[i]["o0"], 2) for i in range(2)] == [2.0, 2.0]  # fester Abstand: ein Takt
    assert hits[0]["o0"] <= 1.2 and hits[2]["src"] == "b.mp4"  # erster Kill früh; dritter aus dem zweiten Clip
    o = 0.0
    for s in pl["segments"]:  # lückenlos: jedes Segment beginnt, wo das vorige endet
        assert abs(s["o0"] - o) < 0.002 and s["ss"] >= 0, s
        o += s["out"]
    assert abs(o - pl["seconds"]) < 0.01
    from math import log

    r = next(s for s in pl["segments"] if s["kind"] == "ramp" and s["v0"] != s["v1"])  # Tempo gleitet, füllt die Lücke genau
    assert abs(r["d"] / (r["v1"] - r["v0"]) * log(r["v1"] / r["v0"]) - r["out"]) < 0.01 and r["v0"] > 1 > r["v1"]
    assert all(abs(h["out"] - 1.0) < 0.01 for h in hits)  # der Kill steht zwei Schläge lang in Zeitlupe
    assert memeclip.ramp_fit(2.0, 0.5)[1:] == (0.25, 0.25)  # zu wenig Material: gleichmäßig langsam
    assert memeclip.word_times(["A", "B", "1.45:C"], bt)[:3] == [(0.1, 0.6, "A"), (0.6, 1.45, "B"), (1.45, 1.95, "C")]


def test_onset_cut_and_word_merge():
    import numpy as np

    m = np.zeros(100)
    m[42:] = 5.0  # Bewegung setzt bei 4,2 s ein (10 Werte je Sekunde)
    assert abs(memeclip.onset_cut((10, m), 3.0, 6.0) - 4.1) < 0.15
    assert memeclip.onset_cut(None, 3.0, 6.0) == 6.0
    bt = [round(0.5 * i, 3) for i in range(20)]
    ws = memeclip.word_times(["1.00:I", "1.10:AM", "1.20:HERE", "2.0:NOW"], bt)
    assert [w[2] for w in ws] == ["I AM", "HERE", "NOW"]  # zu kurz hintereinander: zusammen, höchstens zwei


def test_wall_picks_held_words_before_pause():
    bt = [round(0.5 * i, 3) for i in range(30)]
    words = ["1.00-1.15:TALK", "1.20-1.35:TO", "1.40-1.55:ME", "1.60-2.40:BABY", "2.90-3.05:IM", "3.10-3.30:GOING",
             "3.35-3.50:SO", "3.55-3.70:FAST"]
    wl = memeclip.word_list(words, bt)
    wb = next(x for x in wl if x["txt"] == "BABY")
    assert wb["sung"] == 2.4 and wb["next"] == 2.86  # an der Wand bis zum nächsten Wort (das 40 ms früher kommt)  # steht bis zum nächsten Wort
    picks = memeclip.wall_picks(wl)
    assert [x["txt"] for x in wl] == ["TALK TO", "ME", "BABY", "IM GOING", "SO FAST"]
    assert "BABY" in [wl[j]["txt"] for j in picks] and not {0, 1} & picks  # gezogen + Pause ja, schnelle Wörter nein
    assert memeclip.wall_picks(memeclip.word_list(["EINS", "ZWEI"], bt)) == set()  # eingetippt: einfache Regel
    assert memeclip.word_times(["1.45:A"], bt) == [(1.45, 1.95, "A")]


def test_kill_beats_prefer_strong_and_vary():
    bt = [round(0.5 * i, 3) for i in range(40)]
    st = [0.1] * 40
    for i in (2, 7, 10, 16, 20, 25):
        st[i] = 1.0  # betonte Schläge
    kb = memeclip.kill_beats(4, 40, st, bt)
    assert kb == [2, 7, 10, 16]  # jeweils der starke Schlag im Fenster 3 bis 6
    gaps = [b - a for a, b in zip(kb, kb[1:])]
    assert len(set(gaps)) > 1  # kein starres Raster
    assert memeclip.kill_beats(3, 40, None, bt) == [2, 6, 10]  # ohne Stärken: gleichmäßig
    w = memeclip.word_list(["1.00-1.50:BABY", "2.00:EINS"], bt)
    assert w[0]["a"] == 0.96 and w[1]["a"] == 2.0  # gesungen: 40 ms früher; feste Zeit: genau
