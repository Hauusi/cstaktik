"""Kurs: Einstufung aus den eigenen Matches, aktuelle Lektion = Auftrag, Lektionsseite, je Spieler getrennt."""

import re

from fastapi.testclient import TestClient
from synth import BRO, ME

from cstaktik import accounts, api, coaching, course, course_texts, history, pipeline

O = {"Origin": "http://testserver"}


def _m(mid, lessons, rounds=20, sid="a", at=None):
    return {"id": mid, "analyzed_at": at or f"2026-10-0{mid[-1]}T20:00", "rounds": rounds, "map": "de_mirage",
            "players": {sid: {"name": sid, "rounds": rounds}}, "lessons": {sid: lessons}}


def test_placement_statuses_and_path_order():
    hist = [_m("m1", {"utility": 4, "crosshair": 3, "alone": 1}), _m("m2", {"utility": 4, "crosshair": 2, "alone": 1})]
    pl = course.placement(hist, "a")
    # 40 Runden: Utility 2,0 > 1,5 und Fadenkreuz 1,25 > 1,0 sind Baustellen; allein 0,5 sitzt
    assert pl["utility"]["status"] == pl["crosshair"]["status"] == "baustelle"
    # gute Werte aus nur 40 Runden: noch nicht "sitzt", erst ab settle_rounds (etwa drei Matches)
    assert pl["alone"]["status"] == "offen" and pl["moving_shot"]["status"] == "offen"
    three = hist + [_m("m3", {"utility": 4, "crosshair": 2, "alone": 1})]
    assert course.placement(three, "a")["alone"]["status"] == "sitzt"
    assert pl["utility"]["rate"] == 2.0 and pl["utility"]["n"] == 8 and pl["utility"]["rounds"] == 40
    # Grundlagen zuerst: Fadenkreuz (Schießen) vor Utility (Granaten), obwohl Utility häufiger ist
    assert course.baustellen(hist, "a") == ["crosshair", "utility"]
    assert course.current(None, pl) == "crosshair"
    # laufender Auftrag bleibt die aktuelle Lektion, auch wenn eine frühere Baustelle offen ist
    assert course.current({"focus": {"lesson": "utility"}}, pl) == "utility"
    # zu wenig Runden: noch offen, auch bei vielen Fehlern
    short = course.placement([_m("m1", {"utility": 5}, rounds=12)], "a")
    assert short["utility"]["status"] == "offen" and short["moving_shot"]["status"] == "offen"
    # hohe Rate, aber unter goals.min_count Vorkommen: noch offen statt Baustelle
    few = course.placement([_m("m1", {"blind": 2}, rounds=20)], "a", {**course.settings(), "max_per_10": 0.5})
    assert few["blind"]["status"] == "offen"
    # nur die letzten window_matches Matches zählen
    old = [_m(f"m{i}", {"utility": 9}) for i in range(1, 3)] + [_m(f"m{i}", {}) for i in range(3, 8)]
    assert course.placement(old, "a")["utility"]["status"] == "sitzt"


def test_new_focus_follows_course_order_and_mastery_moves_on():
    past = [_m("m1", {"utility": 6, "moving_shot": 3})]
    s2 = _m("m2", {"utility": 6, "moving_shot": 3})
    st = {"players": {}}
    tops, ok = course.plan_for(s2, past)
    assert tops["a"] == ["moving_shot", "utility"]
    res = coaching.update_all(st, s2, tops, past=past, settled=ok)
    assert res["a"]["focus"]["lesson"] == "moving_shot"  # erste Baustelle im Pfad, nicht der häufigste Fehler
    hist = past + [s2]
    for mid in ("m3", "m4"):  # zweimal sauber, genug Runden
        s = _m(mid, {"utility": 6}, rounds=22)
        tops, ok = course.plan_for(s, hist)
        res = coaching.update_all(st, s, tops, past=hist, settled=ok)
        hist.append(s)
    assert res["a"]["mastered"] == "moving_shot" and res["a"]["focus"]["lesson"] == "utility"
    slot = st["players"]["a"]
    assert slot["done"][-1]["status"] == "gemeistert"
    ov = course.overview(hist, "a", slot)
    rows = {r["id"]: r for stg in ov["stages"] for r in stg["lessons"]}
    assert rows["moving_shot"]["status"] == "geschafft" and rows["utility"]["status"] == "aktuell"
    assert ov["done"] == 1 and ov["current"]["id"] == "utility" and ov["total"] == len(course_texts.LESSONS)


def test_running_focus_that_now_sits_hands_over():
    first = {"match": "m2", "date": "2026-10-02T20:00", "rate": 0.5, "count": 1, "rounds": 20, "met": False}
    st = {"focus": {"lesson": "alone", "target": 0.4, "baseline": 2.0, "created_at": "2026-10-01T00:00",
                    "created_from": "m0", "matches": [first], "status": "aktiv"}, "done": [], "drills": []}
    hist = [_m("m1", {"alone": 1, "crosshair": 4}), _m("m2", {"alone": 1, "crosshair": 4})]
    s3 = _m("m3", {"alone": 1, "crosshair": 4})
    tops, ok = course.plan_for(s3, hist)
    assert "alone" in ok["a"]
    res = coaching.update(st, s3, tops["a"], sid="a", past=hist, settled=ok["a"])
    # Ziel 0,4 zweimal knapp verfehlt, aber laut Kurs sitzt die Lektion: weiter zur nächsten Baustelle, nicht "gemeistert"
    assert res["settled"] == "alone" and res["mastered"] is None and res["focus"]["lesson"] == "crosshair"
    assert st["done"][-1]["status"] == "sitzt"
    ov = course.overview(hist + [s3], "a", st)
    assert ov["done"] == 0  # "sitzt" zählt nicht als geschafft


def _setup_two_players():
    pipeline.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    sc = {"lesson": "crosshair", "lessons": ["crosshair"], "sid": ME, "round": 7, "tick": 900, "from": 800, "cost": 30,
          "happened": "Bei 1:05 gewinnt g1 aus A-Site das Duell. Du triffst nicht. Dein Fadenkreuz lag 40° neben ihm.",
          "snap": {"secs": 50, "place": "PalaceInterior"},
          "pro_clip": "Pro (T) in Palace bei 1:05. Der Gegner kam wie bei dir aus A-Site. Runde gewonnen: überlebt."}
    for i, (n_me, n_bro) in enumerate(((4, 0), (3, 0)), start=1):
        history.save({"id": f"k{i}", "map": "de_mirage", "rounds": 22, "analyzed_at": f"2026-10-0{i}T20:00",
                      "report_file": f"k{i}.html", "players": {ME: {"name": "Ich", "rounds": 22},
                                                                BRO: {"name": "Bruder", "rounds": 22}},
                      "lessons": {ME: {"crosshair": n_me}, BRO: {"utility": 5 + n_bro}},
                      "scenes": [sc, {**sc, "sid": BRO, "lesson": "utility", "lessons": ["utility"], "round": 9,
                                      "happened": "Bruder-Szene."}]}, pipeline.HISTORY_DIR)
        (pipeline.REPORTS_DIR / f"k{i}.html").write_text("<html><head><title>x</title></head></html>")
    coaching.save({"players": {ME: {"focus": {"lesson": "crosshair", "target": 1.0, "baseline": 1.6, "matches": [
        {"match": "k2", "rate": 1.4, "count": 3, "rounds": 22, "met": False}], "created_at": "2026-10-01T20:00",
        "status": "aktiv"}, "done": [], "drills": []}}}, pipeline.COACHING_FILE)


def test_lesson_page_five_parts_in_sentences():
    _setup_two_players()
    c = TestClient(api.app)
    page = c.get(f"/kurs/crosshair?p={ME}").text
    parts = re.findall(r'data-part="([a-z-]+)"', page)
    assert parts == ["verstehen", "bei-dir", "pros", "ueben", "pruefen"]
    t = course.texts("crosshair")
    assert t["title"] in page and "Das ist deine aktuelle Lektion" in page
    # Bei dir: eigene Szene mit Ort und Uhr als Satz, Sprung ins Replay
    assert "Runde 7 auf Mirage, bei 1:05 auf der Uhr in Palace." in page
    assert 'href="/reports/k2.html#s7-800"' in page and "Bruder-Szene" not in page
    # Bei den Pros: nur weil die Szene einen Pro-Vergleich hat
    assert "Dieselbe Lage in einer Pro-Demo" in page and "Im Report mit Pro-Lösung ansehen" in page
    # Üben: Übung mit Haken für genau diese Lektion
    assert f'action="/training/done?p={ME}&lesson=crosshair&back=kurs"' in page
    # Prüfen: Verlauf je Match und ganze Sätze gegen das Ziel
    assert "Im letzten Match auf Mirage kam der Fehler 3 Mal in 22 Runden vor, erlaubt waren höchstens 2." in page
    assert "Die Lektion ist geschafft, wenn du das Ziel in 2 Matches in Folge erreichst." in page
    assert c.get("/kurs/gibtsnicht").status_code == 404
    # andere Lektion ohne Pro-Daten: Teil 3 fällt weg, Status als Satz
    other = c.get(f"/kurs/moving_shot?p={ME}").text
    assert re.findall(r'data-part="([a-z-]+)"', other) == ["verstehen", "bei-dir", "ueben", "pruefen"]
    assert "Bisher sieht es hier gut aus" in other and "nach etwa drei Matches" in other


def test_lesson_drill_tick_and_per_player_isolation():
    _setup_two_players()
    for u, sid in (("Hausi", ME), ("Bruder", BRO)):
        accounts.add_user(u, "Geheim-12345")
        accounts.link_steamid(u, sid)
    b = TestClient(api.app)
    b.post("/login", data={"name": "Bruder", "password": "Geheim-12345"}, headers=O)
    page = b.get(f"/kurs/crosshair?p={ME}").text  # fremder Spieler per Parameter: trotzdem nur der eigene
    assert "Runde 7 auf Mirage" not in page and "Das ist deine aktuelle Lektion" not in page
    home = b.get("/").text
    assert re.search(r'href="/kurs/utility"><span class="lt">[^<]+</span><span class="chip aktuell">', home)
    assert b.post(f"/training/done?p={ME}&lesson=crosshair&back=kurs", headers=O).status_code == 403
    r = b.post(f"/training/done?p={BRO}&lesson=utility&back=kurs", headers=O, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/kurs/utility?p={BRO}&ok=1#ueben"
    st = coaching.load(pipeline.COACHING_FILE)["players"]
    assert [d["lesson"] for d in st[BRO]["drills"]] == ["utility"] and st[ME]["drills"] == []
    assert "Eingetragen." in b.get(r.headers["location"]).text
