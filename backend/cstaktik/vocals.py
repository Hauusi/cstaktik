"""Stimme von der Musik trennen, damit die Spracherkennung nur den Gesang hört (wie bei Karaoke-Tools).

Modell: MDX-Net "Kim_Vocal_2" (aus dem Projekt Ultimate Vocal Remover, öffentlich auf GitHub, ONNX, ca. 65 MB),
läuft lokal über onnxruntime auf der CPU, ohne Kosten. Wird beim ersten Gebrauch nach data/models/ geladen und per
SHA-256 geprüft. Grund: Whisper hörte den Gesang zusammen mit der Musik und verhörte sich im Refrain (Nutzer-Song
"Cannibal": "cannibal" bei 9,76 s erkannt, gesungen bei 11,84 s).

Verarbeitung wie im Original: Stereo 44,1 kHz, STFT (n_fft 7680, hop 1024, Hann), 3072 Frequenzbänder x 256 Zeitschritte
je Stück, Real-/Imaginärteil beider Kanäle als 4 Kanäle; Stücke überlappen um n_fft/2 an beiden Rändern.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

MODEL_URL = "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/Kim_Vocal_2.onnx"
MODEL_SHA256 = "ce74ef3b6a6024ce44211a07be9cf8bc6d87728cc852a68ab34eb8e58cde9c8b"
MODEL_FILE = Path(__file__).resolve().parent.parent / "data" / "models" / "Kim_Vocal_2.onnx"
N_FFT, HOP, DIM_F, DIM_T, SR = 7680, 1024, 3072, 256, 44100
CHUNK = HOP * (DIM_T - 1)
TRIM = N_FFT // 2
GEN = CHUNK - 2 * TRIM
NOTE = ""  # warum die Trennung nicht lief (Anzeige)
_SESS: dict = {}
_CACHE: dict = {}


def _window() -> np.ndarray:
    return np.hanning(N_FFT + 1)[:-1].astype(np.float32)  # periodisch wie torch.hann_window


def stft(x: np.ndarray) -> np.ndarray:
    """(2, CHUNK) -> (2, n_fft/2+1, DIM_T) komplex, Ränder gespiegelt (wie torch.stft center=True)."""
    xp = np.pad(x, ((0, 0), (N_FFT // 2, N_FFT // 2)), mode="reflect")
    idx = np.arange(DIM_T)[:, None] * HOP + np.arange(N_FFT)[None, :]
    return np.fft.rfft(xp[:, idx] * _window(), axis=-1).transpose(0, 2, 1)


def istft(spec: np.ndarray) -> np.ndarray:
    """Umkehrung von stft: (2, n_fft/2+1, DIM_T) -> (2, CHUNK)."""
    w = _window()
    fr = np.fft.irfft(spec.transpose(0, 2, 1), n=N_FFT, axis=-1).astype(np.float32) * w
    total = N_FFT + HOP * (DIM_T - 1)
    out = np.zeros((2, total), np.float32)
    norm = np.zeros(total, np.float32)
    for t in range(DIM_T):
        out[:, t * HOP:t * HOP + N_FFT] += fr[:, t]
        norm[t * HOP:t * HOP + N_FFT] += w * w
    out /= np.maximum(norm, 1e-8)
    return out[:, N_FFT // 2:N_FFT // 2 + CHUNK]


def separate_array(mix: np.ndarray, run) -> np.ndarray:
    """Stimme aus (2, n) Stereo 44,1 kHz. ``run``: Modell-Aufruf (4, DIM_F, DIM_T) -> (4, DIM_F, DIM_T)."""
    n = mix.shape[1]
    pad = GEN - n % GEN
    m = np.concatenate([np.zeros((2, TRIM), np.float32), mix.astype(np.float32),
                        np.zeros((2, pad + TRIM), np.float32)], axis=1)
    out = []
    for i in range(0, n + pad, GEN):
        sp = stft(m[:, i:i + CHUNK])[:, :DIM_F]
        x = np.stack([sp[0].real, sp[0].imag, sp[1].real, sp[1].imag]).astype(np.float32)
        y = run(x)
        full = np.zeros((2, N_FFT // 2 + 1, DIM_T), np.complex64)
        full[0, :DIM_F] = y[0] + 1j * y[1]
        full[1, :DIM_F] = y[2] + 1j * y[3]
        out.append(istft(full)[:, TRIM:-TRIM])
    return np.concatenate(out, axis=1)[:, :n]


def _session():
    global NOTE
    if "s" in _SESS:
        return _SESS["s"]
    _SESS["s"] = None
    try:
        import onnxruntime as ort
    except ImportError:
        NOTE = "onnxruntime nicht installiert"
        return None
    try:
        if not MODEL_FILE.exists():
            import hashlib
            import urllib.request

            MODEL_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = MODEL_FILE.with_suffix(".part")
            urllib.request.urlretrieve(MODEL_URL, tmp)
            if hashlib.sha256(tmp.read_bytes()).hexdigest() != MODEL_SHA256:
                tmp.unlink()
                NOTE = "Trennmodell: Prüfsumme falsch, nicht verwendet"
                return None
            tmp.rename(MODEL_FILE)
        so = ort.SessionOptions()
        so.log_severity_level = 3
        _SESS["s"] = ort.InferenceSession(str(MODEL_FILE), so, providers=["CPUExecutionProvider"])
    except Exception as e:  # noqa: BLE001 - ohne Trennung hört die Erkennung wie bisher die ganze Musik
        NOTE = f"Trennmodell nicht verfügbar: {str(e)[:120]}"
    return _SESS["s"]


def vocals_16k(music: str, ss: float, d: float) -> np.ndarray | None:
    """Gesang aus dem Musik-Ausschnitt, Mono 16 kHz (für die Spracherkennung). None ohne Modell."""
    key = (music, round(ss, 3), round(d, 3))
    if key in _CACHE:
        return _CACHE[key]
    s = _session()
    if s is None:
        return None
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{ss:.3f}", "-t", f"{d:.3f}", "-i", music, "-vn", "-ac", "2",
                          "-ar", str(SR), "-f", "f32le", "-"], capture_output=True).stdout
    mix = np.frombuffer(raw, np.float32)
    if len(mix) < 2 * SR // 2:
        return None
    mix = mix[: len(mix) // 2 * 2].reshape(-1, 2).T
    name = s.get_inputs()[0].name
    voc = separate_array(mix, lambda x: s.run(None, {name: x[None]})[0][0])
    mono = voc.mean(axis=0).astype(np.float32).tobytes()
    out = subprocess.run(["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-", "-ar", "16000",
                          "-f", "f32le", "-"], input=mono, capture_output=True).stdout
    res = np.frombuffer(out, np.float32).copy()
    _CACHE.clear()
    _CACHE[key] = res
    return res
