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


PLAYERS_FILE = CONFIG_DIR / "players.yaml"  # gitignored: echte SteamIDs


def load_focus_steamids(path: Path | None = None) -> set[str]:
    """Wen der Coach analysiert: die mit Steam verbundenen Accounts. Erst wenn niemand verbunden ist, gilt
    players.yaml (Seite 'Spieler'). So wird niemand ausgewertet, der sich nicht selbst angemeldet hat."""
    if path is None:
        from cstaktik.accounts import linked_steamids

        linked = linked_steamids()
        if linked:
            return linked
    path = path or PLAYERS_FILE
    if not path.exists():
        return set()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(s) for s in data.get("focus_steamids", [])}


def save_focus_steamids(players: list[tuple[str, str]], path: Path | None = None) -> None:
    """players.yaml schreiben: [(steamid, name), ...]. Namen nur als Kommentar zur Orientierung."""
    path = path or PLAYERS_FILE
    lines = ["# Von der Seite 'Spieler' geschrieben. SteamID64 der Spieler, die der Coach analysiert.",
             "focus_steamids:"]
    for sid, name in players:
        if not sid.isdigit():
            raise ValueError(f"Ungültige SteamID: {sid}")
        safe = "".join(ch for ch in name if ch.isprintable() and ch not in "\n#")[:40]
        lines.append(f'  - "{sid}"  # {safe}')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
