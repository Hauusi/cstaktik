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


SIG_SAME = 0.5  # Ähnlichkeit (0..1) ab der zwei Einträge als derselbe gelten
SIG_CONFIRM = 4  # so viele Bilder (0,2 s) muss ein neuer Eintrag stehen


def _sig(fr, box):
    """Fingerabdruck eines Eintrags: Breite des roten Rahmens und das Spaltenprofil der hellen Schrift (Name, Waffe,
    Gegner), rechtsbündig in 4-px-Streifen. Der halb durchsichtige Hintergrund zählt nicht (nur helle Pixel)."""
    import numpy as np

    x0, y0, x1, y1 = box
    inner = fr[y0 + 3:y1 - 2, x0 + 4:x1 - 3].mean(axis=2)
    if inner.shape[0] < 4 or inner.shape[1] < 12:
        return None
    bright = (inner > 150).mean(axis=0)[::-1]  # rechts beginnen
    n = len(bright) // 4
    prof = bright[:n * 4].reshape(n, 4).mean(axis=1).astype(np.float32)
    return {"w": x1 - x0, "p": prof}


def _same(a, b) -> float:
    """Ähnlichkeit zweier Fingerabdrücke 0..1: ähnliche Breite (±12 px: ein neuer Eintrag gleitet herein, gemessen
    209 -> 225 px) und ähnliches Schriftprofil (bis 2 Streifen verschoben)."""
    import numpy as np

    if abs(a["w"] - b["w"]) > 12:
        return 0.0
    best = 0.0
    for sh in (-2, -1, 0, 1, 2):
        pa, pb = (a["p"][sh:], b["p"]) if sh >= 0 else (a["p"], b["p"][-sh:])
        n = min(len(pa), len(pb))
        if n < 4:
            continue
        d = float(np.abs(pa[:n] - pb[:n]).mean())
        best = max(best, 1.0 - d / 0.15)
    return max(best, 0.0)


def kills_from_boxes(frames_boxes: list[list[tuple]], sigs: list[list], fps: int = FPS_SCAN) -> list[tuple[float, int, tuple]]:
    """Kills aus den Einträgen je Bild, über ihren Fingerabdruck: Ein Eintrag mit neuem Aussehen ist ein neuer Kill,
    egal wie viele gerade sichtbar sind. Verschwindet ein Eintrag kurz (Mündungsfeuer, heller Hintergrund) und kommt
    gleich aussehend wieder, bleibt es derselbe. Vorher wurde nur gezählt: verschwand ein alter Eintrag, während ein
    neuer kam, ging der Kill verloren (nachgestellt mit einem echten Clip: 2 von 4 Kills erkannt)."""
    import numpy as np

    entries: list[dict] = []  # {"sig", "first", "last", "hits", "box"}
    for i, (boxes, ss) in enumerate(zip(frames_boxes, sigs)):
        used = set()
        for box, sg in zip(boxes, ss):
            if sg is None:
                continue
            best, bi = SIG_SAME, None
            for k, e in enumerate(entries):
                if k in used or i - e["last"] > GAP_S * fps:
                    continue
                c = _same(e["sig"], sg)
                if c > best:
                    best, bi = c, k
            if bi is None:
                entries.append({"sig": sg, "first": i, "last": i, "hits": 1, "box": box})
                used.add(len(entries) - 1)
            else:
                e = entries[bi]
                e["last"], e["hits"], e["sig"] = i, e["hits"] + 1, sg  # neuester Stand (Eintrag gleitet herein)
                used.add(bi)
    out = [(round(e["first"] / fps, 2), e["first"], e["box"]) for e in entries if e["hits"] >= SIG_CONFIRM]
    return sorted(out)


def detect(path: str) -> list[dict]:
    """Eigene Kills im Clip: [{"t": Sekunde, "box": (x0, y0, x1, y1) im 1280x720-Bild}]."""
    import numpy as np

    raw = _run(["ffmpeg", "-v", "error", "-i", path, "-vf", f"fps={FPS_SCAN},scale={W}:{H},crop={CW}:{CH}:{W - CW}:0",
                "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
    frames = np.frombuffer(raw, np.uint8).reshape(-1, CH, CW, 3).astype(np.int16)
    boxes = [_boxes(f) for f in frames]
    sigs = [[_sig(f, bx) for bx in b] for f, b in zip(frames, boxes)]
    return [{"t": t, "box": (bx[0] + W - CW, bx[1], bx[2] + W - CW, bx[3])} for t, _, bx in kills_from_boxes(boxes, sigs)]


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
WALL_MAX_ASPECT = 3.6  # breitere Wörter nicht auf Wände: gemessen wurden sie dort nur 59-101 px hoch (zu klein)
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


def kill_start(t: float, shot_times: list[float] | None) -> float:
    """Wo die Kill-Zeitlupe beginnt: am Kill-Schuss = letzter Schuss im Spielton vor dem Killfeed-Eintrag (bis 1,5 s
    davor). Der Eintrag erscheint erst nach dem Treffer (gemessen 0,14-0,34 s, beim Nutzer teils viel mehr); vorher
    begann die Zeitlupe pauschal 0,1 s vor dem Eintrag, und der eigentliche Kill fiel heraus. Ohne Schuss (Granate,
    Messer): wie bisher."""
    prev = [x for x in (shot_times or []) if t - KILL_SHOT_BACK <= x <= t + 0.05]
    return round(max((prev[-1] - KILL_PRE) if prev else (t - 0.10), 0.0), 3)


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

    t = unicodedata.normalize("NFKC", text).translate(LOOKALIKE).upper()
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


def lyric_pos(j: int, during_kill: bool) -> tuple[int, float]:
    """Mitte (y) und Größe eines flachen Songtext-Worts. Hält die Bildmitte frei."""
    if LANDSCAPE:
        return int(OUT_H * 0.82) + LYRIC_DY[j % len(LYRIC_DY)] // 2, 0.62
    return (BOX_Y // 2 + 70) + LYRIC_DY[j % len(LYRIC_DY)] // 2, 0.72


def one_scene(a: float, b: float, cuts: list[float]) -> tuple[float, float]:
    """Zeitfenster [a, b] auf das längste Stück ohne Schnitt kürzen."""
    pts = [a] + sorted(c for c in cuts if a + 0.02 < c < b - 0.02) + [b]
    best = max(zip(pts, pts[1:]), key=lambda p: p[1] - p[0])
    return round(best[0], 3), round(best[1], 3)


def png_aspect(path) -> float:
    from PIL import Image

    with Image.open(path) as im:
        return im.width / max(im.height, 1)


def word_png(text: str, path: Path, j: int, font_file: str, wall: bool = False) -> None:
    """Ein Wort als Bild: fette, enge Großbuchstaben, die die Breite füllen, schräg gestellt und leicht gedreht,
    dicker schwarzer Rand und ein farbiger, versetzter Schatten. Farbe und Drehung wechseln von Wort zu Wort."""
    from PIL import Image, ImageDraw, ImageFont

    text = printable(text, font_file)
    fill, shadow = LYRIC_COLORS[j % len(LYRIC_COLORS)]
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
    err = subprocess.run(["ffmpeg", "-nostats", "-i", path, "-af", "ebur128", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", err)
    gain = max(min(target - float(m[-1]), 24.0), -24.0) if m else 0.0
    return f"volume={gain:.2f}dB,alimiter=limit=0.89:attack=1:release=60:level=0,aresample=48000"


def make_beat(src, music: str, out: str, music_ss: float = 0.0, music_d: float | None = None,
              words: list[str] | None = None, progress=None, song: str | None = None, fmt: str = "hoch") -> dict:
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
    pl = plan_beat(kills, duration(srcs[0]), bt["beats"], mots, bt.get("strength"), shot_times)
    frame_grid(pl)
    try:  # Clips von hellen und dunklen Maps angleichen: ein durchgehender Look statt Farbsprüngen an Schnitten
        offs = brightness_offsets({x: luma(x) for x in srcs})
    except Exception:  # noqa: BLE001
        offs = {}
    for sg in pl["segments"]:
        sg["bright"] = offs.get(sg.get("src") or srcs[0], 0.0)
    font = _font()
    shown, source = 0, "eingetragen" if words else None
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
                # LRCLIB hat nur Zeiten je Zeile: Wortzeiten mit der Spracherkennung nachschärfen (falls installiert)
                if words:
                    if sung is None:
                        near = [w for a, _, w in tw if music_ss + off - 2 <= a <= music_ss + off + pl["seconds"] + 2]
                        sung = sung_words(music, music_ss, pl["seconds"], " ".join(near)[:600])
                    words, n_fit = lrclib.refine(words, sung)
                    if n_fit:
                        why += f", Wortzeiten über {n_fit} erkannte Wörter angepasst"
                source, lrc_note = ("lrclib", f"{name}, {why}") if words else (None, f"{name}: an dieser Stelle "
                                                                                     "kein Gesang im Songtext.")
    if words and not any(":" in w for w in words):
        # Text eingefügt: mit der Spracherkennung (falls installiert) auf den Gesang legen, Text bleibt der eigene
        sung = sung_words(music, music_ss, pl["seconds"], " ".join(words))
        if sung:
            words, source = align_lyrics(words, sung, pl["seconds"]), "ausgerichtet"
    elif not words and not song:  # weder Text noch Song: aus dem Gesang erkennen (falls installiert)
        words = sung_words(music, music_ss, pl["seconds"])
        source = "erkannt" if words else None
    if lrc_note:
        SUNG_NOTE = lrc_note
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
            measured = sync_report(game_shots, bt["beats"], pl["beat"])
        except Exception:  # noqa: BLE001 - die Messung ist nur eine Anzeige
            measured, game_shots = None, []
        # an jedem Schnitt den Spielton 6 ms ein- und ausblenden: sonst knackt es hörbar (eigener Ton-Graph)
        # Ton jedes Segments exakt auf seine Bildlänge: AAC-Ton ist oft ein paar ms länger; beim gemeinsamen
        # Aneinanderhängen entsteht sonst eine Lücke im Bild und ein doppeltes Bild (gemessen: 4 je Video)
        afc_e = "".join(f"[{i}:a]apad=whole_dur={sg['out']},atrim=end={sg['out']},asetpts=PTS-STARTPTS,"
                        f"afade=t=in:d=0.006,areverse,afade=t=in:d=0.006,areverse[e{i}];"
                        for i, sg in enumerate(pl["segments"]))
        fc = ""
        # Pixel-Seitenverhältnis vereinheitlichen: Segmente kamen mit "nicht gesetzt" und 1280:1281 an, dann bricht
        # concat ab (Fehler beim Nutzer)
        fc += "".join(f"[{i}:v]setsar=1[sv{i}];" for i in range(n))
        fc += "".join(f"[sv{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vc0];"
        tcuts = transition_cuts(pl["segments"])
        fc += f"[vc0]{transition_vf(tcuts)}null[vc];"
        afc = afc_e + "".join(f"[e{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[ga];"
        afc += (f"aevalsrc='{sfx_expr(pl['segments'], pl['beat'], tcuts)}':d={total:.3f}:s=48000,"
                f"aformat=channel_layouts=stereo,highpass=f=30,lowpass=f=9000,volume={SFX_VOL}[sfx];")
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
                wanted = (j in picks) if picks else len(txt) >= 3
                png = tmp / f"wall{j:02d}.png"
                if wall_on and b - a >= WALL_MIN_S and wanted:
                    word_png(txt, png, j, font, wall=True)
                # Wand-Wort bleibt in einer Szene: Liegt ein Schnitt im Zeitfenster, nur das längere Stück zeigen.
                # Vorher suchte es nach dem Schnitt eine neue Wand: wirkte wie dasselbe Wort doppelt (Nutzer).
                wa, wb = one_scene(a, b, cuts) if wanted else (a, b)
                if wall_on and wb - wa >= WALL_MIN_S and wanted and png_aspect(png) <= WALL_MAX_ASPECT:
                    wall_words.append({"a": wa, "b": wb, "png": str(png), "cuts": []})
                    shown += 1
                    continue
                png = tmp / f"w{j:02d}.png"
                word_png(txt, png, j, font)
                ins += ["-loop", "1", "-framerate", str(OUT_FPS), "-t", f"{total:.3f}", "-i", str(png)]
                # während eines Kills gehört die Bildmitte dem Kill: das Wort steht dann kleiner am unteren Bildrand
                low = any(x0 - 0.05 <= a < x1 - 0.05 for x0, x1 in busy)
                # nie in der Bildmitte: dort ist das Fadenkreuz, also der Kill (Nutzer: Wörter verdeckten Kills).
                # Hochformat: über dem Spielbild (frei, seit der Zähler weg ist); Querformat: unteres Fünftel.
                cy, sc = lyric_pos(j, low)
                fc += (f"[{k}:v]format=rgba,scale=w='2*trunc(iw*{sc}*(1+0.2*exp(-22*max(t-{a}\\,0)))/2)':h=-2:eval=frame[w{j}];"
                       f"[{last}][w{j}]overlay=x='(W-w)/2':y='{cy}-h/2':eval=frame:"
                       f"enable='between(t,{a},{min(b, total)})'[t{j}];")
                last, k, shown = f"t{j}", k + 1, shown + 1
        # Musik beim Kill-Schuss weich absenken (40 ms runter, 300 ms zurück) statt schlagartig: kein Pumpen
        duck = "+".join(f"min(1\\,max(0\\,(t-{x['o0'] - 0.04:.3f})/0.04))*min(1\\,max(0\\,({x['o0'] + KILL_SND_S + 0.3:.3f}-t)/0.3))"
                        for x in pl["segments"] if x["kind"] == "hit") or "0"
        # bei jedem gemessenen Schuss die Musik kurz absenken: der Knall sticht heraus (Vorbild)
        dips = "+".join(f"exp(-pow((t-{x + 0.03:.3f})/{SHOT_DIP_S / 2:.3f}\\,2))" for x in game_shots) or "0"
        fc += f"[{last}]null[v]"
        afc += (f"[{n}:a]aresample=48000,volume='max(0.25\\,1-{KILL_DUCK}*min(1\\,{duck})-{SHOT_DIP}*min(1\\,{dips}))':eval=frame,"
                f"afade=t=out:st={max(total - 0.12, 0):.3f}:d=0.12[mu];"
                f"[ga][mu][sfx]amix=inputs=3:duration=first:normalize=0[a]")
        mix = tmp / "mix.wav"
        _run(["ffmpeg", "-v", "error", "-y", *[x for f in files for x in ("-i", str(f))],
              "-ss", str(music_ss), "-t", str(total), "-i", music, "-filter_complex", afc, "-map", "[a]",
              "-t", str(total), "-c:a", "pcm_f32le", str(mix)])
        mix2 = tmp / "mix2.wav"
        _run(["ffmpeg", "-v", "error", "-y", "-i", str(mix), "-af", level_chain(str(mix)), "-c:a", "pcm_f32le", str(mix2)])
        fc = fc.replace("[LOOPIN]", f"[{k}:v]")  # Schleifenbild ist der letzte Eingang
        ins += ["-loop", "1", "-framerate", str(OUT_FPS), "-t", f"{total:.3f}", "-i", str(first_png)]
        ins_music = ["-i", str(mix2)]  # fertig gemischter Ton (Eingang n)
        _run(["ffmpeg", "-v", "error", "-y", *ins[:2 * n], *ins_music, *ins[2 * n:],
              "-filter_complex", fc, "-map", "[v]", "-map", f"{n}:a", "-t", str(total),
              "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(OUT_FPS),
              "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(tmp / "flat.mp4") if wall_words else out])
        wall_stats = None
        if wall_words:  # zweiter Durchgang: Wörter auf Wände legen und mit der Kamera mitführen
            from cstaktik import wall_text

            wall_stats = wall_text.apply(str(tmp / "flat.mp4"), out, wall_words, BOX_Y, BOX, OUT_FPS,
                                         lyric_pos(0, False)[0], size=(OUT_W, OUT_H), box_x=BOX_X, enc=
                                         ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                                          "-movflags", "+faststart"])
        if progress:
            progress(len(pl["segments"]) + 1, len(pl["segments"]) + 1)
    return {"kills": kills, "bpm": bt["bpm"], "seconds": round(duration(out), 2), "kills_used": pl["kills_used"],
            "segments": pl["segments"], "words": shown, "clips": len(srcs), "lyrics_source": source,
            "lyrics_note": SUNG_NOTE, "wall": wall_stats,
            "synced_shots": sum(len(x["anchors"]) - 2 for x in pl["segments"] if x.get("anchors")),
            "sync_measured": measured}


if __name__ == "__main__":
    import sys

    r = make(sys.argv[1], sys.argv[2], progress=lambda i, n: print(f"Segment {i}/{n}", flush=True))
    print(f"{len(r['kills'])} Kills bei {[k['t'] for k in r['kills']]} s, Video {r['seconds']} s")
