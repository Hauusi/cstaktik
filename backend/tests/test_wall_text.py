"""Wand-Text: Homographie, robuste Schätzung mit Ausreißern, Verfolgung einer Verschiebung, Kantenwinkel."""

import numpy as np

from cstaktik import wall_text as wt


def test_homography_and_ransac():
    h_true = np.array([[1.05, 0.08, 4.0], [-0.03, 0.97, -2.0], [0.0004, -0.0002, 1.0]])
    rng = np.random.default_rng(1)
    src = rng.uniform(20, 200, (30, 2))
    dst = wt.apply_h(h_true, src)
    assert np.allclose(wt.apply_h(wt.homography(src[:4], dst[:4]), src), dst, atol=1e-6)
    dst[:6] += 25  # Ausreißer: falsch verfolgte Punkte
    h, frac = wt.ransac_h(src, dst)
    assert frac > 0.75 and np.allclose(wt.apply_h(h, src[6:]), dst[6:], atol=0.5)
    assert wt.ransac_h(src[:5], dst[:5]) == (None, 0.0)  # zu wenige Punkte


def test_track_shift_and_slopes():
    rng = np.random.default_rng(2)
    a = np.kron(rng.uniform(0, 255, (34, 34)), np.ones((8, 8))).astype(np.float32)[:270, :270]  # Muster mit Struktur
    b = np.roll(a, (3, 5), axis=(0, 1))  # Kamera bewegt sich: 5 nach rechts, 3 nach unten
    pts = wt.corners(a, (40, 40, 230, 230), n=30)
    new, ok = wt.track(a, b, pts)
    assert ok.mean() > 0.8 and np.allclose(np.median(new[ok] - pts[ok], axis=0), (5, 3), atol=0.6)
    g = np.zeros((200, 200), np.float32)
    for y0 in range(20, 200, 25):  # schräge Fugen wie an einer Wand: Steigung 0,2
        for x in range(200):
            y = int(y0 + 0.2 * x)
            if 0 <= y < 200:
                g[y:y + 3, x] = 200
    top, bot = wt.edge_slopes(g, (0, 0, 200, 200))
    assert abs(top - 0.2) < 0.05 and abs(bot - 0.2) < 0.05
