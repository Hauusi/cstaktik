"""MatchData <-> JSON. Dient als Cache für geparste Demos und als Format der Test-Fixtures."""

from __future__ import annotations

from pathlib import Path

from cstaktik.fsutil import write_atomic
from cstaktik.model import MatchData


def load_match(path: Path) -> MatchData:
    return MatchData.model_validate_json(path.read_text(encoding="utf-8")).split_post_round()


def save_match(match: MatchData, path: Path) -> None:
    # atomar: ein abgebrochener Schreibvorgang (20-60 MB) darf keinen halben Cache hinterlassen
    write_atomic(path, match.model_dump_json())
