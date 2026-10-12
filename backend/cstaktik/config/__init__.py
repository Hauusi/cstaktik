"""Laden von rules.yaml und players.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).parent


def load_rules_config(path: Path | None = None) -> dict:
    path = path or CONFIG_DIR / "rules.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_focus_steamids(path: Path | None = None) -> set[str]:
    path = path or CONFIG_DIR / "players.yaml"
    if not path.exists():
        return set()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(s) for s in data.get("focus_steamids", [])}
