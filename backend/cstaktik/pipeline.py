"""Gemeinsamer Ablauf für CLI und Web: Demo/JSON -> MatchData -> Analyse -> HTML."""

from __future__ import annotations

import bz2
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
CACHE_SCHEMA = 2
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


def load_any(path: Path, focus: set[str], config: dict, use_cache: bool = True) -> MatchData:
    """``.dem`` wird mit awpy geparst (Ergebnis als JSON gecacht), ``.json`` direkt geladen."""
    if path.suffix.lower() == ".json":
        match = load_match(path)
    elif path.suffix.lower() == ".dem":
        from cstaktik.parser.awpy_adapter import parse_demo, sha256_of

        cache = CACHE_DIR / f"{sha256_of(path)}.v{CACHE_SCHEMA}.json"
        if use_cache and cache.exists():
            match = load_match(cache)
        else:
            match = parse_demo(path, focus, config["parser"])
            save_match(match, cache)
    else:
        raise ValueError(f"Unbekanntes Format: {path.suffix} (erwartet .dem oder .json)")
    if focus:  # Fokus-Spieler immer aus der aktuellen Config, nicht aus dem Cache
        for p in match.players:
            p.is_focus = p.steamid in focus
    return match


def run(path: Path, focus: set[str] | None = None, out_dir: Path = REPORTS_DIR) -> Path:
    config = load_rules_config()
    focus = focus or load_focus_steamids()
    path = prepare_demo(path)
    match = load_any(path, focus, config)
    result = analyze(match, config)
    return write_report(match, result, out_dir / f"{demo_stem(path.name)}.html")
