"""Laden von rules.yaml und players.yaml."""

from __future__ import annotations

from pathlib import Path

import copy

import yaml

CONFIG_DIR = Path(__file__).parent


_RULES_CACHE: dict[tuple, dict] = {}


def load_rules_config(path: Path | None = None) -> dict:
    """rules.yaml; gemerkt bis zur nächsten Änderung der Datei. Jeder Aufruf bekommt eine eigene Kopie."""
    path = path or CONFIG_DIR / "rules.yaml"
    key = (str(path), path.stat().st_mtime_ns)
    if key not in _RULES_CACHE:
        _RULES_CACHE.clear()
        _RULES_CACHE[key] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return copy.deepcopy(_RULES_CACHE[key])


def load_focus_steamids(path: Path | None = None) -> set[str]:
    path = path or CONFIG_DIR / "players.yaml"
    if not path.exists():
        return set()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(s) for s in data.get("focus_steamids", [])}
