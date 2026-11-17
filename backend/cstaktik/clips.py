"""Clips in der App: Video (und optional Musik) hochladen, im Hintergrund schneiden lassen, ansehen und laden.

Je Auftrag ein Ordner data/clips/<nutzer>/<id>/ mit in.<endung>, music.<endung>, out.mp4 und state.json
(status: wartet | läuft | fertig | fehler). Es läuft immer nur ein Schnitt gleichzeitig (der Server hat keine
Grafikkarte). Ohne Musik: normaler Kill-Schnitt (memeclip.make). Mit Musik: Beat-Schnitt (memeclip.make_beat).
"""

from __future__ import annotations

import json
import re
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path

from cstaktik import pipeline
from cstaktik.fsutil import write_atomic

MAX_VIDEO_BYTES, MAX_MUSIC_BYTES, KEEP, MAX_CLIPS = 400 * 1024 * 1024, 40 * 1024 * 1024, 12, 8
VIDEO_EXT, MUSIC_EXT = (".mp4", ".mov", ".mkv", ".webm"), (".mp3", ".m4a", ".wav", ".ogg", ".aac", ".mp4")
_render_lock = threading.Lock()


def safe_ext(name: str, default: str) -> str:
    """Dateiendung für die Ablage. Handys liefern oft Namen ohne oder mit unbekannter Endung: Die Endung entscheidet
    nicht, ob die Datei angenommen wird. ffmpeg erkennt das Format am Inhalt."""
    ext = Path(name or "").suffix.lower()
    return ext if re.fullmatch(r"\.[a-z0-9]{1,5}", ext) else default


def _user_dir(user: str | None) -> Path:
    return pipeline.CLIPS_DIR / re.sub(r"[^0-9A-Za-z_.-]", "_", user or "alle")


def new_job(user: str | None) -> Path:
    d = _user_dir(user) / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6])
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state(d: Path) -> dict:
    try:
        return json.loads((d / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def set_state(d: Path, **kw) -> None:
    st = {**_state(d), **kw}
    write_atomic(d / "state.json", json.dumps(st, ensure_ascii=False))


def jobs(user: str | None) -> list[dict]:
    base = _user_dir(user)
    out = []
    for d in sorted(base.iterdir(), reverse=True) if base.exists() else []:
        st = _state(d)
        if st:
            out.append({"id": d.name, **st, "has_video": (d / "out.mp4").exists()})
    return out


def job_dir(user: str | None, job_id: str) -> Path | None:
    if not re.fullmatch(r"[0-9a-f-]{10,40}", job_id):
        return None
    d = _user_dir(user) / job_id
    return d if d.is_dir() else None


def delete(user: str | None, job_id: str) -> None:
    d = job_dir(user, job_id)
    if d and _state(d).get("status") != "läuft":
        shutil.rmtree(d, ignore_errors=True)


def _cleanup(user: str | None) -> None:
    """Nur die letzten KEEP Aufträge behalten (Videos sind groß)."""
    base = _user_dir(user)
    for d in sorted(base.iterdir(), reverse=True)[KEEP:] if base.exists() else []:
        if _state(d).get("status") != "läuft":
            shutil.rmtree(d, ignore_errors=True)



def render(d: Path, user: str | None = None) -> None:
    """Einen Auftrag schneiden (blockiert; für den Hintergrund-Thread). Fehler landen als Text im Status."""
    from cstaktik import memeclip

    st = _state(d)
    src = [str(p) for p in sorted(d.glob("in*.*"))]  # in0.mp4, in1.mp4 ... in Reihenfolge der Auswahl
    music = next((str(p) for p in d.glob("music.*")), None)
    with _render_lock:
        set_state(d, status="läuft", step="Kills suchen")
        try:
            prog = lambda i, n: set_state(d, step=f"Schneiden {i} von {n}")  # noqa: E731
            if music:
                words = [w for w in re.split(r"\s+", st.get("lyrics") or "") if w]
                ss = float(st.get("music_ss") or 0)
                if ss < 0:  # leer gelassen: am Drop starten
                    from cstaktik import beats

                    set_state(d, step="Drop in der Musik suchen")
                    drop = beats.find_drop(music)
                    ss = beats.drop_start(music, drop) if drop is not None else 0.0
                    set_state(d, music_auto=drop is not None, music_used=ss)
                r = memeclip.make_beat(src, music, str(d / "out.mp4"), music_ss=ss,
                                       words=words or None, progress=prog, song=st.get("song") or None,
                                       fmt="quer" if st.get("fmt") == "quer" else "hoch",
                                       lyrics_shift=float(st.get("lyrics_shift") or 0.0))
            else:
                r = memeclip.make(src, str(d / "out.mp4"), progress=prog)
            set_state(d, status="fertig", step=None, kills=r.get("kills_used", len(r["kills"])), seconds=r["seconds"],
                      bpm=r.get("bpm"), words=r.get("words"), found=len(r["kills"]),
                      lyrics_source=r.get("lyrics_source"), lyrics_note=r.get("lyrics_note"),
                      wall=r.get("wall"), synced=r.get("synced_shots"),
                      sync_measured=r.get("sync_measured"),
                      audio_note=r.get("audio_note"))
        except ValueError as e:
            set_state(d, status="fehler", step=None, error=str(e))
        except RuntimeError as e:  # ffmpeg konnte eine Datei nicht lesen oder schneiden
            msg = str(e)
            hint = "Eine der Dateien ist kein lesbares Video oder Audio." if "Invalid data" in msg or "moov atom" in msg \
                else "Der Schnitt ist fehlgeschlagen: " + msg[:300]
            set_state(d, status="fehler", step=None, error=hint)
        except Exception as e:  # noqa: BLE001 - ffmpeg-Fehler u. Ä. sollen im Auftrag stehen, nicht den Server stoppen
            set_state(d, status="fehler", step=None, error="Der Schnitt ist fehlgeschlagen: " + str(e)[:300])
    _cleanup(user)


def start(d: Path, user: str | None = None) -> None:
    threading.Thread(target=render, args=(d, user), daemon=True, name="clip-render").start()
