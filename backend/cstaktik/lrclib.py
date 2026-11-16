"""Songtext mit Zeitstempeln von LRCLIB (lrclib.net, frei, ohne Konto) für den Clip-Generator.

Ablauf: Songname + Künstler suchen -> Zeilen mit Startzeit ("[mm:ss.xx] Text") -> Wörter je Zeile gleichmäßig
verteilen -> herausfinden, welche Stelle des Songs die hochgeladene Musik ist -> Wörter mit Zeiten im Video.

Welche Stelle: Ist die Musikdatei so lang wie der Song (± 4 s), ist es der ganze Song (Versatz 0). Sonst wird der
Versatz aus der Spracherkennung bestimmt: Ein paar richtig erkannte Wörter reichen, ihr Zeitunterschied zum
Songtext ergibt die Stelle (Median, mindestens 3 übereinstimmende Wörter).

Gesendet wird nur der eingegebene Songname, sonst nichts.
"""

from __future__ import annotations

import difflib
import json
import re
import urllib.parse
import urllib.request

API = "https://lrclib.net/api/search"
UA = "cstaktik-clips/1.0"
FULL_SONG_TOL = 4.0  # Musikdatei höchstens so viel kürzer/länger als der Song: gilt als ganzer Song
MIN_MATCH = 3


def _norm(w: str) -> str:
    return re.sub(r"[^0-9a-zäöüß]", "", w.lower())


def parse_lrc(text: str) -> list[tuple[float, str]]:
    """LRC-Zeilen "[mm:ss.xx] Text" -> [(Sekunde, Text)], leere Zeilen weg, nach Zeit sortiert."""
    out = []
    for line in (text or "").splitlines():
        stamps = re.findall(r"\[(\d+):(\d+(?:\.\d+)?)\]", line)
        words = re.sub(r"\[[^\]]*\]", "", line).strip()
        if not words:
            continue
        for mm, ss in stamps:
            out.append((int(mm) * 60 + float(ss), words))
    return sorted(out)


def timed_words(lines: list[tuple[float, str]], per_word: float = 0.42) -> list[tuple[float, float, str]]:
    """Wörter mit (Start, Ende): je Zeile gleichmäßig von der Startzeit bis zur nächsten Zeile verteilt, höchstens
    ``per_word`` Sekunden je Wort (danach Pause bis zur nächsten Zeile)."""
    out = []
    for i, (t, txt) in enumerate(lines):
        ws = txt.split()
        nxt = lines[i + 1][0] if i + 1 < len(lines) else t + per_word * len(ws) + 0.5
        span = max(min(nxt - t, per_word * len(ws) + 0.3), 0.2 * len(ws))
        step = span / len(ws)
        for k, w in enumerate(ws):
            out.append((round(t + k * step, 3), round(t + (k + 1) * step, 3), w))
    return out


def fetch(query: str, music_dur: float | None = None, timeout: float = 8.0) -> dict | None:
    """Suche bei LRCLIB. Rückgabe {"track", "artist", "duration", "lines"} oder None (nichts gefunden / kein Netz).
    Bei mehreren Treffern mit Zeitstempeln: der, dessen Länge am besten zur Musikdatei passt."""
    q = " ".join((query or "").split())[:120]
    if not q:
        return None
    req = urllib.request.Request(f"{API}?{urllib.parse.urlencode({'q': q})}", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - kein Netz, Zeitüberschreitung, kaputte Antwort: ohne Songtext weiter
        return None
    return pick(data, music_dur)


def pick(data, music_dur: float | None = None) -> dict | None:
    hits = [x for x in (data or []) if isinstance(x, dict) and x.get("syncedLyrics")]
    if not hits:
        return None
    if music_dur:  # passt die Länge zum ganzen Song, diesen nehmen; sonst den ersten Treffer (beste Suche)
        full = [x for x in hits if x.get("duration") and abs(x["duration"] - music_dur) <= FULL_SONG_TOL]
        if full:
            hits = full
    x = hits[0]
    lines = parse_lrc(x["syncedLyrics"])
    if not lines:
        return None
    return {"track": x.get("trackName") or "", "artist": x.get("artistName") or "",
            "duration": x.get("duration"), "lines": lines}


def locate(words: list[tuple[float, float, str]], sung: list[str] | None, file_dur: float,
           song_dur: float | None, sung_at: float = 0.0) -> tuple[float | None, str]:
    """Versatz = Songzeit an Sekunde 0 der Musikdatei. ``sung``: erkannte Wörter "a-e:WORT" mit Zeiten ab
    ``sung_at`` Sekunden in der Datei. Rückgabe (Versatz oder None, Begründung)."""
    if song_dur and abs(file_dur - song_dur) <= FULL_SONG_TOL:
        return 0.0, "ganzer Song"
    if not sung:
        return None, "Ausschnitt eines Songs, ohne Spracherkennung lässt sich die Stelle nicht finden"
    rec = []
    for w in sung:
        tm, txt = w.split(":", 1)
        rec.append((float(tm.split("-")[0]) + sung_at, _norm(txt)))
    sm = difflib.SequenceMatcher(a=[_norm(w[2]) for w in words], b=[r[1] for r in rec], autojunk=False)
    diffs = [words[b.a + k][0] - rec[b.b + k][0] for b in sm.get_matching_blocks() for k in range(b.size)
             if len(words[b.a + k][2]) > 1]
    if len(diffs) < MIN_MATCH:
        return None, f"nur {len(diffs)} Wörter passten zum Songtext, zu wenig für die Stelle"
    diffs.sort()
    med = diffs[len(diffs) // 2]
    near = [d for d in diffs if abs(d - med) <= 1.0]
    if len(near) < MIN_MATCH:
        return None, "erkannte Wörter passen an verschiedene Stellen, Stelle unsicher"
    return round(sum(near) / len(near), 2), f"Stelle über {len(near)} erkannte Wörter gefunden"


def clip_words(words: list[tuple[float, float, str]], offset: float, music_ss: float, total: float) -> list[str]:
    """Wörter im Video als "a-e:WORT" (Sekunden ab Videostart)."""
    out = []
    for a, e, w in words:
        va, ve = a - offset - music_ss, e - offset - music_ss
        if 0 <= va < total:
            out.append(f"{va:.2f}-{min(ve, total):.2f}:{w}")
    return out
