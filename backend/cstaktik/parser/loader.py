"""MatchData <-> JSON. Dient als Cache für geparste Demos und als Format der Test-Fixtures."""

from __future__ import annotations

from pathlib import Path

from cstaktik.model import MatchData


def load_match(path: Path) -> MatchData:
    return MatchData.model_validate_json(path.read_text(encoding="utf-8"))


def save_match(match: MatchData, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(match.model_dump_json(), encoding="utf-8")
