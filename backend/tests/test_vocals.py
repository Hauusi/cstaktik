"""Stimmtrennung: STFT hin und zurück ohne Verlust, Stücke lückenlos zusammengesetzt."""

import numpy as np

from cstaktik import vocals


def test_stft_roundtrip():
    rng = np.random.default_rng(7)
    x = rng.uniform(-0.5, 0.5, (2, vocals.CHUNK)).astype(np.float32)
    y = vocals.istft(vocals.stft(x))
    assert np.abs(y - x).max() < 1e-4


def test_separate_identity_model_keeps_signal():
    """Mit einem Modell, das alles durchlässt, kommt das Eingangssignal wieder heraus (Stücke und Ränder stimmen)."""
    t = np.arange(int(vocals.SR * 9.3)) / vocals.SR
    mix = np.stack([np.sin(2 * np.pi * 440 * t), 0.5 * np.sin(2 * np.pi * 220 * t)]).astype(np.float32)
    out = vocals.separate_array(mix, lambda x: x)
    assert out.shape == mix.shape
    assert np.abs(out - mix)[:, 2000:-2000].max() < 1e-3


def test_no_model_no_crash(tmp_path):
    assert vocals.vocals_16k(str(tmp_path / "fehlt.mp3"), 0.0, 5.0) is None
