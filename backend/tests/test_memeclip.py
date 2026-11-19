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


def test_sync_anchors_put_shots_on_eighth_notes():
    half = 0.25  # Achtelschlag bei 120 Schlägen pro Minute
    anc = memeclip.sync_anchors([1.4, 1.7, 1.95], s0=1.0, ks=2.2, gap=1.5, half=half)
    assert anc[0] == (1.0, 0.0) and anc[-1] == (2.2, 1.5)  # Anfang und Kill (auf dem Schlag) fest
    for (x0, y0), (x1, y1) in zip(anc, anc[1:]):
        assert x1 > x0 and y1 > y0  # zeitlich vorwärts
    for x, y in anc[1:]:
        assert abs((1.5 - y) / half - round((1.5 - y) / half)) < 1e-6  # jeder Schuss auf einem Achtelschlag
    for (x0, y0), (x1, y1) in zip(anc[1:], anc[2:]):
        assert memeclip.SYNC_MIN <= (x1 - x0) / (y1 - y0) <= memeclip.SYNC_MAX
    v = [(x1 - x0) / (y1 - y0) for (x0, y0), (x1, y1) in zip(anc, anc[1:])] + [memeclip.HIT_SLOW]
    assert all(max(a / b, b / a) <= memeclip.SYNC_JUMP + 1e-6 for a, b in zip(v, v[1:]))  # keine Tempo-Sprünge
    assert len(anc) >= 4  # mehrere Schüsse eingerastet
    assert memeclip.sync_anchors([], 1.0, 2.2, 1.5, half) == [(1.0, 0.0), (2.2, 1.5)]


def test_align_lyrics_keeps_text_and_fills_gaps():
    typed = "Talk to me baby im going blind".split()
    sung = ["1.00-1.20:talk", "1.25-1.40:too", "1.45-1.60:me", "1.65-2.40:Baby", "3.00-3.20:I'm", "3.80-4.10:blind"]
    out = memeclip.align_lyrics(typed, sung, 10.0)
    assert [w.split(":", 1)[1] for w in out] == typed  # Text bleibt der eingefügte, vollständig
    assert out[0] == "1.00-1.20:Talk" and out[3] == "1.65-2.40:baby" and out[6] == "3.80-4.10:blind"
    t_to, t_going = float(out[1].split(":")[0]), float(out[5].split(":")[0])
    assert 1.2 < t_to < 1.45 and 3.0 < t_going < 3.8  # verpasste Wörter zwischen die Nachbarn verteilt
    assert memeclip.align_lyrics(typed, None, 10.0) == typed
    assert memeclip.align_lyrics(typed, ["1.0-1.2:xyz"], 10.0) == typed  # nichts passt: unverändert


def test_hallucinated_segments_dropped():
    from types import SimpleNamespace as S
    assert memeclip._hallucinated(S(text=" Thanks for watching!", no_speech_prob=0.1, avg_logprob=-0.3))
    assert memeclip._hallucinated(S(text=" na na", no_speech_prob=0.8, avg_logprob=-1.4))
    assert not memeclip._hallucinated(S(text=" Im a diva", no_speech_prob=0.2, avg_logprob=-0.6))


def test_end_on_bar_and_brightness_match():
    bt = [round(0.5 * i, 3) for i in range(40)]
    h = memeclip.end_hold(5.0, bt, 2, 0.5)  # erster Kill auf Schlag 2: Takte beginnen bei 2, 6, 10, 14 ...
    assert 0.95 <= h <= 2.05 and round((5.0 + h) / 0.5) % 4 == 2
    assert memeclip.end_hold(19.5, bt, 2, 0.5) == 1.0  # Musik zu Ende: 2 Schläge
    off = memeclip.brightness_offsets({"hell.mp4": 150.0, "dunkel.mp4": 70.0})
    assert off["hell.mp4"] < 0 < off["dunkel.mp4"] and max(abs(v) for v in off.values()) <= 0.08
    assert memeclip.brightness_offsets({"a.mp4": 90.0}) == {"a.mp4": 0.0}


def test_transitions_and_sfx_only_at_scene_changes():
    segs = [{"kind": "shot", "o0": 0.0}, {"kind": "ramp", "o0": 0.5}, {"kind": "hit", "o0": 1.0, "out": 1.0},
            {"kind": "shot", "o0": 2.0}, {"kind": "ramp", "o0": 2.5}, {"kind": "hit", "o0": 3.0, "out": 1.0},
            {"kind": "hold", "o0": 4.0}]
    cuts = memeclip.transition_cuts(segs)
    assert cuts == [2.0]  # nur neue Szene nach einem Kill, nicht der Anfang, nicht innerhalb der Szene
    assert memeclip.transition_vf([]) == "" and "gblur" not in memeclip.transition_vf(cuts)  # Zoom ohne Unschärfe
    e = memeclip.sfx_expr(segs, 0.5, cuts)
    assert e.count("*pow((t-") == 2 and "sin(2*PI*(220" not in e and e.count("exp(-pow(") == 1 and "(t-1.000)" in e and "(t-3.000)" in e  # je Kill ein Riser und ein Impact


def test_drop_found_where_bass_starts():
    import numpy as np
    from cstaktik import beats

    e = np.concatenate([np.full(400, 0.1), np.full(600, 1.0)])  # 20 s ruhig, dann Bass (ein Wert je 50 ms)
    assert abs(beats.drop_time(e, 0.05) - 20.0) < 0.3
    assert beats.drop_time(np.full(1000, 0.5), 0.05) is None  # kein Anstieg: kein Drop
    from cstaktik.api import _music_start
    assert _music_start("") == -1.0 and _music_start("12,5") == 12.5 and _music_start("x") == -1.0


def test_margin_keeps_ramp_formula_valid():
    r = {"kind": "ramp", "d": 0.3, "v0": 1.6, "v1": 0.4}
    m = memeclip._margin(r)
    assert 0 < m <= 0.15 and r["v1"] - (r["v0"] - r["v1"]) * m / r["d"] > 0  # Tempo bleibt positiv
    assert memeclip._margin({"kind": "hit", "d": 0.5}) == 0.15


def test_printable_lyrics_and_wall_perspective():
    import glob

    from cstaktik import wall_text
    f = glob.glob(str(memeclip.Path(memeclip.__file__).parent / "static/fonts/*.ttf"))[0]
    assert memeclip.printable("mу", f) == "MY"  # kyrillisches y sieht aus wie ein lateinisches
    assert memeclip.printable("don’t​", f) == "DON'T"  # typografischer Apostroph, unsichtbares Zeichen
    assert memeclip.printable("(cannibal,", f) == "CANNIBAL," and memeclip.printable("up)", f) == "UP"  # keine Klammern
    assert memeclip.printable("go\U0001F600", f) == "GO"  # Zeichen ohne Glyph fällt weg statt Kästchen
    t, b = wall_text.limit_perspective(0.6, -0.4, 100, 20)
    hl, hr = 20 + (t - b) * 50, 20 - (t - b) * 50
    assert hl / hr <= wall_text.MAX_PERSP + 1e-6 and abs((t + b) / 2 - 0.1) < 1e-6


def test_hit_speeds_up_into_next_scene():
    box = (1100, 80, 1270, 105)
    bt = [round(0.1 + 0.5 * i, 3) for i in range(27)]
    pl = memeclip.plan_beat([{"t": 1.5, "box": box, "src": "a", "dur": 9.0}, {"t": 5.0, "box": box, "src": "a", "dur": 9.0}],
                            9.0, bt)
    h = [x for x in pl["segments"] if x["kind"] == "hit"]
    assert h[0].get("ramp_out") and not h[-1].get("ramp_out")  # der letzte Kill bleibt bis zum Ende langsam
    o1, o2, s = h[0]["out"] - h[0]["ramp_out"], h[0]["ramp_out"], h[0]["slow"]
    assert abs(h[0]["d"] - (o1 * s + o2 * (s + memeclip.OUT_V) / 2)) < 0.002  # Material passt genau zur Tempokurve
    assert "settb=1/60000" in memeclip.hit_pts(h[0], 0.5)  # feines Zeitraster: keine doppelten Zeitstempel


def test_drop_start_puts_drop_on_first_kill_beat(monkeypatch):
    from cstaktik import beats
    monkeypatch.setattr(beats, "beats", lambda *a, **k: {"beats": [0.0, 0.5, 1.0, 1.5, 2.0]})
    assert beats.drop_start("x.mp3", 12.0) == 10.75  # Drop auf Schlag-Index 2 (Schläge bei 0,25 / 0,75 / 1,25)
    monkeypatch.setattr(beats, "beats", lambda *a, **k: {"beats": [0.0, 0.3, 0.6, 0.9]})
    assert beats.drop_start("x.mp3", 12.0) == 10.95  # schnelles Tempo: Index 3
    assert "setsar=1" in memeclip.LOOK  # Vignette nie als schwarze Ellipse


def test_look_and_dedup_settings():
    assert memeclip.SAT > 1.2 and memeclip.GRADE in memeclip.LOOK  # Farbabstimmung nach Vorbild
    assert memeclip.INTERP == "none" and memeclip.DEDUP == ""  # nur echte Bilder: clean, keine Bildfehler
    assert not memeclip.KILL_FX and memeclip.SHOW_FEED and memeclip.HIT_SLOW >= 0.7  # wenig Edit beim Kill


def test_sync_report_and_sixteenths():
    bt = [0.0, 0.5, 1.0, 1.5, 2.0]
    r = memeclip.sync_report([0.26, 0.13, 0.69, 1.01], bt, 0.5)  # 0.26 Achtel, 0.13 Sechzehntel, 0.69 daneben (60 ms)
    assert r["total"] == 4 and r["on"] == 3 and r["worst_ms"] == 10
    # dichtes Feuer: Schuss 0,13 s vor dem Kill passt auf kein Achtel (0,25 s), aber auf ein Sechzehntel
    anc = memeclip.sync_anchors([2.87, 2.95], s0=1.0, ks=3.0, gap=1.5, half=0.25)
    assert any(abs((1.5 - y) / 0.125 - round((1.5 - y) / 0.125)) < 1e-6 for _, y in anc[1:-1])


def test_frame_grid_whole_frames_no_drift():
    pl = {"segments": [{"o0": 0.0, "out": 1.008}, {"o0": 1.008, "out": 0.504}, {"o0": 1.512, "out": 1.008}], "seconds": 2.52}
    memeclip.frame_grid(pl)
    for a, b in zip(pl["segments"], pl["segments"][1:]):
        assert abs(a["o0"] + a["out"] - b["o0"]) < 1e-6  # lückenlos
    assert all(abs(s["out"] * 60 - round(s["out"] * 60)) < 1e-3 for s in pl["segments"])  # ganze Bilder
    assert abs(pl["segments"][2]["o0"] - 1.512) <= 1 / 120 + 1e-6  # höchstens halbe Bilddauer verschoben


def test_render_workers_bounded():
    assert 1 <= memeclip.render_workers() <= 4


def test_kills_from_boxes_new_entry_while_old_expires():
    import numpy as np
    rng = np.random.default_rng(1)
    A = {"w": 150, "e": rng.standard_normal((12, 70)).astype(np.float32)}  # Kantenbild Gegnername A
    B = {"w": 226, "e": rng.standard_normal((12, 70)).astype(np.float32)}  # anderer Gegner B
    box = (1120, 80, 1270, 105)  # Breite 150 wie A
    fb, sg = [], []
    for i in range(160):  # 8 s bei 20 Bildern/s
        t = i / 20
        e = []
        if 1.0 <= t < 3.0 and not (2.0 <= t < 2.4):  # Eintrag A mit kurzem Aussetzer (Mündungsfeuer)
            e.append(A)
        if 3.0 <= t < 5.5:  # A verschwindet genau, als B kommt: Anzahl bleibt 1
            e.append(dict(B, w=226))
        fb.append([box if x is A else (1044, 80, 1270, 105) for x in e]); sg.append(e)
    k = memeclip.kills_from_boxes(fb, sg)
    assert [x[0] for x in k] == [1.0, 3.0]  # Aussetzer kein neuer Kill, B trotz gleicher Anzahl erkannt
    assert memeclip._same(A, dict(A, w=A["w"] + 10)) == 1.0 and memeclip._same(A, dict(B, w=150)) == 0.0


def test_kill_starts_at_kill_shot():
    assert memeclip.kill_start(4.15, [3.25, 3.52, 3.81]) == 3.73  # letzter Schuss vor dem Eintrag
    assert memeclip.kill_start(9.3, [8.1, 8.2, 12.0]) == 8.12  # Eintrag kam spät: trotzdem der Schuss
    assert memeclip.kill_start(4.15, []) == 3.8 and memeclip.kill_start(4.15, None) == 3.8  # ohne Schuss: 0,35 s davor
    assert memeclip.kill_start(9.3, [5.0]) == 8.95  # Schuss zu weit weg: nicht dieser


def test_plan_clean_fixed_rules():
    box = (1100, 80, 1270, 105)
    bt = [round(0.2 + 0.5 * i, 3) for i in range(40)]  # 120 BPM, erster Schlag bei 0,2 s
    kills = [{"t": 4.15, "box": box, "src": "a", "dur": 18.0}, {"t": 5.3, "box": box, "src": "a", "dur": 18.0},  # Doppel-Kill
             {"t": 10.1, "box": box, "src": "a", "dur": 18.0}, {"t": 3.0, "box": box, "src": "b", "dur": 9.0}]
    shots = {"a": [3.81, 5.10, 9.96], "b": [2.80]}
    pl = memeclip.plan_clean(kills, bt, shots)
    segs = pl["segments"]
    assert [s["kind"] for s in segs] == ["clip"] * 3 and pl["kills_used"] == 4
    assert len(segs[0]["kills"]) == 2  # Doppel-Kill bleibt ein durchgehendes Stück
    o = 0.0
    for s in segs:  # lückenlos, echtes Tempo, ganze Schläge
        assert abs(s["o0"] - o) < 1e-3 and s["d"] == s["out"] and abs(s["out"] / 0.5 - round(s["out"] / 0.5)) < 1e-3
        o += s["out"]
    a = [s for s in segs if s["src"] == "a"]
    assert a[1]["ss"] >= a[0]["ss"] + a[0]["out"] - 1e-3  # nie zurück, nichts doppelt
    for s in segs:  # erster Kill-Schuss auf einem Schlag (Video beginnt am ersten Schlag)
        assert abs(s["kills"][0]["shot"] / 0.5 - round(s["kills"][0]["shot"] / 0.5)) < 1e-3
        assert all(k["feed"] >= k["shot"] for k in s["kills"])  # Killfeed nie vor dem Schuss
    assert pl["music_shift"] == 0.2


def test_boxes_two_stacked_entries_share_a_line():
    import numpy as np
    fr = np.full((120, 400, 3), 30, np.int16)  # dunkler Killfeed-Hintergrund
    for y in (20, 42, 64):  # drei rote Linien: Eintrag 1 = 20..42, Eintrag 2 = 42..64 (gemeinsame Linie)
        fr[y:y + 2, 100:380] = (220, 30, 30)
    fr[28:36, 150:300:6] = (240, 240, 240)  # helle Schrift in beiden Einträgen
    fr[50:58, 150:300:6] = (240, 240, 240)
    b = memeclip._boxes(fr)
    assert [(x[1], x[3]) for x in b] == [(20, 43), (42, 65)]  # beide Einträge, nicht nur der obere
    fr2 = fr.copy(); fr2[50:58, 150:300:6] = (30, 30, 30)  # zwischen den Linien keine Schrift: kein Eintrag
    assert len(memeclip._boxes(fr2)) == 1


def test_lyric_schedule_one_word_at_a_time():
    items = [{"a": 1.0, "b": 1.3, "txt": "START", "eol": False, "stop": 1.4},
             {"a": 1.4, "b": 1.7, "txt": "LIVING", "eol": False, "stop": 2.0},
             {"a": 2.0, "b": 2.4, "txt": "DANGEROUSLY", "eol": True, "stop": 6.0},
             {"a": 6.0, "b": 6.3, "txt": "TALK", "eol": False, "stop": 6.5}]  # danach ein Wand-Wort ab 6,5
    s = memeclip.lyric_schedule(items, 8.0)
    assert [(x["a"], x["end"]) for x in s[:2]] == [(1.0, 1.4), (1.4, 2.0)]  # bleibt bis zum nächsten, keine Lücke
    assert s[2]["fade"] and abs(s[2]["end"] - 3.5) < 1e-6  # Zeilenende: länger stehen, dann ausblenden
    assert s[3]["end"] == 6.5  # endet, wenn das Wand-Wort beginnt: nie zwei Wörter gleichzeitig


def test_silent_mix_is_an_error_not_a_flat_line(tmp_path):
    import subprocess
    f = tmp_path / "still.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "aevalsrc=-0.08:d=2:s=48000", str(f)], check=True)
    import pytest
    with pytest.raises(ValueError, match="fast still"):
        memeclip.level_chain(str(f))
    g = tmp_path / "ton.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=2:sample_rate=48000", str(g)], check=True)
    assert memeclip.level_chain(str(g)).startswith("highpass=f=20,")


def test_mix_audio_python_not_silent(tmp_path):
    import subprocess
    import numpy as np
    seg = tmp_path / "s0.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=300:d=2:sample_rate=48000",
                    "-c:a", "aac", str(seg)], check=True)
    mus = tmp_path / "m.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=500:d=3:sample_rate=44100", str(mus)], check=True)
    out = tmp_path / "mix.wav"
    marks = [{"o0": 1.0, "kind": "hit", "out": 1.0}]
    memeclip.mix_audio([seg], [{"o0": 0.0, "out": 2.0}], str(mus), 0.0, 2.0, marks, [1.0], 0.5, [], out)
    a = memeclip._read_audio(str(out))
    assert abs(len(a) - 96000) < 100 and float(np.sqrt((a ** 2).mean())) > 0.05  # Ton da, richtige Länge
    assert abs(float(a.mean())) < 0.01  # kein Gleichspannungsversatz


def test_shift_words_and_form_value():
    assert memeclip.shift_words(["1.00-1.40:A", "0.10:B", "C"], -0.2) == ["0.80-1.20:A", "0.00:B", "C"]
    from cstaktik.api import _shift
    assert _shift("-0,3") == -0.3 and _shift("") == 0.0 and _shift("9") == 2.0 and _shift("x") == 0.0


def test_story_keep_all_words_until_first_kill_then_keywords():
    ws = [{"txt": t, "a": a, "b": a + 0.2, "sung": a + h, "next": a + 0.3, "eol": e}
          for t, a, h, e in [("I", 0.0, 0.1, False), ("can", 0.3, 0.1, False), ("feel", 0.6, 0.1, True),
                             ("and", 2.0, 0.1, False), ("the", 2.3, 0.1, False), ("thunder", 2.6, 0.1, False),
                             ("oh", 3.5, 0.6, False), ("is", 4.5, 0.1, False), ("loud", 4.8, 0.1, True)]]
    keep = memeclip.story_keep(ws, first_kill=1.5)
    assert {0, 1, 2} <= keep  # vor dem ersten Kill: jedes Wort
    assert 5 in keep and 6 in keep and 8 in keep  # Inhaltswort, gezogenes Wort, Zeilenende
    assert not {3, 4, 7} & keep  # Füllwörter fallen weg
    assert memeclip.story_keep(ws, None) == set(range(len(ws)))  # ohne Kill: alles


def test_sign_png_marks_front_face(tmp_path):
    from PIL import Image

    p = tmp_path / "s.png"
    memeclip.sign_png("TALK", p, str(memeclip.LYRIC_FONT))
    im = Image.open(p)
    x0, y0, x1, y1 = (float(v) for v in im.info["inner"].split(","))
    assert 0 < x0 < x1 < im.width and 0 < y0 < y1 < im.height
    px = im.convert("RGBA").getpixel((int((x0 + x1) / 2), int(y1) + 2))  # unter der Vorderseite: Tiefe oder Leuchten
    assert px[3] > 0


def test_align_lyrics_new_line_after_pause_sticks_to_next_word():
    typed = "when I say¶ let me take you dancing¶".split()
    sung = ["1.50-1.80:when", "1.80-1.95:i", "2.00-2.30:say", "5.30-5.90:dancing"]
    out = memeclip.align_lyrics(typed, sung, 10.0)
    t = {w.split(":", 1)[1]: float(w.split(":", 1)[0].split("-")[0]) for w in out}
    # "let me take you" nach der Pause direkt vor "dancing", nicht gleichmäßig in die Pause verteilt
    assert t["let"] > 4.0 and t["let"] < t["me"] < t["take"] < t["you"] < 5.3
    assert t["dancing¶"] == 5.3


def test_typed_words_keep_line_ends():
    from cstaktik import clips

    txt = clips.lyrics_text("hope you know  what I mean\r\n\nLet me take you dancing \n")
    assert txt == "hope you know what I mean\nLet me take you dancing"
    assert clips.typed_words(txt)[5] == "mean¶" and clips.typed_words(txt)[-1] == "dancing¶"


def test_story_drop_at_cut_where_bass_rises(tmp_path):
    """Drop am Schnitt, an dem der Bass einsetzt (Vorbilder: Text-Teil, dann Kills ohne Text)."""
    import subprocess

    m = tmp_path / "m.wav"
    # 20 s: bis 11 s leise Hi-Hats, ab 11 s Bass
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "aevalsrc='0.05*(random(0)*2-1)+gte(t,11)*0.8*sin(2*PI*55*t)':d=20:s=8000", str(m)], check=True)
    segs = [{"o0": x} for x in (0.0, 3.0, 7.0, 11.0, 14.0, 17.0)]
    assert memeclip.story_drop(str(m), 0.0, 20.0, segs) == 11.0
    assert memeclip.story_drop(str(m), 0.0, 8.0, segs) is None  # zu kurz
    flat = tmp_path / "f.wav"  # ohne Anstieg: Schnitt nahe 45 %
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "aevalsrc='0.3*sin(2*PI*55*t)':d=20:s=8000",
                    str(flat)], check=True)
    assert memeclip.story_drop(str(flat), 0.0, 20.0, segs) == 7.0


def test_lyrics_debug_compact():
    d = memeclip._lyrics_debug({"lrclib": ["-1.50:so", "0.50:hope", "0.90:you¶"]}, ["0.40-0.80:hope", "0.85-1.20:you¶"],
                               ["0.42-0.70:hope", "0.88-1.10:you"])
    assert d["gezeigt"] == ["0.40 hope", "0.85 you"] and d["erkannt"][0] == "0.42 hope" and d["lrclib"][:3] == ["-1.50 so", "0.50 hope", "0.90 you"]
    assert memeclip._lyrics_debug({}, [], None) is None
    assert memeclip._safe_debug(None, ["0.1-0.2:x"], None) is None  # kaputte Eingabe: nie ein Fehler


def test_text_plan_lines_first_then_emphasis():
    def w(t, a, eol=False, held=0.1):
        return {"txt": t, "a": a, "b": a + 0.3, "sung": a + held, "next": a + 0.3, "eol": eol}

    ws = [w("hope", 0.0), w("you", 0.3), w("know", 0.6, True),  # Zeile 1 vor dem ersten Kill: ganze Zeile
          w("let", 2.0), w("me", 2.3), w("take", 2.6), w("you", 2.9), w("dancing", 3.2, True, 0.8),  # betont: dancing
          w("two-step", 5.0), w("to", 5.4), w("the", 5.6), w("bedroom", 5.9, True, 0.5),
          w("after", 12.5), w("drop", 12.8, True)]
    lines, emph = memeclip.text_plan(ws, first_kill=1.5, t_drop=12.0)
    assert set(lines) == {0, 1, 2} and lines[1] == (["hope", "you", "know"], 1)
    best = {j for j, (g, r, need) in emph.items() if r == 0}
    assert best == {7, 11} and all(wd < 12 for wd in emph)  # je Zeile das betonte Wort zuerst, nichts nach dem Drop
    assert {g for g, _, _ in emph.values()} == {0, 1} and max(r for _, r, _ in emph.values()) >= 1  # Ersatz-Kandidaten
    assert not {ws[j]["txt"] for j in emph} & {"to", "the", "you", "me", "let"}  # Füllwörter nie betont
    lines2, _ = memeclip.text_plan(ws, first_kill=4.0, t_drop=12.0)
    assert set(lines2) == {0, 1, 2, 3, 4, 5, 6, 7}  # beide Zeilen beginnen vor dem Kill


def test_line_layout_and_frame_no_jump():
    f = str(memeclip.LYRIC_FONT)
    lay = memeclip._line_layout(["we", "don't", "need", "no", "dance", "floor"], f, 1080, 360)
    assert len({y for _, y, _ in lay["pos"]}) in (1, 2) and all(0 <= x and x < 1080 for x, _, _ in lay["pos"])
    a = memeclip._line_frame(lay, 1, 1.0, False, 1080, 360).getbbox()
    b = memeclip._line_frame(lay, 3, 1.0, False, 1080, 360).getbbox()
    assert a[0] == b[0] or a[1] == b[1]  # bereits stehende Wörter bewegen sich nicht


def test_split_walls_groups_pick_best_with_wall(tmp_path, monkeypatch):
    """Je Gruppe das beste Wort mit Wand; ohne Wand das beste flach; nie zwei Wörter gleichzeitig."""
    import subprocess

    from cstaktik import wall_text

    base = tmp_path / "b.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=108x192:r=10:d=6", str(base)],
                   check=True)
    lyr = {"out_w": 108, "out_h": 192, "box": 108, "box_y": 44, "box_x": 0, "y_mid": 60, "band": 36}
    monkeypatch.setattr(wall_text, "place_on_wall", lambda g, rgb, asp, full=None: {"quad": 1}
                        if WALLS.get(round(TIMES.pop(0), 1)) else None)
    WALLS = {1.5: True}  # nur das zweitbeste Wort der Gruppe 0 hat eine Wand
    TIMES = []
    orig = subprocess.run

    def run(cmd, **kw):  # Startzeit des geprüften Bilds mitschreiben
        if "-ss" in cmd:
            TIMES.append(float(cmd[cmd.index("-ss") + 1]) - 0.04)
        return orig(cmd, **kw)

    monkeypatch.setattr(subprocess, "run", run)

    def w(txt, a, g, r):
        return {"a": a, "b": a + 2.0, "txt": txt, "j": 0, "group": g, "rank": r, "need": 1, "eligible": True}

    walls = [w("DANCING", 1.0, 0, 0), w("TAKE", 1.5, 0, 1), w("LET", 2.0, 0, 2),
             w("BEDROOM", 4.0, 1, 0), w("STEP", 4.3, 1, 1)]
    keep, moved = memeclip.split_walls(str(base), walls, lyr)
    assert [x["txt"] for x in keep] == ["TAKE"]  # Gruppe 0: bestes Wort mit Wand
    assert [x["txt"] for x in moved] == ["BEDROOM"]  # Gruppe 1: keine Wand, bestes flach
    assert keep[0]["b"] <= 4.0  # endet, wenn das nächste Wort kommt
