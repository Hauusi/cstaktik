"""Gemeinsamer Ablauf für CLI und Web: Demo/JSON -> MatchData -> Analyse -> HTML."""

from __future__ import annotations

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


def load_any(path: Path, focus: set[str], config: dict, use_cache: bool = True) -> MatchData:
    """``.dem`` wird mit awpy geparst (Ergebnis als JSON gecacht), ``.json`` direkt geladen."""
    if path.suffix.lower() == ".json":
        match = load_match(path)
    elif path.suffix.lower() == ".dem":
        from cstaktik.parser.awpy_adapter import parse_demo, sha256_of

        cache = CACHE_DIR / f"{sha256_of(path)}.json"
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
    match = load_any(path, focus, config)
    result = analyze(match, config)
    return write_report(match, result, out_dir / f"{path.stem}.html")
