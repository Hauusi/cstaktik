"""Forced Alignment: den bekannten Songtext (LRCLIB oder eingefügt) in der getrennten Gesangsspur wiederfinden.

Die Spracherkennung rät, was gesungen wird, und verhört sich im Gesang (Nutzer-Song "Cannibal"). Hier ist der Text
vorgegeben; ein Sprachmodell (NVIDIA NeMo Conformer-CTC small, Apache-2.0, ONNX über das sherpa-onnx-Projekt auf GitHub,
ca. 76 MB, lokal, kostenlos) liefert alle 40 ms, wie wahrscheinlich welcher Laut ist; ein Viterbi-Weg sucht, wo die
Zeile am besten liegt. Nur sichere Wörter (deutlicher Ausschlag im Modell) verschieben ihre Zeile.

Gemessen am Nutzer-Video gegen eine unabhängige Erkennung: "I'll eat you up" 15,52/15,88/16,20/16,56 s (gemessen
15,52/15,84/16,20/16,56), 2. "cannibal" 11,88 (11,84), "you" 0,72 (0,64); vorher bis 0,8 s daneben.
"""

from __future__ import annotations

import re
import tarfile
from pathlib import Path

import numpy as np

MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
             "sherpa-onnx-nemo-ctc-en-conformer-small.tar.bz2")
ARCHIVE_SHA256 = "83dcb462aece5bef4e8072c267419389f0b8d1f91152d8851765f284ff664caa"
MODEL_DIR = Path(__file__).resolve().parent.parent / "data" / "models" / "ctc-en-conformer-small"
FRAME = 0.04          # Sekunden je Modell-Schritt (10 ms Merkmale, 4fach verdichtet)
SEARCH_S = 1.0        # so weit vor/nach der bisherigen Schätzung wird eine Zeile gesucht
SURE_LOGP = -6.0      # Wort gilt als sicher gefunden, wenn ein Schritt mindestens so wahrscheinlich ist
MAX_MOVE_S = 1.2      # ein sicheres Wort darf höchstens so weit von der Schätzung liegen
GARBAGE = 2.0         # Schritte außerhalb der Zeile: "anderer Laut" (Pause oder anderer Gesang)
EOL = "¶"
NOTE = ""
_SESS: dict = {}

# ---- Merkmale wie Kaldi-Fbank (dither 0, snip_edges False, 80 Bänder, 16 kHz), dann je Band normiert ----
_SR, _FL, _FS, _NB, _NFFT = 16000, 400, 160, 80, 512


def _mel(f):
    return 1127.0 * np.log(1.0 + f / 700.0)


def _banks() -> np.ndarray:
    pts = np.linspace(_mel(20.0), _mel(_SR / 2), _NB + 2)
    fm = _mel(np.arange(_NFFT // 2) * _SR / _NFFT)
    b = np.zeros((_NB, _NFFT // 2 + 1), np.float32)
    for k in range(_NB):
        l, c, r = pts[k], pts[k + 1], pts[k + 2]
        b[k, :_NFFT // 2] = np.maximum(0.0, np.minimum((fm - l) / (c - l), (r - fm) / (r - c)))
    return b


_BANKS = _banks()
_WIN = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(_FL) / (_FL - 1))) ** 0.85  # Povey-Fenster


def features(x: np.ndarray) -> np.ndarray:
    """Samples (-1..1, 16 kHz) -> (Rahmen, 80), Log-Mel wie Kaldi, je Band auf Mittel 0 / Streuung 1."""
    x = np.asarray(x, np.float64) * 32768.0
    n = (len(x) + _FS // 2) // _FS
    pad = _FL // 2 - _FS // 2
    xp = np.concatenate([x[pad:0:-1], x, x[::-1][:_FL]])
    fr = xp[np.arange(n)[:, None] * _FS + np.arange(_FL)[None, :]]
    fr = fr - fr.mean(axis=1, keepdims=True)
    fr = np.concatenate([fr[:, :1] * 0.03, fr[:, 1:] - 0.97 * fr[:, :-1]], axis=1)
    spec = np.abs(np.fft.rfft(fr * _WIN, n=_NFFT, axis=1)) ** 2
    f = np.log(np.maximum(spec @ _BANKS.T, np.finfo(np.float32).eps)).astype(np.float32)
    return (f - f.mean(axis=0, keepdims=True)) / (f.std(axis=0, keepdims=True) + 1e-5)


# ---- Text -> Token ----
class Vocab:
    def __init__(self, path: Path):
        self.tok: dict[str, int] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                s, i = line.rsplit(None, 1)
                self.tok[s] = int(i)
        self.blank = max(self.tok.values())

    def encode(self, word: str) -> list[int]:
        """Wort -> Token (längste passende Stücke, das erste mit Wortanfang-Zeichen ▁)."""
        w = re.sub(r"[^a-z']", "", word.lower())
        out, i, first = [], 0, True
        while i < len(w):
            for j in range(len(w), i, -1):
                piece = ("▁" if first else "") + w[i:j]
                if piece in self.tok:
                    out.append(self.tok[piece])
                    i, first = j, False
                    break
            else:
                if first and "▁" in self.tok:
                    out.append(self.tok["▁"])
                    first = False
                    continue
                i += 1
        return out


def align_line(logp: np.ndarray, toks: list[int], word_of: list[int], t0: int, t1: int, blank: int,
               garbage: float = GARBAGE):
    """Beste Lage der Token-Folge zwischen Schritt t0 und t1 (Viterbi, CTC). Vor und nach der Zeile zählt jeder Schritt
    als "anderer Laut" (Blank oder bester Nicht-Blank minus ``garbage``), so gewinnen keine zusammengedrückten Treffer.
    Rückgabe ({Wort: erster Schritt}, {Wort: bester Log-Wert}) oder None."""
    L, T = len(toks), t1 - t0
    if L == 0 or T < L:
        return None
    ext = [blank]
    for k in toks:
        ext += [k, blank]
    S = len(ext)
    sub = logp[t0:t1]
    lp = sub[:, ext]
    bg = np.maximum(sub[:, blank], np.delete(sub, blank, axis=1).max(axis=1) - garbage)
    cb = np.concatenate([[0.0], np.cumsum(bg)])
    NEG = -1e18
    alpha = np.full((T, S), NEG)
    back = np.zeros((T, S), np.int8)  # 0 bleiben, 1 von s-1, 2 von s-2, 3 hier begonnen
    skip = np.array([s >= 2 and ext[s] != blank and ext[s] != ext[s - 2] for s in range(S)])
    for t in range(T):
        prev = alpha[t - 1] if t else None
        for s in range(S):
            best, how = (cb[t], 3) if s <= 1 else (NEG, 0)
            if prev is not None:
                if prev[s] > best:
                    best, how = prev[s], 0
                if s >= 1 and prev[s - 1] > best:
                    best, how = prev[s - 1], 1
                if skip[s] and prev[s - 2] > best:
                    best, how = prev[s - 2], 2
            alpha[t, s] = best + lp[t, s]
            back[t, s] = how
    tail = cb[T] - cb[1:]
    cands = [(alpha[t, S - 1] + tail[t], t, S - 1) for t in range(T)] + \
            [(alpha[t, S - 2] + tail[t], t, S - 2) for t in range(T)]
    _, t, s = max(cands)
    path = []
    while t >= 0:
        path.append((t, s))
        h = back[t, s]
        if h == 3:
            break
        s -= int(h)
        t -= 1
    first: dict[int, int] = {}
    conf: dict[int, float] = {}
    for t_, s_ in reversed(path):
        if s_ % 2 == 1:
            w = word_of[(s_ - 1) // 2]
            first.setdefault(w, t_ + t0)
            conf[w] = max(conf.get(w, -1e9), float(lp[t_, s_]))
    return first, conf


def refine(words: list[str], logp: np.ndarray, vocab: Vocab) -> tuple[list[str], int]:
    """Wörter "a-e:WORT" (Zeilenende EOL) zeilenweise in der Gesangsspur suchen. Sichere Wörter bekommen die gefundene
    Zeit, die übrigen der Zeile werden um den Median der sicheren verschoben; Zeilen ohne sicheres Wort bleiben.
    Rückgabe (Wörter, Zahl sicher gefundener Wörter)."""
    items = []
    for w in words:
        tm, txt = w.split(":", 1)
        a, e = (float(x) for x in tm.split("-"))
        items.append([a, e, txt])
    lines, cur = [], []
    for k, it in enumerate(items):
        cur.append(k)
        if it[2].endswith(EOL):
            lines.append(cur)
            cur = []
    if cur:
        lines.append(cur)
    n_steps = logp.shape[0]
    prev_end, found = 0, 0
    for ln in lines:
        toks, word_of = [], []
        for wi, k in enumerate(ln):
            ids = vocab.encode(items[k][2].rstrip(EOL))
            toks += ids
            word_of += [wi] * len(ids)
        t0 = max(int((items[ln[0]][0] - SEARCH_S) / FRAME), prev_end, 0)
        t1 = min(int((items[ln[-1]][0] + SEARCH_S + 0.5) / FRAME), n_steps)
        r = align_line(logp, toks, word_of, t0, t1, vocab.blank)
        if r is None:
            continue
        first, conf = r
        sure = {wi: first[wi] * FRAME for wi in first
                if conf[wi] >= SURE_LOGP and abs(first[wi] * FRAME - items[ln[wi]][0]) <= MAX_MOVE_S}
        if not sure:
            continue
        d = sorted(sure[wi] - items[ln[wi]][0] for wi in sure)[len(sure) // 2]
        for wi, k in enumerate(ln):
            new = sure.get(wi, items[k][0] + d)
            items[k][1] = max(items[k][1] + (new - items[k][0]), new + 0.1)
            items[k][0] = new
        found += len(sure)
        prev_end = int(max(sure.values()) / FRAME) + 1
    out, last = [], -1e9
    for a, e, txt in items:  # Reihenfolge bleibt, nie zwei Wörter gleichzeitig
        a = max(a, last + 0.05)
        out.append(f"{a:.2f}-{max(e, a + 0.1):.2f}:{txt}")
        last = a
    return out, found


def _load():
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
        model, tokens = MODEL_DIR / "model.int8.onnx", MODEL_DIR / "tokens.txt"
        if not (model.exists() and tokens.exists()):
            import hashlib
            import urllib.request

            MODEL_DIR.mkdir(parents=True, exist_ok=True)
            arc = MODEL_DIR / "model.tar.bz2.part"
            urllib.request.urlretrieve(MODEL_URL, arc)
            if hashlib.sha256(arc.read_bytes()).hexdigest() != ARCHIVE_SHA256:
                arc.unlink()
                NOTE = "Sprachmodell: Prüfsumme falsch, nicht verwendet"
                return None
            with tarfile.open(arc, "r:bz2") as tf:
                for m in tf.getmembers():
                    name = Path(m.name).name
                    if name in ("model.int8.onnx", "tokens.txt") and m.isfile():
                        src = tf.extractfile(m)
                        (MODEL_DIR / name).write_bytes(src.read())
            arc.unlink()
        so = ort.SessionOptions()
        so.log_severity_level = 3
        _SESS["s"] = (ort.InferenceSession(str(model), so, providers=["CPUExecutionProvider"]), Vocab(tokens))
    except Exception as e:  # noqa: BLE001 - ohne Modell bleibt die bisherige Zuordnung
        NOTE = f"Sprachmodell nicht verfügbar: {str(e)[:120]}"
    return _SESS["s"]


def refine_words(words: list[str], vocals16k: np.ndarray | None) -> tuple[list[str], int]:
    """Wörter mit der Gesangsspur (16 kHz, ab Videostart) nachschärfen. Ohne Modell oder Spur: unverändert."""
    if not words or vocals16k is None or len(vocals16k) < 16000:
        return words, 0
    m = _load()
    if m is None:
        return words, 0
    sess, vocab = m
    f = features(vocals16k).T[None].astype(np.float32)
    logp = sess.run(None, {sess.get_inputs()[0].name: f,
                           sess.get_inputs()[1].name: np.array([f.shape[2]], np.int64)})[0][0]
    return refine(words, logp, vocab)
