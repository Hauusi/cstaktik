"""Demos aus .zip- und .rar-Archiven holen (z. B. HLTV: ein .rar mit einer Demo je Map).

ZIP entpackt Python selbst. Für RAR braucht der Server eins dieser Programme (das erste gefundene wird genutzt):
unrar, 7z/7zz, unar, bsdtar. Installieren z. B. mit ``sudo apt install unar`` oder ``sudo apt install libarchive-tools``.

Aus dem Archiv werden nur .dem- und .dem.bz2-Dateien übernommen (ohne Ordnerpfad, Name bereinigt), alles andere
wird verworfen. Jede Demo darf höchstens ``max_bytes`` groß sein.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

ARCHIVE_SUFFIXES = (".zip", ".rar")
TOOL_TIMEOUT_S = 900
MAX_DEMOS = 10  # mehr Demos in einem Archiv: eher kein Match-Archiv
MAX_TOTAL_FACTOR = 3  # alle Demos zusammen höchstens 3x die Grenze einer Demo


def is_archive_name(name: str) -> bool:
    return name.lower().endswith(ARCHIVE_SUFFIXES)


def _is_demo(name: str) -> bool:
    return name.lower().endswith((".dem", ".dem.bz2", ".dem.gz"))


def _safe(name: str) -> str:
    low = name.lower()
    suffix = ".dem.bz2" if low.endswith(".dem.bz2") else ".dem.gz" if low.endswith(".dem.gz") else ".dem"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", name[: -len(suffix)]).strip("._") or "demo"
    return stem[:80] + suffix


def _unique(dest: Path, name: str) -> Path:
    """Freier Name in ``dest``. Für .dem.bz2 muss auch die entpackte .dem frei sein (prepare_demo legt sie daneben)."""
    stem, suffix = ((name[:-8], ".dem.bz2") if name.endswith(".dem.bz2") else (name[:-7], ".dem.gz")
                    if name.endswith(".dem.gz") else (name[:-4], ".dem"))
    cand, i = stem, 2
    while any((dest / f"{cand}{x}").exists() for x in (suffix, ".dem", ".dem.bz2", ".dem.gz")):
        cand, i = f"{stem}_{i}", i + 1
    return dest / f"{cand}{suffix}"


def rar_tool() -> list[str] | None:
    """Befehl zum Entpacken eines RAR in einen Ordner: Platzhalter {src} und {dst}. None = kein Programm da."""
    for exe, args in (("unrar", ["x", "-o+", "-idq", "{src}", "{dst}/"]), ("7z", ["x", "-y", "-o{dst}", "{src}"]),
                      ("7zz", ["x", "-y", "-o{dst}", "{src}"]), ("unar", ["-q", "-f", "-D", "-o", "{dst}", "{src}"]),
                      ("bsdtar", ["-xf", "{src}", "-C", "{dst}"])):
        path = shutil.which(exe)
        if path:
            return [path, *args]
    return None


def _from_zip(src: Path, dest: Path, max_bytes: int, out: list[Path]) -> list[Path]:
    total = 0
    with zipfile.ZipFile(src) as zf:
        infos = [i for i in zf.infolist() if not i.is_dir() and _is_demo(Path(i.filename.replace("\\", "/")).name)]
        if len(infos) > MAX_DEMOS:
            raise ValueError(f"Zu viele Demos im Archiv ({len(infos)}, höchstens {MAX_DEMOS}).")
        for info in infos:
            name = Path(info.filename.replace("\\", "/")).name
            if info.file_size > max_bytes:
                raise ValueError(f"{name} im Archiv ist zu groß.")
            target = _unique(dest, _safe(name))
            out.append(target)  # vorher eintragen: bei Abbruch wird auch die halbe Datei gelöscht
            written = 0
            with zf.open(info) as fin, target.open("wb") as fout:
                while chunk := fin.read(1 << 20):
                    written += len(chunk)
                    total += len(chunk)
                    if written > max_bytes or total > MAX_TOTAL_FACTOR * max_bytes:  # Angabe im Archiv kann lügen
                        raise ValueError(f"{name} im Archiv ist zu groß.")
                    fout.write(chunk)
    return out


MAX_FILES = 200  # mehr Dateien im Archiv: kein Demo-Archiv


def _dir_usage(path: Path) -> tuple[int, int]:
    size = n = 0
    for p in path.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                size += p.stat().st_size
                n += 1
        except OSError:
            continue
    return size, n


def _run_watched(args: list[str], tmp: Path, limit: int) -> subprocess.CompletedProcess:
    """Entpack-Programm starten und den Zielordner beobachten: wird er größer als ``limit`` (z. B. ein Archiv, das
    sich auf viele GB aufbläht) oder dauert es zu lange, wird abgebrochen, bevor die Platte voll ist."""
    import time

    start = time.monotonic()
    log = tempfile.TemporaryFile()  # nicht PIPE: bei viel Ausgabe liefe die Pipe voll und alles stünde
    with log, subprocess.Popen(args, stdout=log, stderr=log) as proc:  # noqa: S603
        while proc.poll() is None:
            size, n = _dir_usage(tmp)
            if size > limit or n > MAX_FILES:
                proc.kill()
                raise ValueError("Archiv entpackt zu groß oder zu viele Dateien: abgebrochen.")
            if time.monotonic() - start > TOOL_TIMEOUT_S:
                proc.kill()
                raise ValueError("Entpacken dauerte zu lange.")
            time.sleep(0.3)
        log.seek(0)
        out = log.read()[-4000:]
    size, n = _dir_usage(tmp)
    if size > limit or n > MAX_FILES:
        raise ValueError("Archiv entpackt zu groß oder zu viele Dateien: abgebrochen.")
    return subprocess.CompletedProcess(args, proc.returncode, out, b"")


def _from_rar(src: Path, dest: Path, max_bytes: int, out: list[Path]) -> list[Path]:
    cmd = rar_tool()
    if cmd is None:
        raise ValueError("Für .rar fehlt auf dem Server ein Entpack-Programm. Einmal installieren: "
                         "sudo apt install unar   (oder libarchive-tools). Alternativ die .dem-Dateien entpackt hochladen.")
    with tempfile.TemporaryDirectory(dir=dest, prefix=".unpack-") as tmp:
        args = [a.replace("{src}", str(src)).replace("{dst}", tmp) for a in cmd]
        res = _run_watched(args, Path(tmp), MAX_TOTAL_FACTOR * max_bytes)
        found = [p for p in Path(tmp).rglob("*") if p.is_file() and not p.is_symlink() and _is_demo(p.name)]
        if res.returncode != 0 and not found:
            msg = (res.stderr or res.stdout).decode(errors="ignore").strip().splitlines()
            raise ValueError("RAR konnte nicht entpackt werden" + (f": {msg[-1][:200]}" if msg else "."))
        if len(found) > MAX_DEMOS:
            raise ValueError(f"Zu viele Demos im Archiv ({len(found)}, höchstens {MAX_DEMOS}).")
        for p in found:
            if p.stat().st_size > max_bytes:
                raise ValueError(f"{p.name} im Archiv ist zu groß.")
        for p in found:
            target = _unique(dest, _safe(p.name))
            p.replace(target)
            out.append(target)
    return out


def extract_demos(src: Path, dest: Path, max_bytes: int) -> list[Path]:
    """Alle Demos aus dem Archiv nach ``dest``; das Archiv selbst wird danach gelöscht."""
    dest.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    try:
        if src.name.lower().endswith(".zip"):
            try:
                _from_zip(src, dest, max_bytes, out)
            except zipfile.BadZipFile as exc:
                raise ValueError("Die ZIP-Datei ist beschädigt oder keine ZIP-Datei.") from exc
        else:
            _from_rar(src, dest, max_bytes, out)
    except BaseException:
        for p in out:  # halb entpacktes Archiv: nichts liegen lassen, was nie ausgewertet wird
            p.unlink(missing_ok=True)
        raise
    finally:
        src.unlink(missing_ok=True)
    if not out:
        raise ValueError("Im Archiv ist keine .dem-Datei.")
    return sorted(out, key=lambda p: p.name)
