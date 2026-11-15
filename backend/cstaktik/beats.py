"""Beat eines Musikstücks finden (ohne Zusatz-Bibliotheken, nur ffmpeg + numpy).

Verfahren: Ton als Mono laden, Energie-Anstiege im Spektrum je 10 ms (Onset-Stärke), Tempo per Autokorrelation
(70 bis 180 Schläge pro Minute), dann das Raster so legen, dass möglichst viel Onset-Stärke auf den Schlägen liegt.
Ergebnis sind gleichmäßige Beat-Zeiten. Bei Musik ohne klaren Takt ist das Raster nur eine Näherung.
"""

from __future__ import annotations

import subprocess

SR, HOP, WIN = 22050, 220, 1024  # 10 ms Schritt


def onset_envelope(path: str, ss: float = 0.0, d: float | None = None):
    import numpy as np

    cmd = ["ffmpeg", "-v", "error", "-ss", str(ss)] + (["-t", str(d)] if d else []) + \
          ["-i", path, "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode:
        raise RuntimeError(p.stderr.decode(errors="replace")[-400:])
    x = np.frombuffer(p.stdout, np.float32)
    n = 1 + max(0, (len(x) - WIN) // HOP)
    if n < 50:
        raise ValueError("Die Musik ist zu kurz für eine Beat-Erkennung.")
    idx = np.arange(WIN)[None, :] + HOP * np.arange(n)[:, None]
    mag = np.abs(np.fft.rfft(x[idx] * np.hanning(WIN), axis=1))
    flux = np.maximum(np.diff(np.log1p(20 * mag), axis=0), 0).sum(axis=1)
    flux = np.concatenate([[0.0], flux])
    return flux - np.convolve(flux, np.ones(40) / 40, mode="same")  # langsame Schwankung abziehen


def beat_grid(env, lo_bpm: float = 70, hi_bpm: float = 180) -> dict:
    """Tempo und Beat-Zeiten (Sekunden ab Beginn des Ausschnitts) aus der Onset-Stärke."""
    import numpy as np

    fps = SR / HOP
    e = np.maximum(env, 0)
    ac = np.correlate(e, e, mode="full")[len(e) - 1:]
    lags = np.arange(int(fps * 60 / hi_bpm), int(fps * 60 / lo_bpm) + 1)
    # Bevorzugt mittlere Tempi (um 120), damit nicht das halbe oder doppelte Tempo gewinnt
    pref = np.exp(-0.5 * (np.log2((60 * fps / lags) / 120) / 0.6) ** 2)
    lag = int(lags[np.argmax(ac[lags] * pref)])
    best, cands = 0, np.arange(max(lag - 2, 1), lag + 3)
    period = float(lag)
    for c in np.linspace(cands[0], cands[-1], 41):  # Periode fein nachstellen
        score = max(e[np.clip(np.round(np.arange(ph, len(e), c)).astype(int), 0, len(e) - 1)].sum() for ph in range(int(c)))
        if score > best:
            best, period = score, float(c)
    phase = max(range(int(period)), key=lambda ph: e[np.clip(np.round(np.arange(ph, len(e), period)).astype(int), 0, len(e) - 1)].sum())
    times = [round(float(t / fps), 3) for t in np.arange(phase, len(e), period)]
    strength = [float(e[min(int(round(t * fps)), len(e) - 1)]) for t in times]
    return {"bpm": round(60 * fps / period, 1), "beats": times, "strength": strength}


def beats(path: str, ss: float = 0.0, d: float | None = None) -> dict:
    return beat_grid(onset_envelope(path, ss, d))
