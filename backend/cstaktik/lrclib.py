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

import numpy as np

API = "https://lrclib.net/api/search"
UA = "cstaktik-clips/1.0"
FULL_SONG_TOL = 4.0  # Musikdatei höchstens so viel kürzer/länger als der Song: gilt als ganzer Song
MIN_MATCH = 3
EOL = "\u00b6"  # Marke am letzten Wort einer Songzeile
EARLY_S = 0.6  # Wörter, die so kurz vor dem Videostart beginnen, werden ab Sekunde 0 gezeigt (Nutzer: erste Wörter fehlten)


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


def syllables(w: str) -> int:
    """Grobe Silbenzahl (Vokalgruppen), mindestens 1. Reicht, um Singzeit zu verteilen."""
    return max(1, len(re.findall(r"[aeiouyäöü]+", w.lower())))


def split_sung(txt: str) -> list[str]:
    """Wörter einer Zeile, Bindestrich-Wörter getrennt ("Papa-paparazzi" -> "Papa", "paparazzi"): jeder Teil kommt,
    wenn er gesungen wird (Nutzer: sonst stand "PAPARAZZI" schon da, bevor es gesungen wurde)."""
    out = []
    for w in txt.split():
        parts = [p for p in re.split(r"(?<=\w)-(?=\w)", w) if p]
        out += parts or [w]
    return out


def timed_words(lines: list[tuple[float, str]], per_syl: float = 0.21) -> list[tuple[float, float, str]]:
    """Wörter mit (Start, Ende): je Zeile ab ihrer Startzeit nach Silben verteilt (lange Wörter brauchen länger),
    höchstens ``per_syl`` Sekunden je Silbe (danach Pause bis zur nächsten Zeile)."""
    out = []
    for i, (t, txt) in enumerate(lines):
        ws = split_sung(txt)
        syl = [syllables(w) for w in ws]
        n = sum(syl)
        nxt = lines[i + 1][0] if i + 1 < len(lines) else t + per_syl * n + 0.5
        span = max(min(nxt - t, per_syl * n + 0.3), 0.12 * n)
        pos = t
        for k, (w, sy) in enumerate(zip(ws, syl)):
            d = span * sy / n
            # letztes Wort der Zeile markieren: dort bleibt der Text länger stehen und blendet aus
            out.append((round(pos, 3), round(pos + d, 3), w + (EOL if k == len(ws) - 1 else "")))
            pos += d
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
        if -EARLY_S <= va < 0 and ve > 0.05:  # kurz vor Videostart begonnen, aber noch zu hören: ab 0 zeigen
            va = 0.0
        if 0 <= va < total:
            out.append(f"{va:.2f}-{min(max(ve, va + 0.1), total):.2f}:{w}")
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



FUZZY_MIN = 0.6  # so ähnlich geschrieben muss ein erkanntes Wort sein ("paparazi" ~ "paparazzi")


def fuzzy_align(lrc: list[tuple[float, str]], rec: list[tuple[float, str]], max_shift: float) -> dict[int, int]:
    """Erkannte Wörter den Songtext-Wörtern zuordnen, in Reihenfolge, unscharf: ähnliche Schreibung (≥ FUZZY_MIN)
    und höchstens ``max_shift`` s neben der geschätzten Zeit. Vorher nur exakt gleiche Wörter: Gesang wird oft leicht
    falsch erkannt, diese Wörter blieben dann bei der Schätzung (Nutzer: Timing nicht on point). Rückgabe i -> j."""
    n, m = len(lrc), len(rec)
    if not n or not m:
        return {}

    def sim(i, j):
        (ta, a), (tb, b) = lrc[i], rec[j]
        if not a or not b or abs(ta - tb) > max_shift:
            return 0.0
        r = difflib.SequenceMatcher(None, a, b).ratio()
        return r if r >= FUZZY_MIN else 0.0

    # Ausrichtung mit Lücken (Needleman-Wunsch ohne Strafe für Lücken): Summe der Ähnlichkeiten maximieren
    score = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            s = sim(i - 1, j - 1)
            score[i][j] = max(score[i - 1][j], score[i][j - 1], score[i - 1][j - 1] + s if s else -1.0)
    out, i, j = {}, n, m
    while i > 0 and j > 0:
        s = sim(i - 1, j - 1)
        if s and abs(score[i][j] - (score[i - 1][j - 1] + s)) < 1e-9:
            out[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif score[i][j] == score[i - 1][j]:
            i -= 1
        else:
            j -= 1
    return out


def refine(words: list[str], sung: list[str] | None, max_shift: float = 1.5) -> tuple[list[str], int]:
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
    pairs = fuzzy_align([(x[0], _norm(x[2])) for x in lw], [(r[0], r[2]) for r in rec], max_shift)
    corr: dict[int, float] = {i: rec[j][0] - lw[i][0] for i, j in pairs.items()}
    ends: dict[int, float] = {i: rec[j][1] for i, j in pairs.items() if rec[j][1] > rec[j][0]}
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
        e2 = ends.get(i, e + c)  # wiedergefunden: Ende aus dem Gesang (Tipp-Tempo)
        out.append(f"{max(a + c, 0):.2f}-{max(e2, a + c + 0.1):.2f}:{txt}")
    # Reihenfolge erhalten (nie ein Wort vor seinem Vorgänger)
    fixed, last = [], 0.0
    for w in out:
        tm, txt = w.split(":", 1)
        a, e = (float(x) for x in tm.split("-"))
        a = max(a, last + 0.05) if fixed else a
        fixed.append(f"{a:.2f}-{max(e, a + 0.1):.2f}:{txt}")
        last = a
    return fixed, len(corr)


PASSAGE_MIN = 0.7  # so gut muss der eingefügte Textanfang zu einer Stelle im Songtext passen
LEAD_S = 0.25      # Musik so viel vor dem ersten Wort starten (Einsatz nicht abschneiden)


def find_passage(lines: list[tuple[float, str]], text: str, n: int = 8) -> float | None:
    """Wo im Song beginnt der eingefügte Text? Die ersten ``n`` Wörter werden mit jeder Stelle des Songtexts
    verglichen (Schreibweise unscharf); bei gleich guten Stellen zählt die erste. Rückgabe: Songzeit des ersten
    Worts oder None, wenn keine Stelle gut genug passt."""
    want = [_norm(w) for w in split_sung(" ".join(text.replace(EOL, " ").split()))]
    want = [w for w in want if w][:n]
    if len(want) < 2:
        return None
    tw = timed_words(lines)
    have = [_norm(w[2].rstrip(EOL)) for w in tw]
    best, best_i = 0.0, None
    for i in range(len(have)):
        win = have[i:i + len(want)]
        if not win or win[0] != want[0] and difflib.SequenceMatcher(a=win[0], b=want[0]).ratio() < 0.8:
            continue
        r = difflib.SequenceMatcher(a=want, b=win, autojunk=False).ratio()
        if r > best + 1e-6:
            best, best_i = r, i
    if best_i is None or best < PASSAGE_MIN:
        return None
    return tw[best_i][0]


def hook_start(lines: list[tuple[float, str]]) -> float | None:
    """Beginn der Hook: die Zeile (ab 3 Wörtern), die im Song am häufigsten vorkommt (mind. 2x); ihr erstes
    Vorkommen. Bei gleicher Häufigkeit die frühere. None ohne Wiederholung."""
    seen: dict[str, list[float]] = {}
    for t, txt in lines:
        key = " ".join(_norm(w) for w in txt.split())
        if len(key.split()) >= 3:
            seen.setdefault(key, []).append(t)
    rep = [(len(ts), -ts[0], ts[0]) for ts in seen.values() if len(ts) >= 2]
    return max(rep)[2] if rep else None


def music_start(lines: list[tuple[float, str]], text: str | None) -> tuple[float | None, str]:
    """Start in der Musikdatei (ganzer Song): eingefügter Text -> seine Stelle; sonst die Hook."""
    if text and text.strip():
        t = find_passage(lines, text)
        if t is not None:
            return max(t - LEAD_S, 0.0), "Stelle des eingefügten Texts im Song"
        return None, "eingefügter Text passt zu keiner Stelle im Songtext von LRCLIB"
    t = hook_start(lines)
    if t is not None:
        return max(t - LEAD_S, 0.0), "Hook (am häufigsten wiederholte Zeile)"
    return None, "keine wiederholte Zeile im Songtext"


LOCAL_WINDOW_S = 30.0  # Songtext so weit vor/nach dem geschätzten Ausschnitt mit dem Gesang vergleichen
LOCAL_SHIFT_S = 20.0   # so weit darf eine Zeile in der Musikdatei anders liegen als die eine geschätzte Verschiebung


CHAIN_LAMBDA = 1.5   # Strafe je Sekunde, um die sich die Verschiebung zwischen zwei Ankern derselben Zeile ändert
LINE_STEEP = 2.5     # je Sekunde Zeilen-Verschiebung über 1 s (Nutzer-Daten "Cannibal": falsch gehörte "am"/"cannibal"
                     # zogen den 2. Refrain 1,7 s nach vorn; unabhängige Erkennung bestätigte LRCLIB + 1,4 s)
JUMP_COST = 3.0      # Sprung zwischen Zeilen über 2,5 s (Datei anders geschnitten): fester Preis, lohnt ab ~4 Wörtern
LINE_LAMBDA = 0.25   # dasselbe zwischen zwei Zeilen: LRCLIB setzt jede Zeile von Hand, jede liegt anders daneben
COLLAPSE_S = 0.03    # erkannte Wörter mit (fast) gleicher Startzeit: Zeitstempel der Erkennung kaputt, nicht verwenden
REPLACE_MIN = 4      # so viele erkannte Wörter am Stück ohne passende LRCLIB-Wörter: dort steht anderer Text im Song


def _collapsed(rec: list[tuple]) -> set[int]:
    """Erkannte Wörter, deren Startzeit mit dem nächsten zusammenfällt (Nutzer-Daten "Cannibal": vier Wörter bei
    15,78 s, "better"/"run" bei 0,80 s). Deren Zeiten sind geraten; nur das letzte Wort der Gruppe zählt."""
    bad = set()
    for j in range(1, len(rec)):
        if abs(rec[j][0] - rec[j - 1][0]) < COLLAPSE_S:
            bad.add(j - 1)  # das letzte Wort der Gruppe behält seine Zeit (Nutzer-Daten: "eat" 15,78 stimmte,
            # "cannibal"/"I'll" davor nicht; "run" 0,80 stimmte, "better" davor nicht)
    return bad


def _anchors(win: list[tuple[float, float, str]], rec: list[tuple]) -> list[tuple[int, float, float, int]]:
    """Anker (LRCLIB-Wort i, Korrektur, Ende im Gesang, erkanntes Wort j) als beste Kette: Reihenfolge in beiden
    Listen steigend, Summe der Ähnlichkeiten (lange Wörter zählen mehr) minus CHAIN_LAMBDA je Sekunde Änderung der
    Verschiebung. So folgt die Kette einer Verschiebung, die sich im Lied langsam ändert (LRCLIB-Zeiten sind von Hand
    gesetzt und teils über 1 s daneben), einzelne falsch erkannte Wörter fallen raus. Vorher: feste Ausreißer-Grenze
    gegen den Median; die verwarf bei "Cannibal" die richtigen Wörter ab 9 s, der Text lag dann 1,4 s zu spät."""
    bad = _collapsed(rec)
    line = _lines(win)
    cand = []
    for i, (a, _, w) in enumerate(win):
        nw = _norm(w.rstrip(EOL))
        if len(nw) < 2:
            continue
        for j, r in enumerate(rec):
            if j in bad or not r[2] or abs(r[0] - a) > LOCAL_SHIFT_S:
                continue
            sim = difflib.SequenceMatcher(None, nw, r[2]).ratio()
            if sim >= FUZZY_MIN:
                # weit weg von der Schätzung: etwas weniger wert (bei gleichen Wörtern gewinnt die nahe Stelle)
                cand.append((i, j, sim * (0.5 + min(len(nw), 8) / 8) - 0.05 * abs(r[0] - a), r[0] - a))
    if not cand:
        return []
    cand.sort()
    best = [c[2] for c in cand]
    prev = [-1] * len(cand)
    for k, (i, j, w, c) in enumerate(cand):
        for m in range(k):
            im, jm, _, cm = cand[m]
            if im < i and jm < j:
                d = abs(c - cm)
                # gleiche Zeile: streng; neue Zeile: bis 2,5 s billig (Handarbeit-Fehler je Zeile), darüber teuer
                # (sonst springt die Kette bei wiederholten Wörtern zu einer ganz anderen Zeile)
                if line[im] == line[i]:
                    pen = CHAIN_LAMBDA * d
                else:  # bis 1 s je Zeile billig (Handarbeit), darüber teuer, ab 3 s fester Sprungpreis (Schnitt)
                    pen = LINE_LAMBDA * min(d, 1.0) + (JUMP_COST if d > 3.0 else LINE_STEEP * max(d - 1.0, 0.0))
                v = best[m] + w - pen
                if v > best[k]:
                    best[k], prev[k] = v, m
    k = max(range(len(cand)), key=lambda x: best[x])
    chain = []
    while k >= 0:
        i, j, _, c = cand[k]
        chain.append((i, c, rec[j][1], j))
        k = prev[k]
    return chain[::-1]


def _lines(win: list[tuple[float, float, str]]) -> list[int]:
    """Zeilennummer je Wort (Zeilenende = EOL-Marke am letzten Wort)."""
    out, n = [], 0
    for _, _, w in win:
        out.append(n)
        if w.endswith(EOL):
            n += 1
    return out


def _paren_flags(win: list[tuple[float, float, str]]) -> list[int]:
    """Gruppennummer (ab 1) für Wörter in Klammern (Hintergrund-Gesang, z. B. "(cannibal, cannibal)"), sonst 0."""
    out, g, inside = [], 0, False
    for _, _, w in win:
        if w.startswith("("):
            inside, g = True, g + 1
        out.append(g if inside else 0)
        if w.rstrip(EOL).rstrip(",.!?").endswith(")"):
            inside = False
    return out


def align_local(words: list[tuple[float, float, str]], offset: float, music_ss: float, total: float,
                sung: list[str] | None) -> tuple[list[str], int]:
    """LRCLIB-Wörter auf den Gesang legen. LRCLIB liefert Text und ungefähre Zeiten, die Spracherkennung die echten
    Zeiten. Anker als beste Kette (``_anchors``), jedes Wort bekommt die Korrektur seiner Nachbarn. Hintergrund-Gesang
    in Klammern nur, wenn er auch erkannt wurde. Singt der Sänger an einer Stelle anderen Text als LRCLIB (andere
    Version, Nutzer: "Can you buy me a book" statt "(I'll eat you up)"), steht dort der erkannte Text.
    Rückgabe (Wörter "a-e:WORT" im Video, Zahl der Anker). Unter MIN_MATCH Ankern: ([], n)."""
    if not sung:
        return [], 0
    base = offset + music_ss
    win = [(a - base, e - base, w) for a, e, w in words if -LOCAL_WINDOW_S <= a - base <= total + LOCAL_WINDOW_S]
    rec = []
    for w in sung:
        tm, txt = w.split(":", 1)
        parts = [float(x) for x in tm.split("-") if x]
        if parts:
            rec.append((parts[0], parts[-1], _norm(txt), txt.strip("-")))
    good = _anchors(win, rec)
    # Ausreißer in der eigenen Zeile: hat eine Zeile mindestens 3 Anker, zählt keiner, der mehr als 0,35 s von ihrem
    # Median abweicht (Nutzer-Daten: "I'll" 0,5 s zu früh erkannt, "eat you up" derselben Zeile richtig)
    ln_of = _lines(win)
    by_line: dict = {}
    for g in good:
        by_line.setdefault(ln_of[g[0]], []).append(g[1])
    med = {k: sorted(v)[len(v) // 2] for k, v in by_line.items() if len(v) >= 3}
    outliers = {g[3] for g in good if ln_of[g[0]] in med and abs(g[1] - med[ln_of[g[0]]]) > 0.35}
    good = [g for g in good if g[3] not in outliers]
    if len(good) < MIN_MATCH:
        return [], len(good)
    idx = [g[0] for g in good]
    corr = {g[0]: g[1] for g in good}
    ends = {g[0]: g[2] for g in good}
    used_rec = {g[3] for g in good}
    paren = _paren_flags(win)
    heard = {paren[g[0]] for g in good if paren[g[0]]}  # Klammer-Gruppen mit mindestens einem erkannten Wort
    line = _lines(win)
    bad = _collapsed(rec)
    rec_t = np.array([r[0] for r in rec])

    def speech_near(t: float, r: float = 1.0) -> bool:  # gibt es dort überhaupt erkannten Gesang?
        return bool(len(rec_t)) and float(np.min(np.abs(rec_t - t))) <= r

    placed = []  # (Start, Ende, Text, Anker?)
    for i, (a, e, w) in enumerate(win):
        if i in corr:
            c = corr[i]
        else:
            if paren[i] and paren[i] not in heard:  # Hintergrund-Gesang, den die Erkennung nicht hört: weglassen
                continue
            same = [k for k in idx if line[k] == line[i]]
            if same:  # Zeile hat erkannte Wörter: deren Verschiebung (jede LRCLIB-Zeile liegt anders daneben)
                lo = max((k for k in same if k < i), default=None)
                hi = min((k for k in same if k > i), default=None)
            else:
                lo = max((k for k in idx if k < i), default=None)
                hi = min((k for k in idx if k > i), default=None)
            if lo is not None and hi is not None and abs(corr[hi] - corr[lo]) <= 1.0:
                f = (a - win[lo][0]) / max(win[hi][0] - win[lo][0], 1e-6)
                c = corr[lo] + (corr[hi] - corr[lo]) * f
                # lange Strecke zwischen zwei erkannten Wörtern ohne jeden erkannten Gesang: Instrumental-Pause,
                # dort kein Text (sonst stand dort Text aus einer Refrain-Wiederholung)
                if (win[hi][0] + corr[hi]) - (win[lo][0] + corr[lo]) > 4.0 and not speech_near(a + c, 1.5):
                    continue
            elif lo is not None and hi is not None:
                # Sprung zwischen den Nachbarn (Datei anders geschnitten): nicht über die Lücke verteilen. Die
                # Verschiebung der Seite, auf der dort Gesang erkannt wurde; auf keiner Seite Gesang: weglassen.
                cands = [(abs(a - win[k][0]), corr[k]) for k in (lo, hi) if speech_near(a + corr[k])]
                if not cands:
                    continue
                c = min(cands)[1]
            else:  # Rand: Verschiebung des nächsten Ankers weiterführen (Text läuft weiter, auch ohne Erkennung)
                c = corr[lo if lo is not None else hi]
        placed.append((a + c, ends.get(i, e + c), w, i in corr))
    # nicht verankerte Wörter: gleich geschriebenes erkanntes Wort bis 1 s daneben, noch frei -> dessen Zeit
    # (Nutzer-Daten: "you" bei 0,00 erkannt, über die Nachbarn geschätzt 0,67)
    fixed = [p[3] for p in placed]
    for k, (va, ve, w, anc) in enumerate(placed):
        if anc:
            continue
        nw = _norm(w.rstrip(EOL))
        if len(nw) < 3:  # kurze Wörter ("I", "am") hört die Erkennung im Gesang an vielen Stellen
            continue
        js = [j for j, r in enumerate(rec) if j not in used_rec and j not in bad and j not in outliers
              and abs(r[0] - va) <= 1.0
              and r[2] and difflib.SequenceMatcher(None, nw, r[2]).ratio() >= 0.8]
        # Reihenfolge gegenüber den festen (erkannten) Nachbarn bleibt
        lo_t = max((placed[m][0] for m in range(k) if fixed[m]), default=-1e9)
        hi_t = min((placed[m][0] for m in range(k + 1, len(placed)) if fixed[m]), default=1e9)
        js = [j for j in js if lo_t < rec[j][0] < hi_t]
        if js:
            j = min(js, key=lambda j: abs(rec[j][0] - va))
            placed[k] = (rec[j][0], rec[j][1], w, True)
            fixed[k] = True
            used_rec.add(j)
    # Reihenfolge: ein geschätztes Wort darf nicht nach einem späteren festen Wort liegen; sonst davor rücken
    nxt_t = None
    for k in range(len(placed) - 1, -1, -1):
        va, ve, w, anc = placed[k]
        if fixed[k]:
            nxt_t = va
        elif nxt_t is not None and va > nxt_t - 0.1:
            placed[k] = (nxt_t - 0.25, nxt_t - 0.05, w, False)
            nxt_t = nxt_t - 0.25
    last_t = None  # und nicht vor einem früheren festen Wort
    for k, (va, ve, w, anc) in enumerate(placed):
        if fixed[k]:
            last_t = va
        elif last_t is not None and va < last_t + 0.1:
            placed[k] = (last_t + 0.25, max(ve, last_t + 0.45), w, False)
            last_t = last_t + 0.25
    # anderer Text im Song: erkannte Wörter am Stück ohne Gegenstück in LRCLIB ersetzen die LRCLIB-Wörter dort
    # (frei = nicht verankert, oder nur an Hintergrund-Gesang in Klammern verankert)
    paren_rec = {g[3] for g in good if paren[g[0]]}
    runs, cur = [], []
    for j, r in enumerate(rec):
        free = (j not in used_rec or j in paren_rec) and j not in bad and r[2]
        if free and (not cur or r[0] - rec[cur[-1]][0] <= 1.0):
            cur.append(j)
        else:
            if len(cur) >= REPLACE_MIN:
                runs.append(cur)
            cur = [j] if free else []
    if len(cur) >= REPLACE_MIN:
        runs.append(cur)
    for run in runs:
        # nur echter Text ersetzt LRCLIB: mindestens 2 Wörter ab 4 Buchstaben (Nutzer-Daten: "I am I am" aus dem
        # Hintergrund-Gesang stand sonst zusätzlich da)
        if sum(1 for j in run if len(rec[j][2]) >= 4) < 2:
            continue
        t0, t1 = rec[run[0]][0] - 0.2, rec[run[-1]][0] + 0.2
        inside = [p for p in placed if t0 <= p[0] <= t1]
        if sum(1 for p in inside if p[3] and not p[2].startswith("(") and not p[2].rstrip(EOL).endswith(")")) \
                > 0.3 * len(run):
            continue  # dort passt LRCLIB doch: nichts ersetzen
        placed = [p for p in placed if not t0 <= p[0] <= t1]
        placed += [(rec[j][0], rec[j][1], rec[j][3] + (EOL if j == run[-1] else ""), True) for j in run]
    placed.sort(key=lambda p: p[0])
    out, last = [], -1e9
    for va, ve, w, heard in placed:
        # kurz vor dem Videostart begonnen: nur zeigen, wenn es auch gehört wurde (Nutzer-Clip: "cannibal" aus der
        # Zeile davor stand bei 0,00)
        if -EARLY_S <= va < 0 and ve > 0.3 and heard:
            va = 0.0
        if not 0 <= va < total:
            continue
        va = max(va, last + 0.05)  # Reihenfolge erhalten
        out.append(f"{va:.2f}-{min(max(ve, va + 0.1), total):.2f}:{w}")
        last = va
    return out, len(good)