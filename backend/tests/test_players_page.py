"""Seite 'Spieler': Spieler aus den Matches wählen, speichern, alles wird für die Auswahl neu berechnet."""

import time

from fastapi.testclient import TestClient
from synth import BRO, ME, build_match

from cstaktik import coaching, config, history, pipeline
from cstaktik.parser.loader import save_match


def test_choose_players_recomputes_everything(tmp_path, monkeypatch):
    import shutil

    shutil.copy(config.CONFIG_DIR / "rules.yaml", tmp_path / "rules.yaml")
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)  # nie die echte players.yaml schreiben
    monkeypatch.setattr(pipeline, "REPORTS_DIR", tmp_path / "reports")
    config.save_focus_steamids([(ME, "Ich")])
    for i in range(2):
        m = build_match(focus=(ME,))
        m.source_sha256 = f"m{i}"
        src = tmp_path / f"m{i}.json"
        save_match(m, src)
        pipeline.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        save_match(m, pipeline.CACHE_DIR / f"m{i}.v{pipeline.CACHE_SCHEMA}.json")
        pipeline.run(src, None, tmp_path / "reports")
    assert all(BRO not in h["players"] for h in history.load_all(pipeline.HISTORY_DIR))

    from cstaktik import api

    c = TestClient(api.app)
    page = c.get("/spieler").text
    assert "Spieler" in page and "wird analysiert" in page
    bro = next(e for e in pipeline.roster() if e["sid"] == BRO)
    assert bro["matches"] == 2 and bro["with_focus"] == 2  # im selben Team wie der Fokus-Spieler

    r = c.post("/spieler", data={"sid": [ME, BRO]}, follow_redirects=False)
    assert r.status_code == 303 and config.load_focus_steamids() == {ME, BRO}
    job = r.headers["location"].rsplit("/", 1)[-1]
    for _ in range(200):
        j = c.get(f"/api/jobs/{job}").json()
        if j["status"] in ("fertig", "fehler"):
            break
        time.sleep(0.05)
    assert j["status"] == "fertig", j
    hs = history.load_all(pipeline.HISTORY_DIR)
    assert all(BRO in h["players"] for h in hs)  # Bruder jetzt überall dabei
    st = coaching.load(pipeline.COACHING_FILE)
    assert set(st["focus_ids"]) == {ME, BRO}
    assert c.post("/spieler", data={}, follow_redirects=False).status_code == 400


def test_more_page_has_guide_and_settings():
    from fastapi.testclient import TestClient

    from cstaktik import api

    t = TestClient(api.app).get("/mehr").text
    assert "So arbeitet der Coach" in t and 'href="/spieler"' in t and 'href="/pro"' in t


def test_fonts_served_once_and_cached(monkeypatch):
    from fastapi.testclient import TestClient

    from cstaktik import api, fonts

    c = TestClient(api.app)
    monkeypatch.setattr(fonts, "font_css", lambda: "@font-face{}")
    r = c.get("/fonts.css")
    assert r.status_code == 200 and "max-age" in r.headers["cache-control"] and r.headers["content-type"].startswith("text/css")
    monkeypatch.setattr(fonts, "font_css", lambda: "")
    assert c.get("/fonts.css").headers["cache-control"] == "no-cache"  # ohne Schriften nicht eine Woche cachen
    home = c.get("/").text
    assert '<link rel="stylesheet" href="/fonts.css">' in home and "@font-face" not in home


def test_matches_list_uses_analysis_date_and_topic(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from cstaktik import api, history, pipeline

    monkeypatch.setattr(pipeline, "REPORTS_DIR", tmp_path / "r")
    monkeypatch.setattr(pipeline, "HISTORY_DIR", tmp_path / "h")
    (tmp_path / "r").mkdir()
    for i, (f, at) in enumerate((("a.html", "2026-10-01T20:00"), ("b.html", "2026-10-03T21:30"))):
        (tmp_path / "r" / f).write_text(f"<title>Mirage {13 - i}:{i} – x</title>")
        history.save({"id": f, "report_file": f, "analyzed_at": at, "map": "de_mirage", "main_lesson": "alone"},
                     tmp_path / "h")
    t = TestClient(api.app).get("/matches").text
    assert "03.10.2026 21:30" in t and "Thema: Nicht ohne Trade-Partner peeken" in t
    assert t.index("03.10.2026") < t.index("01.10.2026")  # neuestes Match zuerst, unabhängig von der Dateizeit
