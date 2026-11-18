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
    assert len(got) == len(want)
    err = sorted(abs(g - t) for g, t in zip(got, want))
    assert err[len(err) // 2] < 0.05 and err[-1] < 0.6  # ein nicht erkanntes Wort direkt an der Schnittkante: 0,57 s
    assert not [g for g in got if 6.0 < g < 18.0]  # in der Pause ohne Gesang steht kein Text
