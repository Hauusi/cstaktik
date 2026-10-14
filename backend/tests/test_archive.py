"""Demos aus ZIP/RAR: nur .dem/.dem.bz2, ohne Pfade, Größenlimit, klare Fehler."""

import zipfile

import pytest

from cstaktik import archive


def _zip(path, files):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return path


def test_zip_takes_only_demos_flat_and_safe(tmp_path):
    src = _zip(tmp_path / "hltv.zip", {"navi-vs-vit/m1-mirage.dem": b"A" * 10, "m2 inferno.dem.bz2": b"B",
                                       "../../evil.dem": b"C", "readme.txt": b"x"})
    out = archive.extract_demos(src, tmp_path / "demos", max_bytes=100)
    assert [p.name for p in out] == ["evil.dem", "m1-mirage.dem", "m2_inferno.dem.bz2"]
    assert all(p.parent == tmp_path / "demos" for p in out) and not src.exists()
    assert (tmp_path / "demos" / "m1-mirage.dem").read_bytes() == b"A" * 10


def test_zip_errors(tmp_path):
    with pytest.raises(ValueError, match="keine .dem"):
        archive.extract_demos(_zip(tmp_path / "a.zip", {"x.txt": b"1"}), tmp_path / "d", 100)
    with pytest.raises(ValueError, match="zu groß"):
        archive.extract_demos(_zip(tmp_path / "b.zip", {"x.dem": b"1" * 200}), tmp_path / "d", 100)
    (tmp_path / "c.zip").write_bytes(b"kein zip")
    with pytest.raises(ValueError, match="beschädigt"):
        archive.extract_demos(tmp_path / "c.zip", tmp_path / "d", 100)


def test_rar_via_tool_and_missing_tool(tmp_path, monkeypatch):
    src = tmp_path / "m.rar"
    src.write_bytes(b"rar")
    # Ersatz-Programm: legt wie ein Entpacker zwei Dateien in Unterordner
    monkeypatch.setattr(archive, "rar_tool", lambda: ["sh", "-c", "mkdir -p '{dst}/sub' && printf demo > '{dst}/sub/m1.dem'"
                                                                   " && printf x > '{dst}/info.txt'"])
    out = archive.extract_demos(src, tmp_path / "d", 100)
    assert [p.name for p in out] == ["m1.dem"] and out[0].read_text() == "demo"
    assert not any(p.name.startswith(".unpack-") for p in (tmp_path / "d").iterdir())  # Temp-Ordner weg
    src.write_bytes(b"rar")
    monkeypatch.setattr(archive, "rar_tool", lambda: None)
    with pytest.raises(ValueError, match="sudo apt install unar"):
        archive.extract_demos(src, tmp_path / "d", 100)


def test_upload_rejects_other_files():
    from fastapi.testclient import TestClient

    from cstaktik import api

    r = TestClient(api.app).post("/analyze", files={"demo": ("x.7z", b"1")}, headers={"Origin": "http://testserver"})
    assert r.status_code == 400 and "zip" in r.text
