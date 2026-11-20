"""Deezer-Hörprobe in der Musikdatei wiederfinden (Kreuzkorrelation der Band-Änderungen)."""

import subprocess

from cstaktik import preview


def test_locate_excerpt_other_encoding(tmp_path):
    import numpy as np

    full = tmp_path / "full.wav"
    # 30 s "Song": zufällige Töne und Rauschstöße (fester Startwert), damit jede Stelle anders klingt
    rng = np.random.default_rng(3)
    sr = 22050
    parts = []
    for _ in range(120):
        n = int(sr * 0.25)
        t = np.arange(n) / sr
        tone = 0.3 * np.sin(2 * np.pi * rng.uniform(150, 2000) * t) * rng.uniform(0.2, 1)
        parts.append(tone + rng.uniform(0, 0.2) * rng.standard_normal(n))
    x = np.concatenate(parts).astype(np.float32)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "-", str(full)],
                   input=x.tobytes(), check=True)
    ex = tmp_path / "ex.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "12.3", "-t", "10", "-i", str(full), "-af", "volume=0.6",
                    "-b:a", "64k", str(ex)], check=True)
    t, score = preview.locate(str(full), str(ex))
    assert t is not None and abs(t - 12.3) < 0.05 and score > preview.MIN_SCORE


def test_no_preview_without_network(tmp_path):
    assert preview.best_part(str(tmp_path / "x.mp3"), "Kesha Cannibal", str(tmp_path)) == (None, "keine Deezer-Hörprobe gefunden")


def test_queries_strip_youtube_title_parts():
    qs = preview._queries("Kesha - Cannibal (Official Lyric Video) – kesha")
    assert qs[0].startswith("Kesha - Cannibal") and qs[-1] == "Kesha Cannibal kesha"
