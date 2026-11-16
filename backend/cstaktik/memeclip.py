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
OUT_W, OUT_H, OUT_FPS = 1080, 1920, 30
GAP_S = 2.5  # so lange darf der Rahmen kurz verschwinden (Hintergrund), ohne als neuer Kill zu zählen

LEAD_S, HIT_BEFORE, HIT_AFTER, LAST_HOLD_S = 1.6, 0.30, 0.32, 0.9
SLOW, Z_HIT, PUNCH_S = 0.4, 1.12, 0.12  # Zeitlupe kurz vor dem Kill, Zoom schlägt in 0,09 s zu


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


def plan(kills: list[dict], dur: float) -> list[dict]:
    """Schnittplan: Segmente in Reihenfolge. kind: lead (normal) | hit (Zoom-Schlag, Kill läuft in Zeitlupe aus) |
    hold (kurzes Standbild am Ende mit der Summe)."""
    segs: list[dict] = []
    end_prev = 0.0
    n = len(kills)
    for k, kill in enumerate(kills, start=1):
        t = max(kill["t"] - 0.10, 0.0)  # der Killfeed-Eintrag erscheint kurz nach dem Kill
        hit0, hit1 = max(t - HIT_BEFORE, end_prev), min(t + HIT_AFTER, dur)
        lead0 = max(hit0 - LEAD_S, end_prev)
        if hit0 - lead0 > 0.15:
            segs.append({"kind": "lead", "ss": round(lead0, 3), "d": round(hit0 - lead0, 3)})
        segs.append({"kind": "hit", "ss": round(hit0, 3), "d": round(hit1 - hit0, 3), "box": kill["box"],
                     "feed_at": round(min(kill["t"] + 0.2, dur - 0.05), 3), "text": f"+{k}",
                     "kill_at": round((t - hit0) / SLOW, 3)})  # Kill-Moment im fertigen Segment: Zähler, Killfeed, Sound
        if k == n:
            segs.append({"kind": "hold", "ss": round(max(hit1 - 0.03, 0), 3), "d": LAST_HOLD_S, "box": kill["box"],
                         "feed_at": round(min(kill["t"] + 0.2, dur - 0.05), 3), "text": f"{n} KILLS" if n > 1 else "KILL"})
        end_prev = hit1
    return segs


def _font() -> str:
    for want in ("Inter:style=ExtraBold", "DejaVu Sans:style=Bold", ":bold"):
        p = subprocess.run(["fc-match", "-f", "%{file}", want], capture_output=True, text=True).stdout.strip()
        if p:
            return p
    return ""


BOX, BOX_Y = 1080, 400  # Spielbild als Quadrat in der Mitte: zeigt mehr Breite als ein voller Hochformat-Schnitt


def _vf(src: str, z: str, out: str) -> str:
    """Hochformat-Aufbau: unscharfer, dunkler Hintergrund aus demselben Bild, darauf das Spielbild als Quadrat
    (Zoom auf die Bildmitte, dort ist das Fadenkreuz). Oben bleibt Platz für den Killfeed, unten für den Zähler,
    so verdeckt nichts den Kill. Kein Wackeln."""
    return (f"{src}split[m{out}][g{out}];"
            f"[g{out}]scale=-2:480,crop=270:480,boxblur=10:2,eq=brightness=-0.22,scale={OUT_W}:{OUT_H}[b{out}];"
            f"[m{out}]scale=-2:'2*trunc({BOX // 2}*({z}))':eval=frame:flags=bilinear,crop={BOX}:{BOX}[f{out}];"
            f"[b{out}][f{out}]overlay=0:{BOX_Y}[{out}]")


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
    size, color = (230, "white") if " " in text or text == "KILL" else (340, "0xFFD23F")  # Zähler groß und gelb
    return (f"drawtext=fontfile='{font}':text='{text}':fontsize={size}:fontcolor={color}:borderw=16:bordercolor=black:"
            f"x=(w-text_w)/2:y=1530")


def _render_seg(src: str, seg: dict, out: Path, tmp: Path, font: str) -> None:
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
        fc = (f"{_vf('[0:v]', str(Z_HIT), 'bg')};[bg][1:v]overlay=(W-w)/2:{BOX_Y - 130}[v0];[v0]{_draw(seg['text'], font)},fps={OUT_FPS}[v];"
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
          f"[bg][1:v]overlay=(W-w)/2:{BOX_Y - 130}:enable='gte(t,{ka})'[v0];[v0]{draw},fps={OUT_FPS}[v];"
          f"[0:a]aresample=48000,asetpts=PTS-STARTPTS,asetrate=48000*{SLOW},aresample=48000,volume=0.8[ga];"
          f"aevalsrc='{BOOM}':d={od:.3f}:s=48000,aformat=channel_layouts=stereo,adelay={int(ka * 1000)}:all=1[bm];"
          f"[ga][bm]amix=inputs=2:duration=first:normalize=0[a]")
    _run(["ffmpeg", "-v", "error", "-y", "-ss", str(ss), "-t", str(d), "-i", src, "-i", str(kf),
          "-filter_complex", fc, "-map", "[v]", "-map", "[a]", *ENC, str(out)])


def make(src: str, out: str, progress=None) -> dict:
    """Clip analysieren und Hochformat-Video schreiben. Rückgabe: Kills, Segmente, Länge. Ohne Kill: ValueError."""
    kills = detect(src)
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
        fc = "".join(f"[{i}:v][{i}:a]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a0];[a0]alimiter=limit=0.95[a]"
        _run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
              "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(OUT_FPS),
              "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out])
    return {"kills": kills, "segments": segs, "seconds": round(duration(out), 2)}


# --- Beat-Edit: Musik gibt den Takt vor, jeder Kill fällt genau auf einen Schlag ------------------------------------

APPROACH_SRC, APPROACH_SPEED, LEAD_SPEED = 0.30, 0.5, 1.6  # kurz vor dem Kill langsam, davor schneller Anlauf


def plan_beat(kills: list[dict], dur: float, beat_times: list[float]) -> dict:
    """Schnittplan auf dem Beat-Raster. Jeder Kill bekommt einen Schlag; der Anlauf davor wird so gedehnt oder
    gestaucht, dass der Kill-Moment exakt auf dem Schlag liegt. Rückgabe: Segmente mit ``out`` (Länge im fertigen
    Video) und ``o0`` (Startzeit im fertigen Video), dazu die Gesamtlänge."""
    n, nb = len(kills), len(beat_times)
    if nb < 6:
        raise ValueError("Zu wenige Schläge im Musik-Ausschnitt.")
    beat = (beat_times[-1] - beat_times[0]) / (nb - 1)
    first = min(4, max(nb - 3 - (n - 1) * 2, 1))            # erster Kill nach etwa 4 Schlägen
    step = max(2, min(8, (nb - 3 - first) // max(n - 1, 1)))  # Abstand der Kills in Schlägen
    step -= step % 2 if step > 2 else 0
    used = [k for k in range(n) if first + k * step < nb - 1]  # passen nicht alle Kills in die Musik: die ersten
    segs, o, src_prev = [], 0.0, 0.0
    for j, k in enumerate(used):
        kill = kills[k]
        ks = max(kill["t"] - 0.10, 0.0)               # Kill-Moment im Clip
        kb = beat_times[first + j * step]             # Schlag, auf dem er landen soll
        gap = kb - o
        ap_src = min(APPROACH_SRC, max(ks - src_prev, 0.0))
        ap_out = min(ap_src / APPROACH_SPEED, gap)
        lead_out = gap - ap_out
        if lead_out > 0.05:
            want = lead_out * LEAD_SPEED
            have = max(ks - ap_src - src_prev, 0.0)
            src_len = min(want, have) if have > 0.05 else 0.0
            if src_len > 0.05:
                segs.append({"kind": "lead", "ss": round(ks - ap_src - src_len, 3), "d": round(src_len, 3),
                             "out": round(lead_out, 3), "o0": round(o, 3)})
            else:
                ap_out = gap                           # kein Material für den Anlauf: Annäherung füllt die Lücke
        if ap_src > 0.02:
            segs.append({"kind": "approach", "ss": round(ks - ap_src, 3), "d": round(ap_src, 3), "out": round(ap_out, 3),
                         "o0": round(kb - ap_out, 3)})
        after_src = min(beat * SLOW, max(dur - ks - 0.02, 0.05))
        segs.append({"kind": "hit", "ss": round(ks, 3), "d": round(after_src, 3), "out": round(beat, 3), "o0": round(kb, 3),
                     "box": kill["box"], "feed_at": round(min(kill["t"] + 0.2, dur - 0.05), 3), "text": f"+{j + 1}",
                     "kill_at": 0.0})
        o, src_prev = kb + beat, ks + after_src
    last = segs[-1]
    hold = min(2 * beat, max(beat_times[-1] + beat - o, beat))
    segs.append({"kind": "hold", "ss": round(max(last["ss"] + last["d"] - 0.03, 0), 3), "d": round(hold, 3),
                 "out": round(hold, 3), "o0": round(o, 3), "box": last["box"], "feed_at": last["feed_at"],
                 "text": f"{len(used)} KILLS" if len(used) > 1 else "KILL"})
    return {"segments": segs, "seconds": round(o + hold, 3), "beat": round(beat, 4), "kills_used": len(used)}


def _pulse(seg: dict, beat_times: list[float], amp: float = 0.07) -> str:
    """Zoom-Stoß auf jedem Schlag innerhalb eines Segments (klingt schnell ab)."""
    local = [round(b - seg["o0"], 3) for b in beat_times if seg["o0"] - 0.001 <= b < seg["o0"] + seg["out"] - 0.05]
    return "1" + "".join(f"+{amp}*gte(t\\,{b})*exp(-11*(t-{b}))" for b in local[:10])


def _render_beat_seg(src: str, seg: dict, out: Path, tmp: Path, font: str, beat_times: list[float]) -> None:
    """Ein Segment des Beat-Edits: Tempo so, dass es genau ``out`` Sekunden füllt. Spielton leise, tiefer bei Zeitlupe."""
    if seg["kind"] == "hold":
        _render_seg(src, seg, out, tmp, font)
        return
    speed = seg["d"] / seg["out"]
    vol = 0.9 if seg["kind"] == "hit" else 0.55
    audio = (f"[0:a]aresample=48000,asetpts=PTS-STARTPTS,asetrate=48000*{speed:.5f},aresample=48000,"
             f"apad=whole_dur={seg['out']},atrim=0:{seg['out']},volume={vol}[a]")
    if seg["kind"] == "hit":
        kf = _feed_png(src, seg, tmp, out.stem)
        z = f"1+({Z_HIT}-1)*min(t/{PUNCH_S}\\,1)"
        fc = (f"[0:v]scale={W}:{H},setpts=(PTS-STARTPTS)/{speed:.5f}[s];{_vf('[s]', z, 'bg')};"
              f"[bg]fade=t=in:st=0:d=0.05:color=white[fl];[fl][1:v]overlay=(W-w)/2:{BOX_Y - 130}[v0];"
              f"[v0]{_draw(seg['text'], font)},fps={OUT_FPS},tpad=stop_mode=clone:stop_duration=1,trim=0:{seg['out']}[v];{audio}")
        _run(["ffmpeg", "-v", "error", "-y", "-ss", str(seg["ss"]), "-t", str(seg["d"]), "-i", src, "-i", str(kf),
              "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", str(seg["out"]), *ENC, str(out)])
        return
    z = "1"  # ruhiges Bild: kein Zoom im Anlauf, damit man den Kill kommen sieht
    fc = (f"[0:v]scale={W}:{H},setpts=(PTS-STARTPTS)/{speed:.5f}[s];{_vf('[s]', z, 'c')};"
          f"[c]fps={OUT_FPS},tpad=stop_mode=clone:stop_duration=1,trim=0:{seg['out']}[v];{audio}")
    _run(["ffmpeg", "-v", "error", "-y", "-ss", str(seg["ss"]), "-t", str(seg["d"]), "-i", src,
          "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", str(seg["out"]), *ENC, str(out)])


def word_times(words: list[str], beat_times: list[float], per_beat: int = 1) -> list[tuple[float, float, str]]:
    """Wörter auf das Beat-Raster legen (ein Wort je Schlag). Das ist eine Näherung: echte Gesangs-Zeiten kennt das
    Tool nicht. Für exakte Zeiten kann man je Wort eine Sekunde angeben ("1.45:WORT")."""
    out, i = [], 0
    for w in words:
        if ":" in w and w.split(":", 1)[0].replace(".", "").isdigit():
            t, txt = w.split(":", 1)
            out.append([float(t), None, txt])
            continue
        if i >= len(beat_times):
            break
        out.append([beat_times[i], None, w])
        i += per_beat
    out.sort(key=lambda x: x[0])
    beat = (beat_times[-1] - beat_times[0]) / max(len(beat_times) - 1, 1)
    for j, x in enumerate(out):
        x[1] = min(out[j + 1][0] if j + 1 < len(out) else x[0] + beat, x[0] + 2 * beat)
    return [(round(a, 3), round(b, 3), t) for a, b, t in out]


LYRIC_COLORS = ["white", "0xFFD23F", "white", "0x4DE08A", "white", "0xFF5A6E"]


def make_beat(src: str, music: str, out: str, music_ss: float = 0.0, music_d: float | None = None,
              words: list[str] | None = None, progress=None) -> dict:
    """Beat-Edit: Musik-Ausschnitt gibt den Takt vor, Kills fallen auf die Schläge, Songtext Wort für Wort in der
    Bildmitte. ``words``: Wörter in Reihenfolge (ein Wort je Schlag) oder "Sekunde:WORT" für feste Zeiten."""
    from cstaktik import beats as beatmod

    kills = detect(src)
    if not kills:
        raise ValueError("Im Clip wurde kein eigener Kill gefunden (kein rot umrandeter Killfeed-Eintrag oben rechts).")
    bt = beatmod.beats(music, music_ss, music_d)
    pl = plan_beat(kills, duration(src), bt["beats"])
    font = _font()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        files = []
        for i, seg in enumerate(pl["segments"]):
            f = tmp / f"b{i:03d}.mp4"
            _render_beat_seg(src, seg, f, tmp, font, bt["beats"])
            files.append(f)
            if progress:
                progress(i + 1, len(pl["segments"]))
        n = len(files)
        ins = [x for f in files for x in ("-i", str(f))]
        total = pl["seconds"]
        draw = []
        if font and words:
            # während eines Kills gehört die Bildmitte dem Kill: dort kein Songtext
            quiet = "".join(f"*(1-between(t,{x['o0']},{round(x['o0'] + x['out'], 3)}))"
                            for x in pl["segments"] if x["kind"] in ("hit", "hold"))
            for j, (a, b, txt) in enumerate(word_times(words, bt["beats"])):
                if a >= total:
                    break
                txt = txt.replace(":", r"\\:").replace("'", "").upper()
                base = 210 if len(txt) <= 5 else 170 if len(txt) <= 8 else 125  # kurze Wörter größer
                dy = (-150, 90, -40, 150, -100, 40)[j % 6]                       # Wörter springen in der Höhe
                draw.append(f"drawtext=fontfile='{font}':text='{txt}':fontsize='{base}+90*exp(-18*max(t-{a},0))':"
                            f"fontcolor={LYRIC_COLORS[j % len(LYRIC_COLORS)]}:borderw=14:bordercolor=black:"
                            f"shadowcolor=black@0.6:shadowx=10:shadowy=10:"
                            f"x=(w-text_w)/2:y={BOX_Y + BOX // 2 + dy}-text_h/2:enable='between(t,{a},{min(b, total)}){quiet}'")
        fc = ("".join(f"[{i}:v][{i}:a]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v0][ga];"
              f"[v0]{','.join(draw) if draw else 'null'}[v];"
              f"[{n}:a]aresample=48000,afade=t=out:st={max(total - 0.4, 0):.3f}:d=0.4[mu];"
              f"[ga][mu]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]")
        _run(["ffmpeg", "-v", "error", "-y", *ins, "-ss", str(music_ss), "-t", str(total), "-i", music,
              "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", str(total),
              "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(OUT_FPS),
              "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out])
    return {"kills": kills, "bpm": bt["bpm"], "seconds": round(duration(out), 2), "kills_used": pl["kills_used"],
            "segments": pl["segments"]}


if __name__ == "__main__":
    import sys

    r = make(sys.argv[1], sys.argv[2], progress=lambda i, n: print(f"Segment {i}/{n}", flush=True))
    print(f"{len(r['kills'])} Kills bei {[k['t'] for k in r['kills']]} s, Video {r['seconds']} s")
