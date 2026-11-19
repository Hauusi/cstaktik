"""Forced Alignment: Viterbi findet die Zeile an der richtigen Stelle, nur sichere Wörter verschieben die Zeile."""

import numpy as np

from cstaktik import forced


class _Voc:
    blank = 3

    def encode(self, w):
        return {"you": [0], "better": [1], "run": [2]}.get(w.rstrip(forced.EOL).lower(), [])


def _logp(peaks, n=100):
    """Künstliche Modell-Ausgabe: überall Blank, an den angegebenen Schritten deutlich das Token."""
    lp = np.full((n, 4), -8.0)
    lp[:, 3] = -0.05
    for t, k in peaks.items():
        lp[t, k], lp[t, 3] = -0.1, -5.0
    return lp


def test_align_line_finds_tokens_and_ignores_shorter_fakes():
    lp = _logp({30: 0, 40: 1, 52: 2, 5: 0})  # "you" auch bei 5 (Echo), die Zeile liegt bei 30/40/52
    first, conf = forced.align_line(lp, [0, 1, 2], [0, 1, 2], 0, 100, 3)
    assert first == {0: 30, 1: 40, 2: 52} and min(conf.values()) > -1


def test_refine_moves_line_by_sure_words_only():
    lp = _logp({30: 0, 40: 1})  # "run" ohne Ausschlag: unsicher, folgt der Zeile
    words = ["0.90-1.10:you", "1.30-1.50:better", "1.80-2.00:run¶"]
    out, n = forced.refine(words, lp, _Voc())
    t = [float(w.split("-")[0]) for w in out]
    assert n == 2 and abs(t[0] - 1.20) < 0.01 and abs(t[1] - 1.60) < 0.01
    assert abs(t[2] - (1.80 + 0.30)) < 0.06  # um den Median der sicheren (+0,30) verschoben


def test_features_shape_and_no_model():
    f = forced.features(np.random.default_rng(1).uniform(-0.1, 0.1, 16000).astype(np.float32))
    assert f.shape == (100, 80) and abs(float(f.mean())) < 1e-3
    assert forced.refine_words(["0.1-0.2:you"], np.zeros(32000, np.float32)) == (["0.1-0.2:you"], 0)  # ohne Modell


def test_refine_needs_two_agreeing_sure_words():
    """Ein einzelnes sicheres Wort verschiebt seine Zeile nicht (Nutzer: bestätigter Anfang rutschte sonst weg)."""
    lp = _logp({30: 0})
    words = ["0.00-0.40:you", "0.94-1.20:better", "1.44-1.60:run\u00b6"]
    out, n = forced.refine(words, lp, _Voc())
    assert n == 0 and out[0].startswith("0.00-")
