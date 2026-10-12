import re
from pathlib import Path

from fastapi.testclient import TestClient
from synth import build_match

from cstaktik import pipeline
from cstaktik.config import load_rules_config
from cstaktik.parser.loader import load_match, save_match
from cstaktik.report.render import render_report
from cstaktik.rules import analyze


def test_json_roundtrip(tmp_path):
    m = build_match()
    save_match(m, tmp_path / "m.json")
    assert load_match(tmp_path / "m.json") == m


def test_report_is_selfcontained_and_mobile(tmp_path):
    m = build_match()
    html = render_report(m, analyze(m, load_rules_config()), maps_dir=tmp_path)
    assert 'name="viewport"' in html
    assert not re.search(r'(src|href)="https?://', html)  # keine externen Ressourcen
    assert "Tod ohne Trade" in html and "Gleicher Todesort" in html and "Force-Buy" in html
    assert "Radarbild fehlt" in html  # ohne awpy-Kartendaten ehrlich melden
    assert html.count("<polyline") > 0


def test_report_uses_awpy_radar_when_present(tmp_path):
    import json
    import struct
    import zlib

    def png(w, h):
        raw = b"".join(b"\x00" + b"\x00\x00\x00" * w for _ in range(h))
        chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))

    (tmp_path / "de_mirage.png").write_bytes(png(4, 4))
    (tmp_path / "map-data.json").write_text(json.dumps({"de_mirage": {"pos_x": -1000, "pos_y": 1000, "scale": 5}}))
    m = build_match()
    html = render_report(m, analyze(m, load_rules_config()), maps_dir=tmp_path)
    assert "data:image/png;base64," in html and "Radarbild fehlt" not in html
    assert 'viewBox="0 0 4 4"' in html


def test_cli_analyze_json(tmp_path, monkeypatch):
    from cstaktik.cli import main
    from synth import BRO, ME

    src = tmp_path / "match.json"
    save_match(build_match(focus=()), src)
    out = tmp_path / "out"
    assert main(["analyze", str(src), "--me", ME, "--me", BRO, "--out", str(out)]) == 0
    assert (out / "match.html").exists()


def test_api_upload(tmp_path, monkeypatch):
    from cstaktik import api

    monkeypatch.setattr(pipeline, "DEMOS_DIR", tmp_path / "demos")
    monkeypatch.setattr(pipeline, "REPORTS_DIR", api.pipeline.REPORTS_DIR)

    def fake_run(path: Path, focus=None, out_dir=None):
        assert path.read_bytes() == b"FAKE" and path.suffix == ".dem"
        assert focus == {"1", "2"}
        target = tmp_path / "x.html"
        target.write_text("ok")
        return target

    monkeypatch.setattr(pipeline, "run", fake_run)
    c = TestClient(api.app)
    assert c.get("/").status_code == 200
    r = c.post("/analyze", files={"demo": ("../böse name.dem", b"FAKE")}, data={"steamids": "1, 2"},
               follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/reports/x.html"
    assert [p.name for p in (tmp_path / "demos").iterdir()] == ["b_se_name.dem"]
    assert c.post("/analyze", files={"demo": ("a.txt", b"x")}).status_code == 400


def test_api_upload_bz2(tmp_path, monkeypatch):
    import bz2

    from cstaktik import api

    monkeypatch.setattr(pipeline, "DEMOS_DIR", tmp_path / "demos")
    seen = {}

    def fake_run(path: Path, focus=None, out_dir=None):
        seen["path"], seen["data"] = path, path.read_bytes()
        target = tmp_path / "x.html"
        target.write_text("ok")
        return target

    monkeypatch.setattr(pipeline, "run", fake_run)
    c = TestClient(api.app)
    r = c.post("/analyze", files={"demo": ("match_123.dem.bz2", bz2.compress(b"DEMO"))}, follow_redirects=False)
    assert r.status_code == 303
    assert seen["path"].name == "match_123.dem" and seen["data"] == b"DEMO"
    assert [p.name for p in (tmp_path / "demos").iterdir()] == ["match_123.dem"]  # .bz2 entfernt
    bad = c.post("/analyze", files={"demo": ("kaputt.dem.bz2", b"nicht bz2")})
    assert bad.status_code == 400


def test_bz2_size_limit(tmp_path):
    import bz2

    import pytest

    src = tmp_path / "big.dem.bz2"
    src.write_bytes(bz2.compress(b"0" * 5000))
    with pytest.raises(ValueError):
        pipeline.decompress_bz2(src, tmp_path / "big.dem", max_bytes=1000)
    assert not (tmp_path / "big.dem").exists()


def test_demo_stem():
    assert pipeline.demo_stem("a.dem.bz2") == "a"
    assert pipeline.demo_stem("a.DEM") == "a"
    assert pipeline.demo_stem("a.json") == "a"
