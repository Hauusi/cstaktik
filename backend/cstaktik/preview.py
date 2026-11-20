"""Beste Stelle eines Songs über die Deezer-Hörprobe finden.

Deezer bietet zu jedem Titel eine 30-Sekunden-Hörprobe; Labels und Plattformen legen sie meist auf den eingängigsten
Teil (Hook/Refrain). Die Hörprobe wird geladen und per Klangvergleich in der Musikdatei des Nutzers gesucht: Lautstärke
in 16 Frequenzbändern alle 20 ms, je Band normiert, Kreuzkorrelation über alle Verschiebungen. Nutzer: "Das muss doch
herausfindbar sein, welcher Part der beste vom Song ist."
"""

from __future__ import annotations

import json
import subprocess
import urllib.parse
import urllib.request

import numpy as np

DEEZER = "https://api.deezer.com/search"
UA = "cstaktik-clips/1.0"
SR, HOP, NFFT, BANDS = 8000, 160, 512, 16
MIN_SCORE = 6.0   # Treffer muss so viele Streuungen über dem Durchschnitt aller Verschiebungen liegen
INTRO_S = 8.0     # Musik startet so viel vor der Hook (Text-Teil als Aufbau), Drop auf die Hook


def _queries(query: str) -> list[str]:
    """Suchtexte: wie eingegeben, dann ohne Klammern und Zusätze wie "Official Lyric Video" (YouTube-Titel)."""
    import re

    q = " ".join((query or "").split())[:120]
    clean = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", q)
    clean = re.sub(r"(?i)\b(official|lyrics?|video|audio|music|visuali[sz]er|hd|4k|remaster(ed)?)\b", " ", clean)
    clean = " ".join(clean.replace("–", " ").replace(" - ", " ").split())
    return [x for x in dict.fromkeys([q, clean]) if x]


def deezer_preview_url(query: str, timeout: float = 6.0) -> str | None:
    for q in _queries(query):
        req = urllib.request.Request(f"{DEEZER}?{urllib.parse.urlencode({'q': q, 'limit': 5})}",
                                     headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
        except Exception:  # noqa: BLE001 - kein Netz: ohne Hörprobe weiter
            return None
        for x in (data or {}).get("data") or []:
            if isinstance(x, dict) and str(x.get("preview") or "").startswith("https://"):
                return x["preview"]
    return None


def _bands(path: str, ss: float = 0.0, d: float | None = None) -> np.ndarray | None:
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{ss:.3f}"] + (["-t", f"{d:.3f}"] if d else []) + \
          ["-i", path, "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    x = np.frombuffer(subprocess.run(cmd, capture_output=True).stdout, np.float32)
    n = (len(x) - NFFT) // HOP
    if n < 50:
        return None
    fr = x[np.arange(n)[:, None] * HOP + np.arange(NFFT)[None, :]] * np.hanning(NFFT)
    spec = np.abs(np.fft.rfft(fr, axis=1)) ** 2
    edges = np.unique(np.geomspace(4, NFFT // 2, BANDS + 1).astype(int))
    e = np.stack([spec[:, a:b].sum(axis=1) for a, b in zip(edges[:-1], edges[1:])], axis=1)
    e = np.log(e + 1e-9)
    e = np.diff(e, axis=0)  # Änderung je Schritt: unabhängig von Lautstärke und Klangfarbe der Kodierung
    return (e - e.mean(axis=0)) / (e.std(axis=0) + 1e-6)


def locate(full: str, excerpt: str) -> tuple[float | None, float]:
    """Wo liegt ``excerpt`` in ``full``? Rückgabe (Sekunde oder None, Trefferstärke)."""
    a, b = _bands(full), _bands(excerpt)
    if a is None or b is None or len(b) >= len(a):
        return None, 0.0
    n = len(a) + len(b)
    size = 1 << (n - 1).bit_length()
    corr = np.zeros(len(a) - len(b) + 1)
    for k in range(a.shape[1]):
        fa = np.fft.rfft(a[:, k], size)
        fb = np.fft.rfft(b[::-1, k], size)
        c = np.fft.irfft(fa * fb, size)
        corr += c[len(b) - 1:len(a)]
    score = (corr.max() - corr.mean()) / (corr.std() + 1e-9)
    if score < MIN_SCORE:
        return None, float(score)
    return round(int(corr.argmax()) * HOP / SR, 2), float(score)


def best_part(music: str, query: str, tmpdir) -> tuple[float | None, str]:
    """Hook laut Deezer-Hörprobe in der Musikdatei. Rückgabe (Sekunde der Hook oder None, Begründung)."""
    url = deezer_preview_url(query)
    if not url:
        return None, "keine Deezer-Hörprobe gefunden"
    path = f"{tmpdir}/deezer_preview.mp3"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=10) as r, open(path, "wb") as f:
            f.write(r.read(5_000_000))
    except Exception as e:  # noqa: BLE001
        return None, f"Deezer-Hörprobe nicht ladbar ({type(e).__name__})"
    try:
        t, score = locate(music, path)
    finally:
        import os

        try:
            os.remove(path)
        except OSError:
            pass
    if t is None:
        return None, "Deezer-Hörprobe in der Datei nicht wiedergefunden (andere Version?)"
    return t, f"Hook laut Deezer-Hörprobe bei Sekunde {t:.1f}"
