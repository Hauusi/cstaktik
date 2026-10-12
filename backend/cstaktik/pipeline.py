"""Gemeinsamer Ablauf für CLI und Web: Demo/JSON -> MatchData -> Analyse -> HTML."""

from __future__ import annotations

import bz2
import json
import statistics
import time
from collections.abc import Callable
from pathlib import Path

from cstaktik.config import load_focus_steamids, load_rules_config
from cstaktik.model import MatchData
from cstaktik.parser.loader import load_match, save_match
from cstaktik.report.render import write_report
from cstaktik.rules import analyze

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEMOS_DIR = DATA_DIR / "demos_raw"
REPORTS_DIR = DATA_DIR / "reports"
CACHE_DIR = DATA_DIR / "cache"
# Bei Änderungen am Datenmodell erhöhen, damit alte Caches neu geparst werden.
CACHE_SCHEMA = 4
# Obergrenze für entpackte Demos (Schutz gegen manipulierte .bz2-Dateien).
MAX_DEMO_BYTES = 2 * 1024**3


def demo_stem(name: str) -> str:
    """'match.dem.bz2' -> 'match', 'match.dem' -> 'match'."""
    low = name.lower()
    for suffix in (".dem.bz2", ".bz2", ".dem", ".json"):
        if low.endswith(suffix):
            return name[: -len(suffix)]
    return name


def is_demo_name(name: str) -> bool:
    return name.lower().endswith((".dem", ".dem.bz2"))


def decompress_bz2(src: Path, dst: Path, max_bytes: int = MAX_DEMO_BYTES) -> Path:
    written = 0
    try:
        with bz2.open(src, "rb") as fin, dst.open("wb") as fout:
            while chunk := fin.read(1 << 20):
                written += len(chunk)
                if written > max_bytes:
                    raise ValueError(f"Entpackte Demo größer als {max_bytes // 1024**2} MB")
                fout.write(chunk)
    except (OSError, EOFError, ValueError) as exc:
        dst.unlink(missing_ok=True)
        if isinstance(exc, ValueError):
            raise
        raise ValueError(f"Keine gültige .bz2-Datei: {exc}") from exc
    return dst


def prepare_demo(path: Path, remove_source: bool = False) -> Path:
    """.dem.bz2 wird neben die Quelle als .dem entpackt; alles andere bleibt unverändert."""
    if not path.name.lower().endswith(".bz2"):
        return path
    target = decompress_bz2(path, path.with_name(f"{demo_stem(path.name)}.dem"))
    if remove_source:
        path.unlink(missing_ok=True)
    return target


Progress = Callable[[str, float], None]
TIMINGS_FILE = CACHE_DIR / "timings.json"
_TIMINGS_KEEP = 20


def _record_timing(size_bytes: int, seconds: float) -> None:
    """Gemessene Parse-Dauer speichern: Basis für die Restzeit-Schätzung."""
    try:
        data = json.loads(TIMINGS_FILE.read_text()) if TIMINGS_FILE.exists() else []
    except (OSError, ValueError):
        data = []
    data.append({"mb": round(size_bytes / 1024**2, 2), "s": round(seconds, 1)})
    TIMINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TIMINGS_FILE.write_text(json.dumps(data[-_TIMINGS_KEEP:]))


def estimate_seconds(size_bytes: int) -> float | None:
    """Median Sekunden/MB der bisherigen Läufe auf diesem Rechner x Dateigröße. None ohne Messwerte."""
    try:
        data = json.loads(TIMINGS_FILE.read_text()) if TIMINGS_FILE.exists() else []
    except (OSError, ValueError):
        return None
    rates = [d["s"] / d["mb"] for d in data if d.get("mb", 0) > 0]
    if not rates:
        return None
    return statistics.median(rates) * size_bytes / 1024**2


def timing_samples() -> int:
    try:
        return len(json.loads(TIMINGS_FILE.read_text())) if TIMINGS_FILE.exists() else 0
    except (OSError, ValueError):
        return 0


def is_cached(path: Path) -> bool:
    if path.suffix.lower() != ".dem":
        return False
    from cstaktik.parser.awpy_adapter import sha256_of

    return (CACHE_DIR / f"{sha256_of(path)}.v{CACHE_SCHEMA}.json").exists()


def load_any(
    path: Path, focus: set[str], config: dict, use_cache: bool = True, progress: Progress | None = None
) -> MatchData:
    """``.dem`` wird mit awpy geparst (Ergebnis als JSON gecacht), ``.json`` direkt geladen."""
    if path.suffix.lower() == ".json":
        match = load_match(path)
    elif path.suffix.lower() == ".dem":
        from cstaktik.parser.awpy_adapter import parse_demo, sha256_of

        cache = CACHE_DIR / f"{sha256_of(path)}.v{CACHE_SCHEMA}.json"
        if use_cache and cache.exists():
            match = load_match(cache)
        else:
            t0 = time.monotonic()
            match = parse_demo(path, focus, config["parser"], progress)
            _record_timing(path.stat().st_size, time.monotonic() - t0)
            save_match(match, cache)
    else:
        raise ValueError(f"Unbekanntes Format: {path.suffix} (erwartet .dem oder .json)")
    if focus:  # Fokus-Spieler immer aus der aktuellen Config, nicht aus dem Cache
        for p in match.players:
            p.is_focus = p.steamid in focus
    return match


def run(
    path: Path, focus: set[str] | None = None, out_dir: Path = REPORTS_DIR, progress: Progress | None = None
) -> Path:
    """``progress(stufe, anteil)``: Parsen belegt 0–0.9, Regeln und Report den Rest."""
    report = progress or (lambda _stage, _frac: None)
    config = load_rules_config()
    focus = focus or load_focus_steamids()
    path = prepare_demo(path)
    match = load_any(path, focus, config, progress=lambda st, f: report(st, 0.9 * f))
    report("Fehler suchen", 0.92)
    result = analyze(match, config)
    report("Report bauen", 0.96)
    out = write_report(match, result, out_dir / f"{demo_stem(path.name)}.html")
    report("Fertig", 1.0)
    return out
