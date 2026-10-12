import pytest

from cstaktik import maps

TXT = b'"de_mirage"\n{\n "pos_x" "-3230" // x\n "pos_y" "1713"\n "scale" "5.00"\n}'
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 30


def test_fetch_map_saves_validated_files(tmp_path, monkeypatch):
    calls = []

    def fake(url, timeout):
        calls.append(url)
        return TXT if url.endswith(".txt") else PNG

    monkeypatch.setattr(maps, "_get", fake)
    maps.fetch_map("de_mirage", tmp_path)
    assert maps.has_map("de_mirage", tmp_path)
    assert calls[0].endswith("/data/radar_info/de_mirage.txt")
    assert calls[1].endswith("/images/radars/de_mirage_radar_psd.png")

    from cstaktik.report.radar import build_radar
    from synth import build_match

    r = build_radar(build_match(), [tmp_path])
    assert (r.pos_x, r.pos_y, r.scale) == (-3230.0, 1713.0, 5.0) and r.image_data_uri.startswith("data:image/png")


def test_fetch_map_rejects_bad_data(tmp_path, monkeypatch):
    monkeypatch.setattr(maps, "_get", lambda url, timeout: TXT if url.endswith(".txt") else b"<html>")
    with pytest.raises(ValueError):
        maps.fetch_map("de_mirage", tmp_path)
    assert not maps.has_map("de_mirage", tmp_path)
    with pytest.raises(ValueError):
        maps.fetch_map("../etc", tmp_path)


def test_ensure_map_reports_failure_instead_of_crashing(tmp_path):
    note = maps.ensure_map("de_mirage", tmp_path)  # Netz ist in Tests aus
    assert note and "de_mirage" in note
    assert maps.ensure_map(None, tmp_path)
