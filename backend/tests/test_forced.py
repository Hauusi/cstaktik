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


class _Voc2:
    blank = 3

    def encode(self, w):
        return {"cannibal": [0, 1], "i": [2], "am": [2]}.get(w.rstrip(forced.EOL).lower(), [])


def test_confirm_when_model_and_whisper_agree():
    """Nutzer-Clip: LRCLIB "cannibal" 2 s zu früh; Modell (deutlicher Ausschlag) und Whisper hören es bei 5,32/5,36."""
    lp = np.full((200, 4), -8.0)
    lp[:, 3] = -0.05
    lp[133, 0], lp[133, 3] = -0.2, -5.0  # 133 x 0,04 = 5,32 s
    words = ["2.85-3.08:I", "3.08-3.31:am", "3.31-3.80:cannibal¶", "8.58-8.83:I"]
    out, n = forced.confirm(words, lp, _Voc2(), ["5.36-5.80:cannibal"])
    t = [float(w.split("-")[0]) for w in out]
    assert n == 1 and abs(t[2] - 5.32) < 0.01 and t[0] == 2.85 and t[3] == 8.58  # nur dieses Wort, Folgezeile bleibt
    out2, n2 = forced.confirm(words, lp, _Voc2(), ["7.50-7.80:cannibal"])  # Whisper woanders: keine Bestätigung
    assert n2 == 0 and out2[2].startswith("3.31")
