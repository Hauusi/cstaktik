"""Meme-Clip: aus einem CS2-Clip automatisch ein Hochformat-Video für Shorts schneiden (Prototyp).

Ablauf: eigene Kills im Clip finden -> Schnittplan -> mit ffmpeg rendern.

- Kills: Der Killfeed-Eintrag des eigenen Kills hat oben rechts einen roten Rahmen. Gesucht werden zwei lange
  rötliche Linien im Abstand einer Killfeed-Zeile mit dunklem Inneren. Kein Rahmen im Bild = kein Kill gefunden,
  dann wird nichts geraten.
- Schnitt je Kill: kurzer Anlauf, Zeitlupe mit Zoom auf die Bildmitte (dort ist das Fadenkreuz), Standbild mit
  Blitz, Wackeln, Zähler und dem Killfeed-Eintrag als Einblendung, dann zurück. Totzeit zwischen Kills fällt weg.
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

LEAD_S, HIT_BEFORE, HIT_AFTER, FREEZE_S, AFTER_S, LAST_FREEZE_S = 1.6, 0.30, 0.15, 0.55, 0.6, 1.3
SLOW, Z_LEAD, Z_HIT = 0.5, 1.08, 1.45


def _run(cmd: list[str]) -> bytes:
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode:
        raise RuntimeError(p.stderr.decode(errors="replace")[-600:])
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
    """Schnittplan: Segmente in Reihenfolge. kind: lead | hit | freeze | after."""
    segs: list[dict] = []
    end_prev = 0.0
    n = len(kills)
    for k, kill in enumerate(kills, start=1):
        t = max(kill["t"] - 0.10, 0.0)  # der Eintrag erscheint kurz nach dem Kill
        hit0, hit1 = max(t - HIT_BEFORE, end_prev), min(t + HIT_AFTER, dur)
        lead0 = max(hit0 - LEAD_S, end_prev)
        if hit0 - lead0 > 0.15:
            segs.append({"kind": "lead", "ss": round(lead0, 3), "d": round(hit0 - lead0, 3)})
        if hit1 - hit0 > 0.05:
            segs.append({"kind": "hit", "ss": round(hit0, 3), "d": round(hit1 - hit0, 3)})
        last = k == n
        segs.append({"kind": "freeze", "ss": round(hit1, 3), "d": LAST_FREEZE_S if last else FREEZE_S, "box": kill["box"],
                     "text": (f"{n} KILLS" if n > 1 else "KILL") if last else f"+{k}"})
        nxt = kills[k]["t"] - 0.10 - HIT_BEFORE if not last else dur
        a1 = min(hit1 + AFTER_S, dur, max(nxt, hit1))
        if not last and a1 - hit1 > 0.1:
            segs.append({"kind": "after", "ss": round(hit1, 3), "d": round(a1 - hit1, 3)})
        end_prev = a1 if not last else hit1
    return segs


def _font() -> str:
    for want in ("Inter:style=ExtraBold", "DejaVu Sans:style=Bold", ":bold"):
        p = subprocess.run(["fc-match", "-f", "%{file}", want], capture_output=True, text=True).stdout.strip()
        if p:
            return p
    return ""


def _vf(z: str, shake: bool = False) -> str:
    """Hochformat: auf Zielhöhe mal Zoom skalieren, mittig ausschneiden (Fadenkreuz bleibt in der Mitte)."""
    x = f"(iw-{OUT_W})/2" + ("+14*sin(t*97)*exp(-t*5)" if shake else "")
    y = f"(ih-{OUT_H})/2" + ("+10*cos(t*83)*exp(-t*5)" if shake else "")
    return f"scale=-2:'2*trunc({OUT_H // 2}*({z}))':eval=frame:flags=bilinear,crop={OUT_W}:{OUT_H}:'{x}':'{y}'"


ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p", "-r", str(OUT_FPS),
       "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "192k"]


def _render_seg(src: str, seg: dict, out: Path, tmp: Path, font: str) -> None:
    ss, d = seg["ss"], seg["d"]
    if seg["kind"] == "freeze":
        png = tmp / f"{out.stem}.png"
        _run(["ffmpeg", "-v", "error", "-y", "-ss", str(ss), "-i", src, "-frames:v", "1", "-vf", f"scale={W}:{H}", str(png)])
        x0, y0, x1, y1 = seg["box"]
        pad = 3
        feed = f"crop={x1 - x0 + 2 * pad}:{y1 - y0 + 2 * pad}:{max(x0 - pad, 0)}:{max(y0 - pad, 0)},scale=940:-2:flags=lanczos"
        text = seg["text"].replace(":", r"\:").replace("'", "")
        size, color = (230, "white") if " " in text or text == "KILL" else (380, "0xFFD23F")  # Zähler groß und gelb
        draw = (f"drawtext=fontfile='{font}':text='{text}':fontsize={size}:fontcolor={color}:borderw=16:bordercolor=black:"
                f"x=(w-text_w)/2:y=1180") if font else "null"
        boom = "0.95*sin(2*PI*(48+60*exp(-t*22))*t)*exp(-t*5.5)+0.25*(random(0)*2-1)*exp(-t*60)"
        fc = (f"[0:v]split[a][b];[a]{_vf(str(Z_HIT), shake=True)},fade=t=in:st=0:d=0.14:color=white[bg];"
              f"[b]{feed}[kf];[bg][kf]overlay=(W-w)/2:'300-60*exp(-t*14)'[v0];[v0]{draw},fps={OUT_FPS}[v];"
              f"aevalsrc='{boom}':d={d}:s=48000,aformat=channel_layouts=stereo[a]")
        _run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-framerate", str(OUT_FPS), "-t", str(d), "-i", str(png),
              "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", str(d), *ENC, str(out)])
        return
    if seg["kind"] == "hit":  # Zeitlupe, Zoom fährt rein, Ton tiefer
        od = d / SLOW
        v = f"setpts=PTS/{SLOW},{_vf(f'{Z_LEAD}+({Z_HIT}-{Z_LEAD})*min(t/{od:.3f}\\,1)')},fps={OUT_FPS}"
        a = f"asetrate=48000*{SLOW},aresample=48000"
    elif seg["kind"] == "after":  # Zoom fährt schnell zurück
        v = f"{_vf(f'{Z_HIT}-({Z_HIT}-1)*min(t/0.18\\,1)')},fps={OUT_FPS}"
        a = "anull"
    else:  # Anlauf: leichtes Reinfahren für Spannung
        v = f"{_vf(f'1+({Z_LEAD}-1)*min(t/{d:.3f}\\,1)')},fps={OUT_FPS}"
        a = "afade=t=in:d=0.04"
    _run(["ffmpeg", "-v", "error", "-y", "-ss", str(ss), "-t", str(d), "-i", src,
          "-filter_complex", f"[0:v]scale={W}:{H},setpts=PTS-STARTPTS,{v}[v];[0:a]aresample=48000,asetpts=PTS-STARTPTS,{a}[a]",
          "-map", "[v]", "-map", "[a]", *ENC, str(out)])


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


if __name__ == "__main__":
    import sys

    r = make(sys.argv[1], sys.argv[2], progress=lambda i, n: print(f"Segment {i}/{n}", flush=True))
    print(f"{len(r['kills'])} Kills bei {[k['t'] for k in r['kills']]} s, Video {r['seconds']} s")
