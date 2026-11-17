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
    yy, xx = np.mgrid[0:200, 0:200].astype(np.float32)
    g = 100 * (1 + np.sin(2 * np.pi * (yy - 0.2 * xx) / 25))  # weiche schräge Fugen wie an einer Wand: Steigung 0,2
    top, bot = wt.edge_slopes(g, (0, 0, 200, 200))
    assert abs(top - 0.2) < 0.05 and abs(bot - 0.2) < 0.05


def test_similarity_robust():
    rng = np.random.default_rng(3)
    src = rng.uniform(10, 200, (25, 2))
    dst = src * 1.1 + [7.0, -4.0]
    dst[:4] += 30  # Ausreißer
    sc, t, err = wt.similarity(src, dst)
    assert abs(sc - 1.1) < 0.01 and np.allclose(t, [7, -4], atol=0.5) and err < 0.5
    assert wt.similarity(src[:4], dst[:4]) is None


def _scene():
    """Spielbild 270 x 270 (kleine Auflösung): unruhiger Hintergrund, links eine glatte Wand in Perspektive
    (Ober- und Unterkante laufen zum Fluchtpunkt rechts auf dem Horizont)."""
    rng = np.random.default_rng(4)
    rgb = rng.uniform(0, 255, (270, 270, 3)).astype(np.float32)
    yy, xx = np.mgrid[0:270, 0:270]
    vx, hz = 420.0, 135.0
    top = hz + (40 - hz) * (vx - xx) / vx   # bei x=0 auf 40, läuft zum Fluchtpunkt
    bot = hz + (230 - hz) * (vx - xx) / vx
    wall = (xx < 110) & (yy > top) & (yy < bot)
    rgb[wall] = (90, 110, 170)
    return rgb, wall, (vx, hz)


def test_place_on_wall_follows_wall_perspective():
    rgb, wall, (vx, hz) = _scene()
    g = rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114
    pl = wt.place_on_wall(g, rgb, 2.5)
    assert pl is not None
    q = pl["quad"]
    # Wort liegt auf der Wand und hat deren Winkel: Ober- und Unterkante zeigen zum Fluchtpunkt
    assert wall[int(q[:, 1].mean()), int(q[:, 0].mean())]
    for a, b in ((q[0], q[1]), (q[3], q[2])):
        slope = (b[1] - a[1]) / (b[0] - a[0])
        expect = (hz - a[1]) / (vx - a[0])
        assert abs(slope - expect) < 0.06
    assert q[1, 1] > q[0, 1] and q[2, 1] < q[3, 1]  # rechts kleiner (weiter weg)


def test_no_wall_in_noise():
    rng = np.random.default_rng(5)
    rgb = rng.uniform(0, 255, (270, 270, 3)).astype(np.float32)
    g = rgb.mean(axis=2)
    assert wt.place_on_wall(g, rgb, 2.5) is None


def test_full_quad_inner_box():
    from PIL import Image

    im = Image.new("RGBA", (200, 100))
    im.info["inner"] = "50,25,150,75"
    q = np.array([[0, 0], [100, 0], [100, 50], [0, 50]], np.float32)
    f = wt.full_quad(im, q)
    assert np.allclose(f, [[-50, -25], [150, -25], [150, 75], [-50, 75]], atol=1e-3)
    assert abs(wt.word_aspect(im) - 2.0) < 1e-6
