from pathlib import Path

from fastapi.testclient import TestClient
from synth import ENEMIES, MATES, ME, build_match

from cstaktik import pipeline, pro
from cstaktik.config import load_rules_config
from cstaktik.parser.loader import save_match
from cstaktik.reference import enrich_pro, pro_spots
from cstaktik.rules import analyze


def _pro_match():
    """Pro-Demo-Ersatz: alle CT-Spieler stehen in den Siegrunden 3 und 4 in SynthJungle bzw. SynthB."""
    m = build_match(focus=())
    for p in m.positions:
        p.place = "SynthJungle" if MATES.index(p.steamid) < 3 else "SynthB"
    return m


def test_pro_summary_covers_all_players():
    s = pro.summarize(_pro_match())
    sids = {t["sid"] for t in s["timeline"]}
    assert set(MATES) <= sids and set(ENEMIES) <= sids  # alle 10, nicht nur Fokus
    assert s["map"] == "de_mirage"


def test_pro_spots_distribution_and_minimum(monkeypatch):
    from cstaktik import reference

    s = pro.summarize(_pro_match())
    ps = pro_spots([s, {**s, "id": "2"}], "de_mirage", "ct", 20)
    assert ps["spots"][0] == {"place": "SynthJungle", "pct": 60} and ps["demos"] == 2 and ps["samples"] == 20
    assert pro_spots([s, {**s, "id": "2"}], "de_inferno", "ct", 20) is None  # andere Map
    monkeypatch.setattr(reference, "PRO_MIN_SAMPLES", 11)
    assert pro_spots([s], "de_mirage", "ct", 20) is None  # eine Demo = 10 Samples, zu wenig


def test_enrich_pro_adds_comparison_to_death_review():
    s = pro.summarize(_pro_match())
    m = build_match()
    res = analyze(m, load_rules_config())
    enrich_pro(m, res.findings, [s, {**s, "id": "2"}])
    f = next(f for f in res.findings if f.rule_id == "death_review" and f.round == 2)
    assert f.evidence["pro"].startswith("Pros auf CT in Siegrunden nach 0:20: SynthJungle 60 %")


def test_run_pro_and_upload(tmp_path, monkeypatch):
    from cstaktik import api

    src = tmp_path / "pro.json"
    save_match(_pro_match(), src)
    info = pipeline.run_pro(src)
    assert info["rounds"] == 6 and len(pro.load_all(pipeline.PRO_DIR)) == 1

    monkeypatch.setattr(pipeline, "DEMOS_DIR", tmp_path / "demos")
    monkeypatch.setattr(pipeline, "run_pro", lambda path, progress=None: {
        "map": "de_mirage", "rounds": 24, "players": 10, "nades": 180, "reports": 2})
    c = TestClient(api.app)
    r = c.post("/analyze", files={"demo": ("navi.dem", b"X")}, data={"pro": "1"}, follow_redirects=False)
    import time

    for _ in range(100):
        j = c.get("/api/jobs/" + r.headers["location"].rsplit("/", 1)[1]).json()
        if j["status"] == "fertig":
            break
        time.sleep(0.02)
    assert j["report"] is None and "Pro-Demo gespeichert: Mirage, 24 Runden, 180 Granaten" in j["message"]
    assert "2 eigene Mirage-Reports" in j["message"]
    assert list((tmp_path / "pro_demos").glob("navi*")) and not (tmp_path / "demos").exists()  # getrennt abgelegt
    assert "Pro-Referenz" in c.get("/").text


def test_pro_summary_has_nades_and_deaths():
    from cstaktik.model import GrenadeThrow

    m = _pro_match()
    r = m.rounds[2]
    m.grenades.append(GrenadeThrow(round=r.num, entity_id=1, thrower_steamid=MATES[0], grenade_type="smoke",
                                   kind="smoke", points=[(r.freeze_end_tick + 640, 3000, 3000, 0),
                                                         (r.freeze_end_tick + 700, 3400, 3000, 0)]))
    s = pro.summarize(m)
    assert s["version"] == pro.VERSION
    n = s["nades"][0]
    assert n["side"] == "ct" and n["t"] == 10.0 and n["from"] == "SynthJungle" and n["kind"] == "smoke"
    assert s["deaths"] and {"place", "traded", "first", "side", "t"} <= set(s["deaths"][0])


def _scene_pro(n_rounds=6, util_rounds=4):
    """Handgebaute Pro-Zusammenfassung: CT steht in Siegrunden bei 0:20 in SynthMid."""
    tl = [{"round": r, "sid": "p", "side": "ct", "won": True, "places": [None] * 4 + ["SynthMid"]}
          for r in range(1, n_rounds + 1)]
    nades = [{"r": r, "side": "ct", "won": True, "kind": "molotov", "t": 12.0, "from": "SynthMid", "to": "SynthB",
              "fx": 0, "fy": 0, "tx": 500, "ty": 0} for r in range(1, util_rounds + 1)]
    deaths = [{"r": 1, "side": "ct", "won": False, "t": 30.0, "place": "SynthMid", "first": False,
               "traded": i < 6} for i in range(10)]
    return {"id": "x", "map": "de_mirage", "version": 2, "timeline": tl, "nades": nades, "deaths": deaths}


def test_pro_scene_util_trade_and_lineup_overlay():
    from cstaktik.reference import pro_scene

    sc = pro_scene([_scene_pro()], "de_mirage", "ct", "SynthMid", 20)
    assert sc["rounds"] == 6 and sc["with_util"] == 4 and sc["kinds"] == [("molotov", 4)]
    assert sc["lineup"]["from"] == "SynthMid" and sc["lineup"]["n"] == 4
    assert pro_scene([_scene_pro(n_rounds=4)], "de_mirage", "ct", "SynthMid", 20) is None  # zu wenige Runden

    m = build_match()
    res = analyze(m, load_rules_config())
    enrich_pro(m, res.findings, [_scene_pro()])
    f = next(f for f in res.findings if f.rule_id == "death_review" and f.round == 2)
    assert f.evidence["pro_util"] == ("Pros (CT) in SynthMid um 0:20: in 4 von 6 Siegrunden kam vorher "
                                      "Utility von dort (Molotov 4).")
    assert "Molotov aus SynthMid nach SynthB (4x)" in f.evidence["pro_lineup"]
    assert f.evidence["pro_trade"] == "Pros, die in SynthMid sterben (CT), werden zu 60 % getradet (10 Tode)."
    assert f.overlay["pro_nade"] == {"kind": "molotov", "xy": [0, 0, 500, 0]}


def test_upgrade_old_pro_and_rerender_reports(tmp_path, monkeypatch):
    import json

    from cstaktik import history

    m = _pro_match()
    m.source_sha256 = "abc123"
    save_match(m, pipeline.CACHE_DIR / f"abc123.v{pipeline.CACHE_SCHEMA}.json")
    old = {"id": "abc123", "map": "de_mirage", "rounds": 6, "timeline": [], "analyzed_at": "2026-01-01T10:00"}
    pro.save(old, pipeline.PRO_DIR)
    assert pipeline.upgrade_pro() == 1
    d = pro.load_all(pipeline.PRO_DIR)[0]
    assert d["version"] == pro.VERSION and "nades" in d and d["analyzed_at"] == "2026-01-01T10:00"
    assert pipeline.upgrade_pro() == 0

    # eigenes Match im Verlauf mit Cache -> Report wird neu gebaut, Ziel-Check bleibt
    own = build_match()
    own.source_sha256 = "own1"
    save_match(own, pipeline.CACHE_DIR / f"own1.v{pipeline.CACHE_SCHEMA}.json")
    monkeypatch.setattr(pipeline, "REPORTS_DIR", tmp_path / "reports")
    (tmp_path / "reports").mkdir()
    history.save({"id": "own1", "map": "de_mirage", "report_file": "own1.html", "analyzed_at": "x",
                  "goal_check": {"checks": [], "new": [], "active": []}}, pipeline.HISTORY_DIR)
    assert pipeline.rerender_reports({"de_inferno"}) == 0
    assert pipeline.rerender_reports({"de_mirage"}) == 1
    assert (tmp_path / "reports" / "own1.html").exists()
    assert json.loads(next(pipeline.HISTORY_DIR.glob("*.json")).read_text())["analyzed_at"] == "x"
