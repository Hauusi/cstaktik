import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def _isolated_history(tmp_path, monkeypatch):
    """Tests schreiben den Match-Verlauf nie in backend/data."""
    from cstaktik import pipeline

    monkeypatch.setattr(pipeline, "HISTORY_DIR", tmp_path / "history")
    monkeypatch.setattr(pipeline, "GOALS_FILE", tmp_path / "goals.json")


@pytest.fixture(autouse=True)
def _no_network_maps(tmp_path, monkeypatch):
    """Kein Karten-Download in Tests; Kartenordner isoliert."""
    from cstaktik import maps
    from cstaktik.report import radar

    def offline(url, timeout):
        raise OSError("offline im Test")

    monkeypatch.setattr(maps, "_get", offline)
    from cstaktik import icons

    monkeypatch.setattr(icons, "_get", offline)
    monkeypatch.setattr(icons, "ICONS_DIR", tmp_path / "icons")
    monkeypatch.setattr(radar, "LOCAL_MAPS_DIR", tmp_path / "maps")
