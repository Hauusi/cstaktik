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
    assert [w for _, _, w in tw[4:11]] == "I'll follow you until you love me".split()


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
