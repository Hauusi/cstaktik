"""LRCLIB-Songtext: Zeilen lesen, Wörter verteilen, Stelle im Song finden, Wörter im Video. Ohne Netz."""
from cstaktik import lrclib

LRC = """[00:10.00] I'm your biggest fan
[00:12.50] I'll follow you until you love me
[00:16.00] Papa paparazzi
[00:18.00]
[00:20.00] Baby there's no other superstar"""


def test_parse_and_timed_words():
    lines = lrclib.parse_lrc(LRC)
    assert [t for t, _ in lines] == [10.0, 12.5, 16.0, 20.0]  # leere Zeile weg
    tw = lrclib.timed_words(lines)
    assert tw[0][2] == "I'm" and tw[0][0] == 10.0 and all(10.0 <= a < 12.5 for a, _, w in tw[:4])
    assert [w.rstrip(lrclib.EOL) for _, _, w in tw[4:11]] == "I'll follow you until you love me".split()
    assert tw[10][2].endswith(lrclib.EOL) and not tw[9][2].endswith(lrclib.EOL)  # Zeilenende markiert


def test_pick_prefers_synced_and_matching_length():
    data = [{"trackName": "A", "syncedLyrics": None, "duration": 200},
            {"trackName": "B", "artistName": "X", "syncedLyrics": LRC, "duration": 150},
            {"trackName": "C", "artistName": "Y", "syncedLyrics": LRC, "duration": 208}]
    assert lrclib.pick(data, 207.0)["track"] == "C"  # Länge passt zur Musikdatei
    assert lrclib.pick(data, 60.0)["track"] == "B"   # Ausschnitt: erster Treffer mit Zeitstempeln
    assert lrclib.pick([], 60.0) is None


def test_locate_full_song_and_snippet():
    tw = lrclib.timed_words(lrclib.parse_lrc(LRC))
    assert lrclib.locate(tw, None, 207.0, 208.0)[0] == 0.0  # ganzer Song
    assert lrclib.locate(tw, None, 15.0, 208.0)[0] is None  # Ausschnitt ohne Erkennung: unbekannt
    # Ausschnitt ab Song-Sekunde 9: Erkennung (Zeiten ab Ausschnitt) mit Fehlern, aber genug Treffer
    sung = [f"{a - 9.0:.2f}-{e - 9.0:.2f}:{w}" for a, e, w in tw if w not in ("you", "me")]
    sung[2] = "1.6-1.9:biggist"  # falsch verstanden
    off, why = lrclib.locate(tw, sung, 15.0, 208.0)
    assert abs(off - 9.0) < 0.05, why
    words = lrclib.clip_words(tw, off, 0.0, 12.0)
    assert words[0].endswith(":I'm") and float(words[0].split("-")[0]) == 1.0  # erstes Wort 1 s nach Start


def test_fetch_without_network_returns_none(monkeypatch):
    def boom(*a, **k):
        raise OSError("kein Netz")
    monkeypatch.setattr(lrclib.urllib.request, "urlopen", boom)
    assert lrclib.fetch("Paparazzi Lady Gaga") is None
    assert lrclib.fetch("") is None


def test_suggestions_only_synced_with_images():
    lrc = [{"trackName": "Paparazzi", "artistName": "Lady Gaga", "albumName": "The Fame", "duration": 208,
            "syncedLyrics": "[00:01.00] x"},
           {"trackName": "Paparazzi", "artistName": "Lady Gaga", "duration": 208, "syncedLyrics": "[00:01.00] x"},  # doppelt
           {"trackName": "Paparazzi (Live)", "artistName": "Lady Gaga", "duration": 300, "syncedLyrics": None},  # ohne Zeiten
           {"trackName": "Other", "artistName": "Unknown Band", "duration": 61, "syncedLyrics": "[00:01.00] y"}]
    dz = {"data": [{"title": "Paparazzi", "artist": {"name": "Lady Gaga", "picture_medium": "https://img/gaga.jpg"},
                    "album": {"cover_medium": "https://img/fame.jpg"}},
                   {"title": "Evil", "artist": {"name": "Hacker", "picture_medium": "javascript:alert(1)"}}]}
    s = lrclib.suggestions(lrc, dz)
    assert [(x["track"], x["artist"]) for x in s] == [("Paparazzi", "Lady Gaga"), ("Other", "Unknown Band")]
    assert s[0]["image"] == "https://img/gaga.jpg" and s[0]["duration"] == "3:28" and s[1]["image"] == ""
    assert lrclib.suggestions(None, None) == [] and lrclib.suggest("ab") == []  # zu kurz: keine Anfrage


def test_song_suggest_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    from cstaktik import accounts, api
    monkeypatch.setattr(lrclib, "suggest_full", lambda q: {"items": [{"track": "T", "artist": "A", "album": "", "duration": "", "image": ""}], "error": None})
    accounts.add_user("Hausi", "Geheim-12345")
    c = TestClient(api.app)
    c.post("/login", data={"name": "Hausi", "password": "Geheim-12345"}, headers={"Origin": "http://testserver"})
    r = c.get("/clips/song-suggest?q=Paparazzi")
    assert r.status_code == 200 and r.json()["items"][0]["track"] == "T"



def test_suggest_reports_network_error(monkeypatch):
    def boom(*a, **k):
        raise TimeoutError("timed out")
    monkeypatch.setattr(lrclib.urllib.request, "urlopen", boom)
    lrclib._CACHE.clear()
    r = lrclib.suggest_full("Paparazzi Lady Gaga")
    assert r["items"] == [] and "LRCLIB nicht erreichbar" in r["error"] and "TimeoutError" in r["error"]
    assert "paparazzi lady gaga" not in lrclib._CACHE  # Fehler nicht zwischenspeichern


def test_suggestions_clean_messy_uploads():
    syn = "[00:01.00] x"
    lrc = [{"trackName": "Lady Gaga - Bad Romance", "artistName": "Lady Gaga", "albumName": "Lady Gaga", "duration": 292, "syncedLyrics": syn},
           {"trackName": "Poker Face Lady GaGa", "artistName": "Lady Gaga", "albumName": "Lady Gaga", "duration": 221, "syncedLyrics": syn},
           {"trackName": "Bad Romance", "artistName": "Lady Gaga", "albumName": "The Fame Monster", "duration": 294, "syncedLyrics": syn},
           {"trackName": "Lady Gaga - Judas", "artistName": "Lady Gaga", "albumName": "Lady Gaga - Judas", "duration": 335, "syncedLyrics": syn}]
    s = lrclib.suggestions(lrc, None)
    assert [x["track"] for x in s] == ["Bad Romance", "Poker Face", "Judas"]  # aufgeräumt, doppelte weg, Album zuerst
    assert s[0]["album"] == "The Fame Monster" and s[1]["album"] == ""  # Künstler als Album nicht anzeigen
    assert lrclib.clean_title("Paparazzi", "Lady Gaga") == "Paparazzi"


def test_refine_word_times_with_recognition():
    # LRC verteilt gleichmäßig; gesungen werden die ersten Wörter schneller, "superstar" kommt früher
    words = ["1.00-1.40:baby", "1.40-1.80:there's", "1.80-2.20:no", "2.20-2.60:other", "2.60-3.00:superstar"]
    sung = ["1.05-1.20:baby", "1.25-1.40:theres", "1.70-1.90:other", "2.00-2.90:superstar"]  # "no" nicht erkannt
    out, n = lrclib.refine(words, sung)
    t = [float(w.split("-")[0]) for w in out]
    assert n == 4 and [w.split(":", 1)[1] for w in out] == ["baby", "there's", "no", "other", "superstar"]
    assert abs(t[0] - 1.05) < 0.01 and abs(t[4] - 2.0) < 0.01 and t[1] < t[2] < t[3]  # Reihenfolge bleibt
    assert lrclib.refine(words, None) == (words, 0)
    far = ["5.00-5.20:baby"]  # mehr als 1 s daneben: nicht übernehmen
    assert lrclib.refine(words, far)[1] == 0


def test_wall_word_stays_in_one_scene():
    from cstaktik import memeclip
    assert memeclip.one_scene(1.0, 3.0, [1.4]) == (1.4, 3.0)  # längeres Stück nach dem Schnitt
    assert memeclip.one_scene(1.0, 3.0, [2.5]) == (1.0, 2.5)
    assert memeclip.one_scene(1.0, 3.0, []) == (1.0, 3.0)


def test_clip_words_keeps_word_started_just_before_video():
    tw = [(9.95, 10.3, "I'm"), (10.3, 10.6, "your"), (8.0, 8.3, "old")]
    w = lrclib.clip_words(tw, 0.0, 10.0, 5.0)
    assert w[0].startswith("0.00-") and w[0].endswith(":I'm") and len(w) == 2  # ab 0 statt weg; 2 s davor: weg


def test_hyphen_words_split_and_timed_by_syllables():
    tw = lrclib.timed_words(lrclib.parse_lrc("[00:10.00] Papa-paparazzi\n[00:13.00] next"))
    words = [w.rstrip(lrclib.EOL) for _, _, w in tw]
    assert words[:2] == ["Papa", "paparazzi"]  # getrennt: "paparazzi" kommt erst, wenn es gesungen wird
    (a1, e1, _), (a2, e2, _) = tw[0], tw[1]
    assert a1 == 10.0 and abs(e1 - a2) < 1e-6 and (e2 - a2) > 1.5 * (e1 - a1)  # 4 Silben brauchen länger als 2
    assert lrclib.split_sung("don't stop-and-go") == ["don't", "stop", "and", "go"]


def test_refine_fuzzy_matches_misheard_words():
    words = ["1.00-1.40:Papa", "1.40-2.20:paparazzi", "2.40-2.80:baby", "2.80-3.20:there's", "3.20-3.60:no"]
    sung = ["1.20-1.50:papa", "1.70-2.60:paparazi", "2.90-3.20:babe", "3.25-3.50:theres", "3.70-3.90:know"]
    out, n = lrclib.refine(words, sung)
    t = [float(w.split("-")[0]) for w in out]
    assert n >= 4  # falsch erkannte "paparazi", "babe" (ähnlich genug) zählen jetzt mit
    assert abs(t[1] - 1.70) < 0.01 and abs(t[2] - 2.90) < 0.01
    assert out[1].split(":")[0].endswith("2.60")  # Ende aus dem Gesang: Tipp-Tempo passt
    assert lrclib.fuzzy_align([(1.0, "papa")], [(5.0, "papa")], 1.5) == {}  # zu weit weg


DERULO = [(10.0, "So you know what I mean when I say"), (14.0, "Let me take you dancing"),
          (16.5, "Two-step to the bedroom"), (40.0, "Let me take you dancing"), (42.0, "Two-step to the bedroom"),
          (60.0, "Hope you know what I mean when I say"), (64.0, "Let me take you dancing")]


def test_find_passage_pasted_text_start():
    t = lrclib.find_passage(DERULO, "hope you know what I mean when I say\nLet me take you dancing")
    assert t == 60.0  # die Stelle mit "hope", nicht die frühere mit "so you know"
    assert lrclib.find_passage(DERULO, "Let me take you dancing") == 14.0  # erste von mehreren gleichen Stellen
    assert lrclib.find_passage(DERULO, "völlig anderer text hier drin") is None


def test_hook_and_music_start():
    assert lrclib.hook_start(DERULO) == 14.0  # 3x "let me take you dancing"
    assert lrclib.music_start(DERULO, "") == (14.0 - lrclib.LEAD_S, "Hook (am häufigsten wiederholte Zeile)")
    t, why = lrclib.music_start(DERULO, "two-step to the bedroom")
    assert t == 16.5 - lrclib.LEAD_S and "Stelle" in why
    assert lrclib.music_start([(1.0, "nur eine zeile hier")], "")[0] is None


def test_align_local_file_cut_differently_than_lrclib():
    """Datei anders geschnitten als die LRCLIB-Version: Abschnitt A liegt 24 s früher als im Songtext, Abschnitt B
    nur 11 s (in der Datei ist zwischen A und B eine Pause länger). Eine Verschiebung für alles (die von B) liess A
    vor dem Videostart verschwinden (Nutzer: Gesang ab Sekunde 2, Text erst ab 15)."""
    lines = [(40.0, "I wanted you to know"), (43.0, "that I am ready for the night"), (46.5, "never gonna leave you"),
             (49.0, "you are my heartbeat tonight"),
             (55.0, "running through the city lights"), (58.0, "calling out your name again"),
             (61.0, "we can make it if we try"), (64.0, "hold me closer through the fire")]
    tw = lrclib.timed_words(lines)
    music_ss = 14.0
    sung = []
    for k, (a, e, w) in enumerate(tw):
        off = 24.0 if a < 52 else 11.0
        va, ve = a - off - music_ss, e - off - music_ss
        if k % 4 == 3:
            continue  # nicht erkannt
        txt = w.rstrip(lrclib.EOL)
        if k % 7 == 2:
            txt = txt + "e"  # leicht falsch erkannt
        sung.append(f"{va:.2f}-{ve:.2f}:{txt}")
    words, n = lrclib.align_local(tw, 11.0, music_ss, 36.0, sung)  # Schätzung passt nur zu Abschnitt B
    t = {w.split(":", 1)[1].rstrip(lrclib.EOL).lower(): float(w.split(":", 1)[0].split("-")[0]) for w in words}
    assert n >= 10
    assert abs(t["wanted"] - (tw[1][0] - 24 - music_ss)) < 0.3  # Abschnitt A: ab etwa Sekunde 2 da
    assert abs(t["running"] - (55.0 - 11 - music_ss)) < 0.3  # Abschnitt B stimmt weiter
    assert all(0 <= float(w.split("-")[0]) < 36 for w in words)


def test_align_local_chorus_repeats_stay_in_sync():
    """Refrain wiederholt dieselben Wörter alle 4 s; in der Datei liegt ab Songzeit 116 alles 13 s später (dort eine
    Pause ohne Gesang). Jedes Wort muss bei seinem Gesang bleiben, in der Pause darf kein Text stehen."""
    lines = []
    for k in range(8):
        lines.append((100.0 + 4 * k, "heartbeat heartbeat"))
        lines.append((102.0 + 4 * k, "I wanted you to know"))
    tw = lrclib.timed_words(lines)
    music_ss = 110.0
    truth, sung = {}, []
    for k, (a, e, w) in enumerate(tw):
        off = 0.0 if a < 116 else -13.0  # ab Songzeit 116 liegt alles 13 s später in der Datei
        va, ve = a - off - music_ss, e - off - music_ss
        truth[k] = va
        if k % 5 != 4 and va >= 0:
            sung.append(f"{va:.2f}-{ve:.2f}:{w.rstrip(lrclib.EOL)}")
    sung.sort(key=lambda x: float(x.split("-")[0]))
    words, n = lrclib.align_local(tw, 0.0, music_ss, 30.0, sung)
    got = [float(w.split("-")[0]) for w in words]
    want = sorted(v for v in truth.values() if 0 <= v < 30)
    assert abs(len(got) - len(want)) <= 3  # an den Rändern der Pause sind ein paar Wörter unsicher
    err = sorted(min(abs(g - t) for t in want) for g in got)
    assert err[len(err) // 2] < 0.05  # jedes Wort liegt bei einem gesungenen Wort
    assert not [g for g in got if 7.5 < g < 17.0]  # mitten in der Pause ohne Gesang steht kein Text


def test_align_local_keeps_text_when_recognition_stops():
    """Spracherkennung erkennt nur die ersten 3 s (danach laute Musik): der Text muss trotzdem bis zum Ende laufen,
    mit der Verschiebung der letzten erkannten Wörter (Nutzer: nach 3 s gar kein Text mehr)."""
    lines = [(110.0 + 2 * k, f"line number {k} goes here") for k in range(14)]
    tw = lrclib.timed_words(lines)
    sung = [f"{a - 110 + 0.4:.2f}-{e - 110 + 0.4:.2f}:{w.rstrip(lrclib.EOL)}" for a, e, w in tw if a < 113]
    words, n = lrclib.align_local(tw, 0.0, 110.0, 28.0, sung)
    starts = [float(w.split("-")[0]) for w in words]
    assert n >= 3 and max(starts) > 25  # Text bis zum Ende
    late = [float(w.split("-")[0]) for w in words if w.endswith(":line")]
    assert all(abs(t - (round(t - 0.4) + 0.4)) < 0.05 for t in late)  # Verschiebung 0,4 s überall


# Echte Daten aus einem Nutzer-Clip ("Cannibal", Diagnose-Anzeige): was die Spracherkennung hörte und was LRCLIB sagt
CANNIBAL_REC = "0.00 you · 0.92 better · 1.44 run · 2.56 I · 3.62 am · 5.50 cannibal · 7.06 I · 9.24 am · 9.76 cannibal · 14.46 I · 15.66 am · 15.78 cannibal · 15.78 I'll · 15.78 eat · 16.08 you · 16.44 up · 16.92 I · 18.44 am · 19.62 cannibal · 21.98 I · 23.94 am · 24.54 cannibal · 28.12 Can · 28.64 you · 29.04 buy · 29.36 me · 29.84 a · 29.98 book · 30.32 Oh · 30.76 you · 30.82 should · 31.18 read · 31.60 me · 31.86 Whenever · 32.26 you · 32.70 tell · 32.94 me · 33.20 I'm · 33.44 pretty · 33.74 That's · 34.22 when · 34.32 the · 34.40 hunger · 34.70 really · 35.22 hits · 35.48 me · 35.72 Your · 35.96 little · 36.22 heart · 36.44 goes · 36.64 pitter · 37.08 -patter · 37.60 I · 37.80 want · 37.98 your · 38.10 liver · 38.38 on · 38.84 a · 39.00 pla · 39.16 -"
CANNIBAL_LRC = "-1.69 I · -1.44 eat · -1.20 boys · -0.95 up, · -0.70 you · -0.45 better · 0.04 run · 2.09 I · 2.32 am · 2.56 cannibal · 3.26 (cannibal, · 3.96 cannibal, · 4.65 I · 4.89 am) · 9.51 I · 9.76 am · 10.01 cannibal · 10.75 (cannibal) · 14.90 (I'll · 15.16 eat · 15.42 you · 15.68 up) · 15.94 I · 16.20 am · 16.87 I · 17.10 am · 17.34 cannibal · 18.04 (cannibal, · 18.73 cannibal, · 19.43 I · 19.67 am) · 24.25 I · 24.50 am · 24.75 cannibal · 25.49 (cannibal) · 29.70 (I'll · 29.98 eat · 30.27 you · 30.56 up) · 31.60 Whenever · 32.18 you · 32.37 tell · 32.57 me · 32.76 I'm · 32.95 pretty · 33.34 That's · 33.56 when · 33.78 the · 34.00 hunger · 34.43 really · 34.87 hits · 35.09 me · 35.31 You're · 35.64 little · 35.97 heart · 36.14 goes · 36.31 pitter · 36.64 patter · 36.97 I · 37.20 want · 37.42 your · 37.65 liver · 38.10 on · 38.32 a · 38.55 platter · 39.00 Use · 39.40 your · 39.59 finger · 39.99 to · 40.19 stir · 40.38 my · 40.58 tea · 40.78 And · 41.01 for"


def _cannibal():
    def parse(s):
        return [(float(x.split(" ", 1)[0]), x.split(" ", 1)[1]) for x in s.split(" · ")]

    lrc, rec = parse(CANNIBAL_LRC), parse(CANNIBAL_REC)
    tw = []
    for k, (a, w) in enumerate(lrc):
        nxt = lrc[k + 1][0] if k + 1 < len(lrc) else a + 1
        tw.append((a, a + 0.2, w + (lrclib.EOL if nxt - a > 0.6 or w in ("pretty", "patter", "platter") else "")))
    sung = [f"{t:.2f}-{max(min(rec[k + 1][0] if k + 1 < len(rec) else t + 0.3, t + 0.6), t + 0.05):.2f}:{w}"
            for k, (t, w) in enumerate(rec)]
    words, n = lrclib.align_local(tw, 0.0, 0.0, 39.3, sung)
    return [(float(w.split("-")[0]), w.split(":", 1)[1].rstrip(lrclib.EOL)) for w in words], n


def test_align_local_real_user_data_cannibal():
    """Nutzer: Anfang passt, dann daneben. LRCLIB liegt je Zeile etwas anders daneben (+1,4 s am Anfang, +0,3 s bei
    32 s), die Server-Erkennung hört einzelne Wörter im Refrain falsch, setzt bei 15,78 s vier Wörter auf dieselbe
    Zeit, bei 28-31 s wird anderer Text gesungen."""
    out, n = _cannibal()
    t = {}
    for a, w in out:
        t.setdefault(w, []).append(a)
    assert n >= 20
    # Anfang: vom Nutzer bestätigt ("die ersten 3 Wörter sind genau richtig")
    assert t["you"][0] == 0.0 and t["better"][0] == 0.92 and t["run"][0] == 1.44
    assert "boys" not in t  # vor dem Videostart gesungen
    # 2. Refrain: unabhängige Erkennung (sherpa-onnx) am Nutzer-Ausschnitt hört "cannibal" bei ca. 11,4 s, LRCLIB+1,4 s
    # sagt 11,41; die Server-Erkennung hörte 9,76 (falsch, Text kam zu früh, Nutzer: "kommen viel zu früh")
    assert any(abs(a - 11.4) < 0.5 for a in t["cannibal"]) and not any(9.0 < a < 10.5 for a in t["cannibal"])
    assert t["Can"] == [28.12] and t["book"] == [29.98] and t["read"] == [31.18]  # gesungener Text statt LRCLIB
    assert t["Whenever"] == [31.86]
    times = [a for a, _ in out]
    assert all(b > a for a, b in zip(times, times[1:]))  # Reihenfolge, nie zwei Wörter gleichzeitig


CANNIBAL_REC_SEPARATED = ("0.00 you · 0.94 better · 1.44 run · 2.08 I · 3.34 am · 5.64 cannibal · 7.18 cannibal · 8.72 I · "
                          "9.26 am · 9.88 I · 10.68 am · 12.30 cannibal · 15.00 I'll · 15.78 eat · 16.08 you · 16.46 up · "
                          "16.92 I · 18.22 am · 20.04 cannibal · 22.12 cannibal · 23.54 I · 24.10 am · 24.72 I · 25.96 am · "
                          "27.36 cannibal · 29.32 cannibal")


def test_align_local_real_user_data_separated_vocals():
    """Zweiter Nutzer-Clip (Whisper auf getrennter Stimme): bestätigter Anfang bleibt; zusätzlich gehörtes "I am I am"
    (8,7-10,7 s) darf nicht als eigener Text erscheinen. "I'll" (0,5 s zu früh erkannt) korrigiert erst das Forced
    Alignment (forced.py), siehe test_forced."""
    global CANNIBAL_REC
    old = CANNIBAL_REC
    CANNIBAL_REC = CANNIBAL_REC_SEPARATED
    try:
        out, n = _cannibal()
    finally:
        CANNIBAL_REC = old
    t = {}
    for a, w in out:
        t.setdefault(w, []).append(a)
    assert t["you"][0] == 0.0 and t["better"][0] == 0.94 and t["run"][0] == 1.44  # vom Nutzer bestätigter Anfang
    assert "boys" not in t
    assert not [a for a, w in out if 8.0 < a < 10.3]


def test_align_local_collapsed_pair_keeps_last_and_no_early_word():
    """Nutzer-Clip: Whisper setzte "better" und "run" beide auf 0,80 s; vorher wurden beide verworfen, die erste Zeile
    rutschte 2 s nach hinten und ein "cannibal" aus der Zeile vor dem Videostart stand bei 0,00."""
    E = lrclib.EOL
    tw = [(-4.60, -4.40, "I"), (-4.37, -4.17, "am"), (-4.13, -3.93, "cannibal" + E),
          (-2.37, -2.17, "I"), (-2.12, -1.92, "eat"), (-2.00, -1.88, "boys"), (-1.87, -1.67, "up,"),
          (-1.62, -1.42, "you"), (-1.37, -1.17, "better"), (-0.88, -0.68, "run" + E),
          (1.17, 1.37, "I"), (1.40, 1.60, "am"), (1.64, 1.84, "cannibal" + E)]
    sung = ["0.00-0.30:You", "0.80-1.10:better", "0.80-1.10:run", "1.60-1.90:I", "3.26-3.56:am", "5.38-5.70:cannibal"]
    words, n = lrclib.align_local(tw, 0.0, 0.0, 10.0, sung)
    t = {w.split(":", 1)[1].rstrip(E): float(w.split("-")[0]) for w in words}
    assert t["you"] == 0.0 and t["run"] == 0.80 and t["better"] < t["run"]
    assert min(float(w.split("-")[0]) for w in words if "cannibal" in w) > 1.0  # kein "cannibal" am Anfang


def test_hook_ignores_filler_lines():
    """Nutzer-Song "Cannibal": "Oh, oh, whoa, oh, whoa" kommt 8x hintereinander, der Refrain "I am cannibal" seltener."""
    lines = [(10.0, "I am cannibal"), (12.0, "(Cannibal, cannibal, I am)"), (30.0, "I am cannibal")]
    lines += [(120.0 + 4 * k, "Oh, oh, whoa, oh, whoa") for k in range(8)]
    lines += [(160.0, "I am cannibal"), (162.0, "(Cannibal, cannibal, I am)")]
    assert lrclib.hook_start(lines) == 10.0
