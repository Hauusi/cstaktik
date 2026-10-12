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
    monkeypatch.setattr(pipeline, "run_pro", lambda path, progress=None: {"map": "de_mirage", "rounds": 24, "players": 10})
    c = TestClient(api.app)
    r = c.post("/analyze", files={"demo": ("navi.dem", b"X")}, data={"pro": "1"}, follow_redirects=False)
    import time

    for _ in range(100):
        j = c.get("/api/jobs/" + r.headers["location"].rsplit("/", 1)[1]).json()
        if j["status"] == "fertig":
            break
        time.sleep(0.02)
    assert j["report"] is None and "Pro-Demo gespeichert: Mirage, 24 Runden" in j["message"]
    assert "Pro-Referenz" in c.get("/").text
