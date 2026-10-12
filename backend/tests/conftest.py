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
