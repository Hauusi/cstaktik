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
    """Rote Rahmen in einem Frame-Ausschnitt (x0, y0, x1, y1 im Ausschnitt)."""
    import numpy as np

    r, g, b = fr[..., 0], fr[..., 1], fr[..., 2]
    red = (r > 95) & (r - np.maximum(g, b) > 40)
    rows = red.sum(axis=1)
    lines: list[list[int]] = []
    for y in range(fr.shape[0]):
        if rows[y] > 90:
            if lines and y - lines[-1][1] <= 2:
                lines[-1][1] = y
            else:
                lines.append([y, y])
    out, i = [], 0
    while i + 1 < len(lines):
        gap = lines[i + 1][0] - lines[i][1]
        if 10 <= gap <= 30:
            xs = np.where(red[lines[i][0]:lines[i][1] + 1].any(axis=0))[0]
            inner = fr[lines[i][1] + 2:lines[i + 1][0] - 1, xs.min() + 4:xs.max() - 3]
            if inner.size and np.median(inner.sum(axis=2)) < 200:  # Killfeed-Hintergrund ist dunkel
                out.append((int(xs.min()), lines[i][0], int(xs.max()), lines[i + 1][1]))
                i += 2
                continue
        i += 1
    return out


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


def detect(path: str) -> list[dict]:
    """Eigene Kills im Clip: [{"t": Sekunde, "box": (x0, y0, x1, y1) im 1280x720-Bild}]."""
    import numpy as np

    raw = _run(["ffmpeg", "-v", "error", "-i", path, "-vf", f"fps={FPS_SCAN},scale={W}:{H},crop={CW}:{CH}:{W - CW}:0",
                "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
    frames = np.frombuffer(raw, np.uint8).reshape(-1, CH, CW, 3).astype(np.int16)
    boxes = [_boxes(f) for f in frames]
    out = []
    for t, i in kills_from_counts([len(b) for b in boxes]):
        bx = next((boxes[j][-1] for j in range(i, min(i + 6, len(boxes))) if boxes[j]), None)  # neuester = unterster
        if bx:
            out.append({"t": t, "box": (bx[0] + W - CW, bx[1], bx[2] + W - CW, bx[3])})
    return out


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


def _vf(src: str, z: str, out: str) -> str:
    """Hochformat-Aufbau: unscharfer, dunkler Hintergrund aus demselben Bild, darauf das Spielbild als Quadrat
    (Zoom auf die Bildmitte, dort ist das Fadenkreuz). Oben bleibt Platz für den Killfeed, unten für den Zähler,
    so verdeckt nichts den Kill. Kein Wackeln."""
    return (f"{src}split[m{out}][g{out}];"
            f"[g{out}]scale=-2:480,crop=270:480,boxblur=10:2,eq=brightness=-0.22,scale={OUT_W}:{OUT_H}[b{out}];"
            f"[m{out}]scale=-2:'2*trunc({BOX // 2}*({z}))':eval=frame:flags=bilinear,crop={BOX}:{BOX},eq=contrast=1.06:saturation=1.2[f{out}];"
            f"[b{out}][f{out}]overlay=0:{BOX_Y}[{out}]")


LOUDNORM = "loudnorm=I=-14:TP=-1:LRA=11,aresample=48000"
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

RAMP_V0, RAMP_V1 = 1.6, 0.4  # Anlauf beginnt schnell und gleitet in die Zeitlupe; der Kill selbst läuft mit SLOW
HIT_SLOW = 0.5  # Tempo während des Kills im Beat-Schnitt: langsam genug, um den Treffer zu sehen
MAX_WORDS = 40
WALL_MIN_S = 0.22  # so lange muss ein Wort an der Wand stehen können
WALL_TEXT = True  # Songtext teils auf Wände legen (wall_text.py)
WORD_LEAD_S = 0.04  # Text minimal vor dem Gesang: späterer Text fällt eher auf als früherer
MIN_WORD_S = 0.28  # kürzer steht ein Wort nicht lesbar im Bild
SHOT_SPEED, SHOT_BACK = 1.25, 1.0  # eigener Schnitt vor dem Kill: leicht schnell, etwa 1 s früher im Clip
LOOP_S = 0.3  # Übergang am Ende zurück zum ersten Bild
BLUR = "tmix=frames=3:weights='1 2 1',"  # leichte Bewegungsunschärfe aus drei Nachbarbildern (wie eine Kamera)
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


SYNC_MIN, SYNC_MAX = 0.35, 2.3  # erlaubtes Tempo zwischen zwei Schüssen beim Einrasten auf den Beat


def sync_anchors(shot_times: list[float], s0: float, ks: float, gap: float, half: float) -> list[tuple[float, float]]:
    """Ankerpunkte (Zeit im Clip, Zeit im Segment) für einen Anlauf von s0 bis zum Kill ks, der ``gap`` Sekunden
    füllt. Der Kill landet am Ende (auf dem Schlag); jeder Schuss davor auf einem Achtelschlag (``half`` = halber
    Schlag), rückwärts vom Kill aus, so dass das Tempo zwischen zwei Ankern in [SYNC_MIN, SYNC_MAX] bleibt. Schüsse,
    die sich so nicht einrasten lassen, werden übersprungen. Anfang (s0 -> 0) ist immer Anker."""
    anchors = [(ks, gap)]
    for t in sorted((x for x in shot_times if s0 + 0.05 < x < ks - 0.05), reverse=True):
        src_gap = anchors[-1][0] - t
        best = None
        for k in range(1, 9):
            out_t = anchors[-1][1] - k * half
            if out_t < 0.08:
                break
            v = src_gap / (k * half)
            if SYNC_MIN <= v <= SYNC_MAX and (best is None or abs(v - 1) < abs(best[1] - 1)):
                best = (out_t, v)
        if best is None:
            continue
        # der Rest bis zum Anfang muss auch ein erlaubtes Tempo haben
        if not (SYNC_MIN * 0.5 <= (t - s0) / best[0] <= SYNC_MAX * 1.6):
            continue
        anchors.append((t, round(best[0], 4)))
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
            score = st[i] - (0.15 if gap == prev_gap else 0) - 0.05 * max(0, gap - 4)
            if score > bscore:
                best, bscore = gap, score
        if best is None:
            break
        prev_gap, idx = best, idx + best
    return out


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
        ks = max(kill["t"] - 0.10, 0.0)               # Kill-Moment im Clip
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
        after_src = min(hit_out * HIT_SLOW, max(cdur - ks - 0.02, 0.05))
        segs.append({"kind": "hit", "ss": round(ks, 3), "d": round(after_src, 3), "out": round(hit_out, 3), "o0": round(kb, 3),
                     "box": kill["box"], "feed_at": round(min(kill["t"] + 0.2, cdur - 0.05), 3), "text": f"+{j + 1}",
                     "kill_at": 0.0, "src": kill.get("src")})
        o, src_prev = kb + hit_out, ks + after_src
    last = segs[-1]
    hold = 2 * beat
    segs.append({"kind": "hold", "ss": round(max(last["ss"] + last["d"] - 0.03, 0), 3), "d": round(hold, 3),
                 "out": round(hold, 3), "o0": round(o, 3), "box": last["box"], "feed_at": last["feed_at"],
                 "text": f"{len(used)} KILLS" if len(used) > 1 else "KILL", "src": last.get("src")})
    return {"segments": segs, "seconds": round(o + hold, 3), "beat": round(beat, 4), "kills_used": len(used)}


def _render_beat_seg(src: str, seg: dict, out: Path, tmp: Path, font: str) -> None:
    """Ein Segment des Beat-Edits, genau ``out`` Sekunden lang. Spielton leise unter der Musik."""
    src = seg.get("src") or src
    if seg["kind"] == "hold":
        _render_seg(src, seg, out, tmp, font)
        return
    speed = max(seg["d"] / seg["out"], 0.05)
    tempo = ",".join(["atempo=0.5"] * (1 if speed < 0.5 else 0) + [f"atempo={max(speed, 0.5) if speed >= 0.5 else speed / 0.5:.5f}"])
    audio = (f"[0:a]aresample=48000,asetpts=PTS-STARTPTS,{tempo},apad=whole_dur={seg['out']},atrim=0:{seg['out']},"
             f"volume={0.8 if seg['kind'] == 'hit' else 0.3}[a]")
    tail = f"fps={OUT_FPS},tpad=stop_mode=clone:stop_duration=1,trim=0:{seg['out']}"
    if seg["kind"] == "hit":
        kf = _feed_png(src, seg, tmp, out.stem)
        z = f"1+({Z_HIT}-1)*min(t/{PUNCH_S}\\,1)"
        fc = (f"[0:v]scale={W}:{H},setpts=(PTS-STARTPTS)/{speed:.5f}[s];{_vf('[s]', z, 'bg')};"
              f"[bg]hue=s='min(1\\,max(0\\,(t-0.18)/0.25))',"
              f"eq=contrast='1.25-0.25*min(1\\,t/0.45)':eval=frame[fl];[fl][1:v]overlay=(W-w)/2:{BOX_Y - 115}[v0];"
              f"[v0]{_draw(seg['text'], font)},{tail}[v];{audio}")
        fc = fc.replace(f"[0:v]scale={W}:{H},setpts=(PTS-STARTPTS)/{speed:.5f}[s];",
                        f"[0:v]scale={W}:{H},setpts=(PTS-STARTPTS)/{speed:.5f},"
                        f"minterpolate=fps={OUT_FPS}:mi_mode=blend[s];")
        _run(["ffmpeg", "-v", "error", "-y", "-ss", str(seg["ss"]), "-t", str(seg["d"]), "-i", src, "-i", str(kf),
              "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", str(seg["out"]), *ENC, str(out)])
        return
    if seg["kind"] == "shot":  # eigener kurzer Schnitt: gleichmäßiges Tempo, Zoom-Schlag beim Bildwechsel
        fc = (f"[0:v]scale={W}:{H},{BLUR}setpts=(PTS-STARTPTS)/{speed:.5f}[s];{_vf('[s]', CUT_POP, 'c')};[c]{tail}[v];{audio}")
        _run(["ffmpeg", "-v", "error", "-y", "-ss", str(seg["ss"]), "-t", str(seg["d"]), "-i", src,
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
                 f"amix=inputs={len(labels)}:duration=longest:normalize=0,volume=0.85,"
                 f"apad=whole_dur={seg['out']},atrim=0:{seg['out']}[a]")
        blur = BLUR if v0 > 1.2 else ""
        fc = f"[0:v]scale={W}:{H},{blur}setpts='{pts}'[s];{_vf('[s]', '1', 'c')};[c]{tail}[v];{audio}"
        _run(["ffmpeg", "-v", "error", "-y", "-ss", str(seg["ss"]), "-t", str(d), "-i", src,
              "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", str(seg["out"]), *ENC, str(out)])
        return
    if abs(v0 - v1) < 1e-3:
        pts = f"(PTS-STARTPTS)/{v0:.5f}"
    else:  # Zeit im fertigen Video als Funktion der Zeit im Clip, bei linear fallendem Tempo
        pts = f"({d}/({v1}-{v0}))*log(({v0}+({v1}-{v0})*((PTS-STARTPTS)*TB)/{d})/{v0})/TB"
    blur = BLUR if seg.get("v0", 1) > 1.2 else ""
    fc = f"[0:v]scale={W}:{H},{blur}setpts='{pts}'[s];{_vf('[s]', '1', 'c')};[c]{tail}[v];{audio}"
    _run(["ffmpeg", "-v", "error", "-y", "-ss", str(seg["ss"]), "-t", str(d), "-i", src,
          "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", str(seg["out"]), *ENC, str(out)])


def word_list(words: list[str], beat_times: list[float], per_beat: int = 1) -> list[dict]:
    """Wörter mit Zeiten: {"a": Start, "b": Ende der Einblendung, "txt", "sung": Ende des gesungenen Worts oder None}.
    Formen: "WORT" (ein Wort je Schlag), "1.45:WORT" (feste Zeit), "1.45-2.10:WORT" (Start und Ende, aus der
    Spracherkennung). Wörter unter MIN_WORD_S Abstand werden zu höchstens zwei Wörtern zusammengefasst."""
    import re

    out, i = [], 0
    for w in words:
        m = re.fullmatch(r"(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))?:(.+)", w)
        if m:
            a = float(m.group(1))
            sung = float(m.group(2)) if m.group(2) else None
            # gesungenes Wort: 40 ms früher einblenden, so wirkt es exakt auf dem Gesang (ITU-R BT.1359)
            out.append({"a": max(a - WORD_LEAD_S, 0.0) if sung is not None else a, "sung": sung, "txt": m.group(3)})
            continue
        if i >= len(beat_times):
            break
        out.append({"a": beat_times[i], "sung": None, "txt": w})
        i += per_beat
    out.sort(key=lambda x: x["a"])
    merged: list[dict] = []
    for x in out:
        held = x["sung"] is not None and x["sung"] - x["a"] >= 0.35  # gezogenes Wort bekommt seine eigene Einblendung
        if merged and not held and x["a"] - merged[-1]["a"] < MIN_WORD_S and " " not in merged[-1]["txt"]:
            merged[-1]["txt"] += " " + x["txt"]
            merged[-1]["sung"] = x["sung"] if x["sung"] is not None else merged[-1]["sung"]
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


def wall_picks(ws: list[dict], max_share: float = 0.6) -> set[int]:
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


def sung_words(music: str, ss: float, d: float) -> list[str] | None:
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
        raw = _run(["ffmpeg", "-v", "error", "-ss", str(ss), "-t", str(d), "-i", music, "-vn", "-ac", "1", "-ar", "16000",
                    "-f", "f32le", "-"])
        audio = np.frombuffer(raw, np.float32)
        model = WhisperModel("small", device="cpu", compute_type="int8")
        # Gesang über Musik: nicht beim ersten unsicheren Stück aufhören (kein Abbruch bei "keine Sprache", kein
        # Fortschreiben des vorigen Texts, das sich sonst aufhängt), gründlichere Suche
        segs, _info = model.transcribe(audio, word_timestamps=True, beam_size=5, vad_filter=False,
                                       condition_on_previous_text=False, no_speech_threshold=0.95,
                                       log_prob_threshold=-2.5, compression_ratio_threshold=3.0)
        out = []
        for sg in segs:
            for w in sg.words or []:
                txt = re.sub(r"[^0-9A-Za-zÄÖÜäöüß'-]", "", w.word)
                if txt:
                    out.append(f"{max(w.start, 0):.2f}-{max(w.end, w.start):.2f}:{txt}")
        if not out:
            SUNG_NOTE = "Die Spracherkennung lief, hat in diesem Ausschnitt aber keine Wörter erkannt."
        else:
            t0 = float(out[0].split("-")[0])
            t1 = float(out[-1].split(":")[0].split("-")[-1])
            SUNG_NOTE = (f"{len(out)} Wörter erkannt, von {t0:.1f} bis {t1:.1f} s".replace(".", ",")
                         + (f" (das Video ist {d:.1f} s lang)".replace(".", ",") if t1 < d * 0.6 else "") + ".")
        return out or None
    except Exception as e:  # noqa: BLE001 - ohne Erkennung läuft der Schnitt trotzdem
        SUNG_NOTE = f"Die Spracherkennung ist installiert, aber fehlgeschlagen: {type(e).__name__}: {str(e)[:300]}"
        return None


LYRIC_COLORS = [((255, 255, 255), (255, 159, 28)), ((255, 210, 63), (20, 20, 20)), ((255, 255, 255), (240, 86, 106)),
                ((77, 224, 138), (20, 20, 20)), ((255, 255, 255), (74, 138, 224)), ((255, 90, 110), (20, 20, 20))]
LYRIC_DY = (0, -40, 20, -25, 35, -15)  # kleine Sprünge im unteren Drittel des Spielbilds
LYRIC_ROT = (-5, 4, -3, 5, -4, 3)


def word_png(text: str, path: Path, j: int, font_file: str, wall: bool = False) -> None:
    """Ein Wort als Bild: fette, enge Großbuchstaben, die die Breite füllen, schräg gestellt und leicht gedreht,
    dicker schwarzer Rand und ein farbiger, versetzter Schatten. Farbe und Drehung wechseln von Wort zu Wort."""
    from PIL import Image, ImageDraw, ImageFont

    text = text.upper()
    fill, shadow = LYRIC_COLORS[j % len(LYRIC_COLORS)]
    size = 260 if wall else 150  # flach: klein genug, dass der Kill sichtbar bleibt; Wand: groß, wird verkleinert
    while size > 60:
        font = ImageFont.truetype(font_file, size)
        l, t, r, b = font.getbbox(text)
        if r - l <= (1000 if wall else 640):
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


def make_beat(src, music: str, out: str, music_ss: float = 0.0, music_d: float | None = None,
              words: list[str] | None = None, progress=None) -> dict:
    """Beat-Edit aus einem oder mehreren Clips: Musik gibt den Takt vor, Kills fallen auf die Schläge, Songtext Wort
    für Wort. ``words``: Wörter in Reihenfolge (ein Wort je Schlag) oder "Sekunde:WORT" für feste Zeiten."""
    from cstaktik import beats as beatmod

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
    pl = plan_beat(kills, duration(srcs[0]), bt["beats"], mots, bt.get("strength"), shot_times)
    font = _font()
    shown, source = 0, "eingetragen" if words else None
    if not words:  # kein Text eingetragen: aus dem Gesang erkennen, falls die Spracherkennung installiert ist
        words = sung_words(music, music_ss, pl["seconds"])
        source = "erkannt" if words else None
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        files = []
        for i, seg in enumerate(pl["segments"]):
            f = tmp / f"b{i:03d}.mp4"
            _render_beat_seg(srcs[0], seg, f, tmp, font)
            files.append(f)
            if progress:
                progress(i + 1, len(pl["segments"]) + 1)
        n = len(files)
        ins = [x for f in files for x in ("-i", str(f))]
        total = pl["seconds"]
        first_png = tmp / "loop.png"  # erstes Bild des Videos: am Ende eingeblendet, damit die Wiederholung nahtlos wirkt
        _run(["ffmpeg", "-v", "error", "-y", "-i", str(files[0]), "-frames:v", "1", str(first_png)])
        fc = "".join(f"[{i}:v][{i}:a]" for i in range(n)) + f"concat=n={n}:v=1:a=1[vc][ga];"
        lp = max(total - LOOP_S, 0)
        fc += (f"[LOOPIN]format=rgba,fade=t=in:st={lp:.3f}:d={LOOP_S}:alpha=1[lp];"
               f"[vc][lp]overlay=0:0:enable='gte(t,{lp:.3f})'[v0];")
        last, k = "v0", n + 1  # Eingang n ist die Musik, danach je Wort ein Bild
        wall_words: list[dict] = []
        wall_on = WALL_TEXT
        if font and words:
            # während eines Kills gehört die Bildmitte dem Kill: dort kein Songtext
            busy = [(x["o0"], x["o0"] + x["out"]) for x in pl["segments"] if x["kind"] in ("hit", "hold")]
            cuts = [x["o0"] for x in pl["segments"]]
            wl = word_list(words, bt["beats"])[:MAX_WORDS]
            picks = wall_picks(wl)
            for j, wd in enumerate(wl):
                a, b, txt = wd["a"], wd["b"], wd["txt"]
                if a >= total or not txt.strip():
                    continue
                b = min(b, total)
                # Wand-Wort: kein Kill im Zeitfenster, mind. 3 Buchstaben. Liegt ein Schnitt im Fenster, endet das Wort
                # an der Wand beim Schnitt (die Wand ist danach weg), sofern bis dahin genug Zeit bleibt.
                if j in picks:  # gezogenes Wort: bleibt durch die Pause an der Wand, bis das nächste Wort kommt
                    b = min(max(b, wd["next"]), a + 2.5, total)
                # gesungener Text: die Wörter, bei denen sich der Sänger Zeit lässt; eingetippter Text: alle passenden.
                # Bei einem Schnitt im Zeitfenster sucht das Wort im neuen Bild eine neue Wand (wall_text.apply).
                wanted = (j in picks) if picks else len(txt) >= 3
                if wall_on and b - a >= WALL_MIN_S and wanted:
                    png = tmp / f"wall{j:02d}.png"
                    word_png(txt, png, j, font, wall=True)
                    wall_words.append({"a": a, "b": b, "png": str(png),
                                       "cuts": [c for c in cuts if a + 0.02 < c < b - 0.02]})
                    shown += 1
                    continue
                png = tmp / f"w{j:02d}.png"
                word_png(txt, png, j, font)
                ins += ["-loop", "1", "-framerate", str(OUT_FPS), "-t", f"{total:.3f}", "-i", str(png)]
                # während eines Kills gehört die Bildmitte dem Kill: das Wort steht dann kleiner am unteren Bildrand
                low = any(x0 - 0.05 <= a < x1 - 0.05 for x0, x1 in busy)
                cy = BOX_Y + BOX - 95 if low else BOX_Y + int(BOX * 0.80) + LYRIC_DY[j % len(LYRIC_DY)]
                sc = 0.7 if low else 1.0
                fc += (f"[{k}:v]format=rgba,scale=w='2*trunc(iw*{sc}*(1+0.2*exp(-22*max(t-{a}\\,0)))/2)':h=-2:eval=frame[w{j}];"
                       f"[{last}][w{j}]overlay=x='(W-w)/2':y='{cy}-h/2':eval=frame:"
                       f"enable='between(t,{a},{min(b, total)})'[t{j}];")
                last, k, shown = f"t{j}", k + 1, shown + 1
        hits = "+".join(f"between(t,{x['o0']},{round(x['o0'] + min(x['out'], 0.6), 3)})"
                        for x in pl["segments"] if x["kind"] == "hit") or "0"
        fc += (f"[{last}]null[v];[{n}:a]aresample=48000,volume='if(gt({hits},0),0.6,1)':eval=frame,afade=t=out:st={max(total - 0.4, 0):.3f}:d=0.4[mu];"
               f"[ga][mu]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95,{LOUDNORM}[a]")
        fc = fc.replace("[LOOPIN]", f"[{k}:v]")  # Schleifenbild ist der letzte Eingang
        ins += ["-loop", "1", "-framerate", str(OUT_FPS), "-t", f"{total:.3f}", "-i", str(first_png)]
        ins_music = ["-ss", str(music_ss), "-t", str(total), "-i", music]
        _run(["ffmpeg", "-v", "error", "-y", *ins[:2 * n], *ins_music, *ins[2 * n:],
              "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", str(total),
              "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(OUT_FPS),
              "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(tmp / "flat.mp4") if wall_words else out])
        wall_stats = None
        if wall_words:  # zweiter Durchgang: Wörter auf Wände legen und mit der Kamera mitführen
            from cstaktik import wall_text

            wall_stats = wall_text.apply(str(tmp / "flat.mp4"), out, wall_words, BOX_Y, BOX, OUT_FPS,
                                         BOX_Y + int(BOX * 0.80),
                                         ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                                          "-movflags", "+faststart"])
        if progress:
            progress(len(pl["segments"]) + 1, len(pl["segments"]) + 1)
    return {"kills": kills, "bpm": bt["bpm"], "seconds": round(duration(out), 2), "kills_used": pl["kills_used"],
            "segments": pl["segments"], "words": shown, "clips": len(srcs), "lyrics_source": source,
            "lyrics_note": SUNG_NOTE, "wall": wall_stats,
            "synced_shots": sum(len(x["anchors"]) - 2 for x in pl["segments"] if x.get("anchors"))}


if __name__ == "__main__":
    import sys

    r = make(sys.argv[1], sys.argv[2], progress=lambda i, n: print(f"Segment {i}/{n}", flush=True))
    print(f"{len(r['kills'])} Kills bei {[k['t'] for k in r['kills']]} s, Video {r['seconds']} s")
