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
        s["players"][ME]["rounds"] = 24  # Trend braucht genug Runden je Seite
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
    h = json.loads(files[0].read_text())
    assert h["clutch"] == []  # Synth-Match hat keinen Clutch, Feld ist trotzdem da (kein Nachrüsten nötig)
    h["impact"] = {ME: {"total": 120, "kill": 300, "death": -180, "plant": 0, "defuse": 0, "rank": 2, "of": 10}}
    h["clutch"] = [{"sid": ME, "side": "t", "vs": 2, "planted": False, "won": True, "kills": 2, "alive": True,
                    "plant": True}]
    files[0].write_text(json.dumps(h))
    page = TestClient(api.app).get(f"/progress?p={ME}").text
    assert "Clutch · als Letzter übrig" in page and "1 gegen 2" in page and "Du 1 von 1" in page
    assert "Punkte Siegchance je Runde" in page
    assert "Tilt-Check" in page and h["seq"]  # seq kommt aus summarize


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
    # 7x in 40 Runden -> 3x in 40 Runden liegt im üblichen Schwanken: kein Trend behaupten
    assert l["trend"]["state"] == "gleich" and "7x in 40 Runden → 3x in 40 Runden" in l["trend"]["text"]


def test_profile_pools_duels_and_lists_lessons():
    from cstaktik.report.progress import profile

    hs = [{"id": str(i), "map": "de_mirage", "rounds": 20, "won": 13, "lost": 7, "analyzed_at": f"2026-10-0{i + 1}T20:00",
           "players": {"a": {"name": "A", "rounds": 20}}, "lessons": {"a": {"alone": 3}},
           "duel_stats": {"a": {"n": 10 * (i + 1), "err": 4.0 + i, "err_n": 10 * (i + 1), "first_hit": 30, "hit_n": 10,
                                "shot_first": 50, "first_n": 10, "react": 200, "react_n": 5, "won": 50}}}
          for i in range(3)]
    p = profile(hs, "a", {"err": 5.0, "first_hit": 30, "shot_first": 59, "react": 250})
    d = p["duels"]
    assert d["n"] == 60 and d["matches"] == 3 and d["err"] == round((4 * 10 + 5 * 20 + 6 * 30) / 60, 1)
    assert d["react"] == 200 and p["lessons"][0]["id"] == "alone" and p["maps"][0]["won"] == 3
    assert p["reading"] and p["reading"].startswith("Dein Zielen ist auf Pro-Niveau")
