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


def is_archive_name(name: str) -> bool:
    return name.lower().endswith(ARCHIVE_SUFFIXES)


def _is_demo(name: str) -> bool:
    return name.lower().endswith((".dem", ".dem.bz2"))


def _safe(name: str) -> str:
    low = name.lower()
    suffix = ".dem.bz2" if low.endswith(".dem.bz2") else ".dem"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", name[: -len(suffix)]).strip("._") or "demo"
    return stem[:80] + suffix


def _unique(dest: Path, name: str) -> Path:
    out, i = dest / name, 2
    while out.exists():
        stem, suffix = (name[:-8], ".dem.bz2") if name.endswith(".dem.bz2") else (name[:-4], ".dem")
        out, i = dest / f"{stem}_{i}{suffix}", i + 1
    return out


def rar_tool() -> list[str] | None:
    """Befehl zum Entpacken eines RAR in einen Ordner: Platzhalter {src} und {dst}. None = kein Programm da."""
    for exe, args in (("unrar", ["x", "-o+", "-idq", "{src}", "{dst}/"]), ("7z", ["x", "-y", "-o{dst}", "{src}"]),
                      ("7zz", ["x", "-y", "-o{dst}", "{src}"]), ("unar", ["-q", "-f", "-D", "-o", "{dst}", "{src}"]),
                      ("bsdtar", ["-xf", "{src}", "-C", "{dst}"])):
        path = shutil.which(exe)
        if path:
            return [path, *args]
    return None


def _from_zip(src: Path, dest: Path, max_bytes: int) -> list[Path]:
    out = []
    with zipfile.ZipFile(src) as zf:
        for info in zf.infolist():
            name = Path(info.filename.replace("\\", "/")).name
            if info.is_dir() or not _is_demo(name):
                continue
            if info.file_size > max_bytes:
                raise ValueError(f"{name} im Archiv ist zu groß.")
            target = _unique(dest, _safe(name))
            written = 0
            with zf.open(info) as fin, target.open("wb") as fout:
                while chunk := fin.read(1 << 20):
                    written += len(chunk)
                    if written > max_bytes:  # Angabe im Archiv kann lügen
                        fout.close()
                        target.unlink(missing_ok=True)
                        raise ValueError(f"{name} im Archiv ist zu groß.")
                    fout.write(chunk)
            out.append(target)
    return out


def _from_rar(src: Path, dest: Path, max_bytes: int) -> list[Path]:
    cmd = rar_tool()
    if cmd is None:
        raise ValueError("Für .rar fehlt auf dem Server ein Entpack-Programm. Einmal installieren: "
                         "sudo apt install unar   (oder libarchive-tools). Alternativ die .dem-Dateien entpackt hochladen.")
    out = []
    with tempfile.TemporaryDirectory(dir=dest, prefix=".unpack-") as tmp:
        args = [a.replace("{src}", str(src)).replace("{dst}", tmp) for a in cmd]
        try:
            res = subprocess.run(args, capture_output=True, timeout=TOOL_TIMEOUT_S, check=False)  # noqa: S603
        except subprocess.TimeoutExpired as exc:
            raise ValueError("Entpacken dauerte zu lange.") from exc
        found = [p for p in Path(tmp).rglob("*") if p.is_file() and not p.is_symlink() and _is_demo(p.name)]
        if res.returncode != 0 and not found:
            msg = (res.stderr or res.stdout).decode(errors="ignore").strip().splitlines()
            raise ValueError("RAR konnte nicht entpackt werden" + (f": {msg[-1][:200]}" if msg else "."))
        for p in found:
            if p.stat().st_size > max_bytes:
                raise ValueError(f"{p.name} im Archiv ist zu groß.")
            target = _unique(dest, _safe(p.name))
            p.replace(target)
            out.append(target)
    return out


def extract_demos(src: Path, dest: Path, max_bytes: int) -> list[Path]:
    """Alle Demos aus dem Archiv nach ``dest``; das Archiv selbst wird danach gelöscht."""
    dest.mkdir(parents=True, exist_ok=True)
    try:
        if src.name.lower().endswith(".zip"):
            try:
                out = _from_zip(src, dest, max_bytes)
            except zipfile.BadZipFile as exc:
                raise ValueError("Die ZIP-Datei ist beschädigt oder keine ZIP-Datei.") from exc
        else:
            out = _from_rar(src, dest, max_bytes)
    finally:
        src.unlink(missing_ok=True)
    if not out:
        raise ValueError("Im Archiv ist keine .dem-Datei.")
    return sorted(out, key=lambda p: p.name)
