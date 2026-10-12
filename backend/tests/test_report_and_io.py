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


def _embedded(html):
    import json

    raw = re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S).group(1)
    return json.loads(raw)


def test_report_is_selfcontained_and_mobile(tmp_path):
    m = build_match()
    html = render_report(m, analyze(m, load_rules_config()), maps_dirs=[tmp_path])
    assert 'name="viewport"' in html
    assert not re.search(r'(src|href)="https?://', html)  # keine externen Ressourcen
    assert "Kein Radarbild" in html  # ohne Radar-Dateien ehrlich melden
    data = _embedded(html)
    assert data["img"] is None and len(data["rounds"]) == 6
    assert data["floor"]["cells"]  # Kartenumriss aus Laufwegen
    r2 = next(r for r in data["rounds"] if r["n"] == 2)
    assert r2["out"] == "L" and r2["tracks"] and r2["kills"]
    titles = {data["findings"][i]["title"] for i in r2["f"]}
    assert {"Tod: Allein, kein Trade", "Uneinheitlicher Kauf"} <= titles
    review = next(data["findings"][i] for i in r2["f"] if data["findings"][i]["rule"] == "death_review")
    assert review["x"] is not None  # Coach-Marker sitzt am Todesort
    assert review["ov"]["line"] and review["evidence"]["ungenutzt"] == ["Flashbang", "Smoke Grenade"]


def test_embedded_json_cannot_break_out_of_script(tmp_path):
    m = build_match()
    m.players[0].name = "</script><img src=x onerror=alert(1)>"
    html = render_report(m, analyze(m, load_rules_config()), maps_dirs=[tmp_path])
    assert "</script><img" not in html
    assert _embedded(html)["players"][m.players[0].steamid]["name"].startswith("</script>")


def test_report_uses_radar_files_when_present(tmp_path):
    import json

    (tmp_path / "de_mirage.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    (tmp_path / "map-data.json").write_text(json.dumps({"de_mirage": {"pos_x": -1000, "pos_y": 1000, "scale": 5}}))
    m = build_match()
    html = render_report(m, analyze(m, load_rules_config()), maps_dirs=[tmp_path])
    data = _embedded(html)
    assert data["img"].startswith("data:image/png;base64,") and "Kein Radarbild" not in html
    assert data["floor"] is None
    # Welt (0,0) -> Pixel ((0+1000)/5, (1000-0)/5)
    k = next(k for r in data["rounds"] for k in r["kills"] if k["vx"] is not None)
    assert (k["vx"], k["vy"]) == (200.0, 200.0)


def test_places_from_demo_positions(tmp_path):
    from cstaktik.report.render import PLACE_MIN_SAMPLES

    m = build_match()
    for i, p in enumerate(m.positions):
        p.place = "SynthMid" if i % 2 else None
    data = _embedded(render_report(m, analyze(m, load_rules_config()), maps_dirs=[tmp_path]))
    assert [p["n"] for p in data["places"]] == ["SynthMid"]
    m.positions = m.positions[: PLACE_MIN_SAMPLES]  # zu wenige Samples -> kein Label
    data = _embedded(render_report(m, analyze(m, load_rules_config()), maps_dirs=[tmp_path]))
    assert data["places"] == []


def test_valve_overview_txt_calibration(tmp_path):
    from cstaktik.report.radar import build_radar

    (tmp_path / "de_mirage_radar.png").write_bytes(b"x")
    (tmp_path / "de_mirage.txt").write_text('"de_mirage"\n{\n "pos_x" "-3230"\n "pos_y" "1713"\n "scale" "5.00"\n}')
    r = build_radar(build_match(), [tmp_path])
    assert (r.pos_x, r.pos_y, r.scale) == (-3230.0, 1713.0, 5.0) and r.image_data_uri


def test_cli_analyze_json(tmp_path, monkeypatch):
    from cstaktik.cli import main
    from synth import BRO, ME

    src = tmp_path / "match.json"
    save_match(build_match(focus=()), src)
    out = tmp_path / "out"
    assert main(["analyze", str(src), "--me", ME, "--me", BRO, "--out", str(out)]) == 0
    assert (out / "match.html").exists()


def _finish(client, location):
    import time

    job_id = location.rsplit("/", 1)[1]
    for _ in range(100):
        r = client.get(f"/api/jobs/{job_id}").json()
        if r["status"] in ("fertig", "fehler"):
            return r
        time.sleep(0.02)
    raise AssertionError("Job wurde nicht fertig")


def test_api_upload(tmp_path, monkeypatch):
    from cstaktik import api

    monkeypatch.setattr(pipeline, "DEMOS_DIR", tmp_path / "demos")
    monkeypatch.setattr(pipeline, "REPORTS_DIR", api.pipeline.REPORTS_DIR)

    def fake_run(path: Path, focus=None, out_dir=None, progress=None):
        progress("Demo parsen", 0.5)
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
    assert r.status_code == 303 and r.headers["location"].startswith("/jobs/")
    page = c.get(r.headers["location"])
    assert page.status_code == 200 and "Auswertung läuft" in page.text
    done = _finish(c, r.headers["location"])
    assert done["status"] == "fertig" and done["report"] == "x.html"
    assert [p.name for p in (tmp_path / "demos").iterdir()] == ["b_se_name.dem"]
    assert c.post("/analyze", files={"demo": ("a.txt", b"x")}).status_code == 400


def test_api_upload_bz2(tmp_path, monkeypatch):
    import bz2

    from cstaktik import api

    monkeypatch.setattr(pipeline, "DEMOS_DIR", tmp_path / "demos")
    seen = {}

    def fake_run(path: Path, focus=None, out_dir=None, progress=None):
        seen["path"], seen["data"] = path, path.read_bytes()
        target = tmp_path / "x.html"
        target.write_text("ok")
        return target

    monkeypatch.setattr(pipeline, "run", fake_run)
    c = TestClient(api.app)
    r = c.post("/analyze", files={"demo": ("match_123.dem.bz2", bz2.compress(b"DEMO"))}, follow_redirects=False)
    assert r.status_code == 303
    _finish(c, r.headers["location"])
    assert seen["path"].name == "match_123.dem" and seen["data"] == b"DEMO"
    assert [p.name for p in (tmp_path / "demos").iterdir()] == ["match_123.dem"]  # .bz2 entfernt
    bad = c.post("/analyze", files={"demo": ("kaputt.dem.bz2", b"nicht bz2")}, follow_redirects=False)
    failed = _finish(c, bad.headers["location"])
    assert failed["status"] == "fehler" and "bz2" in failed["error"]
    assert c.get("/jobs/unbekannt").status_code == 404
    assert c.get("/api/jobs/unbekannt").status_code == 404


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


def test_estimate_from_recorded_timings(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "TIMINGS_FILE", tmp_path / "t.json")
    assert pipeline.estimate_seconds(100 * 1024**2) is None  # ohne Messung keine Schätzung
    pipeline._record_timing(50 * 1024**2, 25.0)  # 0.5 s/MB
    pipeline._record_timing(100 * 1024**2, 100.0)  # 1.0 s/MB
    pipeline._record_timing(10 * 1024**2, 6.0)  # 0.6 s/MB
    assert pipeline.estimate_seconds(200 * 1024**2) == 120.0  # Median 0.6 s/MB
    assert pipeline.timing_samples() == 3


def test_index_lists_reports_with_score(tmp_path, monkeypatch):
    from cstaktik import api

    monkeypatch.setattr(pipeline, "REPORTS_DIR", tmp_path)
    m = build_match()
    (tmp_path / "match.html").write_text(render_report(m, analyze(m, load_rules_config()), maps_dirs=[]))
    html = TestClient(api.app).get("/").text
    assert "Mirage" in html and 'href="/reports/match.html"' in html


def test_nade_kind_and_thin_path():
    from cstaktik.parser.awpy_adapter import nade_kind, thin_path

    assert nade_kind("CSmokeGrenadeProjectile") == "smoke"
    assert nade_kind("Flashbang") == "flash"
    assert nade_kind("Incendiary Grenade") == "molotov"
    assert nade_kind("molotov") == "molotov"
    assert nade_kind("hegrenade") == "he"
    assert nade_kind("Decoy Grenade") == "decoy"
    assert nade_kind("irgendwas") == "other"  # nicht raten
    pts = [(t, float(t), 0.0, 0.0) for t in range(0, 20)] + [(t, 19.0, 0.0, 0.0) for t in range(20, 200)]
    thin = thin_path(pts, 4)
    assert thin[0][0] == 0 and thin[-1][0] == 199  # Start und Ende bleiben
    assert len(thin) < 12  # Stillstand zusammengefasst


def test_report_contains_grenade_paths_and_effects(tmp_path):
    from cstaktik.model import GrenadeThrow, UtilityArea, Vec

    m = build_match()
    r2 = m.round_by_num(2)
    t = r2.freeze_end_tick
    m.grenades.append(GrenadeThrow(round=2, entity_id=7, thrower_steamid=m.players[0].steamid, grenade_type="smokegrenade",
                                   kind="smoke", points=[(t, 0, 0, 0), (t + 32, 200, 100, 50), (t + 64, 300, 100, 0)]))
    m.utility.append(UtilityArea(round=2, kind="smoke", start_tick=t + 64, end_tick=t + 64 + 18 * 64, pos=Vec(x=300, y=100)))
    m.utility.append(UtilityArea(round=2, kind="flash", start_tick=t + 10, end_tick=t + 10, pos=Vec(x=0, y=0)))
    data = _embedded(render_report(m, analyze(m, load_rules_config()), maps_dirs=[tmp_path]))
    r = next(r for r in data["rounds"] if r["n"] == 2)
    assert r["nades"][0]["k"] == "smoke" and len(r["nades"][0]["pts"]) == 3
    assert {u["k"] for u in r["util"]} == {"smoke", "flash"}
    assert data["rSmoke"] > 0 and data["rMolly"] > 0


def test_payload_has_weapons_shots_and_hits(tmp_path):
    from synth import ENEMIES, ME

    from cstaktik.model import Damage, Shot

    m = build_match()
    for p in m.positions:
        p.weapon = "M4A1-S"
    t = m.round_by_num(2).freeze_end_tick + 640
    m.shots = [Shot(round=2, tick=t, steamid=ME, weapon="weapon_m4a1_silencer", speed=0),
               Shot(round=2, tick=t + 1, steamid=ME, weapon="weapon_knife", speed=0)]
    m.damages = [Damage(round=2, tick=t, attacker_steamid=ME, victim_steamid=ENEMIES[0], dmg=27, weapon="m4a1_silencer")]
    data = _embedded(render_report(m, analyze(m, load_rules_config()), maps_dirs=[tmp_path]))
    r2 = next(r for r in data["rounds"] if r["n"] == 2)
    assert len(r2["shots"]) == 1 and data["weapons"][r2["shots"][0][2]] == "m4a1_silencer"  # Messer ausgeblendet
    assert r2["hurts"] == [[t, ME, ENEMIES[0], 27]]
    assert data["weapons"][r2["tracks"][ME][0][4]] == "M4A1-S"


def test_nade_lands_at_detonation_and_unknown_end_is_capped():
    from synth import build_match

    from cstaktik.config import load_rules_config
    from cstaktik.model import GrenadeThrow, UtilityArea, Vec
    from cstaktik.report.render import build_payload
    from cstaktik.rules import analyze

    m = build_match()
    r = m.rounds[1]
    f0 = r.freeze_end_tick
    thr = m.players[0].steamid
    # Projektil liegt nach der Landung noch 18 s (Smoke-Entity), Detonation bei +100
    pts = [(f0 + i * 4, 100.0 + i, 100.0, 0.0) for i in range(25)] + [(f0 + 100 + 64 * 18, 124.0, 100.0, 0.0)]
    m.grenades.append(GrenadeThrow(round=r.num, entity_id=9, thrower_steamid=thr, grenade_type="Smoke Grenade",
                                   kind="smoke", points=pts))
    m.utility.append(UtilityArea(round=r.num, kind="smoke", start_tick=f0 + 100, end_tick=r.end_tick,
                                 end_known=False, thrower_steamid=thr, pos=Vec(x=124, y=100)))
    d = build_payload(m, analyze(m, load_rules_config()))
    rr = next(x for x in d["rounds"] if x["n"] == r.num)
    assert rr["nades"][-1]["land"] == f0 + 100
    u = rr["util"][-1]
    assert u["e"] == f0 + 100 + 18 * m.tickrate and u["ek"] is False
