"""Dateien atomar schreiben: erst in eine Temp-Datei daneben, dann ersetzen. Wer gleichzeitig liest, sieht immer
die alte oder die neue Fassung, nie eine halbe (sonst wirkt z. B. coaching.json kurz leer)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
