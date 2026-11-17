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


def similarity(src: np.ndarray, dst: np.ndarray) -> tuple[float, np.ndarray, float] | None:
    """Verschiebung und Größe von src nach dst (ohne Drehung), robust gegen falsch verfolgte Punkte.
    Rückgabe (Skalierung, Verschiebung, mittlerer Restfehler) oder None bei zu wenigen Punkten."""
    keep = np.ones(len(src), bool)
    for _ in range(3):
        if keep.sum() < 6:
            return None
        cs, cd = np.median(src[keep], axis=0), np.median(dst[keep], axis=0)
        ds, dd = src[keep] - cs, dst[keep] - cd
        s = float(np.sqrt((dd ** 2).sum() / max((ds ** 2).sum(), 1e-6)))
        s = min(max(s, 0.6), 1.7)
        t = cd - s * cs
        err = np.hypot(*(src * s + t - dst).T)
        keep = err < max(2.0, 2.5 * float(np.median(err[keep])))
    return s, t, float(np.median(err[keep]))


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


MAX_PERSP = 1.3  # eine Seite des Worts höchstens so viel höher als die andere, sonst wirken Buchstaben verzerrt
MAX_SLOPE = 0.45  # Neigung der Schrift höchstens so stark


def limit_perspective(top: float, bot: float, qw: float, qh: float) -> tuple[float, float]:
    """Neigung der Ober- und Unterkante begrenzen. Laufen sie stark auseinander, wird ein Ende des Worts winzig und
    das andere riesig (gesehen bei "INFORMATION"). Die gemeinsame Neigung bleibt, nur der Unterschied wird kleiner."""
    mean = max(-MAX_SLOPE, min(MAX_SLOPE, (top + bot) / 2))
    maxd = 2 * qh * (MAX_PERSP - 1) / ((MAX_PERSP + 1) * qw)  # Höhe links/rechts = qh ± (top-bot)*qw/2
    diff = max(-maxd, min(maxd, top - bot))
    return mean + diff / 2, mean - diff / 2


def place(g: np.ndarray, aspect: float) -> dict | None:
    """Wand im Spielbild suchen und das Wort-Viereck dort festlegen (kleine Auflösung, Koordinaten im Quadrat)."""
    size = g.shape[0]
    best = None
    # Bereich ums Fadenkreuz (Bildmitte) bleibt frei: dort passiert der Kill (Nutzer: Wörter verdeckten Kills).
    # Seiten reichen nur bis 40 % / ab 60 % der Breite, die breite Fläche nur im oberen Teil (bis 38 % der Höhe).
    regions = {"left": (0.02, 0.40, 0.12, 0.62), "right": (0.60, 0.98, 0.12, 0.62), "wide": (0.08, 0.92, 0.10, 0.38)}  # oben bleibt Platz für den Killfeed-Eintrag
    found = {}
    for side, (fa, fb, ya, yb) in regions.items():
        x0, x1 = int(size * fa), int(size * fb)
        y0, y1 = int(size * ya), int(size * yb)
        pts = corners(g, (x0, y0, x1, y1))
        if len(pts) < MIN_POINTS * 2:
            continue
        sl = edge_slopes(g, (x0, y0, x1, y1))
        if sl is None:
            continue
        found[side] = (len(pts), side, (x0, y0, x1, y1), sl, pts)
    if not found:
        return None
    # breite Fläche bevorzugen, wenn sie genug Halt bietet: das Wort wird dort groß (gemessen am Nutzer-Video: links/
    # rechts allein ergab Wörter mit nur 31 % der Bildbreite, gute Wände blieben ungenutzt)
    side_best = max((v for k, v in found.items() if k != "wide"), key=lambda v: v[0], default=None)
    wide = found.get("wide")
    best = wide if wide and (side_best is None or wide[0] >= 1.2 * side_best[0]) else (side_best or wide)
    _, side, (x0, y0, x1, y1), (top, bot), pts = best
    qw = (x1 - x0) * (0.80 if side == "wide" else 0.85)
    qh = min(qw / aspect, (y1 - y0) * (0.6 if side == "wide" else 0.35))
    qw = qh * aspect
    top, bot = limit_perspective(top, bot, qw, qh)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    xl, xr = cx - qw / 2, cx + qw / 2
    quad = np.array([[xl, cy - qh / 2 - top * qw / 2], [xr, cy - qh / 2 + top * qw / 2],
                     [xr, cy + qh / 2 + bot * qw / 2], [xl, cy + qh / 2 - bot * qw / 2]], np.float32)
    # Punkte rund um das Viereck verfolgen (dieselbe Wand)
    m = size * 0.03  # Rand: das Wort ragt nie über das Spielbild hinaus
    sh = np.array([max(0.0, m - quad[:, 0].min()) - max(0.0, quad[:, 0].max() - (size - m)),
                   max(0.0, m - quad[:, 1].min()) - max(0.0, quad[:, 1].max() - (size - m))], np.float32)
    quad = quad + sh
    xl, xr = quad[:, 0].min(), quad[:, 0].max()
    pad = qw * 0.5
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


def inner_box(im: "Image.Image") -> tuple[float, float, float, float]:
    """Teil des Wort-Bilds, der auf die Wand gepasst wird (beim 3D-Schild ohne Tiefe und Leuchten)."""
    v = im.info.get("inner") if hasattr(im, "info") else None
    if v:
        try:
            x0, y0, x1, y1 = (float(p) for p in v.split(","))
            return x0, y0, x1, y1
        except ValueError:
            pass
    return 0.0, 0.0, float(im.width), float(im.height)


def word_aspect(im: "Image.Image") -> float:
    x0, y0, x1, y1 = inner_box(im)
    return (x1 - x0) / max(y1 - y0, 1.0)


def full_quad(im: "Image.Image", quad: np.ndarray) -> np.ndarray:
    """Viereck für das ganze Bild, wenn ``quad`` nur den inneren Teil (Vorderseite) trägt."""
    x0, y0, x1, y1 = inner_box(im)
    if (x0, y0, x1, y1) == (0.0, 0.0, float(im.width), float(im.height)):
        return quad
    hm = homography(np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], np.float32), quad)
    if hm is None:
        return quad
    return apply_h(hm, np.array([[0, 0], [im.width, 0], [im.width, im.height], [0, im.height]], np.float32)).astype(
        np.float32)


def apply(src: str, out: str, words: list[dict], box_y: int, box: int, fps: int, flat_y: int,
          enc: list[str], size: tuple[int, int] = (1080, 1920), box_x: int = 0) -> dict:
    """Wörter auf Wände legen. ``words``: [{"a", "b", "png"}] (Zeiten im Video, Bild des Worts).
    Ton wird unverändert übernommen. Rückgabe: wie viele an der Wand klebten und wie viele flach standen."""
    from PIL import Image

    w_out, h_out = size
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", src, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           stdout=subprocess.PIPE)
    encp = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w_out}x{h_out}",
                             "-r", str(fps), "-i", "-", "-i", src, "-map", "0:v", "-map", "1:a", "-c:a", "copy",
                             *enc, out], stdin=subprocess.PIPE)
    n_frame, prev, stats = 0, None, {"wall": 0, "flat": 0}
    active: dict[int, dict] = {}
    imgs = {i: Image.open(w["png"]).convert("RGBA") for i, w in enumerate(words)}
    row = w_out * 3
    try:
        while True:
            raw = dec.stdout.read(row * h_out)
            if len(raw) < row * h_out:
                break
            t = n_frame / fps
            arr = np.frombuffer(raw, np.uint8).reshape(h_out, w_out, 3)
            game = arr[box_y:box_y + box, box_x:box_x + box]
            g = _gray(game)
            frame = None
            for i, w in enumerate(words):
                if not (w["a"] <= t < w["b"]):
                    active.pop(i, None)
                    continue
                st = active.get(i)
                ncut = sum(1 for c in w.get("cuts") or [] if c <= t + 0.5 / fps)
                if st is not None and st.get("ncut", 0) != ncut:  # Schnitt: neue Szene, neue Wand suchen
                    st = None
                if st is None:  # Wortbeginn oder nach einem Schnitt: Wand suchen
                    im = imgs[i]
                    pl = place_on_wall(g, game[::SCALE, ::SCALE], word_aspect(im))
                    st = active[i] = ({"mode": "wall", "quad0": pl["quad"], "pts0": pl["pts"], "pts": pl["pts"].copy(),
                                       "ok": np.ones(len(pl["pts"]), bool)} if pl else {"mode": "flat"})
                    st["ncut"] = ncut
                    if ncut == 0:
                        stats["wall" if pl else "flat"] += 1
                elif st["mode"] == "wall" and prev is not None:
                    st["pts"], ok = track(prev, g, st["pts"])
                    st["ok"] &= ok
                if frame is None:
                    frame = Image.fromarray(arr).convert("RGBA")
                k = min(1.0, (t - w["a"]) / 0.08)  # kurzes Einblenden
                if st["mode"] == "flat":
                    im = imgs[i]
                    sc = min(0.7, w_out * 0.6 / im.width)
                    small = im.resize((int(im.width * sc), int(im.height * sc)), Image.BICUBIC)
                    frame.alpha_composite(small, ((w_out - small.width) // 2, flat_y - small.height // 2))
                    continue
                if st["mode"] == "lost":
                    continue
                sim = similarity(st["pts0"][st["ok"]], st["pts"][st["ok"]])
                if sim is None or sim[2] > 3.0:  # Wand verloren: kurz ausblenden statt springen
                    st["fade"] = st.get("fade", 1.0) - 1 / (0.15 * fps)
                    if st["fade"] <= 0 or "q" not in st:
                        # Wand verloren: das Wort für den Rest seiner Zeit flach zeigen statt verschwinden lassen
                        # (Nutzer: am Anfang fehlten Wörter, obwohl schon gesungen wurde)
                        st["mode"] = "flat"
                        continue
                    q = st["q"]
                else:
                    sc, tr, _err = sim
                    q_new = st["quad0"] * sc + tr
                    st["q"] = q = q_new if "q" not in st else st["q"] * 0.35 + q_new * 0.65  # glätten gegen Zittern
                    st["fade"] = 1.0
                k = min(k, st.get("fade", 1.0))
                c = q.mean(axis=0)
                pop = 0.85 + 0.15 * k
                qf = ((q - c) * pop + c) * SCALE + [box_x, box_y]
                _warp(imgs[i], full_quad(imgs[i], qf.astype(np.float32)), frame, k)
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


# --- Wand als Fläche (Nutzer: Wörter sollen wie im Vorbild "TALK" groß im richtigen Winkel auf einer Wand stehen) ---
CELL = 9            # Zellgröße in Pixeln der kleinen Auflösung (270 px Spielbild -> 30 x 30 Zellen)
COLOR_TOL = 22.0    # Farbabstand, bis zu dem benachbarte Zellen zur selben Fläche gehören
MIN_WALL_CELLS = 24
HORIZON = 0.5       # Höhe des Horizonts im Spielbild (Blick meist waagrecht): dort laufen Wandkanten zusammen
PERSP_MAX = 2.2     # eine Seite des Worts höchstens so viel höher als die andere


def wall_regions(rgb: np.ndarray, g: np.ndarray) -> list[dict]:
    """Glatte, einfarbige Flächen im Spielbild (Wände). Raster aus Zellen: ruhige Zellen (wenig Kanten) mit ähnlicher
    Farbe werden verbunden. Ausgeschlossen: Bildmitte (Fadenkreuz), Himmel (hell-blau am oberen Rand), Boden (ganz
    unter dem Horizont), unteres rechtes Viertel (Waffe), oberer Rand (Killfeed)."""
    size = g.shape[0]
    n = size // CELL
    gy, gx = np.gradient(g)
    mag = np.hypot(gx, gy)[: n * CELL, : n * CELL].reshape(n, CELL, n, CELL).mean(axis=(1, 3))
    col = rgb[: n * CELL, : n * CELL].astype(np.float32).reshape(n, CELL, n, CELL, 3).mean(axis=(1, 3))
    calm = mag <= max(np.percentile(mag, 55), 3.0)
    yy, xx = np.mgrid[0:n, 0:n]
    fx, fy = (xx + 0.5) / n, (yy + 0.5) / n
    blocked = ((np.abs(fx - 0.5) < 0.12) & (np.abs(fy - 0.5) < 0.16)) | (fy < 0.08) | ((fx > 0.55) & (fy > 0.62))
    calm &= ~blocked
    lab = -np.ones((n, n), int)
    regs = []
    for sy in range(n):
        for sx in range(n):
            if not calm[sy, sx] or lab[sy, sx] >= 0:
                continue
            k = len(regs)
            stack, cells = [(sy, sx)], []
            lab[sy, sx] = k
            ref = col[sy, sx].copy()
            while stack:
                y, x = stack.pop()
                cells.append((y, x))
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    v, u = y + dy, x + dx
                    if 0 <= v < n and 0 <= u < n and calm[v, u] and lab[v, u] < 0 and \
                            np.abs(col[v, u] - ref).max() <= COLOR_TOL and np.abs(col[v, u] - col[y, x]).max() <= COLOR_TOL * 0.6:
                        lab[v, u] = k
                        stack.append((v, u))
            c = np.array(cells)
            mean = col[c[:, 0], c[:, 1]].mean(axis=0)
            regs.append({"cells": c, "color": mean, "k": k})
    out = []
    for r in regs:
        c = r["cells"]
        if len(c) < MIN_WALL_CELLS:
            continue
        ys = (c[:, 0] + 0.5) / n
        rr, gg, bb = r["color"]
        lum = 0.299 * rr + 0.587 * gg + 0.114 * bb
        # Himmel: hell und bläulich, oder sehr hell und oben am Rand (der oberste Rand ist gesperrt, daher Zeile 1)
        if (bb > rr + 25 and lum > 140) or (c[:, 0].min() <= 1 and lum > 200):
            continue
        if ys.min() > HORIZON + 0.08:  # nur Boden
            continue
        if ys.max() < HORIZON - 0.25 and c[:, 0].min() <= 1:  # nur Himmel / Decke ganz oben
            continue
        r["mask"] = lab == r["k"]
        out.append(r)
    return out


def _fit_line(x: np.ndarray, y: np.ndarray) -> tuple[float, float] | None:
    """Gerade y = a*x + b, robust (zweimal ohne die schlechtesten 25 %)."""
    if len(x) < 4:
        return None
    keep = np.ones(len(x), bool)
    for _ in range(2):
        a, b = np.polyfit(x[keep], y[keep], 1)
        err = np.abs(y - (a * x + b))
        keep = err <= max(np.percentile(err, 75), 1.0)
        if keep.sum() < 4:
            break
    return float(a), float(b)


def wall_quad(reg: dict, size: int, aspect: float) -> tuple[np.ndarray, float] | None:
    """Wort-Viereck in einer Fläche: Ober- und Unterkante der Fläche je Spalte messen, als Geraden anpassen. Beide
    Geraden laufen zum selben Fluchtpunkt auf dem Horizont; das Wort liegt zwischen ihnen und hat deren Neigung.
    Rückgabe: Viereck (links oben, rechts oben, rechts unten, links unten) und Fläche des Worts."""
    m = reg["mask"]
    n = m.shape[0]
    cols = [u for u in range(n) if m[:, u].any()]
    if len(cols) < 4:
        return None
    xs, tops, bots = [], [], []
    for u in cols:
        rows = np.where(m[:, u])[0]
        # längstes zusammenhängendes Stück in dieser Spalte
        br = np.split(rows, np.where(np.diff(rows) > 1)[0] + 1)
        seg = max(br, key=len)
        if len(seg) < 2:
            continue
        xs.append((u + 0.5) * CELL)
        tops.append(seg[0] * CELL)
        bots.append((seg[-1] + 1) * CELL)
    xs, tops, bots = map(np.asarray, (xs, tops, bots))
    if len(xs) < 4:
        return None
    hz = size * HORIZON
    ft, fb = _fit_line(xs, tops), _fit_line(xs, bots)
    if ft is None or fb is None:
        return None
    # Kante am Bildrand oder an der gesperrten Mitte ist keine echte Wandkante: dann die andere Kante nehmen und den
    # Fluchtpunkt auf den Horizont legen
    top_real = np.median(tops) > CELL * 1.5
    bot_real = np.median(bots) < size - CELL * 1.5
    def through_vp(line, x_ref):
        a, b = line
        if abs(a) < 1e-3:
            return None
        vx = (hz - b) / a  # Schnittpunkt mit dem Horizont
        return vx
    vx = None
    if top_real and bot_real:
        at, bt_ = ft
        ab, bb_ = fb
        vy = None
        if abs(at - ab) > 1e-4:
            vx = (bb_ - bt_) / (at - ab)
            vy = at * vx + bt_
        # Waagrechte Wandkanten laufen auf den Horizont zu. Liegt der Schnittpunkt weit davon weg, ist eine der
        # Kanten keine Wandkante (z. B. zackiger Dachrand): dann nur die gleichmäßigere Kante nehmen.
        if vy is not None and abs(vy - hz) > size * 0.3:
            rt = np.median(np.abs(tops - (at * xs + bt_)))
            rb = np.median(np.abs(bots - (ab * xs + bb_)))
            if rt <= rb:
                bot_real = False
            else:
                top_real = False
            line = ft if top_real else fb
            vx = through_vp(line, xs.mean())
    else:
        line = ft if top_real else (fb if bot_real else None)
        if line is not None:
            vx = through_vp(line, xs.mean())
    x0, x1 = max(xs.min() - CELL / 2, size * 0.05), min(xs.max() + CELL / 2, size * 0.95)  # Rand fürs Leuchten
    if x1 - x0 < size * 0.15:
        return None

    def tb(x):  # Ober- und Unterkante der Fläche bei x (bezogen auf den Fluchtpunkt)
        t, b = ft[0] * x + ft[1], fb[0] * x + fb[1]
        if vx is not None and not (top_real and bot_real):
            # beide Kanten durch (vx, hz): Steigung je Kante aus ihrer mittleren Höhe
            xm = xs.mean()
            tm, bm = np.median(tops), np.median(bots)
            if abs(xm - vx) > 1:
                t = hz + (tm - hz) * (x - vx) / (xm - vx)
                b = hz + (bm - hz) * (x - vx) / (xm - vx)
        return t, b
    # Wort-Breite und Lage: so breit wie möglich bei passender Höhe (Wort füllt die Wand wie im Vorbild)
    best = None
    for frac in (0.95, 0.85, 0.75, 0.65, 0.55, 0.45):
        w = (x1 - x0) * frac
        for pos in (0.5, 0.3, 0.7, 0.15, 0.85):
            xl = x0 + (x1 - x0 - w) * pos
            xr = xl + w
            tl, bl = tb(xl)
            tr, br_ = tb(xr)
            hl, hr = bl - tl, br_ - tr
            if hl <= 4 or hr <= 4:
                continue
            ratio = max(hl, hr) / min(hl, hr)
            if ratio > PERSP_MAX:
                continue
            # Höhe des Worts aus dem Seitenverhältnis (in der Mitte gemessen), höchstens 80 % der Wandhöhe
            hm = (hl + hr) / 2
            hw = min(w / aspect, hm * 0.8)
            if hw < size * 0.07:
                continue
            f = hw / hm
            # senkrecht mittig auf der Wand, aber Mitte des Worts nicht unter 64 % der Bildhöhe
            f0 = (1 - f) / 2
            q = np.array([[xl, tl + f0 * hl], [xr, tr + f0 * hr], [xr, tr + (f0 + f) * hr], [xl, tl + (f0 + f) * hl]],
                         np.float32)
            # zu steil wirkt falsch (gesehen an zackigen Kanten): mittlere Neigung höchstens MAX_SLOPE
            if abs(((q[1, 1] - q[0, 1]) + (q[2, 1] - q[3, 1])) / 2 / w) > MAX_SLOPE:
                continue
            # Breite passt nur, wenn das Wort nicht schmaler gedrückt würde als es ist
            if w > hw * aspect * 1.35:
                continue
            area = float(w * hw)
            if q[:, 1].mean() > size * 0.66 or q[:, 1].min() < size * 0.06:
                continue
            # Viereck muss in der Fläche liegen (mind. 85 % der Zellen unter dem Wort gehören dazu)
            yy, xx = np.mgrid[0:n, 0:n]
            cx, cy = (xx + 0.5) * CELL, (yy + 0.5) * CELL
            inside = _in_quad(q, cx, cy)
            if inside.sum() < 3 or m[inside].mean() < 0.85:
                continue
            if best is None or area > best[1]:
                best = (q, area)
        if best is not None:
            break
    return best


def _in_quad(q: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Liegen die Punkte im (konvexen) Viereck?"""
    s = None
    for i in range(4):
        (ax, ay), (bx, by) = q[i], q[(i + 1) % 4]
        c = (bx - ax) * (y - ay) - (by - ay) * (x - ax)
        s = (c >= 0) if s is None else (s & (c >= 0))
    return s


def place_on_wall(g: np.ndarray, rgb: np.ndarray, aspect: float) -> dict | None:
    """Größte passende Wandfläche suchen und das Wort darauf legen; Punkte rundherum für die Verfolgung."""
    size = g.shape[0]
    cands = []
    for reg in wall_regions(rgb, g):
        r = wall_quad(reg, size, aspect)
        if r is not None:
            cands.append((r[1], r[0], reg))
    if not cands:
        return None
    _, quad, reg = max(cands, key=lambda c: c[0])
    pad = (quad[:, 0].max() - quad[:, 0].min()) * 0.6
    x0, x1 = int(max(quad[:, 0].min() - pad, 0)), int(min(quad[:, 0].max() + pad, size))
    y0, y1 = int(max(quad[:, 1].min() - pad, 0)), int(min(quad[:, 1].max() + pad, size))
    pts = corners(g, (x0, y0, x1, y1))
    if len(pts) < MIN_POINTS:
        return None
    return {"quad": quad, "pts": pts, "side": "wall"}
