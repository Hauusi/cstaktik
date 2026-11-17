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


DEEZER = "https://api.deezer.com/search"
_CACHE: dict[str, tuple[float, list[dict]]] = {}
CACHE_S = 600


def _get_json(url: str, timeout: float = 6.0, errors: list | None = None, name: str = ""):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001 - kein Netz / Zeitüberschreitung: keine Vorschläge, Grund merken
        if errors is not None:
            errors.append(f"{name} nicht erreichbar: {type(e).__name__}: {str(e)[:120]}")
        return None


def suggestions(lrc_data, deezer_data, limit: int = 5) -> list[dict]:
    """Vorschläge für das Songname-Feld: nur Songs, für die LRCLIB Text MIT Zeitstempeln hat (nur die funktionieren),
    doppelte (gleicher Titel + Künstler) weg. Bild: Künstlerfoto von Deezer, sonst Albumcover, sonst keins."""
    pics: dict[str, str] = {}
    covers: dict[tuple[str, str], str] = {}
    for x in (deezer_data or {}).get("data", []) if isinstance(deezer_data, dict) else []:
        art = x.get("artist") or {}
        a = _norm(art.get("name") or "")
        if a and art.get("picture_medium") and a not in pics:
            pics[a] = art["picture_medium"]
        alb = x.get("album") or {}
        if alb.get("cover_medium"):
            covers.setdefault((a, _norm(x.get("title") or "")), alb["cover_medium"])
    cands = []
    for pos, x in enumerate(lrc_data or []):
        if not isinstance(x, dict) or not x.get("syncedLyrics"):
            continue
        raw, artist = (x.get("trackName") or "").strip(), (x.get("artistName") or "").strip()
        track = clean_title(raw, artist)
        if not track:
            continue
        album = (x.get("albumName") or "").strip()
        # sauber gepflegte Einträge zuerst: echter Albumname (nicht der Künstler, nicht "Künstler - Titel") und der
        # Titel kam ohne Künstlernamen an (Nutzer-Uploads heißen oft "Lady Gaga - Bad Romance")
        score = (2 if album and _norm(album) not in (_norm(artist), _norm(raw)) and _norm(artist) not in _norm(album)
                 else 0) + (1 if track == raw else 0)
        cands.append((-score, pos, track, artist, album, x))
    cands.sort(key=lambda c: (c[0], c[1]))
    out, seen = [], set()
    for _, _, track, artist, album, x in cands:
        key = (_norm(track), _norm(artist))
        if key in seen:
            continue
        seen.add(key)
        main = _norm(re.split(r",|&| feat\.| ft\.", artist, flags=re.I)[0])
        img = pics.get(key[1]) or pics.get(main) or covers.get((key[1], key[0])) or ""
        dur = x.get("duration")
        out.append({"track": track, "artist": artist, "album": album if _norm(album) != _norm(artist) else "",
                    "duration": f"{int(dur) // 60}:{int(dur) % 60:02d}" if dur else "",
                    "image": img if img.startswith("https://") else ""})
        if len(out) >= limit:
            break
    return out


def clean_title(title: str, artist: str) -> str:
    """Künstlernamen aus dem Titel nehmen: "Lady Gaga - Bad Romance" und "Poker Face Lady GaGa" -> Titel allein."""
    t = " ".join((title or "").split())
    a = re.escape(" ".join((artist or "").split()))
    if a:
        t = re.sub(rf"^{a}\s*[-–—:]\s*", "", t, flags=re.I)
        t = re.sub(rf"\s*[-–—]?\s*{a}$", "", t, flags=re.I)
    return t.strip(" -–—") or (title or "").strip()


def suggest(query: str) -> list[dict]:
    return suggest_full(query)["items"]


def suggest_full(query: str) -> dict:
    """Suche für die Vorschlagsliste: LRCLIB (welche Songs Text mit Zeiten haben) + Deezer (Bilder). Gesendet wird
    nur der getippte Suchtext. Ergebnisse 10 Minuten zwischengespeichert."""
    import time

    from concurrent.futures import ThreadPoolExecutor

    q = " ".join((query or "").split())[:80]
    if len(q) < 3:
        return {"items": [], "error": None}
    hit = _CACHE.get(q.lower())
    if hit and time.time() - hit[0] < CACHE_S:
        return {"items": hit[1], "error": None}
    enc = urllib.parse.urlencode({"q": q})
    errors: list[str] = []
    with ThreadPoolExecutor(2) as ex:  # beide gleichzeitig: schneller
        f_l = ex.submit(_get_json, f"{API}?{enc}", 6.0, errors, "LRCLIB")
        f_d = ex.submit(_get_json, f"{DEEZER}?{enc}&limit=15", 4.0, errors, "Deezer (Bilder)")
        lrc, dz = f_l.result(), f_d.result()
    res = suggestions(lrc, dz)
    if lrc is not None:  # nur erfolgreiche Suchen merken
        if len(_CACHE) > 200:
            _CACHE.clear()
        _CACHE[q.lower()] = (time.time(), res)
    return {"items": res, "error": "; ".join(errors) or None, "lrclib_ok": lrc is not None}



def refine(words: list[str], sung: list[str] | None, max_shift: float = 1.0) -> tuple[list[str], int]:
    """LRC-Wörter im Video ("a-e:WORT", gleichmäßig je Zeile verteilt) mit der Spracherkennung nachschärfen: Wörter,
    die die Erkennung in derselben Reihenfolge wiederfindet (höchstens ``max_shift`` s daneben), bekommen deren Zeit;
    die übrigen werden um die Korrektur ihrer Nachbarn verschoben (linear dazwischen). Rückgabe (Wörter, Treffer)."""
    if not words or not sung:
        return words, 0
    lw = []
    for w in words:
        tm, txt = w.split(":", 1)
        a, e = (float(x) for x in tm.split("-"))
        lw.append([a, e, txt])
    rec = []
    for w in sung:
        tm, txt = w.split(":", 1)
        parts = [float(x) for x in tm.split("-")]
        rec.append((parts[0], parts[-1], _norm(txt)))
    sm = difflib.SequenceMatcher(a=[_norm(x[2]) for x in lw], b=[r[2] for r in rec], autojunk=False)
    corr: dict[int, float] = {}
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            i, r = blk.a + k, rec[blk.b + k]
            if len(lw[i][2]) > 1 and abs(r[0] - lw[i][0]) <= max_shift:
                corr[i] = r[0] - lw[i][0]
    if not corr:
        return words, 0
    keys = sorted(corr)
    out = []
    for i, (a, e, txt) in enumerate(lw):
        if i in corr:
            c = corr[i]
        else:
            lo = max((k for k in keys if k < i), default=None)
            hi = min((k for k in keys if k > i), default=None)
            if lo is None:
                c = corr[hi]
            elif hi is None:
                c = corr[lo]
            else:
                f = (lw[i][0] - lw[lo][0]) / max(lw[hi][0] - lw[lo][0], 1e-6)
                c = corr[lo] + (corr[hi] - corr[lo]) * f
        out.append(f"{max(a + c, 0):.2f}-{max(e + c, a + c + 0.1):.2f}:{txt}")
    # Reihenfolge erhalten (nie ein Wort vor seinem Vorgänger)
    fixed, last = [], 0.0
    for w in out:
        tm, txt = w.split(":", 1)
        a, e = (float(x) for x in tm.split("-"))
        a = max(a, last + 0.05) if fixed else a
        fixed.append(f"{a:.2f}-{max(e, a + 0.1):.2f}:{txt}")
        last = a
    return fixed, len(corr)
