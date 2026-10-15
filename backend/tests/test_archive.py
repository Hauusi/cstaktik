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


def test_partial_zip_is_cleaned_and_names_do_not_clash(tmp_path):
    dest = tmp_path / "d"
    dest.mkdir()
    (dest / "m.dem").write_bytes(b"alt")  # schon vorhandene Demo
    src = _zip(tmp_path / "a.zip", {"a.dem": b"1", "m.dem.bz2": b"2", "z.dem": b"x" * 200})
    with pytest.raises(ValueError, match="zu groß"):
        archive.extract_demos(src, dest, 100)
    assert sorted(p.name for p in dest.iterdir()) == ["m.dem"]  # nichts Halbes liegen geblieben
    out = archive.extract_demos(_zip(tmp_path / "b.zip", {"m.dem.bz2": b"2"}), dest, 100)
    assert out[0].name == "m_2.dem.bz2" and (dest / "m.dem").read_bytes() == b"alt"


def test_too_many_demos(tmp_path):
    src = _zip(tmp_path / "a.zip", {f"m{i}.dem": b"1" for i in range(archive.MAX_DEMOS + 1)})
    with pytest.raises(ValueError, match="Zu viele"):
        archive.extract_demos(src, tmp_path / "d", 100)


def test_rar_bomb_stopped(tmp_path, monkeypatch):
    src = tmp_path / "bomb.rar"
    src.write_bytes(b"rar")
    # "Entpacker", der viel mehr schreibt als erlaubt: wird abgebrochen, nichts bleibt liegen
    monkeypatch.setattr(archive, "rar_tool", lambda: ["sh", "-c", "head -c 5000 /dev/zero > '{dst}/a.dem'; sleep 5"])
    with pytest.raises(ValueError, match="zu groß"):
        archive.extract_demos(src, tmp_path / "out", 1000)
    assert not [p for p in (tmp_path / "out").rglob("*") if p.is_file()]
