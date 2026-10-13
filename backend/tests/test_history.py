import json

from fastapi.testclient import TestClient
from synth import BRO, ME, build_match

from cstaktik import history, pipeline
from cstaktik.config import load_rules_config
from cstaktik.parser.loader import save_match
from cstaktik.report.progress import build, render_progress
from cstaktik.rules import analyze


def _summary(m, when):
    s = history.summarize(m, analyze(m, load_rules_config()), "r.html")
    s["analyzed_at"] = when
    return s


def test_summary_contains_only_demo_derived_data():
    m = build_match()
    s = history.summarize(m, analyze(m, load_rules_config()), "x.html")
    assert (s["won"], s["lost"], s["rounds"]) == (3, 3, 6)
    assert set(s["players"]) == {ME, BRO}
    assert s["issues"][ME]["Gleicher Todesort"] == 3  # Muster zählt seine Runden
    assert len(s["deaths"]) == 3 and all(d["sid"] == ME for d in s["deaths"])
    assert s["floor"]


def test_save_keeps_first_date_and_load_sorted(tmp_path):
    m = build_match()
    a = _summary(m, "2026-10-10T20:00")
    history.save(a, tmp_path)
    again = _summary(m, "2026-10-12T09:00")
    history.save(again, tmp_path)  # gleiche Demo -> Datum bleibt
    other = {**_summary(m, "2026-10-11T20:00"), "id": "zweite"}
    history.save(other, tmp_path)
    loaded = history.load_all(tmp_path)
    assert [h["analyzed_at"] for h in loaded] == ["2026-10-10T20:00", "2026-10-11T20:00"]


def test_trend_needs_enough_matches_and_detects_improvement():
    m = build_match()
    hs = []
    for i, n in enumerate([4, 4, 1, 1]):
        s = _summary(m, f"2026-10-0{i + 1}T20:00")
        s["id"] = str(i)
        s["issues"][ME] = {"Tod: Allein, kein Trade": n}
        hs.append(s)
    p = next(p for p in build(hs)["players"] if p["sid"] == ME)
    it = next(i for i in p["issues"] if i["title"] == "Tod: Allein, kein Trade")
    assert it["trend"]["state"] == "besser" and it["total"] == 10
    few = next(p for p in build(hs[:2])["players"] if p["sid"] == ME)
    assert next(i for i in few["issues"] if i["title"] == "Tod: Allein, kein Trade")["trend"]["state"] == "wenig"


def test_run_writes_history_and_progress_route(tmp_path, monkeypatch):
    from cstaktik import api

    src = tmp_path / "match.json"
    save_match(build_match(focus=()), src)
    pipeline.run(src, {ME, BRO}, tmp_path / "out")
    files = list(pipeline.HISTORY_DIR.glob("*.json"))
    assert len(files) == 1 and json.loads(files[0].read_text())["report_file"] == "match.html"
    page = TestClient(api.app).get("/progress")
    assert page.status_code == 200 and "Fortschritt" in page.text and "Ich" in page.text
    assert "Noch keine Matches" in render_progress([])


def test_progress_lessons_per_map_and_trend():
    from cstaktik.report.progress import _lessons

    hs = []
    for i, m in enumerate(["de_mirage", "de_inferno", "de_mirage", "de_mirage"]):
        hs.append({"id": str(i), "map": m, "rounds": 20, "players": {"a": {"name": "A"}},
                   "lessons": {"a": {"alone": 4 - i, "duel": 9}}})
    hs.insert(0, {"id": "alt", "map": "de_mirage", "rounds": 20, "players": {"a": {"name": "A"}}})  # ohne Lektionen
    ls = _lessons(hs, "a")
    assert [l["id"] for l in ls] == ["alone"]  # "duel" zählt nicht als Baustelle
    l = ls[0]
    assert l["rates"] == [None, 2.0, 1.5, 1.0, 0.5] and l["total"] == 10
    assert l["by_map"]["de_mirage"] == {"rate": 1.2, "count": 7, "rounds": 60}
    assert l["trend"]["state"] == "besser"
