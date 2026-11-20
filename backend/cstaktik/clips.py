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
            out.append({"id": d.name, **st, "has_video": (d / "out.mp4").exists(),
                        "has_lyrics": (d / "out.lyrics.json").exists() and (d / "out.base.mp4").exists()})
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



MAX_LYRICS = 1500


def lyrics_text(v: str) -> str:
    """Eingefügter Songtext: Zeilen bleiben erhalten (Zeilenende = Pause im Gesang), Leerzeichen je Zeile vereinheitlicht."""
    lines = [" ".join(x.split()) for x in str(v or "").splitlines()]
    return "\n".join(x for x in lines if x)[:MAX_LYRICS]


def typed_words(text: str) -> list[str]:
    """Wörter aus dem eingefügten Text; das letzte Wort jeder Zeile trägt die Zeilenende-Marke (wie bei LRCLIB)."""
    out: list[str] = []
    for line in text.splitlines():
        ws = line.split()
        if ws:
            out += ws[:-1] + [ws[-1] + "\u00b6"]
    return out


def find_start(music: str, lyrics: str, song: str | None) -> tuple[float | None, str | None, str]:
    """Start in einer ganzen Songdatei über LRCLIB: Stelle des eingefügten Texts, ohne Text die Hook.
    Suche mit dem Songnamen, ohne Namen mit der ersten Textzeile. Rückgabe (Start oder None, Song für LRCLIB,
    Begründung)."""
    from cstaktik import lrclib, memeclip

    query = song or (lyrics.splitlines()[0] if lyrics.strip() else "")
    dur = memeclip.duration(music)
    hit = lrclib.fetch(query, dur) if query else None
    if not hit:
        return None, song, "Song bei LRCLIB nicht gefunden (Songname angeben hilft): Musik ab Anfang der Datei"
    name = f"{hit['track']} – {hit['artist']}"
    if not hit.get("duration") or abs(dur - hit["duration"]) > lrclib.FULL_SONG_TOL:
        return None, song, (f"{name}: die Datei ist nicht der ganze Song ({dur:.0f} s statt {hit['duration'] or 0:.0f} s), "
                            "Stelle nicht bestimmbar: Musik ab Anfang der Datei")
    t, why = lrclib.music_start(hit["lines"], lyrics)
    if t is None:
        return None, song, f"{name}: {why}: Musik ab Anfang der Datei"
    return t, f"{hit['track']} {hit['artist']}", f"{name}: {why}, ab Sekunde {t:.1f}"


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
                words = typed_words(st.get("lyrics") or "")
                song = st.get("song") or None
                ss = float(st.get("music_ss") or 0)
                drop_at = float(st["drop_at"]) if (st.get("drop_at") if st.get("drop_at") is not None else -1) >= 0 \
                    else None
                hook = None
                if ss < 0 and song and not words:
                    # Song gewählt, kein Text: Hook über die Deezer-Hörprobe (Nutzer: "welcher Part der beste ist");
                    # Musik startet INTRO_S davor (Text-Teil als Aufbau), der Drop kommt auf die Hook
                    from cstaktik import preview

                    set_state(d, step="Beste Stelle im Song suchen")
                    hook, why_hook = preview.best_part(music, song, str(d))
                    set_state(d, music_hook=why_hook)
                    if hook is not None:
                        ss = max(hook - preview.INTRO_S, 0.0)
                        if drop_at is None:
                            drop_at = hook
                        set_state(d, music_auto=False, music_used=round(ss, 2),
                                  music_found=f"{why_hook}, Musik ab {ss:.1f}, Drop auf der Hook".replace(".", ","))
                if ss < 0 and (words or song):
                    # Songtext eingefügt oder Song gewählt: Stelle im Song suchen (Nutzer: "ich will die Hook nehmen")
                    set_state(d, step="Stelle im Song suchen")
                    ss, song, why = find_start(music, st.get("lyrics") or "", song)
                    if ss is not None and not (st.get("lyrics") or "").strip() and "Hook" in why:
                        # Hook aus LRCLIB: wie bei Deezer davor starten (Text-Teil als Aufbau), Drop auf die Hook
                        from cstaktik import lrclib, preview

                        hook_t = ss + lrclib.LEAD_S
                        ss = max(hook_t - preview.INTRO_S, 0.0)
                        if drop_at is None:
                            drop_at = hook_t
                        why += f", Musik ab {ss:.1f}, Drop auf der Hook"
                    if ss is not None:
                        words = []  # Zeiten je Zeile kommen von LRCLIB (echte Einsätze statt ein Wort je Schlag)
                        set_state(d, music_auto=False, music_used=round(ss, 2), music_found=why)
                    else:  # nicht gefunden: ab Anfang der Datei, eigener Text bleibt
                        ss = 0.0
                        set_state(d, music_auto=False, music_used=0.0, music_start_note=True, music_found=why)
                elif ss < 0:  # leer gelassen, ohne Songtext: am Drop starten
                    from cstaktik import beats

                    set_state(d, step="Drop in der Musik suchen")
                    drop = beats.find_drop(music)
                    ss = beats.drop_start(music, drop) if drop is not None else 0.0
                    set_state(d, music_auto=drop is not None, music_used=ss)
                r = memeclip.make_beat(src, music, str(d / "out.mp4"), music_ss=ss,
                                       words=words or None, progress=prog, song=song,
                                       fmt="quer" if st.get("fmt") == "quer" else "hoch",
                                       lyrics_shift=float(st.get("lyrics_shift") or 0.0),
                                       drop_at=drop_at)
            else:
                r = memeclip.make(src, str(d / "out.mp4"), progress=prog)
            set_state(d, status="fertig", step=None, kills=r.get("kills_used", len(r["kills"])), seconds=r["seconds"],
                      bpm=r.get("bpm"), words=r.get("words"), found=len(r["kills"]),
                      lyrics_source=r.get("lyrics_source"), lyrics_note=r.get("lyrics_note"),
                      wall=r.get("wall"), synced=r.get("synced_shots"),
                      sync_measured=r.get("sync_measured"),
                      audio_note=r.get("audio_note"), drop=r.get("drop"), lyrics_debug=r.get("lyrics_debug"))
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


def relyric(d: Path, shift: float) -> None:
    """Nur den Songtext neu einblenden, um ``shift`` Sekunden verschoben (Kills, Schnitt, Ton bleiben)."""
    from cstaktik import memeclip

    with _render_lock:
        lyr = memeclip.load_lyrics(d / "out.mp4")
        base = d / "out.base.mp4"
        if not lyr or not base.exists():
            set_state(d, error="Für dieses Video fehlt die Vorlage ohne Text (älterer Schnitt). Bitte neu schneiden.")
            return
        set_state(d, status="läuft", step="Songtext neu einblenden")
        tmp = d / "out.new.mp4"
        try:
            memeclip.apply_lyrics(str(base), lyr, str(tmp), shift)
            tmp.replace(d / "out.mp4")
            lyr["shift"] = shift
            memeclip.save_lyrics(d / "out.mp4", lyr)
            set_state(d, status="fertig", step=None, lyrics_shift_applied=shift)
        except Exception as e:  # noqa: BLE001 - altes Video bleibt
            tmp.unlink(missing_ok=True)
            set_state(d, status="fertig", step=None, lyrics_note=f"Songtext neu einblenden fehlgeschlagen: {str(e)[:200]}")


def start_relyric(d: Path, shift: float) -> None:
    threading.Thread(target=relyric, args=(d, shift), daemon=True, name="clip-relyric").start()


def start(d: Path, user: str | None = None) -> None:
    threading.Thread(target=render, args=(d, user), daemon=True, name="clip-render").start()
