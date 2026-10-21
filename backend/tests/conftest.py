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
    monkeypatch.setattr(pipeline, "COACHING_FILE", tmp_path / "coaching.json")
    monkeypatch.setattr(pipeline, "AI_DIR", tmp_path / "ai")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)  # nie die echte API
    monkeypatch.setattr(pipeline, "PRO_DIR", tmp_path / "pro")
    monkeypatch.setattr(pipeline, "PRO_DEMOS_DIR", tmp_path / "pro_demos")
    monkeypatch.setattr(pipeline, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(pipeline, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(pipeline, "DEMOS_DIR", tmp_path / "demos")
    monkeypatch.setattr(pipeline, "TIMINGS_FILE", tmp_path / "timings.json")
    from cstaktik import config

    monkeypatch.setattr(config, "PLAYERS_FILE", tmp_path / "players.yaml")  # nie die echte players.yaml
    from cstaktik import autodl

    monkeypatch.setattr(autodl, "BASE", tmp_path / "autodl")  # nie den echten Download-Ordner
    monkeypatch.setattr(autodl, "CONFIG_DIR", tmp_path / "autodl" / "config")
    monkeypatch.setattr(autodl, "DEMOS_DIR", tmp_path / "autodl" / "demos")


@pytest.fixture(autouse=True)
def _isolated_accounts(tmp_path, monkeypatch):
    """Tests nutzen nie die echte Account-Datenbank oder den echten Sitzungs-Schlüssel."""
    from cstaktik import accounts

    monkeypatch.setattr(accounts, "DB_FILE", tmp_path / "accounts.db")
    monkeypatch.setattr(accounts, "SECRET_FILE", tmp_path / "secret.key")
    monkeypatch.setattr(accounts, "PBKDF2_ROUNDS", 1000)  # schnelle Tests; echte Hashes nutzen 600 000
    monkeypatch.delenv("STEAM_WEB_API_KEY", raising=False)


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
    from cstaktik import fonts

    monkeypatch.setattr(fonts, "_get", offline)
    monkeypatch.setattr(fonts, "FONTS_DIR", tmp_path / "fonts")
    monkeypatch.setattr(radar, "LOCAL_MAPS_DIR", tmp_path / "maps")
