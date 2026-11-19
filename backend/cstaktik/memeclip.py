"""Meme-Clip: aus einem CS2-Clip automatisch ein Hochformat-Video für Shorts schneiden (Prototyp).

Ablauf: eigene Kills im Clip finden -> Schnittplan -> mit ffmpeg rendern.

- Kills: Der Killfeed-Eintrag des eigenen Kills hat oben rechts einen roten Rahmen. Gesucht werden zwei lange
  rötliche Linien im Abstand einer Killfeed-Zeile mit dunklem Inneren. Kein Rahmen im Bild = kein Kill gefunden,
  dann wird nichts geraten.
- Schnitt je Kill: Anlauf in normalem Tempo ohne Zoom; im Kill-Moment schlägt der Zoom auf die Bildmitte zu (dort
  ist das Fadenkreuz) und der Kill läuft in Zeitlupe aus, mit Zähler und ruhig stehendem Killfeed-Eintrag. Kein
  Wackeln, kein langsamer Zoom. Standbild nur ganz am Ende mit der Summe. Totzeit zwischen Kills fällt weg.
- Ton: Spielton bleibt, Zeitlupe klingt tiefer. Der Einschlag-Sound wird selbst erzeugt (kein fremdes Material,
  also keine Rechte-Probleme). Eigene Sounds können später dazu.

Braucht ffmpeg und numpy. Läuft ohne KI und ohne Kosten.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

FPS_SCAN, W, H = 20, 1280, 720
CW, CH = int(W * 0.40), int(H * 0.24)  # Suchbereich oben rechts
OUT_W, OUT_H, OUT_FPS = 1080, 1920, 60  # 60 fps: Shooter-Aufnahmen haben meist 60, Bewegung wirkt flüssiger
GAP_S = 2.5  # so lange darf der Rahmen kurz verschwinden (Hintergrund), ohne als neuer Kill zu zählen

LEAD_S, HIT_BEFORE, HIT_AFTER, LAST_HOLD_S = 1.6, 0.30, 0.32, 0.9
SLOW, Z_HIT, PUNCH_S = 0.4, 1.0, 0.12  # Z_HIT 1.0: beim Kill springt das Bild nicht (kein Zoom, kein Blitz)  # Zeitlupe kurz vor dem Kill, Zoom schlägt in 0,09 s zu


def _run(cmd: list[str]) -> bytes:
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode:
        err = p.stderr.decode(errors="replace")
        raise RuntimeError(err[:300] + " ... " + err[-300:])
    return p.stdout


def duration(path: str) -> float:
    return float(_run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]))


def _boxes(fr) -> list[tuple[int, int, int, int]]:
    """Rote Rahmen in einem Frame-Ausschnitt (x0, y0, x1, y1 im Ausschnitt).

    Rahmenlinie = Kante: deutlich röter als 3 Pixel darüber UND darunter. Vorher galt jedes rote Pixel als Rahmen;
    vor orangem/rotem Hintergrund (Mirage-Tuch) war dann der ganze Bereich "Rahmen" und echte Einträge wurden
    sekundenlang nicht erkannt (Nutzer-Clip: Eintrag ab ca. 5 s sichtbar, erst bei 7,25 s erkannt) bzw. Hintergrund
    als Eintrag gezählt (falsche Mehrfach-Kills)."""
    import numpy as np

    f = fr.astype(np.float32)
    r = f[..., 0]
    q = (r - np.maximum(f[..., 1], f[..., 2])) / np.maximum(r, 1.0)  # Rot-Anteil
    up = np.vstack([np.full((3, q.shape[1]), -1.0, np.float32), q[:-3]])
    dn = np.vstack([q[3:], np.full((3, q.shape[1]), -1.0, np.float32)])
    red = (r > 90) & (q > 0.3) & (q - up > 0.12) & (q - dn > 0.12)
    rows = red.sum(axis=1)
    lines: list[list[int]] = []
    for y in range(fr.shape[0]):
        if rows[y] > 90:
            if lines and y - lines[-1][1] <= 2:
                lines[-1][1] = y
            else:
                lines.append([y, y])
    lum_all = fr.sum(axis=2)
    # Jede rote Linie darf Unterkante des einen und Oberkante des nächsten Eintrags sein (zwei Einträge direkt
    # untereinander teilen sich eine Linie).
    out = []
    for i in range(len(lines) - 1):
        gap = lines[i + 1][0] - lines[i][1]
        if not 10 <= gap <= 30:
            continue
        top = _run_from_right(red[lines[i][0]:lines[i][1] + 1].any(axis=0))
        bot = _run_from_right(red[lines[i + 1][0]:lines[i + 1][1] + 1].any(axis=0))
        if top is None or bot is None or abs(top[1] - bot[1]) > 8 or abs(top[0] - bot[0]) > 12:
            continue  # Ober- und Unterkante gleich lang und rechtsbündig
        x0, x1 = max(top[0], bot[0]), min(top[1], bot[1])
        if x1 - x0 < 90:
            continue
        xs = np.array([x0, x1])
        inner = lum_all[lines[i][1] + 2:lines[i + 1][0] - 1, xs.min() + 4:xs.max() - 3]
        if not inner.size:
            continue
        above = lum_all[max(lines[i][0] - 6, 0):max(lines[i][0] - 1, 0), xs.min():xs.max()]
        dark = np.median(inner) < 200 or (above.size and np.median(inner) < 0.8 * np.median(above))
        # Killfeed-Grund ist (dunkler als die Umgebung) und enthält helle Schrift
        if dark and (inner > 450).mean() > 0.03:
            out.append((int(xs.min()), lines[i][0], int(xs.max()), lines[i + 1][1]))
    return out


def _run_from_right(mask, max_gap: int = 3):
    """Zusammenhängendes Stück einer Rahmenlinie, vom rechtesten Pixel nach links (kleine Lücken erlaubt).
    Rote Pixel im Hintergrund links neben dem Eintrag zählen so nicht zur Breite. Rückgabe (x0, x1) oder None."""
    import numpy as np

    xs = np.where(mask)[0]
    if not len(xs):
        return None
    x1 = x0 = int(xs[-1])
    for x in xs[::-1][1:]:
        if x0 - x > max_gap + 1:
            break
        x0 = int(x)
    return x0, x1


def kills_from_counts(cnt: list[int], fps: int = FPS_SCAN) -> list[tuple[float, int]]:
    """Kill-Zeitpunkte aus der Anzahl roter Rahmen je Frame: (Sekunde, Frame-Index). Kurze Aussetzer werden
    überbrückt, ein neuer Kill zählt erst, wenn der Rahmen 0,2 s steht."""
    cnt = list(cnt)
    last, last_i = 0, -10**9
    for i, c in enumerate(cnt):  # Lücken füllen: fällt die Zahl kurz und kommt wieder, war es derselbe Eintrag
        if c >= last and c > 0:
            if i - last_i <= GAP_S * fps:
                for j in range(last_i + 1, i):
                    cnt[j] = max(cnt[j], min(last, c))
            last, last_i = c, i
        elif c > 0:
            last, last_i = c, i
    out, prev = [], 0
    for i in range(len(cnt) - 3):
        lo, hi = min(cnt[i:i + 4]), max(cnt[i:i + 4])
        if lo > prev:
            out += [(round(i / fps, 2), i)] * (lo - prev)
            prev = lo
        elif hi < prev:
            prev = hi
    return out


SIG_SAME = 0.5  # Ähnlichkeit (0..1) ab der zwei Einträge als derselbe gelten
SIG_CONFIRM = 3  # so oft muss ein neuer Eintrag gesehen werden (vor hellem Hintergrund fehlen einzelne Bilder)
SIG_PATCH_W = 70  # rechtes Ende des Eintrags (Gegnername) für den Fingerabdruck
SIG_NCC = 0.9  # ab dieser Kanten-Korrelation derselbe Eintrag
SIG_NCC_NEAR, SIG_NEAR_S = 0.6, 0.6  # an derselben Stelle kurz danach genügt weniger Ähnlichkeit
SIG_BACK_S = 1.5  # nach Aussetzer bis 1,5 s am selben Platz mit gleicher Breite: derselbe Eintrag
SIG_GAP = 6.0  # so lange wird ein Eintrag wiedererkannt, auch wenn er zwischendurch nicht erkannt wurde
SIG_GROW = (0.4, 8)  # neuer Kasten bis 0,4 s nach einem neuen Eintrag auf gleicher Höhe (±8 px) = derselbe, wächst


def _sig(fr, box):
    """Fingerabdruck eines Eintrags: Breite und das Kantenbild des rechten Endes (Gegnername, 70 px) in voller
    Auflösung. Kanten statt Helligkeit: der halb durchsichtige Hintergrund stört kaum. Gemessen an echten Clips:
    gleicher Eintrag 0,98-1,00, verschiedene Kills ~0,80 (gröbere Fingerabdrücke trennten nicht)."""
    import numpy as np

    x0, y0, x1, y1 = box
    p = fr[y0 + 3:y1 - 2, max(x1 - 3 - SIG_PATCH_W, x0 + 4):x1 - 3].astype(np.float32).mean(axis=2)
    if p.shape[0] < 6 or p.shape[1] < 30:
        return None
    e = np.abs(np.diff(p, axis=1))[:-1] + np.abs(np.diff(p, axis=0))[:, :-1]
    return {"w": x1 - x0, "e": (e - e.mean()) / (e.std() + 1e-6)}


def _ncc(a, b) -> float:
    """Ähnlichkeit zweier Kantenbilder mit kleiner Verschiebungssuche (±1 px senkrecht, ±3 px waagerecht)."""
    import numpy as np

    best = -1.0
    for dy in (-1, 0, 1):
        for dx in (-3, -2, -1, 0, 1, 2, 3):
            A = a[max(dy, 0):a.shape[0] + min(dy, 0), max(dx, 0):a.shape[1] + min(dx, 0)]
            B = b[max(-dy, 0):b.shape[0] + min(-dy, 0), max(-dx, 0):b.shape[1] + min(-dx, 0)]
            h, w = min(A.shape[0], B.shape[0]), min(A.shape[1], B.shape[1])
            if h < 4 or w < 20:
                continue
            best = max(best, float((A[:h, :w] * B[:h, :w]).mean()))
    return best


def _same(a, b) -> float:
    """1 = derselbe Eintrag (ähnliche Breite ±12 px, Kantenbild des Gegnernamens ≥ SIG_NCC), sonst 0."""
    if abs(a["w"] - b["w"]) > 12:
        return 0.0
    return 1.0 if _ncc(a["e"], b["e"]) >= SIG_NCC else 0.0


def kills_from_boxes(frames_boxes: list[list[tuple]], sigs: list[list], fps: int = FPS_SCAN) -> list[tuple[float, int, tuple]]:
    """Kills aus den Einträgen je Bild, über ihren Fingerabdruck: Ein Eintrag mit neuem Aussehen ist ein neuer Kill,
    egal wie viele gerade sichtbar sind. Verschwindet ein Eintrag kurz (Mündungsfeuer, heller Hintergrund) und kommt
    gleich aussehend wieder, bleibt es derselbe. Vorher wurde nur gezählt: verschwand ein alter Eintrag, während ein
    neuer kam, ging der Kill verloren (nachgestellt mit einem echten Clip: 2 von 4 Kills erkannt)."""
    import numpy as np

    entries: list[dict] = []  # {"sigs", "first", "last", "hits", "box"}
    for i, (boxes, ss) in enumerate(zip(frames_boxes, sigs)):
        used = set()
        for box, sg in zip(boxes, ss):
            if sg is None:
                continue
            best, bi = 0.0, None
            for k, e in enumerate(entries):
                if k in used or i - e["last"] > SIG_GAP * fps or abs(e["box"][2] - e["box"][0] - sg["w"]) > 12:
                    continue
                sim = max(_ncc(x["e"], sg["e"]) for x in e["sigs"])
                # kurz zuvor an derselben Stelle mit gleicher Breite: derselbe Eintrag, solange nicht völlig anders
                near = (i - e["last"] <= SIG_NEAR_S * fps and abs(e["box"][1] - box[1]) <= 4
                        and abs(e["box"][2] - e["box"][0] - sg["w"]) <= 6)
                # Eintrag rückt einen Platz hoch, wenn ein älterer darüber abläuft (gleiche Breite, ~21 px höher)
                moved = (i - e["last"] <= 1.5 * fps and 15 <= e["box"][1] - box[1] <= 26
                         and abs(e["box"][2] - e["box"][0] - sg["w"]) <= 6 and sim >= 0.75)
                # gleicher Platz, gleiche Breite (±12), bis 1,5 s später: derselbe, auch wenn der Hintergrund hinter dem
                # halb durchsichtigen Eintrag völlig anders ist (echte Clips: Ähnlichkeit fiel dann bis 0,29)
                back = (i - e["last"] <= SIG_BACK_S * fps and abs(e["box"][1] - box[1]) <= 4
                        and abs(e["box"][2] - e["box"][0] - sg["w"]) <= 12)
                ok = sim >= SIG_NCC or (near and sim >= SIG_NCC_NEAR) or moved or back
                near = near or moved
                if ok and sim + (1.0 if near else 0.0) > best:
                    best, bi = sim + (1.0 if near else 0.0), k
            if bi is None:  # Eintrag kommt gerade erst vollständig ins Bild (Breite wächst, z. B. Assist "+")
                for k, e in enumerate(entries):
                    if k not in used and i - e["first"] <= SIG_GROW[0] * fps and abs(e["box"][1] - box[1]) <= SIG_GROW[1]:
                        bi = k
                        break
            if bi is None:
                entries.append({"sigs": [sg], "first": i, "last": i, "hits": 1, "box": box, "box0": box})
                used.add(len(entries) - 1)
            else:
                e = entries[bi]
                e["last"], e["hits"], e["box"] = i, e["hits"] + 1, box
                e["sigs"] = (e["sigs"] + [sg])[-6:]
                used.add(bi)
    # Position beim ersten Erscheinen (später rückt der Eintrag ggf. hoch, wenn ältere ablaufen)
    out = [(round(e["first"] / fps, 2), e["first"], e["box0"]) for e in entries if e["hits"] >= SIG_CONFIRM]
    return sorted(out)


def detect(path: str) -> list[dict]:
    """Eigene Kills im Clip: [{"t": Sekunde, "box": (x0, y0, x1, y1) im 1280x720-Bild}]."""
    import numpy as np

    raw = _run(["ffmpeg", "-v", "error", "-i", path, "-vf", f"fps={FPS_SCAN},scale={W}:{H},crop={CW}:{CH}:{W - CW}:0",
                "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
    frames = np.frombuffer(raw, np.uint8).reshape(-1, CH, CW, 3).astype(np.int16)
    boxes = [_boxes(f) for f in frames]
    sigs = [[_sig(f, bx) for bx in b] for f, b in zip(frames, boxes)]
    cands = []
    for t, i, bx in kills_from_boxes(boxes, sigs):
        i0 = _first_seen(frames, i, bx)
        cands.append({"t": round(i0 / FPS_SCAN, 2), "box": (bx[0] + W - CW, bx[1], bx[2] + W - CW, bx[3])})
    return cands


def _first_seen(frames, i: int, box, back_s: float = 1.0) -> int:
    """Erstes Bild, in dem der Eintrag schon zu sehen war: rückwärts, solange am selben Platz (±4 px Höhe, gleicher
    rechter Rand) eine rote Rahmen-Kante oben und unten steht (lockerer als _boxes, das beim Einblenden die ersten
    Bilder verwirft; gemessen bis 0,55 s zu spät)."""
    import numpy as np

    x0, y0, x1, y1 = box
    first, misses = i, 0
    for j in range(i - 1, max(i - int(back_s * FPS_SCAN), 0) - 1, -1):
        f = frames[j].astype(np.float32)
        ok = True
        for y in (y0, y1):
            ya = max(y - 6, 0)
            band = f[ya:y + 7, max(x1 - 90, 0):x1 + 1]
            r = band[..., 0]
            q = (r - np.maximum(band[..., 1], band[..., 2])) / np.maximum(r, 1.0)
            up = np.vstack([np.full((3, q.shape[1]), -1.0, np.float32), q[:-3]])
            dn = np.vstack([q[3:], np.full((3, q.shape[1]), -1.0, np.float32)])
            edge = (r > 90) & (q > 0.3) & (q - up > 0.12) & (q - dn > 0.12)  # wie in _boxes: Kante, kein Hintergrund
            rows = edge.sum(axis=1)[4:-4] if edge.shape[0] > 8 else edge.sum(axis=1)  # nur ±2 px um die Kante
            if not len(rows) or rows.max() < 45:
                ok = False
                break
        if not ok:
            misses += 1
            if misses > 2:  # einzelne schwache Bilder (heller Hintergrund) überspringen
                break
            continue
        misses = 0
        first = j
    return first


def detect_all(srcs: list[str]) -> list[dict]:
    """Kills aus mehreren Clips in Reihenfolge der Clips; jeder Kill kennt seinen Clip und dessen Länge."""
    out = []
    for src in srcs:
        d = duration(src)
        out += [{**k, "src": src, "dur": d} for k in detect(src)]
    return out


def plan(kills: list[dict], dur: float) -> list[dict]:
    """Schnittplan: Segmente in Reihenfolge. kind: lead (normal) | hit (Zoom-Schlag, Kill läuft in Zeitlupe aus) |
    hold (kurzes Standbild am Ende mit der Summe)."""
    segs: list[dict] = []
    end_prev = 0.0
    n = len(kills)
    cur = None
    for k, kill in enumerate(kills, start=1):
        dur = kill.get("dur", dur)
        if kill.get("src") != cur:  # neuer Clip: wieder von vorne
            cur, end_prev = kill.get("src"), 0.0
        t = max(kill["t"] - 0.10, 0.0)  # der Killfeed-Eintrag erscheint kurz nach dem Kill
        hit0, hit1 = max(t - HIT_BEFORE, end_prev), min(t + HIT_AFTER, dur)
        lead0 = max(hit0 - LEAD_S, end_prev)
        if hit0 - lead0 > 0.15:
            segs.append({"kind": "lead", "ss": round(lead0, 3), "d": round(hit0 - lead0, 3), "src": kill.get("src")})
        segs.append({"kind": "hit", "ss": round(hit0, 3), "d": round(hit1 - hit0, 3), "box": kill["box"], "src": kill.get("src"),
                     "feed_at": round(min(kill["t"] + 0.2, dur - 0.05), 3), "text": f"+{k}",
                     "kill_at": round((t - hit0) / SLOW, 3)})  # Kill-Moment im fertigen Segment: Zähler, Killfeed, Sound
        if k == n:
            segs.append({"kind": "hold", "ss": round(max(hit1 - 0.03, 0), 3), "d": LAST_HOLD_S, "box": kill["box"], "src": kill.get("src"),
                         "feed_at": round(min(kill["t"] + 0.2, dur - 0.05), 3), "text": f"{n} KILLS" if n > 1 else "KILL"})
        end_prev = hit1
    return segs


FONT_FILE = Path(__file__).parent / "static" / "fonts" / "Anton-Regular.ttf"  # mitgeliefert (SIL Open Font License)


def _font() -> str:
    if FONT_FILE.exists():
        return str(FONT_FILE)
    for want in ("Inter:style=ExtraBold", "DejaVu Sans:style=Bold", ":bold"):
        p = subprocess.run(["fc-match", "-f", "%{file}", want], capture_output=True, text=True).stdout.strip()
        if p:
            return p
    return ""


BOX, BOX_Y = 1080, 440  # Spielbild als Quadrat in der Mitte: zeigt mehr Breite als ein voller Hochformat-Schnitt
BOX_X = 0  # Querformat: Bereich für die Wand-Suche (mittleres Quadrat)
LANDSCAPE = False
SHOW_COUNTER = False  # "+1"-Zähler und "3 KILLS" am Ende (Vorbild: nichts davon)
SHOW_FEED = True  # eigener Killfeed-Eintrag (Name, Waffe, Gegner) während des Kills; im Hochformat sonst abgeschnitten
KILL_FX = False  # Schwarz-Weiß und Kontrastschlag beim Kill (Nutzer: zu viel Edit, nicht clean)
FORMATS = {"hoch": "Hochformat 9:16 (TikTok, Shorts, Reels)", "quer": "Querformat 16:9 (YouTube)"}


def set_layout(fmt: str = "hoch") -> None:
    """Ausgabeformat: "hoch" 1080x1920 (Spielbild als Quadrat auf unscharfem Hintergrund) oder "quer" 1920x1080
    (ganzes Spielbild wie im Vorbild). Gilt für den nächsten Schnitt (es läuft immer nur einer)."""
    global OUT_W, OUT_H, BOX, BOX_Y, BOX_X, LANDSCAPE
    LANDSCAPE = fmt == "quer"
    if LANDSCAPE:
        OUT_W, OUT_H, BOX, BOX_Y, BOX_X = 1920, 1080, 1080, 0, 420
    else:
        OUT_W, OUT_H, BOX, BOX_Y, BOX_X = 1080, 1920, 1080, 440, 0


# Farbabstimmung, gemessen am TikTok-Vorbild des Nutzers (Spielbild): Sättigung 0,48, Wärme (R−B) 0,23; unser
# Ergebnis vorher 0,28 / 0,06. Mit diesen Werten am echten Clip gemessen: 0,44 / 0,17, ohne mehr ausgefressene Stellen.
SAT = 1.6
# Schärfe: 720p-Aufnahmen werden fürs Quadrat 1,5-fach hochgerechnet. Gemessen an einem echten Clip (Varianz des
# Laplace-Filters): Quelle 286, bisher (bilinear) 106, Lanczos 172, Lanczos + leichtes Nachschärfen 283.
SHARPEN = "unsharp=5:5:0.5,"
GRADE = "colorbalance=rm=0.08:bm=-0.08:rh=0.05:bh=-0.06,"
LOOK = GRADE + "setsar=1,vignette=angle=PI/10"  # Ecken etwa 19 % dunkler (PI/6 waren 46 %); setsar: sonst bei nicht quadratischen Pixeln harte schwarze Ellipse: der Blick bleibt in der Mitte, wo der Kill passiert
LUMA_TARGET = 0.0  # 0 = Mittelwert der Clips (in make_beat gesetzt); Helligkeit jedes Clips wird dorthin geschoben


def luma(src: str) -> float:
    """Mittlere Helligkeit eines Clips (0..255), aus wenigen kleinen Bildern."""
    import numpy as np

    raw = _run(["ffmpeg", "-v", "error", "-i", src, "-vf", "fps=2,scale=64:36,format=gray", "-f", "rawvideo", "-"])
    a = np.frombuffer(raw, np.uint8)
    return float(a.mean()) if a.size else 128.0


def brightness_offsets(lumas: dict) -> dict:
    """Helligkeits-Ausgleich je Clip (für eq=brightness), damit Clips von hellen und dunklen Maps wie aus einem Guss
    wirken. Nur sanft (höchstens ±0,08), damit nichts ausgewaschen oder abgesoffen aussieht."""
    if len(lumas) < 2:
        return {k: 0.0 for k in lumas}
    tgt = sum(lumas.values()) / len(lumas)
    return {k: round(max(-0.08, min(0.08, (tgt - v) / 255 * 0.8)), 3) for k, v in lumas.items()}


def _vf(src: str, z: str, out: str, b: float = 0.0) -> str:
    """Hochformat-Aufbau: unscharfer, dunkler Hintergrund aus demselben Bild, darauf das Spielbild als Quadrat
    (Zoom auf die Bildmitte, dort ist das Fadenkreuz). Oben bleibt Platz für den Killfeed, unten für den Zähler,
    so verdeckt nichts den Kill. Kein Wackeln. Querformat: das ganze Spielbild, ohne Hintergrund."""
    if LANDSCAPE:
        return (f"{src}scale=w='2*trunc({OUT_W // 2}*({z}))':h=-2:eval=frame:flags=lanczos,crop={OUT_W}:{OUT_H},"
                f"{SHARPEN}eq=contrast=1.06:saturation={SAT}:brightness={b},{LOOK}[{out}]")
    return (f"{src}split[m{out}][g{out}];"
            f"[g{out}]scale=-2:480,crop=270:480,boxblur=10:2,eq=brightness=-0.22,scale={OUT_W}:{OUT_H}[b{out}];"
            f"[m{out}]scale=-2:'2*trunc({BOX // 2}*({z}))':eval=frame:flags=lanczos,crop={BOX}:{BOX},{SHARPEN}eq=contrast=1.06:saturation={SAT}:brightness={b},{LOOK}[f{out}];"
            f"[b{out}][f{out}]overlay=0:{BOX_Y}[{out}]")


LOUDNORM = "loudnorm=I=-14:TP=-1:LRA=11,aresample=48000"
# Ton wie im Vorbild (gemessen an einem viralen CS2-Edit: −10,8 LUFS, Dynamik LRA 3,9, ~0,9 hörbar herausstechende
# Schüsse je Sekunde; unser Video vorher −13,7 LUFS, LRA 1,0, 0,2 Schüsse je Sekunde): Spielton lauter, Musik bei jedem
# Schuss kurz abgesenkt, Kill-Schuss extra laut, Lautheit per Messung + gleichmäßiger Verstärkung statt Kompression.
TARGET_LUFS = -11.0
GAME_VOL = 0.6  # Spielton im Anlauf/Schnitt (vorher 0,3)
SHOT_VOL = 1.15  # eingerastete Schüsse (vorher 0,85)
KILL_VOL = 2.0  # Kill-Schuss (vorher 0,9): der Treffer soll kurz deutlich lauter sein
KILL_DUCK = 0.6  # Musik beim Kill-Schuss um 60 % leiser (vorher 35 %)
SHOT_DIP, SHOT_DIP_S = 0.45, 0.10  # Musik bei jedem Schuss um 45 % leiser, für etwa 0,1 s
ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p", "-r", str(OUT_FPS),
       "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "192k"]
BOOM = "0.95*sin(2*PI*(48+60*exp(-t*22))*t)*exp(-t*5.5)+0.25*(random(0)*2-1)*exp(-t*60)"


def _feed_png(src: str, seg: dict, tmp: Path, stem: str) -> Path:
    """Der eigene Killfeed-Eintrag als kleines Bild (steht ruhig oben, ohne Bewegung)."""
    x0, y0, x1, y1 = seg["box"]
    pad = 3
    out = tmp / f"{stem}_kf.png"
    _run(["ffmpeg", "-v", "error", "-y", "-ss", str(seg["feed_at"]), "-i", src, "-frames:v", "1", "-vf",
          f"scale={W}:{H},crop={x1 - x0 + 2 * pad}:{y1 - y0 + 2 * pad}:{max(x0 - pad, 0)}:{max(y0 - pad, 0)},"
          "scale=680:-2:flags=lanczos", str(out)])
    return out


def _draw(text: str, font: str) -> str:
    if not font:
        return "null"
    text = text.replace(":", r"\:").replace("'", "")
    size, color = (200, "white") if " " in text or text == "KILL" else (260, "0xFFD23F")  # Zähler groß und gelb
    return (f"drawtext=fontfile='{font}':text='{text}':fontsize={size}:fontcolor={color}:borderw=16:bordercolor=black:"
            f"x=(w-text_w)/2:y=110")  # oben: unten und rechts liegt die Oberfläche von TikTok/Shorts


def _render_seg(src: str, seg: dict, out: Path, tmp: Path, font: str) -> None:
    src = seg.get("src") or src
    ss, d = seg["ss"], seg["d"]
    if seg["kind"] == "lead":  # normales Tempo, kein Zoom
        _run(["ffmpeg", "-v", "error", "-y", "-ss", str(ss), "-t", str(d), "-i", src, "-filter_complex",
              f"[0:v]scale={W}:{H},setpts=PTS-STARTPTS[s];{_vf('[s]', '1', 'c')};[c]fps={OUT_FPS}[v];"
              "[0:a]aresample=48000,asetpts=PTS-STARTPTS,afade=t=in:d=0.03[a]",
              "-map", "[v]", "-map", "[a]", *ENC, str(out)])
        return
    kf = _feed_png(src, seg, tmp, out.stem)
    if seg["kind"] == "hold":  # Standbild nur ganz am Ende: Zoom bleibt, Summe steht
        png = tmp / f"{out.stem}.png"
        _run(["ffmpeg", "-v", "error", "-y", "-ss", str(ss), "-i", src, "-frames:v", "1", "-vf", f"scale={W}:{H}", str(png)])
        fc = (f"{_vf('[0:v]', str(Z_HIT), 'bg')};[bg][1:v]overlay=(W-w)/2:{BOX_Y - 115}[v0];[v0]{_draw(seg['text'], font)},fps={OUT_FPS}[v];"
              f"aevalsrc='0.5*({BOOM})':d={d}:s=48000,aformat=channel_layouts=stereo[a]")
        _run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-framerate", str(OUT_FPS), "-t", str(d), "-i", str(png),
              "-i", str(kf), "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", str(d), *ENC, str(out)])
        return
    # hit: Zoom schlägt im Kill-Moment zu, der Kill läuft in Zeitlupe aus; Zähler und Killfeed stehen ruhig
    od, ka = d / SLOW, seg.get("kill_at", 0.0)
    draw = _draw(seg["text"], font)
    draw = draw if draw == "null" else draw + f":enable='gte(t,{ka})'"
    z = f"1+({Z_HIT}-1)*min(t/{PUNCH_S}\\,1)"
    fc = (f"[0:v]scale={W}:{H},setpts=(PTS-STARTPTS)/{SLOW}[s];{_vf('[s]', z, 'bg')};"
          f"[bg][1:v]overlay=(W-w)/2:{BOX_Y - 115}:enable='gte(t,{ka})'[v0];[v0]{draw},fps={OUT_FPS}[v];"
          f"[0:a]aresample=48000,asetpts=PTS-STARTPTS,asetrate=48000*{SLOW},aresample=48000,volume=0.8[ga];"
          f"aevalsrc='{BOOM}':d={od:.3f}:s=48000,aformat=channel_layouts=stereo,adelay={int(ka * 1000)}:all=1[bm];"
          f"[ga][bm]amix=inputs=2:duration=first:normalize=0[a]")
    _run(["ffmpeg", "-v", "error", "-y", "-ss", str(ss), "-t", str(d), "-i", src, "-i", str(kf),
          "-filter_complex", fc, "-map", "[v]", "-map", "[a]", *ENC, str(out)])


def make(src: str, out: str, progress=None) -> dict:
    """Clip analysieren und Hochformat-Video schreiben. Rückgabe: Kills, Segmente, Länge. Ohne Kill: ValueError."""
    set_layout("hoch")
    srcs = [src] if isinstance(src, str) else list(src)
    src = srcs[0]
    kills = detect_all(srcs)
    if not kills:
        raise ValueError("Im Clip wurde kein eigener Kill gefunden (kein rot umrandeter Killfeed-Eintrag oben rechts).")
    segs = plan(kills, duration(src))
    font = _font()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        files = []
        for i, seg in enumerate(segs):
            f = tmp / f"s{i:03d}.mp4"
            _render_seg(src, seg, f, tmp, font)
            files.append(f)
            if progress:
                progress(i + 1, len(segs))
        ins = [x for f in files for x in ("-i", str(f))]
        n = len(files)
        fc = "".join(f"[{i}:v][{i}:a]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a0];[a0]alimiter=limit=0.95,{LOUDNORM}[a]"
        _run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
              "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(OUT_FPS),
              "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out])
    return {"kills": kills, "segments": segs, "seconds": round(duration(out), 2)}


# --- Beat-Edit: Musik gibt den Takt vor, jeder Kill fällt genau auf einen Schlag ------------------------------------
# Warum so: Schnitte auf dem Schlag werden als angenehmer erlebt als Schnitte daneben (Studien zu Musikvideos, u. a.
# Wenberg & Carlgren 2021). Deshalb: Kills und Schnitte nur auf Schlägen, fester Abstand zwischen den Kills (ein Takt),
# der erste Kill früh (die ersten Sekunden entscheiden, ob jemand dranbleibt), und das Tempo gleitet in die Zeitlupe,
# statt zu springen.

RAMP_V0, RAMP_V1 = 1.3, 0.75  # Anlauf beginnt leicht schnell (vorher 1,6: wirkte wie Vorspulen) und gleitet in die Zeitlupe; der Kill selbst läuft mit SLOW
HIT_SLOW = 0.75  # Tempo während des Kills: leichte Zeitlupe (vorher 0,5; Nutzer: "viel zu viel Edit")
# letzte 20 % der Kill-Zeitlupe: Tempo steigt sanft (bis 1,4×), Schnitt in der Bewegung. Vorher 30 % / 2,0×: gemessen
# sprang die Bewegung am Kill-Ende auf das 4- bis 6-Fache, der Kill wirkte "weggerissen" (Nutzer-Rückmeldung).
OUT_FRAC, OUT_V = 0.2, 1.4
HIT_SLOW_LAST = 0.75  # auch der letzte Kill nur leicht langsamer: gleichmäßigster Takt ohne Zwischenbilder
# Echte Zwischenbilder beim Kill (Bewegung wird geschätzt, wie bei Profi-Zeitlupe) statt Überblenden mit Doppelbildern.
# Kostet Rechenzeit (etwa 7 s je Sekunde Zeitlupe), deshalb nur beim Kill selbst. False = wie vorher überblenden.
MCI = True
MCI_VF = f"minterpolate=fps={OUT_FPS}:mi_mode=mci:mc_mode=obmc:me_mode=bilat:me=ds:search_param=16:scd=none"
# Zwischenbilder: "none" = nur echte Bilder der Aufnahme. Die berechneten (mci) zerfielen bei schnellen Bewegungen in
# verschmierte Blöcke (Nutzer: "verwischt alles komisch"), Überblenden (blend) legt Bilder übereinander.
INTERP = "none"


def interp_vf() -> str:
    return {"mci": MCI_VF, "blend": f"minterpolate=fps={OUT_FPS}:mi_mode=blend"}.get(INTERP, "null")
MAX_WORDS = 40
WALL_MAX_ASPECT = 7.0  # Vorderseite des 3D-Schilds (Breite/Höhe); ob die Wand groß genug ist, prüft wall_text (sonst flach)
WALL_MIN_S = 0.22  # so lange muss ein Wort an der Wand stehen können
WALL_TEXT = True  # Songtext teils auf Wände legen (wall_text.py)
WORD_LEAD_S = 0.04  # Text minimal vor dem Gesang: späterer Text fällt eher auf als früherer
MIN_WORD_S = 0.28  # kürzer steht ein Wort nicht lesbar im Bild
SHOT_SPEED, SHOT_BACK = 1.15, 1.0  # eigener Schnitt vor dem Kill: leicht schnell, etwa 1 s früher im Clip
LOOP_S = 0.3  # Übergang am Ende zurück zum ersten Bild
# Keine künstliche Bewegungsunschärfe mehr: bei schnellen Mausbewegungen lagen drei Bilder sichtbar übereinander
# (Nutzer: "verschwimmt"). Am echten Clip gemessen: Anlauf ohne sie fast doppelt so scharf (279 -> 466).
BLUR = ""
CUT_POP = "1+0.06*exp(-13*t)"       # Zoom-Schlag bei jedem Bildwechsel (klingt in etwa 0,2 s ab, danach ruhig)


def ramp_fit(gap: float, avail: float, v0max: float = RAMP_V0, v1: float = RAMP_V1) -> tuple[float, float, float]:
    """Gleitendes Tempo von v0 auf v1, das genau ``gap`` Sekunden füllt. Rückgabe (Material in s, v0, v1).
    Gibt es weniger Material als gewünscht, beginnt der Anlauf langsamer; reicht es gar nicht, läuft er gleichmäßig."""
    from math import log

    need = lambda v0: gap * (v0 - v1) / log(v0 / v1)  # noqa: E731
    if avail >= need(v0max):
        return round(need(v0max), 3), v0max, v1
    if avail > gap * v1 * 1.05:
        lo, hi = v1 * 1.01, v0max
        for _ in range(40):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if need(mid) < avail else (lo, mid)
        return round(need(lo), 3), round(lo, 4), v1
    v = max(avail / gap, 0.05)
    return round(avail, 3), round(v, 4), round(v, 4)


def motion(src: str, fps: int = 10):
    """Bewegung je Zeitpunkt im Clip (mittlerer Bildunterschied, klein gerechnet). Für die Wahl der Schnittpunkte."""
    import numpy as np

    raw = _run(["ffmpeg", "-v", "error", "-i", src, "-vf", f"fps={fps},scale=96:54,format=gray", "-f", "rawvideo", "-"])
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 54, 96).astype(np.int16)
    m = np.abs(np.diff(fr, axis=0)).mean(axis=(1, 2))
    return fps, np.concatenate([[0.0], m])


def onset_cut(mot, lo: float, hi: float) -> float:
    """Schnittpunkt im Bereich [lo, hi] dort, wo Bewegung einsetzt (größter Anstieg). Ohne Daten: hi."""
    if mot is None or hi - lo < 0.15:
        return hi
    fps, m = mot
    best, bt = -1e9, hi
    for i in range(int(lo * fps) + 1, min(int(hi * fps), len(m) - 2) + 1):
        rise = m[i + 1] + m[i] - m[i - 1] - m[max(i - 2, 0)]
        if rise > best:
            best, bt = rise, i / fps
    return round(max(lo, min(bt, hi)), 3)


def shots(src: str) -> list[float]:
    """Schuss-Zeitpunkte im Spielton: kurze, laute Knalle (Onset-Spitzen deutlich über dem Rest), mind. 70 ms Abstand."""
    from cstaktik import beats as beatmod
    import numpy as np

    try:
        env = beatmod.onset_envelope(src)
    except Exception:  # noqa: BLE001 - Clip ohne Ton: keine Schüsse
        return []
    fps = beatmod.SR / beatmod.HOP
    e = np.maximum(env, 0)
    thr = e.mean() + 3 * e.std()
    out: list[float] = []
    for i in range(1, len(e) - 1):
        if e[i] > thr and e[i] >= e[i - 1] and e[i] >= e[i + 1]:
            t = i / fps
            if not out or t - out[-1] >= 0.07:
                out.append(round(t, 3))
    return out


SYNC_MIN, SYNC_MAX = 0.5, 1.4  # erlaubtes Tempo zwischen zwei Schüssen beim Einrasten auf den Beat
SYNC_JUMP = 2.5  # höchstens so viel schneller/langsamer als das Stück daneben: sonst wirkt der Wechsel wie ein Ruckler
# Anlauf und Schluss: berechnete Zwischenbilder statt Überblenden (Überblenden legte bei schnellen Bewegungen zwei
# Bilder übereinander). Gemessen am echten Clip: schärfstes Ergebnis ohne Standbilder.
SMOOTH = "null,"  # wird je Aufruf über interp_vf() gesetzt (siehe _smooth)


def sync_anchors(shot_times: list[float], s0: float, ks: float, gap: float, half: float) -> list[tuple[float, float]]:
    """Ankerpunkte (Zeit im Clip, Zeit im Segment) für einen Anlauf von s0 bis zum Kill ks, der ``gap`` Sekunden
    füllt. Der Kill landet am Ende (auf dem Schlag); jeder Schuss davor auf einem Achtelschlag (``half`` = halber
    Schlag), rückwärts vom Kill aus, so dass das Tempo zwischen zwei Ankern in [SYNC_MIN, SYNC_MAX] bleibt. Schüsse,
    die sich so nicht einrasten lassen, werden übersprungen. Anfang (s0 -> 0) ist immer Anker."""
    anchors, prev_v = [(ks, gap)], HIT_SLOW  # das Stück direkt vor dem Kill passt zum Tempo des Kills
    jump = lambda a, b: max(a / b, b / a) <= SYNC_JUMP  # noqa: E731
    for t in sorted((x for x in shot_times if s0 + 0.05 < x < ks - 0.05), reverse=True):
        src_gap = anchors[-1][0] - t
        best = None
        # Raster: Sechzehntel (halber Achtel). Achtel werden bevorzugt; Sechzehntel nur, wenn Schüsse so dicht
        # fallen, dass dazwischen kein Achtel passt (gemessen am echten Clip: sonst lag ein Schuss 112 ms daneben).
        q, best_score = half / 2, None
        for k in range(1, 17):
            out_t = anchors[-1][1] - k * q
            if out_t < 0.08:
                break
            v = src_gap / (k * q)
            score = abs(v - 1) + (0.25 if k % 2 else 0.0)
            if SYNC_MIN <= v <= SYNC_MAX and jump(v, prev_v) and (best_score is None or score < best_score):
                best, best_score = (out_t, v), score
        if best is None:
            continue
        # der Rest bis zum Anfang muss auch ein erlaubtes Tempo haben
        rest = (t - s0) / best[0]
        if not (SYNC_MIN <= rest <= SYNC_MAX * 1.1 and jump(rest, best[1])):
            continue
        anchors.append((t, round(best[0], 4)))
        prev_v = best[1]
        if len(anchors) >= 7:
            break
    anchors.append((s0, 0.0))
    return [(round(a, 4), round(b, 4)) for a, b in reversed(anchors)]


def _piecewise_pts(anchors: list[tuple[float, float]], ss: float) -> str:
    """setpts-Ausdruck: Zeit im Segment als stückweise lineare Funktion der Zeit im Clip (relativ zu ss)."""
    expr = None
    for (x0, y0), (x1, y1) in reversed(list(zip(anchors, anchors[1:]))):
        k = (y1 - y0) / max(x1 - x0, 1e-6)
        piece = f"({y0}+(T-{x0 - ss:.4f})*{k:.5f})"
        expr = piece if expr is None else f"if(lt(T\\,{x1 - ss:.4f})\\,{piece}\\,{expr})"
    return f"({expr.replace('T', '((PTS-STARTPTS)*TB)')})/TB"


KILL_SHOT_BACK = 1.5  # so weit vor dem Killfeed-Eintrag wird der Kill-Schuss gesucht
KILL_PRE = 0.08  # Zeitlupe beginnt so kurz vor dem Schuss (Mündungsfeuer und Treffer sind ganz drin)
KILL_NO_SHOT = 0.35  # ohne erkennbaren Schuss (Schalldämpfer, Messer, Granate): so weit vor dem Killfeed-Eintrag


def kill_start(t: float, shot_times: list[float] | None) -> float:
    """Wo die Kill-Zeitlupe beginnt: am Kill-Schuss = letzter Schuss im Spielton vor dem Killfeed-Eintrag (bis 1,5 s
    davor). Der Eintrag erscheint erst nach dem Treffer (gemessen 0,14-0,34 s, beim Nutzer teils viel mehr); vorher
    begann die Zeitlupe pauschal 0,1 s vor dem Eintrag, und der eigentliche Kill fiel heraus. Ohne Schuss (Granate,
    Messer): wie bisher."""
    prev = [x for x in (shot_times or []) if t - KILL_SHOT_BACK <= x <= t + 0.05]
    return round(max((prev[-1] - KILL_PRE) if prev else (t - KILL_NO_SHOT), 0.0), 3)


CLEAN_EDIT = True  # einfacher Schnitt mit festen Regeln (siehe plan_clean); False = alter Effekt-Schnitt (plan_beat)
CLEAN_PRE, CLEAN_POST = 1.2, 1.0  # so viel vor dem Kill-Schuss / nach dem Killfeed-Eintrag
CLEAN_MERGE = 3.0  # Kills, deren Schüsse näher beieinander liegen, bleiben ein durchgehendes Stück (Mehrfach-Kill)
FEED_SHOW_S = 1.8  # so lange steht der eigene Killfeed-Eintrag oben (ab dem Moment, in dem er im Spiel erscheint)


def plan_clean(kills: list[dict], beat_times: list[float], shot_times: dict | None = None) -> dict:
    """Einfacher Schnitt mit festen Regeln (Nutzer: Zeitlupe/Vor- und Zurückspringen/doppelte Szenen "to much"):
    1. nur echtes Tempo; 2. jede Stelle eines Clips höchstens einmal, in zeitlicher Reihenfolge; 3. je Kill ein
    durchgehendes Stück von CLEAN_PRE vor dem Kill-Schuss bis CLEAN_POST nach dem Killfeed-Eintrag, nahe Kills
    (Mehrfach-Kill) als ein Stück; 4. Schnitte nur zwischen den Stücken, auf dem Beat: jedes Stück beginnt so, dass
    sein erster Kill-Schuss auf einem Schlag liegt, und ist eine ganze Zahl Schläge lang; 5. Killfeed-Eintrag ab dem
    Moment, in dem er im Spiel erscheint. Passt nicht alles in die Musik, fallen die letzten Stücke weg."""
    import math

    nb = len(beat_times)
    if nb < 4:
        raise ValueError("Zu wenige Schläge im Musik-Ausschnitt.")
    beat = (beat_times[-1] - beat_times[0]) / (nb - 1)
    music_end = beat_times[-1] + beat * 0.5
    # Gruppen: aufeinanderfolgende Kills im selben Clip mit nahen Schüssen
    groups: list[list[dict]] = []
    for k in kills:
        ks = kill_start(k["t"], (shot_times or {}).get(k.get("src")))
        k = dict(k, ks=ks)
        g = groups[-1] if groups else None
        if g and g[-1].get("src") == k.get("src") and ks - g[-1]["ks"] < CLEAN_MERGE and ks >= g[-1]["ks"]:
            g.append(k)
        else:
            groups.append([k])
    segs, o, used, prev_end = [], beat_times[0], 0, {}
    first_beat = beat_times[0]
    for g in groups:
        src, dur = g[0].get("src"), g[0].get("dur", 1e9)
        ks0 = g[0]["ks"] + KILL_PRE  # der Schuss selbst (ks liegt KILL_PRE davor)
        lead = max(1, round(CLEAN_PRE / beat)) * beat  # erster Kill-Schuss genau auf einem Schlag
        lo = prev_end.get(src, 0.0)
        while ks0 - lead < lo and lead > beat - 1e-6:  # nicht in schon gezeigtes Material zurück
            lead -= beat
        start = ks0 - lead
        if start < lo - 1e-6:  # nicht einmal ein Schlag Vorlauf frei: direkt am Kill-Schuss beginnen
            start = max(lo, ks0 - 0.15)
        end = min(max(k["t"] for k in g) + CLEAN_POST, dur - 0.05)
        n = max(1, math.ceil((end - start) / beat - 0.25))
        if start + n * beat > dur - 0.05:
            n = max(1, int((dur - 0.05 - start) / beat))
        L = n * beat
        if o + L > music_end + 1e-6:  # Musik zu Ende
            break
        marks = [{"shot": round(o + (k["ks"] + KILL_PRE - start), 3), "feed": round(o + (k["t"] - start), 3),
                  "box": k["box"], "feed_at": round(min(k["t"] + 0.2, dur - 0.05), 3)} for k in g]
        segs.append({"kind": "clip", "ss": round(start, 3), "d": round(L, 3), "out": round(L, 3), "o0": round(o, 3),
                     "src": src, "kills": marks})
        prev_end[src] = start + L
        o += L
        used += len(g)
    if not segs:
        raise ValueError("Die Musik ist zu kurz für ein Kill-Stück.")
    shift = first_beat  # Video beginnt bei 0: alles um den ersten Schlag nach vorn
    for sg in segs:
        sg["o0"] = round(sg["o0"] - shift, 3)
        for mk in sg["kills"]:
            mk["shot"], mk["feed"] = round(mk["shot"] - shift, 3), round(mk["feed"] - shift, 3)
    last = segs[-1]
    return {"segments": segs, "seconds": round(last["o0"] + last["out"], 3), "beat": round(beat, 4),
            "kills_used": used, "music_shift": round(shift, 3), "marks": [dict(mk, o0=mk["shot"], out=1.0, kind="hit") for sg in segs for mk in sg["kills"]]}


def _render_clip(src: str, seg: dict, out: Path, tmp: Path, font: str, b: float = 0.0) -> None:
    """Ein Stück des einfachen Schnitts: echtes Tempo, eigener Killfeed-Eintrag ab seinem Erscheinen im Spiel."""
    src = seg.get("src") or src
    L = seg["out"]
    tail = f"setsar=1,fps={OUT_FPS},tpad=stop_mode=clone:stop_duration=1,trim=0:{L}"
    feeds = []
    if SHOW_FEED and not LANDSCAPE:
        for i, mk in enumerate(seg.get("kills") or []):
            feeds.append((_feed_png(src, mk, tmp, f"{out.stem}_{i}"), mk["feed"] - seg["o0"]))
    fc = f"[0:v]scale={W}:{H},setpts=PTS-STARTPTS[s];{_vf('[s]', '1', 'c', b)};"
    last = "c"
    for i, (_png, at) in enumerate(feeds):
        fc += (f"[{last}][{i + 1}:v]overlay=(W-w)/2:{BOX_Y + 24}:enable='between(t,{max(at, 0):.3f},"
               f"{at + FEED_SHOW_S:.3f})'[f{i}];")
        last = f"f{i}"
    fc += (f"[{last}]{tail}[v];[0:a]aresample=48000,asetpts=PTS-STARTPTS,volume={CLEAN_GAME_VOL},"
           f"apad=whole_dur={L},atrim=0:{L}[a]")
    ins = [x for png, _ in feeds for x in ("-i", str(png))]
    _run(["ffmpeg", "-v", "error", "-y", "-ss", str(seg["ss"]), "-t", str(L + 0.1), "-i", src, *ins,
          "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", str(L), *ENC, str(out)])


CLEAN_GAME_VOL = 0.9  # Spielton im einfachen Schnitt: Schüsse sind das Wichtigste


def kill_beats(n: int, nb: int, strength: list[float] | None, beat_times: list[float]) -> list[int]:
    """Schläge, auf denen die Kills landen. Je Kill der stärkste Schlag in einem Fenster (betonte Schläge wirken
    wuchtiger); die Abstände wechseln (3 bis 6 Schläge, bei wenig Musik 2 bis 4), statt starr alle 4 Schläge
    (Cutting u. a. 2010: Einstellungslängen mit Abwechslung statt Raster). Ohne Stärken: gleichmäßig."""
    import numpy as np

    long_music = nb - 3 >= 3 + (n - 1) * 4
    lo, hi = (3, 6) if long_music else (2, 4)
    first = 2 if beat_times[2] >= 0.9 else 3
    if not strength or len(strength) != nb:
        step = 4 if long_music else 2
        return [first + k * step for k in range(n) if first + k * step < nb - 1]
    st = np.asarray(strength, float)
    st = (st - st.min()) / max(st.max() - st.min(), 1e-9)
    out, prev_gap = [], None
    cand = range(first, min(first + 2, nb - 2) + 1)
    idx = max(cand, key=lambda i: st[i]) if cand else first
    while len(out) < n and idx < nb - 1:
        out.append(idx)
        best, bscore = None, -1e9
        for gap in range(lo, hi + 1):
            i = idx + gap
            if i >= nb - 1:
                break
            # stärkerer Schlag gewinnt; derselbe Abstand wie zuletzt kostet etwas; zu lange Pausen auch
            # Steigerung: Abstände werden zum Ende hin eher kürzer als länger (Spannung baut sich auf)
            score = (st[i] - (0.15 if gap == prev_gap else 0) - 0.05 * max(0, gap - 4)
                     - 0.08 * max(0, gap - (prev_gap or gap)))
            if score > bscore:
                best, bscore = gap, score
        if best is None:
            break
        prev_gap, idx = best, idx + best
    return out


def end_hold(o: float, beat_times: list[float], phase: int, beat: float) -> float:
    """Länge des Schlusses: Das Video endet auf einem Taktanfang (gleiche Lage im Takt wie der erste Kill, der auf
    einem betonten Schlag liegt), 2 bis 4 Schläge nach dem letzten Kill. Musik, die mitten im Takt abbricht, wirkt
    unfertig; ein Ende auf dem Taktanfang wirkt geschlossen (Huron 2006). Passt nichts: 2 Schläge."""
    for i, t in enumerate(beat_times):
        if (i - phase) % 4 == 0 and o + 1.9 * beat <= t <= o + 4.1 * beat:
            return round(t - o, 3)
    return round(2 * beat, 3)


def plan_beat(kills: list[dict], dur: float, beat_times: list[float], motions: dict | None = None,
              strength: list[float] | None = None, shot_times: dict | None = None) -> dict:
    """Schnittplan auf dem Beat-Raster, ein Takt (4 Schläge) je Kill:
    Schlag 1 ``shot`` (kurzer Blick auf die Szene davor, eigener Schnitt), Schlag 2 ``ramp`` (Tempo gleitet in die
    Zeitlupe), Schlag 3 und 4 ``hit`` (der Kill, genau auf dem Schlag). Jeder Bildwechsel liegt auf einem Schlag.
    Bei wenig Musik: nur ``ramp`` + ``hit`` je einen Schlag. Am Ende ``hold`` mit der Summe."""
    n, nb = len(kills), len(beat_times)
    if nb < 6:
        raise ValueError("Zu wenige Schläge im Musik-Ausschnitt.")
    beat = (beat_times[-1] - beat_times[0]) / (nb - 1)
    kb_idx = kill_beats(n, nb, strength, beat_times)               # Kill-Schläge: betont, abwechselnde Abstände
    used = list(range(len(kb_idx)))                                 # passen nicht alle Kills in die Musik: die ersten
    segs, o, src_prev, cur = [], 0.0, 0.0, None
    for j, k in enumerate(used):
        kill = kills[k]
        cdur = kill.get("dur", dur)
        if kill.get("src") != cur:
            cur, src_prev = kill.get("src"), 0.0
        ks = kill_start(kill["t"], (shot_times or {}).get(kill.get("src")))  # Kill-Moment im Clip: der Kill-Schuss
        kb = beat_times[kb_idx[j]]                    # Schlag, auf dem er landet
        gap = kb - o
        # Schlag davor: eigener kurzer Schnitt aus der Szene vor dem Kill (nur wenn Zeit und Material reichen)
        shot_out = gap - beat if gap >= 1.7 * beat else 0.0
        ramp_gap = gap - shot_out
        avail = max(ks - src_prev, 0.0)
        if avail < ramp_gap * 0.25:                   # kaum neues Material: früheres noch einmal zeigen
            avail = min(ks, ramp_gap)
        d, v0, v1 = ramp_fit(ramp_gap, avail) if avail > 0.05 and ramp_gap > 0.05 else (0.0, 1.0, 1.0)
        if shot_out:
            sd = round(shot_out * SHOT_SPEED, 3)
            s0 = max(ks - d - SHOT_BACK - sd, src_prev if ks - d - sd >= src_prev else 0.0, 0.0)
            s0 = onset_cut((motions or {}).get(kill.get("src")), s0, max(s0, ks - d - sd))
            if s0 + sd <= ks - d + 0.001 and sd > 0.1:
                segs.append({"kind": "shot", "ss": round(s0, 3), "d": sd, "out": round(shot_out, 3), "o0": round(o, 3),
                             "src": kill.get("src")})
            else:                                     # kein Platz für einen eigenen Schnitt: Anlauf über beide Schläge
                ramp_gap, shot_out = gap, 0.0
                d, v0, v1 = ramp_fit(ramp_gap, max(avail, min(ks, ramp_gap)))
        if d > 0.05:
            seg = {"kind": "ramp", "ss": round(ks - d, 3), "d": d, "out": round(ramp_gap, 3),
                   "o0": round(o + shot_out, 3), "v0": v0, "v1": v1, "src": kill.get("src")}
            st = (shot_times or {}).get(kill.get("src")) or []
            anc = sync_anchors(st, ks - d, ks, ramp_gap, beat / 2) if st else []
            if len(anc) > 2:  # mindestens ein Schuss eingerastet: Schüsse auf dem Achtelschlag
                seg["anchors"] = anc
            segs.append(seg)
        else:
            kb = o + shot_out                         # kein Anlauf möglich: Kill direkt
        nxt_gap = kb_idx[j + 1] - kb_idx[j] if j + 1 < len(kb_idx) else 4
        hit_out = beat * (2 if nxt_gap >= 4 else 1)   # der Kill bleibt zwei Schläge in Zeitlupe, bei kurzem Abstand einen
        slow = HIT_SLOW_LAST if j == len(used) - 1 and len(used) > 1 else HIT_SLOW
        after_src = min(hit_out * slow, max(cdur - ks - 0.02, 0.05))
        extra = {}
        if j < len(used) - 1 and hit_out >= 1.5 * beat:  # nicht der letzte und kein kurzer Kill: sanft beschleunigen
            o2 = hit_out * OUT_FRAC
            need = (hit_out - o2) * slow + o2 * (slow + OUT_V) / 2
            if need <= cdur - ks - 0.02:
                after_src, extra = need, {"ramp_out": round(o2, 3), "slow": slow}
        segs.append({**extra, "kind": "hit", "ss": round(ks, 3), "d": round(after_src, 3), "out": round(hit_out, 3), "o0": round(kb, 3),
                     "box": kill["box"], "feed_at": round(min(kill["t"] + 0.2, cdur - 0.05), 3), "text": f"+{j + 1}",
                     "kill_at": 0.0, "src": kill.get("src")})
        o, src_prev = kb + hit_out, ks + after_src
    last = segs[-1]
    hold = end_hold(o, beat_times, kb_idx[0] if kb_idx else 0, beat)
    h_ss = max(last["ss"] + last["d"] - 0.03, 0)
    h_cdur = kills[used[-1]].get("dur", dur)
    segs.append({"kind": "hold", "ss": round(h_ss, 3), "d": round(max(min(hold * HIT_SLOW, h_cdur - h_ss - 0.05), 0), 3),
                 "out": round(hold, 3), "o0": round(o, 3), "box": last["box"], "feed_at": last["feed_at"],
                 "text": f"{len(used)} KILLS" if len(used) > 1 else "KILL", "src": last.get("src")})
    return {"segments": segs, "seconds": round(o + hold, 3), "beat": round(beat, 4), "kills_used": len(used)}


KILL_SND_S = 0.45  # so viel Originalton vom Kill-Schuss, in echtem Tempo


# Doppelte Bilder aus der Aufnahme entfernen, bevor das Tempo geändert wird. Gemessen an einem echten Clip: 35 %
# der Bilder waren Kopien des vorigen (40 Bilder/s Inhalt in 60 Bilder/s Datei). In der Zeitlupe wurden daraus
# Standbilder von bis zu 7 Bildern (117 ms), sichtbar als Laggen. Die übrigen Bilder behalten ihren Zeitpunkt.
# Doppelte Bilder nur entfernen, wenn Zwischenbilder berechnet werden. Ohne (INTERP "none") gemessen: mit Entfernen
# 84 von 177 Bildern doppelt, ohne nur 31 (wirkt wie normales 30-fps-Video).
DEDUP = ""


def _margin(seg: dict) -> float:
    """Etwas mehr Material einlesen, als das Segment braucht (danach wird genau abgeschnitten). Ohne das fehlen am
    Ende Bilder: Zwischenbilder gibt es nur bis zum letzten Quellbild, der Rest wurde mit dem letzten Bild aufgefüllt.
    Das waren bis zu 9 stehende Bilder je Segment, danach ein Sprung: genau das sichtbare Laggen."""
    m = 0.15
    v0, v1, d = seg.get("v0"), seg.get("v1"), seg.get("d", 0)
    if seg.get("kind") == "ramp" and not seg.get("anchors") and v0 and v1 and v0 > v1 and d > 0:
        m = min(m, 0.8 * d * v1 / (v0 - v1))  # die Tempo-Formel bleibt über das Ende hinaus gültig
    return round(m, 3)


def _render_end(src: str, seg: dict, out: Path, tmp: Path, font: str, b: float = 0.0) -> None:
    """Schluss: die Szene läuft nach dem letzten Kill in Zeitlupe weiter (kein Standbild), Summe und Killfeed stehen.
    Kein Effektton: das Ende gehört der Musik, die auf einem Taktanfang endet."""
    kf = _feed_png(src, seg, tmp, out.stem)
    tail = f"setsar=1,fps={OUT_FPS},tpad=stop_mode=clone:stop_duration={seg['out'] + 1},trim=0:{seg['out']}"
    over = (f"[bg][1:v]overlay=(W-w)/2:{BOX_Y - 115}[v0];[v0]{_draw(seg['text'], font)},{tail}[v]" if SHOW_COUNTER
            else f"[bg]{tail}[v]")
    silent = f"anullsrc=r=48000:cl=stereo,atrim=0:{seg['out']}[a]"
    if seg["d"] >= 0.2:
        speed = max(seg["d"] / seg["out"], 0.05)
        fc = (f"[0:v]scale={W}:{H},{DEDUP}settb=1/60000,setpts=(PTS-STARTPTS)/{speed:.5f},{interp_vf()}[s];{_vf('[s]', str(Z_HIT), 'bg', b)};"
              f"{over};{silent}")
        _run(["ffmpeg", "-v", "error", "-y", "-ss", str(seg["ss"]), "-t", str(seg["d"] + _margin(seg)), "-i", src, "-i", str(kf),
              "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", str(seg["out"]), *ENC, str(out)])
        return
    png = tmp / f"{out.stem}.png"  # Clip zu Ende: letztes Bild steht
    _run(["ffmpeg", "-v", "error", "-y", "-ss", str(max(seg["ss"] - 0.05, 0)), "-i", src, "-frames:v", "1", "-vf",
          f"scale={W}:{H}", str(png)])
    fc = f"{_vf('[0:v]', str(Z_HIT), 'bg', b)};{over};{silent}"
    _run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-framerate", str(OUT_FPS), "-t", str(seg["out"]), "-i", str(png),
          "-i", str(kf), "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", str(seg["out"]), *ENC, str(out)])


def hit_pts(seg: dict, speed: float) -> str:
    """Zeitverlauf der Kill-Zeitlupe als setpts. Mit ``ramp_out``: erst gleichmäßig langsam, in den letzten
    ``ramp_out`` Sekunden steigt das Tempo linear auf OUT_V. So endet der Kill in schneller Bewegung, und der Schnitt
    zur nächsten Szene liegt mitten in der Bewegung: Schnitte während Bewegung fallen am wenigsten auf
    (Smith & Henderson 2008)."""
    if not seg.get("ramp_out"):
        return f"settb=1/60000,setpts=(PTS-STARTPTS)/{speed:.5f}"
    s, o2 = seg["slow"], seg["ramp_out"]
    o1 = seg["out"] - o2
    d1, k = o1 * s, (OUT_V - s) / o2
    x = "((PTS-STARTPTS)*TB)"
    y = f"if(lt({x}\\,{d1:.4f})\\,{x}/{s}\\,{o1:.4f}+(sqrt({s * s:.5f}+{2 * k:.5f}*({x}-{d1:.4f}))-{s})/{k:.5f})"
    return f"settb=1/60000,setpts='({y})/TB'"


def _render_beat_seg(src: str, seg: dict, out: Path, tmp: Path, font: str) -> None:
    """Ein Segment des Beat-Edits, genau ``out`` Sekunden lang. Spielton leise unter der Musik."""
    if seg["kind"] == "clip":
        _render_clip(src, seg, out, tmp, font, seg.get("bright", 0.0))
        return
    src = seg.get("src") or src
    b = seg.get("bright", 0.0)
    if seg["kind"] == "hold":
        _render_end(src, seg, out, tmp, font, b)
        return
    speed = max(seg["d"] / seg["out"], 0.05)
    tempo = ",".join(["atempo=0.5"] * (1 if speed < 0.5 else 0) + [f"atempo={max(speed, 0.5) if speed >= 0.5 else speed / 0.5:.5f}"])
    audio = (f"[0:a]aresample=48000,asetpts=PTS-STARTPTS,{tempo},apad=whole_dur={seg['out']},atrim=0:{seg['out']},"
             f"volume={0.8 if seg['kind'] == 'hit' else GAME_VOL}[a]")
    tail = f"setsar=1,fps={OUT_FPS},tpad=stop_mode=clone:stop_duration=1,trim=0:{seg['out']}"
    if seg["kind"] == "hit":
        # Ton: der Kill-Schuss in echtem Tempo (gestreckter Ton klingt blechern), danach trägt die Musik die Zeitlupe
        audio = (f"[0:a]aresample=48000,asetpts=PTS-STARTPTS,atrim=0:{KILL_SND_S},afade=t=out:st={KILL_SND_S - 0.12}:d=0.12,"
                 f"volume={KILL_VOL},apad=whole_dur={seg['out']},atrim=0:{seg['out']}[a]")
        kf = _feed_png(src, seg, tmp, out.stem)
        z = f"1+({Z_HIT}-1)*min(t/{PUNCH_S}\\,1)"
        fc = (f"[0:v]scale={W}:{H},{DEDUP}{hit_pts(seg, speed)},"
              + interp_vf() + f"[s];{_vf('[s]', z, 'bg', b)};"
              + (f"[bg]hue=s='min(1\\,max(0\\,(t-0.18)/0.25))',eq=contrast='1.25-0.25*min(1\\,t/0.45)':eval=frame[fl];"
                 if KILL_FX else "[bg]null[fl];")
              + (f"[fl][1:v]overlay=(W-w)/2:{BOX_Y - 115}[v0];[v0]{_draw(seg['text'], font)},{tail}[v];" if SHOW_COUNTER
                 else f"[fl][1:v]overlay=(W-w)/2:{BOX_Y + 24}[v0];[v0]{tail}[v];" if SHOW_FEED and not LANDSCAPE
                 else f"[fl]{tail}[v];") + audio)
        _run(["ffmpeg", "-v", "error", "-y", "-ss", str(seg["ss"]), "-t", str(seg["d"] + _margin(seg)), "-i", src, "-i", str(kf),
              "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", str(seg["out"]), *ENC, str(out)])
        return
    if seg["kind"] == "shot":  # eigener kurzer Schnitt: gleichmäßiges Tempo, Zoom-Schlag beim Bildwechsel
        fc = (f"[0:v]scale={W}:{H},{DEDUP}settb=1/60000,setpts=(PTS-STARTPTS)/{speed:.5f},{interp_vf()}[s];"
              f"{_vf('[s]', CUT_POP, 'c', b)};[c]{tail}[v];{audio}")
        _run(["ffmpeg", "-v", "error", "-y", "-ss", str(seg["ss"]), "-t", str(seg["d"] + _margin(seg)), "-i", src,
              "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", str(seg["out"]), *ENC, str(out)])
        return
    v0, v1, d = seg["v0"], seg["v1"], seg["d"]
    if seg.get("anchors"):
        anc = seg["anchors"]
        pts = _piecewise_pts(anc, seg["ss"])
        shots_out = [(x, y) for x, y in anc[1:]]  # Schüsse und Kill: Sound genau an ihrem Beat-Punkt
        parts, labels = [], []
        for i, (x, y) in enumerate(shots_out):
            a0 = max(x - seg["ss"] - 0.01, 0)
            parts.append(f"[0:a]aresample=48000,atrim={a0:.4f}:{a0 + 0.22:.4f},asetpts=PTS-STARTPTS,"
                         f"afade=t=out:st=0.14:d=0.08,adelay={int(max(y - 0.01, 0) * 1000)}:all=1[sh{i}]")
            labels.append(f"[sh{i}]")
        audio = (";".join(parts) + ";" + "".join(labels) +
                 f"amix=inputs={len(labels)}:duration=longest:normalize=0,volume={SHOT_VOL},"
                 f"apad=whole_dur={seg['out']},atrim=0:{seg['out']}[a]")
        blur = BLUR if v0 > 1.2 else ""
        fc = f"[0:v]scale={W}:{H},{DEDUP}{blur}settb=1/60000,setpts='{pts}',{interp_vf()}[s];{_vf('[s]', '1', 'c', b)};[c]{tail}[v];{audio}"
        _run(["ffmpeg", "-v", "error", "-y", "-ss", str(seg["ss"]), "-t", str(d + _margin(seg)), "-i", src,
              "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", str(seg["out"]), *ENC, str(out)])
        return
    if abs(v0 - v1) < 1e-3:
        pts = f"(PTS-STARTPTS)/{v0:.5f}"
    else:  # Zeit im fertigen Video als Funktion der Zeit im Clip, bei linear fallendem Tempo
        pts = f"({d}/({v1}-{v0}))*log(({v0}+({v1}-{v0})*((PTS-STARTPTS)*TB)/{d})/{v0})/TB"
    blur = BLUR if seg.get("v0", 1) > 1.2 else ""
    fc = f"[0:v]scale={W}:{H},{DEDUP}{blur}settb=1/60000,setpts='{pts}',{interp_vf()}[s];{_vf('[s]', '1', 'c', b)};[c]{tail}[v];{audio}"
    _run(["ffmpeg", "-v", "error", "-y", "-ss", str(seg["ss"]), "-t", str(d + _margin(seg)), "-i", src,
          "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", str(seg["out"]), *ENC, str(out)])


def word_list(words: list[str], beat_times: list[float], per_beat: int = 1) -> list[dict]:
    """Wörter mit Zeiten: {"a": Start, "b": Ende der Einblendung, "txt", "sung": Ende des gesungenen Worts oder None}.
    Formen: "WORT" (ein Wort je Schlag), "1.45:WORT" (feste Zeit), "1.45-2.10:WORT" (Start und Ende, aus der
    Spracherkennung). Wörter unter MIN_WORD_S Abstand werden zu höchstens zwei Wörtern zusammengefasst."""
    import re

    out, i = [], 0
    for w in words:
        eol = w.endswith("\u00b6")
        w = w.rstrip("\u00b6")
        m = re.fullmatch(r"(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))?:(.+)", w)
        if m:
            a = float(m.group(1))
            sung = float(m.group(2)) if m.group(2) else None
            # gesungenes Wort: 40 ms früher einblenden, so wirkt es exakt auf dem Gesang (ITU-R BT.1359)
            out.append({"a": max(a - WORD_LEAD_S, 0.0) if sung is not None else a, "sung": sung, "txt": m.group(3),
                        "eol": eol})
            continue
        if i >= len(beat_times):
            break
        out.append({"a": beat_times[i], "sung": None, "txt": w, "eol": eol})
        i += per_beat
    out.sort(key=lambda x: x["a"])
    merged: list[dict] = []
    for x in out:
        held = x["sung"] is not None and x["sung"] - x["a"] >= 0.35  # gezogenes Wort bekommt seine eigene Einblendung
        if (merged and not held and x["a"] - merged[-1]["a"] < MIN_WORD_S and " " not in merged[-1]["txt"]
                and not merged[-1].get("eol")):
            merged[-1]["txt"] += " " + x["txt"]
            merged[-1]["sung"] = x["sung"] if x["sung"] is not None else merged[-1]["sung"]
            merged[-1]["eol"] = x.get("eol", False)
        else:
            merged.append(dict(x))
    beat = (beat_times[-1] - beat_times[0]) / max(len(beat_times) - 1, 1)
    for j, x in enumerate(merged):
        nxt = merged[j + 1]["a"] if j + 1 < len(merged) else x["a"] + beat
        x["b"] = round(min(nxt, x["a"] + 2 * beat), 3)
        x["a"] = round(x["a"], 3)
        x["next"] = nxt
    return merged


def word_times(words: list[str], beat_times: list[float], per_beat: int = 1) -> list[tuple[float, float, str]]:
    """Wie word_list, nur (Start, Ende, Text)."""
    return [(x["a"], x["b"], x["txt"]) for x in word_list(words, beat_times, per_beat)]


STORY_HOLD_S = 1.2  # nach dem ersten Kill: ein Schlüsselwort bleibt so viel länger als bis zum nächsten gesungenen Wort
# kleine Füllwörter, die nach dem ersten Kill wegfallen (Vorbild zeigt dann nur noch die tragenden Wörter)
STOPWORDS = set("""a an the and or but so to of in on at by for from with as is are was were be been am i im i'm me my
mine you your yours he him his she her it its we us our they them their this that these those there here what who
how why when where do does did done not no yes oh ah yeah uh ooh hey all just like if then than too very can could
would should will wont won't don't dont can't cant got get let lets let's up out down off over into onto about
ich du er sie es wir ihr mich dich sich mir dir uns euch der die das den dem des ein eine einen einem einer und oder
aber so zu im in an am auf aus bei mit nach von vor für fur ist bin bist sind war hab habe hat nicht kein keine ja
nein doch noch nur schon auch wie was wer wo wenn dann denn als""".split())


def story_keep(ws: list[dict], first_kill: float | None) -> set[int]:
    """Welche Wörter gezeigt werden (Vorbild: am Anfang jedes Wort, ab dem ersten Kill nur noch wichtige).
    Bis zum ersten Kill alle. Danach: Zeilenende, lang gezogene Wörter (ab 0,35 s gesungen) und Inhaltswörter (keine
    Füllwörter, ab 4 Buchstaben). Folgen zwei behaltene Wörter enger als 0,3 s, bleibt das wichtigere."""
    keep: list[int] = []
    score: dict[int, float] = {}
    for j, x in enumerate(ws):
        txt = x["txt"].strip()
        if not txt:
            continue
        if first_kill is None or x["a"] < first_kill:
            keep.append(j)
            score[j] = 9.0
            continue
        word = "".join(c for c in txt.lower() if c.isalnum() or c == "'")
        held = max((x.get("sung") or x["a"]) - x["a"], 0.0)
        content = word not in STOPWORDS and len(word.replace("'", "")) >= 4
        if x.get("eol") or held >= 0.35 or content:
            sc = held + (0.5 if x.get("eol") else 0) + (0.3 if content else 0) + len(word) * 0.02
            if keep and x["a"] - ws[keep[-1]]["a"] < 0.3 and score[keep[-1]] < 9.0:
                if sc <= score[keep[-1]]:
                    continue
                keep.pop()
            keep.append(j)
            score[j] = sc
    return set(keep)


LINE_INTRO_MAX = 3      # so viele ganze Zeilen höchstens am Anfang
LINE_INTRO_WORDS = 7    # längere Zeilen nicht als ganze Zeile (zu klein zu lesen)


def text_plan(ws: list[dict], first_kill: float | None, t_drop: float) -> tuple[dict, dict]:
    """Was im Text-Teil gezeigt wird (Nutzer + Kollege, Vorbild 1 und 2): am Anfang ganze Zeilen, die sich Wort für
    Wort aufbauen, solange es ruhig ist (Zeilen, die vor dem ersten Kill beginnen, höchstens LINE_INTRO_MAX, mindestens
    die erste); danach je Zeile nur das betonte Wort (bei langen Zeilen zwei), möglichst als Schild an der Wand.
    Rückgabe ({Wort-Index: (Zeile als Wortliste, Position)}, {Kandidat: (Gruppe, Rang, Anzahl)}). Je Gruppe werden
    "Anzahl" Wörter gezeigt: die besten mit Wand im Bild, fehlen welche, die besten übrigen flach (split_walls)."""
    lines: list[list[int]] = [[]]
    for j, x in enumerate(ws):
        if x["a"] >= t_drop - 0.15 or not x["txt"].strip():
            continue
        lines[-1].append(j)
        if x.get("eol") or len(lines[-1]) >= 6 and not any(w.get("eol") for w in ws):
            lines.append([])
    lines = [ln for ln in lines if ln]
    line_words: dict[int, tuple[list[str], int]] = {}
    intro = 0
    for ln in lines:
        start = ws[ln[0]]["a"]
        calm = first_kill is None or start < first_kill or intro == 0
        # die erste Zeile immer ganz (bis 12 Wörter, zwei Reihen), weitere nur vor dem ersten Kill
        if intro < LINE_INTRO_MAX and calm and (len(ln) <= 12 if intro == 0 else
                                               len(ln) <= LINE_INTRO_WORDS and start < (first_kill or 0)):
            words = [ws[j]["txt"] for j in ln]
            for pos, j in enumerate(ln):
                line_words[j] = (words, pos)
            intro += 1
        else:
            break
    emph: dict[int, tuple[int, int, int]] = {}  # Wort -> (Gruppe, Rang, wie viele aus der Gruppe gezeigt werden)
    emph_lines: list[int] = []
    for ln in lines:
        if ln[0] in line_words:
            continue

        def score(j):
            x = ws[j]
            w = "".join(c for c in x["txt"].lower() if c.isalnum() or c == "'")
            held = max((x.get("sung") or x["a"]) - x["a"], 0.0)
            return (held + (0.3 if w not in STOPWORDS else -1.0) + min(len(w), 8) * 0.06
                    + (0.2 if x.get("eol") else 0.0))

        def content(j):  # Füllwörter ("the", "to") nie betonen, auch nicht als Ersatz
            w = "".join(c for c in ws[j]["txt"].lower() if c.isalnum() or c == "'")
            return w not in STOPWORDS and len(w) >= 3

        ranked = sorted((j for j in ln if content(j)), key=score, reverse=True)
        if not ranked:
            continue
        n_emph = 2 if len(ln) >= 7 else 1
        # bis zu 3 Kandidaten je betontem Platz: an die Wand kommt der beste, für den eine Wand im Bild ist
        for r, j in enumerate(ranked[:n_emph + 2]):
            emph[j] = (len(emph_lines), r, n_emph)
        emph_lines.append(ln[0])
    return line_words, emph


def wall_picks(ws: list[dict], max_share: float = 0.5) -> set[int]:
    """Welche Wörter an die Wand: die, bei denen sich der Sänger Zeit lässt. Punkte = wie lange das Wort gesungen
    wird + die Pause danach (bis zum nächsten Wort). Gezogene Wörter vor einer Pause gewinnen. Nur Wörter mit
    mindestens 0,35 s gesungen oder 0,25 s Pause danach, höchstens ``max_share`` aller Wörter, mindestens eins.
    Ohne gesungene Zeiten (Text eingetippt): leer, dann gilt die einfache Regel."""
    timed = [(j, x) for j, x in enumerate(ws) if x.get("sung") is not None]
    if not timed:
        return set()
    scored = []
    for j, x in timed:
        held = max(x["sung"] - x["a"], 0.0)
        pause = max(x["next"] - x["sung"], 0.0)
        if (held >= 0.28 or pause >= 0.2) and len(x["txt"].replace(" ", "")) >= 3:
            scored.append((held + pause, j))
    scored.sort(reverse=True)
    n = max(1, int(len(ws) * max_share))
    return {j for _, j in scored[:n]}


SUNG_NOTE = ""  # warum die letzte Erkennung nichts geliefert hat (für die Anzeige in der App)


# Sätze, die die Spracherkennung bei Musik ohne verständlichen Gesang erfindet: Sie wurde mit vielen untertitelten
# Videos trainiert, deren Abspann so lautet. Solche Stücke werden verworfen.
HALLUCINATIONS = ("thanks for watching", "thank you for watching", "subscribe", "like and subscribe",
                  "see you in the next", "untertitel", "amara.org", "vielen dank fürs zuschauen",
                  "danke fürs zuschauen", "copyright", "please like")


def _hallucinated(seg) -> bool:
    t = (seg.text or "").lower()
    if any(h in t for h in HALLUCINATIONS):
        return True
    # wahrscheinlich keine Sprache und dabei unsicher: erfunden
    return getattr(seg, "no_speech_prob", 0) > 0.6 and getattr(seg, "avg_logprob", 0) < -1.0


def sung_words(music: str, ss: float, d: float, hint: str | None = None) -> list[str] | None:
    """Gesungene Wörter mit Zeitpunkt aus dem Musik-Ausschnitt, als "Sekunde:WORT". Braucht die Bibliothek
    faster-whisper (läuft lokal, ohne Kosten; lädt beim ersten Mal ein Sprachmodell). Ist sie nicht installiert oder
    geht etwas schief: None, dann bleibt es beim eingetragenen Text. Gesang wird nicht immer richtig erkannt."""
    global SUNG_NOTE
    import re
    import sys

    SUNG_NOTE = ""
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        SUNG_NOTE = (f"Die Spracherkennung ist in der Umgebung der App nicht installiert ({e}). Die App läuft mit "
                     f"{sys.executable}. Installieren mit: {sys.executable} -m pip install faster-whisper")
        return None

    try:
        import numpy as np

        # Ton selbst einlesen (16 kHz, Mono) und als Zahlenreihe übergeben: So braucht die Erkennung ihre eigene
        # Datei-Bibliothek (PyAV) nicht, die auf manchen Servern zu alt ist.
        # Bass und Höhen weg (Kick, Hi-Hats), Stimmbereich bleibt: weniger Musik, die die Erkennung stört
        raw = _run(["ffmpeg", "-v", "error", "-ss", str(ss), "-t", str(d), "-i", music, "-vn", "-ac", "1", "-ar", "16000",
                    "-af", "highpass=f=180,lowpass=f=4500", "-f", "f32le", "-"])
        audio = np.frombuffer(raw, np.float32)
        model = WhisperModel("small", device="cpu", compute_type="int8")
        # Gesang über Musik: nicht beim ersten unsicheren Stück aufhören (kein Abbruch bei "keine Sprache", kein
        # Fortschreiben des vorigen Texts, das sich sonst aufhängt), gründlichere Suche
        # Eingefügter Songtext als Vorgabe: Die Erkennung sucht dann gezielt nach diesen Wörtern
        segs, _info = model.transcribe(audio, word_timestamps=True, beam_size=5, vad_filter=False,
                                       condition_on_previous_text=False, no_speech_threshold=0.95,
                                       log_prob_threshold=-2.5, compression_ratio_threshold=3.0,
                                       initial_prompt=(hint or None) and hint[:600])
        out, dropped = [], 0
        for sg in segs:
            if _hallucinated(sg):
                dropped += 1
                continue
            for w in sg.words or []:
                txt = re.sub(r"[^0-9A-Za-zÄÖÜäöüß'-]", "", w.word)
                if txt:
                    out.append(f"{max(w.start, 0):.2f}-{max(w.end, w.start):.2f}:{txt}")
        if not out:
            SUNG_NOTE = "Die Spracherkennung lief, hat in diesem Ausschnitt aber keine Wörter erkannt." + (
                f" {dropped} erfundene Stücke (z. B. „Thanks for watching“) verworfen." if dropped else "")
        else:
            t0 = float(out[0].split("-")[0])
            t1 = float(out[-1].split(":")[0].split("-")[-1])
            SUNG_NOTE = (f"{len(out)} Wörter erkannt, von {t0:.1f} bis {t1:.1f} s".replace(".", ",")
                         + (f" (das Video ist {d:.1f} s lang)".replace(".", ",") if t1 < d * 0.6 else "") + ".")
        return out or None
    except Exception as e:  # noqa: BLE001 - ohne Erkennung läuft der Schnitt trotzdem
        SUNG_NOTE = f"Die Spracherkennung ist installiert, aber fehlgeschlagen: {type(e).__name__}: {str(e)[:300]}"
        return None


def _norm(w: str) -> str:
    import re

    return re.sub(r"[^0-9a-zäöüß]", "", w.lower())


WORD_PACE_S = 0.28  # Abstand nicht erkannter Wörter, wenn sie an ein erkanntes Wort rücken (Sprechtempo)


def align_lyrics(typed: list[str], sung: list[str] | None, d: float) -> list[str]:
    """Eingefügten Songtext zeitlich auf den Gesang legen. ``sung``: erkannte Wörter "a-e:WORT".
    Gleiche Wörter in derselben Reihenfolge bekommen die Zeit aus der Erkennung; Wörter dazwischen, die die
    Erkennung verpasst oder falsch verstanden hat, werden gleichmäßig zwischen die Nachbarn verteilt. Der Text
    bleibt immer der eingefügte. Ohne Erkennung: unverändert (dann ein Wort je Schlag)."""
    import difflib

    if not sung or not typed:
        return typed
    rec = []
    for w in sung:
        tm, txt = w.split(":", 1)
        a, e = (float(x) for x in tm.split("-")) if "-" in tm else (float(tm), float(tm) + 0.3)
        rec.append((a, e, txt))
    sm = difflib.SequenceMatcher(a=[_norm(x) for x in typed], b=[_norm(x[2]) for x in rec], autojunk=False)
    times: list[tuple[float, float] | None] = [None] * len(typed)
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            a, e, _ = rec[blk.b + k]
            times[blk.a + k] = (a, e)
    if not any(times):
        return typed  # nichts passt zusammen (anderer Text oder anderer Ausschnitt): ein Wort je Schlag
    out, i = [], 0
    while i < len(typed):
        if times[i] is not None:
            a, e = times[i]
            out.append(f"{a:.2f}-{e:.2f}:{typed[i]}")
            i += 1
            continue
        j = i
        while j < len(typed) and times[j] is None:
            j += 1
        start = times[i - 1][1] if i > 0 else max((times[j][0] if j < len(typed) else d) - 0.35 * (j - i), 0.0)
        end = times[j][0] if j < len(typed) else min(d, start + 0.35 * (j - i))
        # Zeilenende in der Lücke (Zeile endet mit dem Vorgänger oder einem Wort der Lücke): dort singt der Sänger
        # nicht. Wörter der alten Zeile folgen dem Vorgänger, die der neuen Zeile kommen direkt vor dem nächsten
        # erkannten Wort, im Sprechtempo (Nutzer: "let" nach der Pause erschien mitten in der Pause).
        brk = next((k for k in range(i - 1, j) if k >= 0 and typed[k].endswith("\u00b6")), None)
        if brk is not None and end - start > WORD_PACE_S * (j - i + 1) + 0.3:
            for k in range(i, j):
                if k <= brk:  # noch alte Zeile: hinter den Vorgänger
                    t = start + WORD_PACE_S * (k - i + 1) if i > 0 else end - WORD_PACE_S * (j - k)
                else:  # neue Zeile: vor das nächste erkannte Wort
                    t = end - WORD_PACE_S * (j - k)
                out.append(f"{max(t, 0.0):.2f}:{typed[k]}")
            i = j
            continue
        step = max(end - start, 0.0) / (j - i + 1)
        for k in range(i, j):
            out.append(f"{start + step * (k - i + 1):.2f}:{typed[k]}")
        i = j
    return out


LYRIC_COLORS = [((255, 255, 255), (255, 159, 28)), ((255, 210, 63), (20, 20, 20)), ((255, 255, 255), (240, 86, 106)),
                ((77, 224, 138), (20, 20, 20)), ((255, 255, 255), (74, 138, 224)), ((255, 90, 110), (20, 20, 20))]
LYRIC_DY = (0, -40, 20, -25, 35, -15)  # kleine Sprünge im unteren Drittel des Spielbilds
LYRIC_ROT = (-5, 4, -3, 5, -4, 3)


# Zeichen aus anderen Alphabeten, die wie lateinische aussehen (kopierter Songtext enthält sie manchmal),
# und typografische Anführungszeichen
LOOKALIKE = str.maketrans({
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O",
    "Р": "P", "С": "C", "Т": "T", "Х": "X", "У": "Y", "а": "a", "е": "e",
    "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j",
    "ѕ": "s", "ʏ": "Y", "“": '"', "”": '"', "„": '"', "‘": "'", "’": "'",
    "´": "'", "`": "'",
})


def printable(text: str, font_file: str) -> str:
    """Text so umformen, dass die Schrift jedes Zeichen hat: Unicode vereinheitlichen, Doppelgänger aus anderen
    Alphabeten ersetzen, Großbuchstaben, unsichtbare Zeichen weg. Was die Schrift dann noch nicht kennt, wird
    weggelassen (vorher erschien dafür ein Kästchen, gesehen bei "MY")."""
    import unicodedata

    # Klammern aus dem Songtext (Hintergrund-Gesang) nicht anzeigen (Nutzer: "die () sollen nicht angezeigt werden")
    t = unicodedata.normalize("NFKC", text).translate(LOOKALIKE).upper().replace("(", "").replace(")", "")
    t = "".join(c for c in t if unicodedata.category(c)[0] != "C")  # Steuer- und unsichtbare Zeichen
    t = "".join(c for c in t if c == " " or _has_glyph(c, font_file))
    return t.strip() or text.strip().upper()


def _has_glyph(c: str, font_file: str) -> bool:
    """Hat die Schrift dieses Zeichen? Ein fehlendes Zeichen zeichnet Pillow als Ersatz-Kästchen: vergleichen."""
    from PIL import ImageFont

    f = _GLYPH_FONT.get(font_file) or _GLYPH_FONT.setdefault(font_file, ImageFont.truetype(font_file, 40))
    box = _GLYPH_FONT.get(font_file + "#") or _GLYPH_FONT.setdefault(font_file + "#", bytes(f.getmask("\uffff")))
    return bytes(f.getmask(c)) != box


_GLYPH_FONT: dict = {}


LYRIC_FONT = Path(__file__).parent / "static" / "fonts" / "Montserrat-ExtraBold.ttf"  # breit, modern (OFL)
TYPE_S = 0.22  # so lange dauert es, bis alle Buchstaben eines Worts erschienen sind (Buchstabe für Buchstabe)
LINE_HOLD_S = 1.2  # letztes Wort einer Zeile bleibt mindestens so lange stehen
FADE_OUT_S = 0.3  # dann blendet es aus
LYRIC_MAX_PX = 170  # Schriftgröße (fester Platz, gleiche Größe; nur zu lange Wörter kleiner)
FADE_IN_S = 0.08  # Wort blendet so schnell ein (statt hart zu erscheinen)
BLUR_OUT_PX = 10  # so verschwommen wird ein Wort beim Ausblenden am Zeilenende
LYRIC_FPS = 30  # Textspur mit 30 Bildern/s (reicht für Text, halbiert die Rechenzeit)


def lyric_schedule(items: list[dict], total: float) -> list[dict]:
    """Wann welches Wort steht (Vorbild: ein Wort zur Zeit, bleibt bis zum nächsten, am Zeilenende länger, dann
    weich aus). items: [{"a", "b", "txt", "eol"}] in zeitlicher Reihenfolge. Rückgabe mit "end" und "fade"."""
    out = []
    for j, x in enumerate(items):
        nxt = items[j + 1]["a"] if j + 1 < len(items) else total
        nxt = min(nxt, x.get("stop", nxt))  # nächstes Wort überhaupt (auch an der Wand): nie zwei gleichzeitig
        if x.get("eol") or nxt - x["a"] > 2.5:  # Zeilenende oder lange Pause: länger stehen, dann ausblenden
            end, fade = min(nxt, max(x["b"], x["a"] + LINE_HOLD_S + FADE_OUT_S), total), True
        else:  # mitten in der Zeile: bleibt, bis das nächste Wort beginnt (keine Lücke, kein Aufpoppen)
            end, fade = min(nxt, total), False
        if end - x["a"] >= 0.12:
            out.append(dict(x, end=round(end, 3), fade=fade))
    return out


LINE_MAX_PX = 120  # Schriftgröße ganzer Zeilen (bis zwei Reihen)


def _line_layout(line: list[str], font_file: str, width: int, height: int) -> dict:
    """Zeile auf ein bis drei Reihen verteilen, so groß wie möglich (höchstens LINE_MAX_PX), mittig. Die Lage jedes
    Worts steht fest, damit beim Aufbauen nichts springt."""
    from PIL import ImageFont

    ws = [printable(w, font_file) for w in line]
    best = None
    for size in range(LINE_MAX_PX, 40, -6):
        font = ImageFont.truetype(font_file, size)
        asc, desc = font.getmetrics()
        sp = font.getlength(" ")
        layouts = [[ws]] + [[ws[:k], ws[k:]] for k in range(1, len(ws))] + \
            [[ws[:k], ws[k:m], ws[m:]] for k in range(1, len(ws)) for m in range(k + 1, len(ws))]
        for rows in layouts:
            widths = [sum(font.getlength(w) for w in r) + sp * (len(r) - 1) for r in rows]
            if max(widths) <= width * 0.86 and len(rows) * (asc + desc) <= height * 0.95:
                bal = max(widths) - min(widths) if len(rows) > 1 else 0
                if best is None or (len(rows), bal) < (len(best["rows"]), best["bal"]):
                    best = {"rows": rows, "bal": bal, "widths": widths}
        if best:
            font = ImageFont.truetype(font_file, size)
            asc, desc = font.getmetrics()
            rh = asc + desc
            y0 = (height - rh * len(best["rows"])) // 2
            pos, n = [], 0
            for r, (row, wdt) in enumerate(zip(best["rows"], best["widths"])):
                x = (width - wdt) / 2
                for w in row:
                    pos.append((x, y0 + r * rh, w))
                    x += font.getlength(w) + sp
                    n += 1
            return {"font": font, "size": size, "pos": pos}
    font = ImageFont.truetype(font_file, 44)
    return {"font": font, "size": 44, "pos": [(width * 0.07, 0, " ".join(ws))]}


def _line_frame(lay: dict, k: int, p: float, dark: bool, width: int, height: int):
    """Bild einer Zeile: Wörter vor ``k`` ganz, Wort ``k`` zu Anteil ``p`` (Buchstabe für Buchstabe)."""
    from PIL import Image, ImageDraw, ImageFilter

    font, size = lay["font"], lay["size"]
    parts = []
    for i, (x, y, w) in enumerate(lay["pos"][:k + 1]):
        if i == k:
            w = w[:max(1, int(len(w) * p + 0.999))]
        parts.append((x, y, w))
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    sh = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ds = ImageDraw.Draw(sh)
    glow = (255, 255, 255, 70) if dark else (0, 0, 0, 170)
    for x, y, w in parts:
        ds.text((x, y + (0 if dark else size * 0.05)), w, font=font, fill=glow)
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(max(size // 18, 3))))
    d = ImageDraw.Draw(img)
    for x, y, w in parts:
        d.text((x, y), w, font=font, fill=(17, 17, 17, 255) if dark else (255, 255, 255, 255))
    return img


def render_lyric_track(items: list[dict], total: float, path: Path, width: int, height: int,
                       fps: int = OUT_FPS) -> None:
    """Songtext als eigene, durchsichtige Videospur (RGBA, qtrle): fester Platz, gleiche Größe, Buchstaben
    erscheinen nacheinander, Wort steht bis zum nächsten, Zeilenende blendet weich aus. Weiße Schrift mit weichem
    Schatten, ohne Umrandung, ohne Drehung (Vorbild)."""
    import math

    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    font_file = str(LYRIC_FONT if LYRIC_FONT.exists() else FONT_FILE)
    sched = lyric_schedule(items, total)
    # gleiche Größe für alle Wörter; nur Wörter, die nicht in 86 % der Breite passen, werden kleiner
    texts = [printable(x["txt"], font_file) for x in sched]
    fonts: dict[int, "ImageFont.FreeTypeFont"] = {}
    words = []
    line_dark = False
    for x, t in zip(sched, texts):
        if x.get("line"):  # ganze Zeile, baut sich Wort für Wort auf: eigene Darstellung (siehe _line_frame)
            if x.get("pos", 0) == 0:
                line_dark = x.get("dark", False)
            words.append((dict(x, dark=line_dark), _line_layout(x["line"], font_file, width, height), None, 0))
            continue
        size = LYRIC_MAX_PX
        while size > 50 and ImageFont.truetype(font_file, size).getlength(t) > width * 0.86:
            size -= 6
        font = fonts.setdefault(size, ImageFont.truetype(font_file, size))
        asc, desc = font.getmetrics()
        y0 = (height - (asc + desc)) // 2
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        x0 = (width - font.getlength(t)) / 2
        # Farbe wie im Vorbild: auf hellem Hintergrund schwarz (mit leichtem hellem Schein), auf dunklem weiß
        # (mit weichem Schatten)
        dark = x.get("dark", False)
        sh = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        glow = (255, 255, 255, 70) if dark else (0, 0, 0, 170)
        ImageDraw.Draw(sh).text((x0, y0 + (0 if dark else size * 0.05)), t, font=font, fill=glow)
        sh = sh.filter(ImageFilter.GaussianBlur(max(size // 18, 3)))
        img.alpha_composite(sh)
        ImageDraw.Draw(img).text((x0, y0), t, font=font, fill=(17, 17, 17, 255) if dark else (255, 255, 255, 255))
        edges = [x0 + font.getlength(t[:k]) for k in range(len(t) + 1)]  # rechte Kante nach k Buchstaben
        words.append((x, img, edges, size))
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{width}x{height}",
                             "-r", str(fps), "-i", "-", "-c:v", "qtrle", str(path)], stdin=subprocess.PIPE)
    blank = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    cache: dict = {}
    try:
        for n in range(int(math.ceil(total * fps))):
            t = n / fps
            cur = next((w for w in words if w[0]["a"] <= t < w[0]["end"]), None)
            if cur is None:
                proc.stdin.write(blank.tobytes())
                continue
            x, img, edges, size = cur
            if edges is None:  # ganze Zeile
                sung = (x["sung"] - x["a"]) if x.get("sung") else TYPE_S
                reveal = min(max(0.8 * sung, 0.12), 0.6, 0.6 * (x["end"] - x["a"]))
                p = 1.0 if reveal <= 0 else min(max((t - x["a"]) / reveal, 0.0), 1.0)
                alpha, blur = 1.0, 0.0
                if x.get("pos", 0) == 0:
                    alpha = min(1.0, max(0.0, (t - x["a"]) / FADE_IN_S))
                if x["fade"]:
                    out = min(1.0, max(0.0, (x["end"] - t) / FADE_OUT_S))
                    alpha = min(alpha, out)
                    blur = round((1.0 - out) * BLUR_OUT_PX, 1)
                key = ("L", tuple(x["line"]), x["pos"], round(p, 2), round(alpha, 2), blur, x.get("dark", False))
                if key not in cache:
                    fr = _line_frame(img, x["pos"], p, x.get("dark", False), width, height)
                    if blur > 0:
                        fr = fr.filter(ImageFilter.GaussianBlur(blur))
                    if alpha < 1.0:
                        fr.putalpha(fr.getchannel("A").point(lambda v, f=alpha: int(v * f)))
                    cache[key] = fr.tobytes()
                    if len(cache) > 400:
                        cache.clear()
                proc.stdin.write(cache[key])
                continue
            letters = len(edges) - 1
            # Buchstaben im Tempo des Gesangs: über die Zeit, in der das Wort gesungen wird (0,12-0,6 s)
            sung = (x["sung"] - x["a"]) if x.get("sung") else TYPE_S
            reveal = min(max(0.8 * sung, 0.12), 0.6, 0.6 * (x["end"] - x["a"]))
            p = 1.0 if reveal <= 0 else min(max((t - x["a"]) / reveal, 0.0), 1.0)
            k = min(letters, int(math.floor(p * letters)) + 1)  # sichtbare Buchstaben (der nächste blendet ein)
            alpha = min(1.0, max(0.0, (t - x["a"]) / FADE_IN_S))  # weich einblenden
            blur = 0.0
            if x["fade"]:
                out = min(1.0, max(0.0, (x["end"] - t) / FADE_OUT_S))
                alpha = min(alpha, out)
                blur = round((1.0 - out) * BLUR_OUT_PX, 1)  # verschwommen auflösen (Vorbild)
            key = (id(img), k, round(alpha, 2), blur)
            if key not in cache:
                cut = int(round(edges[k])) + 1 if k < letters else width  # genau an der Buchstabenkante
                fr = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                fr.paste(img.crop((0, 0, cut, height)), (0, 0))
                if blur > 0:
                    fr = fr.filter(ImageFilter.GaussianBlur(blur))
                if alpha < 1.0:
                    a = fr.getchannel("A").point(lambda v, f=alpha: int(v * f))
                    fr.putalpha(a)
                cache[key] = fr.tobytes()
                if len(cache) > 400:
                    cache.clear()
            proc.stdin.write(cache[key])
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode:
        raise RuntimeError("Songtext-Spur: Kodieren fehlgeschlagen")


DARK_TEXT_LUMA = 150  # Hintergrund heller als das (0..255): schwarze Schrift


def mark_dark_text(items: list[dict], files, segs: list[dict], y0: int, band: int) -> None:
    """Für jedes Wort die Helligkeit des Hintergrunds an seiner Stelle messen (Bild aus dem fertigen Segment zur
    Wortmitte, Textbereich) und "dark" setzen: helle Maps bekommen schwarze Schrift wie im Vorbild."""
    import numpy as np

    for x in items:
        t = (x["a"] + min(x.get("stop", x["b"]), x["b"] + 0.5)) / 2
        k = next((i for i, sg in enumerate(segs) if sg["o0"] <= t < sg["o0"] + sg["out"]), None)
        if k is None:
            continue
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(t - segs[k]['o0'], 0):.3f}", "-i", str(files[k]),
                              "-frames:v", "1", "-vf", f"crop={OUT_W}:{band}:0:{y0},scale=96:24,format=gray",
                              "-f", "rawvideo", "-"], capture_output=True).stdout
        if len(raw) == 96 * 24:
            x["dark"] = float(np.frombuffer(raw, np.uint8).mean()) > DARK_TEXT_LUMA


def lyric_pos(j: int, during_kill: bool) -> tuple[int, float]:
    """Mitte (y) eines flachen Songtext-Worts: im Spielbild, oberes Viertel (wie im Vorbild im Bild statt als
    Untertitel daneben), deutlich über dem Fadenkreuz in der Mitte, damit der Kill frei bleibt."""
    if LANDSCAPE:
        return int(OUT_H * 0.28), 1.0
    return BOX_Y + int(BOX * 0.24), 1.0


def one_scene(a: float, b: float, cuts: list[float]) -> tuple[float, float]:
    """Zeitfenster [a, b] auf das längste Stück ohne Schnitt kürzen."""
    pts = [a] + sorted(c for c in cuts if a + 0.02 < c < b - 0.02) + [b]
    best = max(zip(pts, pts[1:]), key=lambda p: p[1] - p[0])
    return round(best[0], 3), round(best[1], 3)


def png_aspect(path) -> float:
    from PIL import Image

    from cstaktik import wall_text

    with Image.open(path) as im:  # beim 3D-Schild zählt die Vorderseite (ohne Leuchten)
        return wall_text.word_aspect(im)


SIGN_FACE = (255, 214, 10)     # Vorderseite des Schilds (Vorbild "TALK": gelb, leuchtend)
SIGN_SIDE = (150, 96, 0)       # Seitenflächen (Tiefe)
SIGN_EDGE = (110, 60, 0)       # feine Kante um die Vorderseite


def sign_png(text: str, path: Path, font_file: str) -> None:
    """Wand-Wort als 3D-Schild: gelbe Vorderseite, dunklere Tiefe nach unten, weiches Leuchten rundherum. Die
    Lage der Vorderseite (ohne Tiefe und Leuchten) steht im Bild als "inner": nur sie wird auf die Wand gepasst."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    from PIL.PngImagePlugin import PngInfo

    size = 300
    while size > 60:
        font = ImageFont.truetype(font_file, size)
        l, t, r, b = font.getbbox(text)
        if r - l <= 1000:
            break
        size -= 10
    depth, glow, edge = max(size // 10, 6), max(size // 7, 10), max(size // 60, 2)
    pad = glow * 2 + depth
    fw, fh = r - l, b - t
    w, h = fw + 2 * pad, fh + 2 * pad
    x, y = pad - l, pad - t
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((x, y), text, font=font, fill=255, stroke_width=edge)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    halo = Image.new("RGBA", (w, h), (*SIGN_FACE, 0))
    halo.putalpha(mask.filter(ImageFilter.GaussianBlur(glow)).point(lambda v: int(min(255, v * 1.6) * 0.7)))
    img.alpha_composite(halo)
    side = Image.new("RGBA", (w, h), (*SIGN_SIDE, 255))
    for d in range(depth, 0, -1):  # Tiefe: Schichten nach unten, leicht nach rechts, hinten dunkler
        k = 0.65 + 0.35 * (1 - d / depth)
        layer = Image.new("RGBA", (w, h), tuple(int(c * k) for c in SIGN_SIDE) + (255,))
        img.paste(layer, (int(d * 0.35), d), mask)
    del side
    dr = ImageDraw.Draw(img)
    dr.text((x, y), text, font=font, fill=(*SIGN_FACE, 255), stroke_width=edge, stroke_fill=(*SIGN_EDGE, 255))
    dr.text((x, y), text, font=font, fill=(255, 236, 120, 255))  # helle Mitte: wirkt beleuchtet
    dr.text((x, y + max(size // 40, 2)), text, font=font, fill=(*SIGN_FACE, 255))
    info = PngInfo()
    info.add_text("inner", f"{pad - edge},{pad - edge},{pad + fw + edge},{pad + fh + edge}")
    img.save(path, pnginfo=info)


def word_png(text: str, path: Path, j: int, font_file: str, wall: bool = False) -> None:
    """Ein Wort als Bild: fette, enge Großbuchstaben, die die Breite füllen, schräg gestellt und leicht gedreht,
    dicker schwarzer Rand und ein farbiger, versetzter Schatten. Farbe und Drehung wechseln von Wort zu Wort."""
    from PIL import Image, ImageDraw, ImageFont

    text = printable(text, font_file)
    if wall:
        sign_png(text, path, font_file)
        return
    fill, shadow = LYRIC_COLORS[j % len(LYRIC_COLORS)]
    if wall:  # gleiche Farbe wie die Textspur: weiß (einheitlicher Look, Nutzer: Text soll wie eine Story wirken)
        fill = (255, 255, 255)
    size = 260 if wall else 240  # groß wie im Vorbild; Wand: wird später perspektivisch verkleinert
    while size > 60:
        font = ImageFont.truetype(font_file, size)
        l, t, r, b = font.getbbox(text)
        if r - l <= (1000 if wall else min(int(OUT_W * 0.8), 1400)):
            break
        size -= 10
    stroke, off = max(size // 13, 6), max(size // 16, 8)
    if wall:  # wie aufgesprüht: dünner Rand, kein versetzter Schatten
        stroke, off = max(size // 30, 3), 0
    w, h = r - l + 2 * stroke + off + 80, b - t + 2 * stroke + off + 60
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    x, y = 40 + stroke - l, 30 + stroke - t
    dr.text((x + off, y + off), text, font=font, fill=(*shadow, 255), stroke_width=stroke, stroke_fill=(*shadow, 255))
    dr.text((x, y), text, font=font, fill=(*fill, 255), stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
    if wall:  # auf der Wand: gerade, ohne Drehung (die Perspektive kommt von der Wand), etwas größer gerechnet
        img.save(path)
        return
    sh = 0.16  # schräg stellen (die Schrift hat keinen Kursiv-Schnitt)
    img = img.transform((w + int(sh * h), h), Image.AFFINE, (1, sh, -sh * h, 0, 1, 0), Image.BICUBIC)
    img.rotate(LYRIC_ROT[j % len(LYRIC_ROT)], expand=True, resample=Image.BICUBIC).save(path)


TR_OUT, TR_Z = 0.14, 0.14  # Übergang: nach dem Schnitt 140 ms aus 14 % Zoom heraus
RISER_MAX = 1.2  # Riser vor dem Kill: höchstens so lang (s), sonst 1,5 Schläge
SFX_VOL = 0.45
IMPACT = "sin(2*PI*(45+30*exp(-t*30))*t)*exp(-t*7)"  # tiefer, kurzer Bass-Schlag ohne Knack-Rauschen


def transition_cuts(segs: list[dict]) -> list[float]:
    """Schnitte, an denen eine neue Szene beginnt (nach einem Kill), ohne den Anfang: dort kommt der Übergang hin.
    Schnitte innerhalb einer Szene bleiben hart, sonst wirkt jeder Wechsel gleich und nichts sticht heraus."""
    return [round(b["o0"], 3) for a, b in zip(segs, segs[1:]) if a["kind"] == "hit" and b["kind"] in ("shot", "ramp")
            and b["o0"] > 0.2]


def transition_vf(cuts: list[float]) -> str:
    """Kurzer Zoom an Szenenwechseln nach einem Kill: die neue Szene beginnt 14 % vergrößert und gleitet in 140 ms
    zurück. Erst nach dem Schnitt (der Kill bleibt unangetastet) und ohne Unschärfe (Nutzer: Verschwimmen störte).
    Ohne Schnitte: nichts."""
    if not cuts:
        return ""
    bumps = "+".join(f"gte(t\\,{c})*pow(max(0\\,1-(t-{c})/{TR_OUT})\\,2)" for c in cuts)
    z = f"(1+{TR_Z}*min(1\\,{bumps}))"
    return f"scale=w='2*trunc({OUT_W}*{z}/2)':h=-2:eval=frame:flags=lanczos,crop={OUT_W}:{OUT_H},"


def sfx_expr(segs: list[dict], beat: float, cuts: list[float]) -> str:
    """Sound-Design als eine Tonspur: Riser (Rauschen + steigender Ton) in die letzten Schläge vor jedem Kill, Impact
    (tiefer Schlag) genau auf dem Kill, Whoosh an jedem Szenenwechsel. Spannung, die sich auf dem Schlag entlädt,
    ist das Grundmuster von Build-up und Drop in elektronischer Musik (Solberg 2014)."""
    import re

    parts = []
    for x in segs:
        if x["kind"] != "hit":
            continue
        o = x["o0"]
        L = min(1.5 * beat, RISER_MAX, o)
        if L > 0.3:
            a = o - L
            # nur Rauschen, das anschwillt (kein Ton: der steigende Sinus klang wie ein Pfeifen)
            parts.append(f"between(t,{a:.3f},{o:.3f})*pow((t-{a:.3f})/{L:.3f},3)*0.30*(random(0)*2-1)")
        boom = re.sub(r"\bt\b", f"(t-{o:.3f})", IMPACT)
        parts.append(f"between(t,{o:.3f},{o + 0.5:.3f})*0.6*({boom})")
    for c in cuts:
        parts.append(f"0.35*(random(0)*2-1)*exp(-pow((t-{c:.3f})/0.05,2))")
    return "+".join(parts) or "0"


SYNC_TOL_MS = 45  # so weit darf ein Schuss vom Raster weg sein und gilt noch als "auf dem Beat"


def sync_report(shot_times: list[float], beat_times: list[float], beat: float) -> dict:
    """Wie viele Schüsse im fertigen Spielton auf dem Raster der Musik liegen (Achtel oder Sechzehntel, ±45 ms).
    Gemessen, nicht geplant: die Schüsse werden im zusammengesetzten Spielton neu erkannt."""
    import numpy as np

    if not shot_times or not beat_times:
        return {"on": 0, "total": len(shot_times), "worst_ms": None}
    g = np.asarray(beat_times, float)
    grid = np.sort(np.concatenate([g + k * beat / 4 for k in range(4)]))
    offs = [abs(t - grid[int(np.argmin(np.abs(grid - t)))]) * 1000 for t in shot_times]
    on = [o for o in offs if o <= SYNC_TOL_MS]
    return {"on": len(on), "total": len(offs), "worst_ms": round(max(on)) if on else None}


def frame_grid(pl: dict, fps: int = OUT_FPS) -> None:
    """Schnittpunkte auf ganze Bilder legen. Sonst sind Segmente z. B. 60,48 Bilder lang; beim Aneinanderhängen
    summiert sich der Rest, und das Video doppelt ab und zu ein Bild (gemessen am echten Clip: 6 doppelte Bilder,
    je kurz nach einem Schnitt). Verschiebung höchstens eine halbe Bilddauer (8 ms), ohne Aufsummieren."""
    for sg in pl["segments"]:
        a = round(sg["o0"] * fps) / fps
        e = round((sg["o0"] + sg["out"]) * fps) / fps
        sg["o0"], sg["out"] = round(a, 6), round(e - a, 6)
    last = pl["segments"][-1]
    pl["seconds"] = round(last["o0"] + last["out"], 6)


def render_workers() -> int:
    """So viele Segmente gleichzeitig: alle Kerne bis höchstens 4 (mehr bringt bei kurzen Videos kaum etwas)."""
    import os

    return max(1, min(4, os.cpu_count() or 1))


def level_chain(path: str, target: float = None) -> str:
    """Lautheit messen und gleichmäßig auf das Ziel anheben, Spitzen hart begrenzen (−1 dBFS). Anders als loudnorm im
    Normalbetrieb bleibt die Dynamik erhalten (Schüsse stechen heraus)."""
    import re

    target = TARGET_LUFS if target is None else target
    lu = loudness(path)
    if lu is not None and lu < SILENT_LUFS:
        raise ValueError(f"Die gemischte Tonspur ist fast still ({lu:.0f} LUFS). Bitte melden; unter dem Fehler stehen "
                         f"die Pegel von Spielton und Musik." + (f" {AUDIO_NOTE}" if AUDIO_NOTE else ""))
    gain = max(min(target - lu, 24.0), -24.0) if lu is not None else 0.0
    # highpass: Gleichspannungsversatz entfernen (sonst wird er mit verstärkt, gesehen als stumme "flache Linie")
    return f"highpass=f=20,volume={gain:.2f}dB,alimiter=limit=0.89:attack=1:release=60:level=0,aresample=48000"


SILENT_LUFS = -45.0  # leiser als das: Tonspur gilt als stumm
SR_MIX = 48000


def _read_audio(path: str, ss: float | None = None, d: float | None = None):
    """Ton als float32-Array (Stereo, 48 kHz). Ohne Ton: leeres Array."""
    import numpy as np

    cmd = ["ffmpeg", "-v", "error"] + (["-ss", str(ss)] if ss else []) + (["-t", str(d)] if d else []) + \
          ["-i", str(path), "-vn", "-ac", "2", "-ar", str(SR_MIX), "-f", "f32le", "-"]
    p = subprocess.run(cmd, capture_output=True)
    a = np.frombuffer(p.stdout, np.float32)
    return a[: len(a) // 2 * 2].reshape(-1, 2).copy()


def sfx_wave(marks: list[dict], beat: float, cuts: list[float], n: int, seed: int = 7):
    """Wie sfx_expr, aber direkt als Samples: Riser (anschwellendes Rauschen) vor jedem Kill, Impact (tiefer
    Schlag) auf dem Kill, Whoosh an Szenenwechseln. Mono, Länge n."""
    import numpy as np

    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=np.float64) / SR_MIX
    out = np.zeros(n, np.float64)
    noise = rng.uniform(-1, 1, n)
    for x in marks:
        o = x["o0"]
        L = min(1.5 * beat, RISER_MAX, o)
        if L > 0.3:
            a = o - L
            m = (t >= a) & (t < o)
            out[m] += ((t[m] - a) / L) ** 3 * 0.30 * noise[m]
        m = (t >= o) & (t < o + 0.5)
        tau = t[m] - o
        out[m] += 0.6 * np.sin(2 * np.pi * (45 + 30 * np.exp(-tau * 30)) * tau) * np.exp(-tau * 7)
    for c in cuts:
        out += 0.35 * noise * np.exp(-(((t - c) / 0.05) ** 2))
    return out.astype(np.float32)


def music_gain(marks: list[dict], game_shots: list[float], total: float, n: int):
    """Lautstärke der Musik über die Zeit: beim Kill-Schuss weich abgesenkt, bei jedem Schuss kurz, am Ende aus."""
    import numpy as np

    t = np.arange(n, dtype=np.float64) / SR_MIX
    duck = np.zeros(n)
    for x in marks:
        o = x["o0"]
        duck += np.clip((t - (o - 0.04)) / 0.04, 0, 1) * np.clip((o + KILL_SND_S + 0.3 - t) / 0.3, 0, 1)
    dips = np.zeros(n)
    for x in game_shots:
        dips += np.exp(-(((t - (x + 0.03)) / (SHOT_DIP_S / 2)) ** 2))
    g = np.maximum(0.25, 1 - KILL_DUCK * np.minimum(1, duck) - SHOT_DIP * np.minimum(1, dips))
    g *= np.clip((total - t) / 0.12, 0, 1)  # am Ende kurz ausblenden
    return g.astype(np.float32)


def mix_audio(files, segs: list[dict], music: str, music_ss: float, total: float, marks: list[dict],
              game_shots: list[float], beat: float, cuts: list[float], out: Path) -> None:
    """Spielton (je Segment exakt an seine Stelle, 6 ms Ein-/Ausblenden gegen Knacken) + Musik (mit Absenkung) +
    Effekte zusammenrechnen und als WAV schreiben."""
    import numpy as np

    n = int(round(total * SR_MIX))
    game = np.zeros((n, 2), np.float32)
    fade = int(0.006 * SR_MIX)
    for f, sg in zip(files, segs):
        a = _read_audio(str(f))
        start, length = int(round(sg["o0"] * SR_MIX)), int(round(sg["out"] * SR_MIX))
        a = a[:length]
        if len(a) < 2 * fade:
            continue
        ramp = np.linspace(0, 1, fade, dtype=np.float32)[:, None]
        a[:fade] *= ramp
        a[-fade:] *= ramp[::-1]
        end = min(start + len(a), n)
        game[start:end] += a[: end - start]
    mu = _read_audio(music, music_ss, total)[:n]
    mus = np.zeros((n, 2), np.float32)
    mus[: len(mu)] = mu
    mus *= music_gain(marks, game_shots, total, n)[:, None]
    fx = sfx_wave(marks, beat, cuts, n)[:, None] * SFX_VOL
    mix = game + mus + fx
    p = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR_MIX), "-ac", "2", "-i", "-",
                        "-c:a", "pcm_f32le", str(out)], input=mix.astype(np.float32).tobytes(), capture_output=True)
    if p.returncode:
        raise RuntimeError("Ton mischen fehlgeschlagen: " + p.stderr.decode(errors="replace")[-300:])
AUDIO_NOTE = ""


def loudness(path: str, ss: float | None = None, d: float | None = None) -> float | None:
    """Integrierte Lautheit (LUFS) einer Datei oder eines Ausschnitts, None wenn nicht messbar."""
    import re

    cmd = ["ffmpeg", "-nostats"] + (["-ss", str(ss)] if ss else []) + (["-t", str(d)] if d else []) + \
          ["-i", path, "-vn", "-af", "ebur128", "-f", "null", "-"]
    err = subprocess.run(cmd, capture_output=True, text=True).stderr
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", err)
    return float(m[-1]) if m else None


def shift_words(words: list[str], sh: float) -> list[str]:
    """Alle Wörter mit Zeit ("a-e:WORT" oder "a:WORT") um ``sh`` Sekunden verschieben, nie vor 0."""
    import re

    out = []
    for w in words:
        m = re.fullmatch(r"(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))?:(.+)", w, re.S)
        if not m:
            out.append(w)
            continue
        a = max(float(m.group(1)) + sh, 0.0)
        tm = f"{a:.2f}" + (f"-{max(float(m.group(2)) + sh, a + 0.1):.2f}" if m.group(2) else "")
        out.append(f"{tm}:{m.group(3)}")
    return out


def base_path(out) -> Path:
    """Video ohne Songtext (für das Nachjustieren des Timings)."""
    return Path(out).with_suffix(".base.mp4")


def lyrics_path(out) -> Path:
    return Path(out).with_suffix(".lyrics.json")


def save_lyrics(out, lyr: dict) -> None:
    import json

    lyrics_path(out).write_text(json.dumps(lyr, ensure_ascii=False))


def load_lyrics(out) -> dict | None:
    import json

    p = lyrics_path(out)
    return json.loads(p.read_text()) if p.exists() else None


def _shifted(items: list[dict], sh: float, total: float) -> list[dict]:
    out = []
    for x in items:
        y = dict(x)
        for key in ("a", "b", "stop", "sung"):
            if y.get(key) is not None:
                y[key] = round(min(max(y[key] + sh, 0.0), total), 3)
        if y["b"] - y["a"] >= 0.1:
            out.append(y)
    return out


def preview_words(lyr: dict) -> list[dict]:
    """Alle Wörter mit Anzeige-Zeiten (ohne Versatz) für die Live-Vorschau im Browser: flache und Wand-Wörter."""
    flat = [{"a": x["a"], "end": x["end"], "txt": printable(x["txt"], str(LYRIC_FONT)), "dark": x.get("dark", False),
             "fade": x["fade"]} for x in lyric_schedule(lyr["flat"], lyr["total"])]
    walls = [{"a": w["a"], "end": w["b"], "txt": printable(w["txt"], str(LYRIC_FONT)), "dark": False, "fade": False,
              "wall": True} for w in lyr["walls"]]
    return sorted(flat + walls, key=lambda x: x["a"])


def split_walls(base: str, walls: list[dict], lyr: dict) -> tuple[list[dict], list[dict]]:
    """Für jedes Wand-Wort das Bild zu seinem Beginn ansehen: Wand gefunden -> bleibt an der Wand, sonst wird es ein
    flaches Wort der Textspur (Farbe nach Hintergrund wie dort). Betonte Wörter in Gruppen ("group", "rank", "need"):
    je Gruppe die besten "need" Wörter mit Wand; fehlen welche, die besten übrigen flach, der Rest entfällt."""
    import numpy as np
    from PIL import Image

    from cstaktik import wall_text

    font = str(LYRIC_FONT) if LYRIC_FONT.exists() else lyr.get("font") or ""
    w_out, h_out = lyr["out_w"], lyr["out_h"]

    def frame(w):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{w['a'] + 0.04:.3f}", "-i", base, "-frames:v", "1",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        return np.frombuffer(raw, np.uint8).reshape(h_out, w_out, 3) if len(raw) == w_out * h_out * 3 else None

    def has_wall(w, arr, td):
        if arr is None or not font or not w.get("eligible", True):
            return False
        game = arr[lyr["box_y"]:lyr["box_y"] + lyr["box"], lyr["box_x"]:lyr["box_x"] + lyr["box"]]
        png = Path(td) / "w.png"
        word_png(w["txt"], png, w.get("j", 0), font, wall=True)
        im = Image.open(png)
        return wall_text.place_on_wall(wall_text._gray(game), game[::wall_text.SCALE, ::wall_text.SCALE],
                                       wall_text.word_aspect(im), full=game) is not None

    def to_flat(w, arr):
        f = {k: w[k] for k in ("a", "b", "txt") if k in w}
        f.update(eol=w.get("eol", False), stop=w.get("stop", w["b"]), sung=w.get("sung"))
        if w.get("flat_b"):
            f["b"] = w["flat_b"]
        if arr is not None:
            y0 = max(lyr["y_mid"] - lyr["band"] // 2, 0)
            f["dark"] = float(arr[y0:y0 + lyr["band"]].mean()) > DARK_TEXT_LUMA
        return f

    keep, moved = [], []
    groups: dict = {}
    with tempfile.TemporaryDirectory() as td:
        for w in walls:
            if "group" in w:
                groups.setdefault(w["group"], []).append(w)
                continue
            arr = frame(w)
            if has_wall(w, arr, td):
                keep.append(w)
            else:
                moved.append(to_flat(w, arr))
        for g, ws in groups.items():
            ws = sorted(ws, key=lambda w: w["rank"])
            need = ws[0].get("need", 1)
            frames = {}
            chosen = []
            for w in ws:
                if len(chosen) >= need:
                    break
                frames[id(w)] = frame(w)
                if has_wall(w, frames[id(w)], td):
                    chosen.append(w)
            fill = [w for w in ws if w not in chosen][:need - len(chosen)]
            keep += chosen
            moved += [to_flat(w, frames.get(id(w)) if id(w) in frames else frame(w)) for w in fill]
    # nie zwei Wörter gleichzeitig: jedes endet, wenn das nächste gezeigte beginnt
    shown = sorted(keep + moved, key=lambda x: x["a"])
    for x, y in zip(shown, shown[1:]):
        if x["b"] > y["a"]:
            x["b"] = max(y["a"], x["a"] + 0.15)
        if x.get("stop", 0) > y["a"]:
            x["stop"] = y["a"]
    return keep, moved


def apply_lyrics(base: str, lyr: dict, out: str, sh: float = 0.0, progress=None) -> dict | None:
    """Songtext über das Video ohne Text legen, um ``sh`` Sekunden verschoben: flache Wörter als Textspur, Wand-Wörter
    auf Wände. Rückgabe: Statistik der Wand-Wörter (oder None)."""
    total = lyr["total"]
    flat = _shifted(lyr["flat"], sh, total)
    walls = _shifted(lyr["walls"], sh, total)
    if lyr.get("drop"):  # verschoben: trotzdem kein Text nach dem Drop
        dr = lyr["drop"]
        flat = [dict(x, b=min(x["b"], dr), stop=min(x.get("stop", dr), dr)) for x in flat if x["a"] < dr - 0.1]
        walls = [dict(x, b=min(x["b"], dr)) for x in walls if x["a"] < dr - 0.1]
    # Wand-Wörter nur dort, wo zu Wortbeginn wirklich eine Wand im Bild ist; sonst in die normale Textspur
    walls, moved = split_walls(base, walls, lyr)
    if moved:
        flat = sorted(flat + moved, key=lambda x: x["a"])
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        step = out if not walls else str(tmp / "flat.mp4")
        if flat:
            y0 = lyr["y_mid"] - lyr["band"] // 2
            track = tmp / "lyrics.mov"
            render_lyric_track(flat, total, track, lyr["out_w"], lyr["band"], LYRIC_FPS)
            _run(["ffmpeg", "-v", "error", "-y", "-i", base, "-i", str(track), "-filter_complex",
                  f"[1:v]format=rgba[lt];[0:v][lt]overlay=0:{y0}:format=auto[v]", "-map", "[v]", "-map", "0:a",
                  "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(lyr["fps"]),
                  "-c:a", "copy", "-movflags", "+faststart", step])
        else:
            import shutil

            shutil.copyfile(base, step)
        if not walls:
            return None
        from cstaktik import wall_text

        font = str(LYRIC_FONT) if LYRIC_FONT.exists() else lyr.get("font") or ""
        for w in walls:
            png = tmp / f"wall{w['j']:02d}.png"
            word_png(w["txt"], png, w["j"], font, wall=True)
            w["png"] = str(png)
        return wall_text.apply(step, out, walls, lyr["box_y"], lyr["box"], lyr["fps"], lyr["y_mid"],
                               size=(lyr["out_w"], lyr["out_h"]), box_x=lyr["box_x"],
                               enc=["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                                    "-movflags", "+faststart"])


STORY_DROP = True      # Aufbau wie die Vorbilder (3 Clips mit 100k+ Likes): Text-Teil, dann Drop, dann Kills ohne Text
DROP_SAT = 0.3         # Sättigung im Text-Teil (Vorbilder: fast schwarz-weiß, Text farbig); ab dem Drop volle Farbe
DROP_FLASH_S = 0.07    # kurzer weißer Blitz am Drop


def story_drop(music: str, music_ss: float, total: float, segs: list[dict]) -> float | None:
    """Wo der Text-Teil endet und die Kills ohne Text beginnen: an einem Schnitt zwischen 25 und 75 % des Videos, dort
    wo die Musik (Bass) am stärksten anzieht (2 s danach gegen 2 s davor). Ohne deutlichen Anstieg: der Schnitt nahe
    45 %. None bei unter 10 s oder weniger als 3 Stücken (dann wie bisher)."""
    import numpy as np

    cuts = [x["o0"] for x in segs[1:] if 0.25 * total <= x["o0"] <= 0.75 * total]
    if total < 10 or len(segs) < 3 or not cuts:
        return None
    try:
        raw = _run(["ffmpeg", "-v", "error", "-ss", f"{music_ss:.3f}", "-t", f"{total:.3f}", "-i", music, "-vn", "-ac", "1",
                    "-ar", "8000", "-af", "lowpass=f=150", "-f", "f32le", "-"])
        x = np.frombuffer(raw, np.float32)
        hop = 400  # 50 ms
        e = np.sqrt((x[: len(x) // hop * hop].reshape(-1, hop) ** 2).mean(axis=1))
        ref = float(np.percentile(e, 90)) or 1e-9

        def score(t):
            k = int(t / 0.05)
            a, b = e[max(k - 40, 0):k], e[k:k + 40]
            return (float(b.mean()) - float(a.mean())) / ref if len(a) and len(b) else -1.0

        best = max(cuts, key=score)
        if score(best) >= 0.15:
            return round(best, 3)
    except Exception:  # noqa: BLE001 - ohne Musik-Analyse: Schnitt nahe 45 %
        pass
    return round(min(cuts, key=lambda c: abs(c - 0.45 * total)), 3)


def _safe_debug(dbg: dict, words, sung) -> dict | None:
    """Diagnose darf den Schnitt nie abbrechen (Nutzer: Fehler "could not convert string to float")."""
    try:
        return _lyrics_debug(dbg, words, sung)
    except Exception:  # noqa: BLE001
        return None


def _lyrics_debug(dbg: dict, words, sung) -> dict | None:
    """Diagnose kompakt: je Liste höchstens 120 Einträge "Sekunde Wort" (Sekunden im Video)."""
    import re

    def fmt(xs):
        out = []
        for w in (xs or [])[:120]:
            tm, _, txt = w.partition(":")
            if not _:
                out.append(w)
                continue
            m = re.match(r"-?\d+(?:\.\d+)?", tm)  # Start, auch negativ ("-1.50" liegt vor dem Videostart)
            out.append(f"{float(m.group(0)):.2f} {txt.rstrip(chr(182))}" if m else w)
        return out

    if not words and not sung:
        return None
    return {"gezeigt": fmt([w for w in words if ":" in w]), "erkannt": fmt(sung),
            "lrclib": fmt(dbg.get("lrclib")), "eingefuegt": [w.rstrip(chr(182)) for w in dbg.get("typed", [])][:120]}


def make_beat(src, music: str, out: str, music_ss: float = 0.0, music_d: float | None = None,
              words: list[str] | None = None, progress=None, song: str | None = None, fmt: str = "hoch",
              lyrics_shift: float = 0.0) -> dict:
    """Beat-Edit aus einem oder mehreren Clips: Musik gibt den Takt vor, Kills fallen auf die Schläge, Songtext Wort
    für Wort. ``words``: Wörter in Reihenfolge (ein Wort je Schlag) oder "Sekunde:WORT" für feste Zeiten."""
    from cstaktik import beats as beatmod

    set_layout(fmt)
    srcs = [src] if isinstance(src, str) else list(src)
    kills = detect_all(srcs)
    # Peak-End-Regel: Erinnert werden vor allem Höhepunkt und Ende. Der Clip mit den meisten Kills kommt zuletzt.
    if len(srcs) > 1:
        cnt = {x: sum(1 for k in kills if k["src"] == x) for x in srcs}
        best = max(srcs, key=lambda x: (cnt[x], -srcs.index(x)))
        order = [x for x in srcs if x != best] + [best]
        kills = [k for x in order for k in kills if k["src"] == x]
    if not kills:
        raise ValueError("In den Clips wurde kein eigener Kill gefunden (kein rot umrandeter Killfeed-Eintrag oben rechts).")
    bt = beatmod.beats(music, music_ss, music_d)
    try:
        mots = {x: motion(x) for x in srcs}
    except Exception:  # noqa: BLE001 - ohne Bewegungsdaten werden die Schnittpunkte wie bisher gesetzt
        mots = None
    shot_times = {x: shots(x) for x in srcs}
    if CLEAN_EDIT:
        pl = plan_clean(kills, bt["beats"], shot_times)
        # Video beginnt am ersten Schlag: Musik ab dort, Raster entsprechend verschieben (sonst liegt alles um diesen
        # Versatz neben der hörbaren Musik)
        sh = pl.get("music_shift", 0.0)
        music_ss = music_ss + sh
        bt = dict(bt, beats=[round(x - sh, 4) for x in bt["beats"] if x - sh >= -1e-6])
    else:
        pl = plan_beat(kills, duration(srcs[0]), bt["beats"], mots, bt.get("strength"), shot_times)
    frame_grid(pl)
    marks = pl.get("marks") or [x for x in pl["segments"] if x["kind"] == "hit"]
    try:  # Clips von hellen und dunklen Maps angleichen: ein durchgehender Look statt Farbsprüngen an Schnitten
        offs = brightness_offsets({x: luma(x) for x in srcs})
    except Exception:  # noqa: BLE001
        offs = {}
    for sg in pl["segments"]:
        sg["bright"] = offs.get(sg.get("src") or srcs[0], 0.0)
    font = _font()
    shown, source = 0, "eingetragen" if words else None
    sung = None
    dbg: dict = {}  # Diagnose für die Anzeige: was LRCLIB sagt, was die Spracherkennung hört, was gezeigt wird
    global SUNG_NOTE
    lrc_note = None
    if song and not words:  # Songname angegeben: Text mit Zeitstempeln von LRCLIB, Stelle im Song bestimmen
        from cstaktik import lrclib

        hit = lrclib.fetch(song, duration(music))
        if not hit:
            lrc_note = f"Für „{song}“ wurde bei LRCLIB kein Songtext mit Zeitstempeln gefunden (oder keine Verbindung)."
        else:
            tw = lrclib.timed_words(hit["lines"])
            off, why = lrclib.locate(tw, None, duration(music), hit["duration"])
            hint = " ".join(w for _, _, w in tw)[:600]
            sung = None
            if off is None:  # Ausschnitt: Stelle über ein paar erkannte Wörter finden
                sung = sung_words(music, music_ss, pl["seconds"], hint)
                off, why = lrclib.locate(tw, sung, duration(music), hit["duration"], sung_at=music_ss)
            name = f"{hit['track']} – {hit['artist']}"
            if off is None:
                lrc_note = f"Songtext für {name} gefunden, aber die Stelle im Song nicht: {why}."
            else:
                words = lrclib.clip_words(tw, off, music_ss, pl["seconds"])
                if sung is None:  # ganzer Song: Gesang im Ausschnitt erkennen, um die Wortzeiten nachzuschärfen
                    near = [w for a, _, w in tw if music_ss + off - 2 <= a <= music_ss + off + pl["seconds"] + 2]
                    sung = sung_words(music, music_ss, pl["seconds"], " ".join(near)[:600])
                # Abschnittsweise auf den Gesang legen: passt auch, wenn die Datei anders geschnitten ist als die
                # LRCLIB-Version (eine Verschiebung für alles ließ den Anfang weg, Nutzer-Video "Heartbeat")
                dbg["lrclib"] = [f"{a - off - music_ss:.2f}:{w}" for a, _, w in tw
                                 if -2 <= a - off - music_ss <= pl["seconds"] + 2]
                local, n_fit = lrclib.align_local(tw, off, music_ss, pl["seconds"], sung)
                if local:
                    words = local
                    why += f", Zeilen abschnittsweise über {n_fit} erkannte Wörter auf den Gesang gelegt"
                elif words:  # zu wenig Anker: wie bisher eine Verschiebung + Nachschärfen in der Nähe
                    words, n_fit = lrclib.refine(words, sung)
                    if n_fit:
                        why += f", Wortzeiten über {n_fit} erkannte Wörter angepasst"
                source, lrc_note = ("lrclib", f"{name}, {why}") if words else (None, f"{name}: an dieser Stelle "
                                                                                     "kein Gesang im Songtext.")
    if words and not any(":" in w for w in words):
        # Text eingefügt: mit der Spracherkennung (falls installiert) auf den Gesang legen, Text bleibt der eigene
        sung = sung_words(music, music_ss, pl["seconds"], " ".join(words))
        dbg["typed"] = list(words)
        if sung:
            words, source = align_lyrics(words, sung, pl["seconds"]), "ausgerichtet"
    elif not words and not song:  # weder Text noch Song: aus dem Gesang erkennen (falls installiert)
        words = sung_words(music, music_ss, pl["seconds"])
        source = "erkannt" if words else None
    if lrc_note:
        SUNG_NOTE = lrc_note
    if lyrics_shift and words:  # vom Nutzer eingestellt: alle Wörter früher (−) oder später (+)
        words = shift_words(words, lyrics_shift)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        files = [tmp / f"b{i:03d}.mp4" for i in range(len(pl["segments"]))]
        # Segmente sind unabhängig: parallel rechnen (die Zwischenbild-Berechnung nutzt nur einen Kern)
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=render_workers()) as ex:
            futs = [ex.submit(_render_beat_seg, srcs[0], seg, f, tmp, font) for seg, f in zip(pl["segments"], files)]
            for done, fu in enumerate(as_completed(futs), 1):
                fu.result()
                if progress:
                    progress(done, len(pl["segments"]) + 1)
        n = len(files)
        ins = [x for f in files for x in ("-i", str(f))]
        total = pl["seconds"]
        first_png = tmp / "loop.png"  # erstes Bild des Videos: am Ende eingeblendet, damit die Wiederholung nahtlos wirkt
        _run(["ffmpeg", "-v", "error", "-y", "-i", str(files[0]), "-frames:v", "1", str(first_png)])
        try:  # Kontrolle: Spielton wie im Video zusammensetzen, Schüsse neu erkennen, Abstand zum Raster messen
            lst = tmp / "segs.txt"
            lst.write_text("".join(f"file '{f}'\n" for f in files))
            _run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-vn", "-c:a", "pcm_s16le",
                  str(tmp / "game.wav")])
            game_shots = shots(str(tmp / "game.wav"))
            # einfacher Schnitt: nur die Kill-Schüsse werden auf den Beat gelegt, also nur die messen (im Spielton
            # wiedergefunden, höchstens 0,12 s neben der geplanten Stelle)
            ks_meas = ([x for x in game_shots if any(abs(x - mk["shot"]) <= 0.12 for mk in marks)] if CLEAN_EDIT
                       else game_shots)
            measured = sync_report(ks_meas, bt["beats"], pl["beat"])
        except Exception:  # noqa: BLE001 - die Messung ist nur eine Anzeige
            measured, game_shots = None, []
        # an jedem Schnitt den Spielton 6 ms ein- und ausblenden: sonst knackt es hörbar (eigener Ton-Graph)
        # Ton jedes Segments exakt auf seine Bildlänge: AAC-Ton ist oft ein paar ms länger; beim gemeinsamen
        # Aneinanderhängen entsteht sonst eine Lücke im Bild und ein doppeltes Bild (gemessen: 4 je Video)
        fc = ""
        # Pixel-Seitenverhältnis vereinheitlichen: Segmente kamen mit "nicht gesetzt" und 1280:1281 an, dann bricht
        # concat ab (Fehler beim Nutzer)
        fc += "".join(f"[{i}:v]setsar=1[sv{i}];" for i in range(n))
        fc += "".join(f"[sv{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vc0];"
        tcuts = [] if CLEAN_EDIT else transition_cuts(pl["segments"])  # einfacher Schnitt: harte Schnitte
        t_drop = story_drop(music, music_ss, total, pl["segments"]) if (STORY_DROP and CLEAN_EDIT) else None
        if t_drop:  # Text-Teil fast schwarz-weiß und etwas mehr Kontrast, am Drop kurzer Blitz, danach volle Farbe
            d0 = f"{t_drop:.3f}"
            grade = (f"hue=s={DROP_SAT}:enable='lt(t,{d0})',eq=contrast=1.08:enable='lt(t,{d0})',"
                     f"drawbox=x=0:y=0:w=iw:h=ih:color=white@0.55:t=fill:"
                     f"enable='between(t,{d0},{t_drop + DROP_FLASH_S:.3f})',")
        else:
            grade = ""
        fc += f"[vc0]{transition_vf(tcuts)}{grade}null[vc];"
        lp = max(total - LOOP_S, 0)
        fc += (f"[LOOPIN]format=rgba,fade=t=in:st={lp:.3f}:d={LOOP_S}:alpha=1[lp];"
               f"[vc][lp]overlay=0:0:enable='gte(t,{lp:.3f})'[v0];")
        last, k = "v0", n + 1  # Eingang n ist die Musik, danach je Wort ein Bild
        wall_words: list[dict] = []
        wall_on = WALL_TEXT
        if font and words:
            # während eines Kills gehört die Bildmitte dem Kill: dort kein Songtext
            busy = [(x["o0"], x["o0"] + x["out"]) for x in (marks + [y for y in pl["segments"] if y["kind"] == "hold"])]
            cuts = [x["o0"] for x in pl["segments"]]
            wl = word_list(words, bt["beats"])[:MAX_WORDS]
            flat_items: list[dict] = []
            # wie eine Story (Vorbild): bis zum ersten Kill jedes Wort, danach nur die Schlüsselwörter
            first_kill = min((mk["shot"] for mk in marks if mk.get("shot") is not None), default=None)
            text_end = t_drop or total
            line_words: dict = {}
            emph_of: dict = {}
            group_next: dict = {}
            if t_drop:  # Aufbau wie die Vorbilder: ganze Zeilen am Anfang, dann betonte Wörter, ab dem Drop keins
                line_words, emph = text_plan(wl, first_kill, t_drop)
                keep = set(line_words) | set(emph)
                picks = set(emph)
                emph_of = emph
                for g in {v[0] for v in emph.values()}:  # bis wann ein betontes Wort stehen darf
                    last_a = max(wl[j]["a"] for j, v in emph.items() if v[0] == g)
                    later = [wl[j]["a"] for j in keep if wl[j]["a"] > last_a and emph.get(j, (None,))[0] != g]
                    group_next[g] = min(later, default=text_end)
            else:
                keep = story_keep(wl, first_kill)
                picks = wall_picks(wl) & keep
            kept = sorted(keep)
            next_kept = {j: (wl[kept[i + 1]]["a"] if i + 1 < len(kept) else text_end) for i, j in enumerate(kept)}
            for j, wd in enumerate(wl):
                a, b, txt = wd["a"], wd["b"], wd["txt"]
                if a >= total or not txt.strip() or j not in keep:
                    continue
                # weggelassene Wörter dazwischen: das Wort bleibt länger stehen (bis zum nächsten gezeigten, begrenzt)
                wd = dict(wd, next=min(max(wd["next"], min(next_kept[j], wd["next"] + STORY_HOLD_S)), text_end))
                b = min(b, text_end)
                # Wand-Wort: kein Kill im Zeitfenster, mind. 3 Buchstaben. Liegt ein Schnitt im Fenster, endet das Wort
                # an der Wand beim Schnitt (die Wand ist danach weg), sofern bis dahin genug Zeit bleibt.
                if j in picks:  # gezogenes Wort: bleibt durch die Pause an der Wand, bis das nächste Wort kommt
                    b = min(max(b, wd["next"]), a + 2.5, text_end)
                # gesungener Text: die Wörter, bei denen sich der Sänger Zeit lässt; eingetippter Text: alle passenden.
                if j in emph_of:  # betontes Wort (Kandidat): Wand oder Ersatz entscheidet split_walls am Bild
                    g, r, need = emph_of[j]
                    b = min(max(b, group_next[g]), a + 2.5, text_end)
                    png = tmp / f"wall{j:02d}.png"
                    word_png(txt, png, j, str(LYRIC_FONT) if LYRIC_FONT.exists() else font, wall=True)
                    wa, wb = one_scene(a, b, cuts)
                    ok = wall_on and wb - wa >= WALL_MIN_S and png_aspect(png) <= WALL_MAX_ASPECT
                    wall_words.append({"a": wa if ok else a, "b": wb if ok else b, "png": str(png), "cuts": [],
                                       "txt": txt, "j": j, "eol": wd.get("eol", False), "stop": group_next[g],
                                       "sung": wd.get("sung"), "group": g, "rank": r, "need": need,
                                       "eligible": ok, "flat_b": b})
                    shown += 1 if r < need else 0
                    continue
                wanted = (j in picks) if (picks or line_words) else len(txt) >= 3
                if j in line_words:  # ganze Zeile: nie an die Wand, Wort für Wort in der Textspur
                    wanted = False
                png = tmp / f"wall{j:02d}.png"
                if wall_on and b - a >= WALL_MIN_S and wanted:
                    word_png(txt, png, j, str(LYRIC_FONT) if LYRIC_FONT.exists() else font, wall=True)
                # Wand-Wort bleibt in einer Szene: Liegt ein Schnitt im Zeitfenster, nur das längere Stück zeigen.
                # Vorher suchte es nach dem Schnitt eine neue Wand: wirkte wie dasselbe Wort doppelt (Nutzer).
                wa, wb = one_scene(a, b, cuts) if wanted else (a, b)
                if wall_on and wb - wa >= WALL_MIN_S and wanted and png_aspect(png) <= WALL_MAX_ASPECT:
                    wall_words.append({"a": wa, "b": wb, "png": str(png), "cuts": [], "txt": txt, "j": j,
                                       "eol": wd.get("eol", False), "stop": wd["next"], "sung": wd.get("sung")})
                    shown += 1
                    continue
                # flache Wörter: eine ruhige Textspur (fester Platz, Buchstabe für Buchstabe, bleibt stehen)
                item = {"a": a, "b": b, "txt": txt, "eol": wd.get("eol", False), "stop": wd["next"],
                        "sung": wd.get("sung")}
                if j in line_words:
                    item["line"], item["pos"] = line_words[j]
                flat_items.append(item)
                shown += 1
            if flat_items:
                # nie in der Bildmitte (Fadenkreuz = Kill); Farbe je Wort nach Hintergrund
                cy = lyric_pos(0, False)[0]
                band = 360 if not LANDSCAPE else 300
                mark_dark_text(flat_items, files, pl["segments"], cy - band // 2, band)
        fc += f"[{last}]null[v]"
        mix = tmp / "mix.wav"
        # Mischen in Python statt mit ffmpeg-Formeln: auf dem Server des Nutzers ergab die ffmpeg-Mischung Stille
        # (Spielton −16, Musik −10, Mischung −70 LUFS), vermutlich eine andere ffmpeg-Version. ffmpeg liest und
        # schreibt jetzt nur noch Dateien.
        mix_audio(files, pl["segments"], music, music_ss, total, marks, game_shots, pl["beat"], tcuts, mix)
        # Diagnose: Pegel der Teile (steht unter dem Video, bei Stille auch in der Fehlermeldung)
        global AUDIO_NOTE
        lv = {"Spielton": loudness(str(tmp / "game.wav")) if (tmp / "game.wav").exists() else None,
              "Musik": loudness(music, music_ss, total), "Mischung": loudness(str(mix))}
        AUDIO_NOTE = ", ".join(f"{k} {v:.0f} LUFS" if v is not None else f"{k} nicht messbar" for k, v in lv.items())
        mix2 = tmp / "mix2.wav"
        _run(["ffmpeg", "-v", "error", "-y", "-i", str(mix), "-af", level_chain(str(mix)), "-c:a", "pcm_f32le", str(mix2)])
        fc = fc.replace("[LOOPIN]", f"[{k}:v]")  # Schleifenbild ist der letzte Eingang
        ins += ["-loop", "1", "-framerate", str(OUT_FPS), "-t", f"{total:.3f}", "-i", str(first_png)]
        ins_music = ["-i", str(mix2)]  # fertig gemischter Ton (Eingang n)
        _run(["ffmpeg", "-v", "error", "-y", *ins[:2 * n], *ins_music, *ins[2 * n:],
              "-filter_complex", fc, "-map", "[v]", "-map", f"{n}:a", "-t", str(total),
              "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(OUT_FPS),
              "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(base_path(out))])
        # Songtext getrennt darüberlegen: Video ohne Text + Wörter werden gespeichert, damit der Nutzer das Timing am
        # fertigen Video nachjustieren kann, ohne alles neu zu schneiden (apply_lyrics mit Versatz)
        lyr = {"flat": flat_items if (font and words) else [], "walls": [
                   {k2: v for k2, v in w.items() if k2 != "png"} for w in wall_words],
               "total": total, "out_w": OUT_W, "out_h": OUT_H, "box": BOX, "box_y": BOX_Y, "box_x": BOX_X,
               "fps": OUT_FPS, "y_mid": lyric_pos(0, False)[0], "band": 360 if not LANDSCAPE else 300,
               "font": font, "shift": 0.0, "drop": t_drop}
        save_lyrics(out, lyr)
        wall_stats = apply_lyrics(str(base_path(out)), lyr, out, 0.0)
        if progress:
            progress(len(pl["segments"]) + 1, len(pl["segments"]) + 1)
    return {"kills": kills, "bpm": bt["bpm"], "seconds": round(duration(out), 2), "kills_used": pl["kills_used"],
            "lyrics_debug": _safe_debug(dbg, words or [], sung),
            "segments": pl["segments"], "words": shown, "drop": t_drop, "clips": len(srcs), "lyrics_source": source,
            "lyrics_note": SUNG_NOTE, "wall": wall_stats,
            "synced_shots": sum(len(x["anchors"]) - 2 for x in pl["segments"] if x.get("anchors")),
            "sync_measured": measured, "audio_note": AUDIO_NOTE}


if __name__ == "__main__":
    import sys

    r = make(sys.argv[1], sys.argv[2], progress=lambda i, n: print(f"Segment {i}/{n}", flush=True))
    print(f"{len(r['kills'])} Kills bei {[k['t'] for k in r['kills']]} s, Video {r['seconds']} s")
