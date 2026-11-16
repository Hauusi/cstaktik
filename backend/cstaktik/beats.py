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


def find_drop(path: str, max_s: float = 240.0) -> float | None:
    """Zeitpunkt des ersten großen Drops (Sekunde im Song): Stelle, an der der Bass nach einer ruhigeren Phase am
    stärksten und dauerhaft einsetzt. Verglichen werden je 4 s Bass-Energie danach und davor. Nur Stellen ab 6 s und
    mit mindestens 12 s Musik danach. None, wenn der Song keinen deutlichen Anstieg hat."""
    import numpy as np

    p = subprocess.run(["ffmpeg", "-v", "error", "-t", str(max_s), "-i", path, "-vn", "-ac", "1", "-ar", "8000",
                        "-af", "lowpass=f=150", "-f", "f32le", "-"], capture_output=True)
    if p.returncode:
        return None
    x = np.frombuffer(p.stdout, np.float32)
    hop = 400  # 50 ms
    n = len(x) // hop
    if n < 20 * 20:
        return None
    e = np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(axis=1))
    return drop_time(e, 0.05)


def drop_time(e, step: float) -> float | None:
    """Wie find_drop, auf einer fertigen Energiekurve (ein Wert je ``step`` Sekunden)."""
    import numpy as np

    w = int(4 / step)
    lo, hi = int(6 / step), len(e) - int(12 / step)
    if hi <= lo:
        return None
    c = np.concatenate([[0.0], np.cumsum(e)])
    idx = np.arange(lo, hi)
    after = (c[idx + w] - c[idx]) / w
    before = (c[idx] - c[idx - w]) / w
    ref = float(np.percentile(e, 90)) or 1e-9
    score = (after - before) / ref
    k = int(np.argmax(score))
    if score[k] < 0.25 or after[k] < 0.6 * ref:
        return None
    return round(float(idx[k] * step), 2)


def drop_start(path: str, drop: float) -> float:
    """Musikstart so, dass der Drop genau auf dem Schlag liegt, auf dem der erste Kill landet (Schlag-Index 2, bei
    schnellem Tempo 3; siehe memeclip.kill_beats). Ohne erkennbares Tempo: 1 s vor dem Drop."""
    import numpy as np

    try:
        b = beats(path, max(drop - 4.0, 0.0), 8.0)["beats"]
        period = float(np.median(np.diff(b)))
    except Exception:  # noqa: BLE001
        return round(max(drop - 1.0, 0.0), 2)
    # Start einen halben Schlag vor einem Schlag: ein Schlag genau auf Sekunde 0 wird oft nicht erkannt, dann
    # verschiebt sich die Zählung. So liegen die Schläge bei 0,5 / 1,5 / 2,5 ... Perioden, der Drop auf Schlag k.
    k = 2 if 2.5 * period >= 0.9 else 3
    return round(max(drop - (k + 0.5) * period, 0.0), 3)
