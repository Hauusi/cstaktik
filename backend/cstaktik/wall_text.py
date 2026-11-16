"""Songtext auf Wänden: ein Wort im Winkel einer Wand ins Spielbild legen und der Wand folgen, während sich die
Kamera bewegt. Nur numpy und Pillow (kein OpenCV nötig).

Ablauf je Wort (im fertigen Hochformat-Video, nur im Spielbild-Quadrat):
1. Wand suchen: linker oder rechter Bildrand des Spielbilds (die Mitte gehört Fadenkreuz und Gegner), dort wo es
   viele markante Punkte und waagrecht laufende Kanten gibt (Fugen, Fenster, Dachkanten).
2. Winkel: Richtung der Kanten in der oberen und unteren Hälfte des Bereichs. Laufen sie zusammen, ergibt das die
   Perspektive der Wand; das Wort wird als Viereck mit genau diesen Kanten gelegt.
3. Verfolgen: markante Punkte Bild für Bild suchen (Blockvergleich, grob nach fein), daraus eine Perspektiv-
   Abbildung (Homographie, RANSAC). Das Wort-Viereck wird damit mitbewegt.
4. Verliert das Tool die Wand (zu schnelle Bewegung, zu wenige Punkte, unplausible Verzerrung), wird das Wort
   ausgeblendet; findet es zu Beginn keine Wand, steht das Wort flach im unteren Drittel wie sonst.

Grenzen: Schnelle Flicks und Schnitte brechen die Verfolgung ab. Nur für Wörter ohne Schnitt und ohne Kill im
Zeitfenster.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

SCALE = 4          # Verfolgung auf einem Viertel der Auflösung
PATCH, SEARCH = 4, 10  # Blockgröße (Radius) und Suchradius in Pixeln der kleinen Auflösung
MIN_POINTS = 8


def _gray(rgb: np.ndarray) -> np.ndarray:
    small = rgb[::SCALE, ::SCALE].astype(np.float32)
    return small[..., 0] * 0.299 + small[..., 1] * 0.587 + small[..., 2] * 0.114


def _blur(a: np.ndarray) -> np.ndarray:
    k = np.array([1, 4, 6, 4, 1], np.float32) / 16
    a = np.apply_along_axis(lambda r: np.convolve(r, k, mode="same"), 1, a)
    return np.apply_along_axis(lambda c: np.convolve(c, k, mode="same"), 0, a)


def corners(g: np.ndarray, mask: tuple[int, int, int, int], n: int = 60) -> np.ndarray:
    """Markante Punkte (Harris) im Rechteck (x0, y0, x1, y1). Rückgabe: Punkte als (x, y)."""
    gy, gx = np.gradient(g)
    sxx, syy, sxy = _blur(gx * gx), _blur(gy * gy), _blur(gx * gy)
    r = sxx * syy - sxy * sxy - 0.05 * (sxx + syy) ** 2
    x0, y0, x1, y1 = mask
    m = PATCH + SEARCH + 2
    x0, y0, x1, y1 = max(x0, m), max(y0, m), min(x1, g.shape[1] - m), min(y1, g.shape[0] - m)
    if x1 <= x0 or y1 <= y0:
        return np.zeros((0, 2))
    sub = r[y0:y1, x0:x1]
    pts = []
    thr = max(sub.max() * 0.01, 1e-3)
    order = np.argsort(sub, axis=None)[::-1]
    for idx in order[: n * 40]:
        y, x = divmod(int(idx), sub.shape[1])
        if sub[y, x] < thr:
            break
        if all((x - px) ** 2 + (y - py) ** 2 >= 25 for px, py in pts):
            pts.append((x, y))
            if len(pts) >= n:
                break
    return np.array([(x + x0, y + y0) for x, y in pts], np.float32)


def edge_slopes(g: np.ndarray, rect: tuple[int, int, int, int]) -> tuple[float, float] | None:
    """Steigung der waagrecht laufenden Kanten oben und unten im Rechteck (dy/dx). None ohne klare Kanten."""
    x0, y0, x1, y1 = rect
    gy, gx = np.gradient(g[y0:y1, x0:x1])
    mag = np.hypot(gx, gy)
    out = []
    for part in (slice(0, (y1 - y0) // 2), slice((y1 - y0) // 2, y1 - y0)):
        m, ex, ey = mag[part], gx[part], gy[part]
        strong = m >= max(np.percentile(m, 80), 8)
        # Kante quer zum Gradienten; nur fast waagrechte Kanten (Gradient vor allem senkrecht)
        sel = strong & (np.abs(ey) > np.abs(ex) * 1.4)
        if sel.sum() < 25:
            return None
        slope = -ex[sel] / ey[sel]  # Richtung der Kante
        w = m[sel]
        o = np.argsort(slope)
        cw = np.cumsum(w[o])
        out.append(float(np.clip(slope[o][np.searchsorted(cw, cw[-1] / 2)], -0.6, 0.6)))
    return out[0], out[1]


def homography(src: np.ndarray, dst: np.ndarray) -> np.ndarray | None:
    """Perspektiv-Abbildung src -> dst aus mindestens 4 Punktpaaren (DLT)."""
    a = []
    for (x, y), (u, v) in zip(src, dst):
        a.append([-x, -y, -1, 0, 0, 0, u * x, u * y, u])
        a.append([0, 0, 0, -x, -y, -1, v * x, v * y, v])
    try:
        _, _, vt = np.linalg.svd(np.asarray(a, np.float64))
    except np.linalg.LinAlgError:
        return None
    h = vt[-1].reshape(3, 3)
    return h / h[2, 2] if abs(h[2, 2]) > 1e-9 else None


def apply_h(h: np.ndarray, pts: np.ndarray) -> np.ndarray:
    p = np.c_[pts, np.ones(len(pts))] @ h.T
    return p[:, :2] / p[:, 2:3]


def ransac_h(src: np.ndarray, dst: np.ndarray, iters: int = 120, tol: float = 1.5, seed: int = 0):
    """Robuste Homographie: Ausreißer (falsch verfolgte Punkte) werden ignoriert. Rückgabe (H, Anteil passend)."""
    n = len(src)
    if n < MIN_POINTS:
        return None, 0.0
    rng = np.random.default_rng(seed)
    best, best_in = None, np.zeros(n, bool)
    for _ in range(iters):
        idx = rng.choice(n, 4, replace=False)
        h = homography(src[idx], dst[idx])
        if h is None:
            continue
        err = np.hypot(*(apply_h(h, src) - dst).T)
        inl = err < tol
        if inl.sum() > best_in.sum():
            best, best_in = h, inl
    if best is None or best_in.sum() < MIN_POINTS:
        return None, 0.0
    h = homography(src[best_in], dst[best_in])
    return h, float(best_in.mean())


def track(prev: np.ndarray, cur: np.ndarray, pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Punkte von ``prev`` nach ``cur`` verfolgen (Blockvergleich mit Vorschätzung über die halbe Auflösung).
    Rückgabe (neue Punkte, gültig)."""
    h, w = prev.shape
    new = pts.copy()
    ok = np.ones(len(pts), bool)
    # grob: gemeinsame Verschiebung auf halber Auflösung (fängt schnellere Schwenks)
    p2, c2 = prev[::2, ::2], cur[::2, ::2]
    shifts = []
    for x, y in pts[:20] / 2:
        s = _match(p2, c2, int(round(x)), int(round(y)), 2, 8)
        if s is not None:
            shifts.append(s)
    base = np.median(np.array(shifts), axis=0) * 2 if shifts else np.zeros(2)
    for i, (x, y) in enumerate(pts):
        xi, yi = int(round(x)), int(round(y))
        s = _match(prev, cur, xi, yi, PATCH, SEARCH, base)
        if s is None:
            ok[i] = False
            continue
        new[i] = (x + s[0], y + s[1])
        if not (PATCH <= new[i][0] < w - PATCH and PATCH <= new[i][1] < h - PATCH):
            ok[i] = False
    return new, ok


def _match(prev, cur, x, y, r, R, base=(0.0, 0.0)):
    h, w = prev.shape
    if not (r <= x < w - r and r <= y < h - r):
        return None
    tpl = prev[y - r:y + r + 1, x - r:x + r + 1]
    if tpl.std() < 2:
        return None  # keine Struktur: nicht verfolgbar
    bx, by = int(round(base[0])), int(round(base[1]))
    best, bs = None, None
    for dy in range(by - R, by + R + 1):
        yy = y + dy
        if not (r <= yy < h - r):
            continue
        rows = cur[yy - r:yy + r + 1]
        for dx in range(bx - R, bx + R + 1):
            xx = x + dx
            if not (r <= xx < w - r):
                continue
            d = float(((rows[:, xx - r:xx + r + 1] - tpl) ** 2).mean())
            if best is None or d < best:
                best, bs = d, (dx, dy)
    if best is None or best > 400:  # zu unähnlich: Punkt verloren
        return None
    return bs


def place(g: np.ndarray, aspect: float) -> dict | None:
    """Wand im Spielbild suchen und das Wort-Viereck dort festlegen (kleine Auflösung, Koordinaten im Quadrat)."""
    size = g.shape[0]
    best = None
    for side in ("left", "right"):
        x0, x1 = (int(size * 0.02), int(size * 0.46)) if side == "left" else (int(size * 0.54), int(size * 0.98))
        y0, y1 = int(size * 0.12), int(size * 0.62)
        pts = corners(g, (x0, y0, x1, y1))
        if len(pts) < MIN_POINTS * 2:
            continue
        sl = edge_slopes(g, (x0, y0, x1, y1))
        if sl is None:
            continue
        score = len(pts)
        if best is None or score > best[0]:
            best = (score, side, (x0, y0, x1, y1), sl, pts)
    if best is None:
        return None
    _, side, (x0, y0, x1, y1), (top, bot), pts = best
    qw = (x1 - x0) * 0.95
    qh = min(qw / aspect, (y1 - y0) * 0.6)
    qw = qh * aspect
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    xl, xr = cx - qw / 2, cx + qw / 2
    quad = np.array([[xl, cy - qh / 2 - top * qw / 2], [xr, cy - qh / 2 + top * qw / 2],
                     [xr, cy + qh / 2 + bot * qw / 2], [xl, cy + qh / 2 - bot * qw / 2]], np.float32)
    # Punkte rund um das Viereck verfolgen (dieselbe Wand)
    pad = qw * 0.35
    near = pts[(pts[:, 0] > xl - pad) & (pts[:, 0] < xr + pad) & (pts[:, 1] > quad[:, 1].min() - pad) &
               (pts[:, 1] < quad[:, 1].max() + pad)]
    if len(near) < MIN_POINTS:
        return None
    return {"quad": quad, "pts": near, "side": side}


def _area(q: np.ndarray) -> float:
    """Fläche eines Vierecks (Gaußsche Trapezformel)."""
    x, y = q[:, 0], q[:, 1]
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2)


def _warp(word: "Image.Image", quad_full: np.ndarray, frame: "Image.Image", alpha: float) -> None:
    """Wort-Bild perspektivisch auf das Viereck (volle Auflösung, Bildkoordinaten) legen."""
    from PIL import Image

    x0, y0 = np.floor(quad_full.min(axis=0)).astype(int)
    x1, y1 = np.ceil(quad_full.max(axis=0)).astype(int)
    x0, y0 = max(x0, 0), max(y0, 0)
    x1, y1 = min(x1, frame.width), min(y1, frame.height)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return
    w, h = word.size
    # PIL braucht die Abbildung Ziel -> Quelle
    hm = homography(quad_full - [x0, y0], np.array([[0, 0], [w, 0], [w, h], [0, h]], np.float32))
    if hm is None:
        return
    patch = word.transform((x1 - x0, y1 - y0), Image.PERSPECTIVE, tuple(hm.flatten()[:8]), Image.BICUBIC)
    if alpha < 1:
        a = patch.getchannel("A").point(lambda v: int(v * alpha))
        patch.putalpha(a)
    frame.alpha_composite(patch, (int(x0), int(y0)))


def apply(src: str, out: str, words: list[dict], box_y: int, box: int, fps: int, flat_y: int,
          enc: list[str]) -> dict:
    """Wörter auf Wände legen. ``words``: [{"a", "b", "png"}] (Zeiten im Video, Bild des Worts).
    Ton wird unverändert übernommen. Rückgabe: wie viele an der Wand klebten und wie viele flach standen."""
    from PIL import Image

    w_out, h_out = 1080, 1920
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", src, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           stdout=subprocess.PIPE)
    encp = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w_out}x{h_out}",
                             "-r", str(fps), "-i", "-", "-i", src, "-map", "0:v", "-map", "1:a", "-c:a", "copy",
                             *enc, out], stdin=subprocess.PIPE)
    n_frame, prev, stats = 0, None, {"wall": 0, "flat": 0}
    active: dict[int, dict] = {}
    imgs = {i: Image.open(w["png"]).convert("RGBA") for i, w in enumerate(words)}
    size = w_out * 3
    try:
        while True:
            raw = dec.stdout.read(size * h_out)
            if len(raw) < size * h_out:
                break
            t = n_frame / fps
            arr = np.frombuffer(raw, np.uint8).reshape(h_out, w_out, 3)
            g = _gray(arr[box_y:box_y + box])
            frame = None
            for i, w in enumerate(words):
                if not (w["a"] <= t < w["b"]):
                    active.pop(i, None)
                    continue
                st = active.get(i)
                if st is None:  # Wortbeginn: Wand suchen
                    im = imgs[i]
                    pl = place(g, im.width / im.height)
                    st = active[i] = ({"mode": "wall", "quad0": pl["quad"], "pts0": pl["pts"], "pts": pl["pts"].copy(),
                                       "ok": np.ones(len(pl["pts"]), bool)} if pl else {"mode": "flat"})
                    stats["wall" if pl else "flat"] += 1
                elif st["mode"] == "wall" and prev is not None:
                    st["pts"], ok = track(prev, g, st["pts"])
                    st["ok"] &= ok
                if frame is None:
                    frame = Image.fromarray(arr).convert("RGBA")
                k = min(1.0, (t - w["a"]) / 0.08)  # kurzes Einblenden
                if st["mode"] == "flat":
                    im = imgs[i]
                    sc = min(1.0, 620 / im.width)
                    small = im.resize((int(im.width * sc), int(im.height * sc)), Image.BICUBIC)
                    frame.alpha_composite(small, ((w_out - small.width) // 2, flat_y - small.height // 2))
                    continue
                if st["mode"] == "lost":
                    continue
                hm, frac = ransac_h(st["pts0"][st["ok"]], st["pts"][st["ok"]]) if st["ok"].sum() >= MIN_POINTS else (None, 0)
                if hm is None or frac < 0.5:
                    st["mode"] = "lost"
                    continue
                q = apply_h(hm, st["quad0"])
                area0, area = _area(st["quad0"]), _area(q)
                if not (0.4 < area / max(area0, 1e-6) < 2.5):
                    st["mode"] = "lost"
                    continue
                c = q.mean(axis=0)
                pop = 0.85 + 0.15 * k
                qf = ((q - c) * pop + c) * SCALE + [0, box_y]
                _warp(imgs[i], qf.astype(np.float32), frame, 0.92 * k)
            if frame is not None:
                arr = np.asarray(frame.convert("RGB"))
            encp.stdin.write(arr.tobytes())
            prev = g
            n_frame += 1
    finally:
        encp.stdin.close()
        encp.wait()
        dec.stdout.close()
        dec.wait()
    if encp.returncode:
        raise RuntimeError("Wand-Text: Kodieren fehlgeschlagen")
    return stats


def available() -> bool:
    try:
        import PIL  # noqa: F401
    except ImportError:
        return False
    return True


__all__ = ["apply", "place", "track", "ransac_h", "homography", "edge_slopes", "corners", "available", "Path"]
