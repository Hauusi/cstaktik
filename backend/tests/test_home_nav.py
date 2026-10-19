"""Startseite mit einem roten Faden (neues Match, Fokus), drei Tabs plus Einstellungen, Fortschritt mit Details."""

import re

from fastapi.testclient import TestClient
from synth import BRO, ME

from cstaktik import accounts, api, coaching, history, pipeline
from cstaktik.coach_voice import LESSONS
from cstaktik.curriculum import TEACH

O = {"Origin": "http://testserver"}
FOCUS = {"lesson": "utility", "target": 1.0, "baseline": 2.0, "created_at": "2026-01-01T10:00",
         "matches": [{"match": "m0", "date": "2026-01-02T10:00", "map": "de_mirage", "rate": 0.8, "count": 2,
                      "rounds": 24, "met": True}], "status": "aktiv"}


def _entry(mid, at):
    pipeline.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    history.save({"id": mid, "map": "de_mirage", "rounds": 20, "analyzed_at": at, "report_file": f"{mid}.html",
                  "won": 13, "lost": 7, "players": {ME: {"name": "Ich"}}, "score_by": {ME: [13, 7]},
                  "impact": {ME: {"total": 250, "rank": 2, "of": 10}}, "scenes": []}, pipeline.HISTORY_DIR)
    (pipeline.REPORTS_DIR / f"{mid}.html").write_text("<html><head><title>x</title></head></html>")


def _focus():
    coaching.save({"players": {ME: {"focus": FOCUS, "done": [{**FOCUS, "lesson": "alone", "status": "gemeistert"}],
                                    "drills": []}}}, pipeline.COACHING_FILE)


def _login():
    accounts.add_user("Hausi", "Geheim-12345")
    accounts.link_steamid("Hausi", ME)
    c = TestClient(api.app)
    c.post("/login", data={"name": "Hausi", "password": "Geheim-12345"}, headers=O)
    return c


def test_home_is_the_course_new_match_lesson_and_path():
    from cstaktik import course_texts

    _entry("m1", "2999-01-01T10:00")
    _entry("m2", "2999-01-02T10:00")
    _focus()
    home = _login().get("/").text
    blocks = re.findall(r'data-block="([a-z-]+)"', home)
    assert blocks == ["new", "lesson", "path"]  # neues Match, aktuelle Lektion, Lernpfad
    assert "2 neue Matches" in home and 'href="/m/m2.html"' in home and 'href="/m/m1.html"' not in home
    # aktuelle Lektion = laufender Auftrag, mit Fortschritt als Satz und Knopf zur Lektion
    assert "Deine aktuelle Lektion" in home and course_texts.LESSONS["utility"]["title"] in home
    assert "1 von 2 Matches in Folge geschafft." in home and 'href="/kurs/utility"' in home and "Lektion öffnen" in home
    # Lernpfad: alle Stufen und Lektionen, jede antippbar, mit Status
    for st in course_texts.STAGES:
        assert st["title"] in home
    for lid in course_texts.LESSONS:
        assert f'href="/kurs/{lid}"' in home
    path = home[home.index('data-block="path"'):]
    assert re.search(r'href="/kurs/alone"><span class="lt">[^<]+</span><span class="chip geschafft">geschafft', path)
    assert re.search(r'href="/kurs/utility"><span class="lt">[^<]+</span><span class="chip aktuell">aktuell', path)
    assert "Du hast <b class=\"num\">1 von 12</b> Lektionen geschafft." in home
    # kleine Links bleiben, der Rest ist weg
    assert 'href="/training#vorbereitung"' in home and 'href="/training#tools"' in home
    body = re.sub(r"<style>.*?</style>|<script>.*?</script>", "", home, flags=re.S)  # nur sichtbarer Inhalt
    for gone in ("Größter Hebel", "/briefing/", "Situations-Training", "Heute ·", "Auftrag", "Wochenplan", "Thema:",
                 "Dein Fokus fürs nächste Match", "Letztes Match", "·"):
        assert gone not in body, gone
    assert "Demo selbst hochladen" in home


def test_home_without_new_match_shows_lesson_and_path():
    _entry("m1", "2026-01-01T10:00")  # vor dem ersten Login: gilt als gesehen
    _focus()
    home = _login().get("/").text
    assert re.findall(r'data-block="([a-z-]+)"', home) == ["lesson", "path"]
    assert 'href="/m/' not in home


def test_home_course_per_player_isolated():
    """Jeder Bruder sieht seinen eigenen Kurs: eigene aktuelle Lektion, eigener Stand."""
    _entry("m1", "2026-01-01T10:00")
    coaching.save({"players": {ME: {"focus": FOCUS, "done": [], "drills": []},
                               BRO: {"focus": {**FOCUS, "lesson": "crosshair", "matches": []}, "done": [],
                                     "drills": []}}}, pipeline.COACHING_FILE)
    me = _login().get("/").text
    assert 'class="cur"' in me and 'href="/kurs/utility"' in me
    assert re.search(r'href="/kurs/crosshair"><span class="lt">[^<]+</span><span class="chip offen">', me)
    accounts.add_user("Bruder", "Geheim-12345")
    accounts.link_steamid("Bruder", BRO)
    b = TestClient(api.app)
    b.post("/login", data={"name": "Bruder", "password": "Geheim-12345"}, headers=O)
    bro = b.get("/").text
    assert re.search(r'href="/kurs/crosshair"><span class="lt">[^<]+</span><span class="chip aktuell">', bro)
    assert "1 von 2 Matches in Folge geschafft." not in bro


def test_nav_has_three_tabs_and_settings_icon():
    for path in ("/", "/matches", "/progress", "/training", "/mehr"):
        page = TestClient(api.app).get(path).text
        nav = re.search(r'<nav class="gnav".*?</nav>', page, re.S).group(0)
        tabs = re.findall(r'<a href="([^"]+)"[^>]*>.*?</svg>([^<]+)</a>', nav, re.S)
        assert tabs == [("/", "Kurs"), ("/matches", "Matches"), ("/progress", "Fortschritt")], path
        assert 'href="/mehr" aria-label="Einstellungen"' in page, path
    nav = re.search(r'<nav class="gnav".*?</nav>', TestClient(api.app).get("/training").text, re.S).group(0)
    assert re.search(r'href="/"\s+class="on"', nav)  # Training gehört zum Kurs
    assert 'hset on' in TestClient(api.app).get("/mehr").text


def test_progress_top_cards_and_details_page():
    _entry("m1", "2026-01-01T10:00")
    _focus()
    c = TestClient(api.app)
    top = c.get(f"/progress?p={ME}").text
    assert "Fokus-Verlauf" in top and LESSONS["utility"][0] in top and "Gemeistert: <b>" + LESSONS["alone"][0] in top
    assert "Impact-Trend" in top and "Alle Details" in top
    # oben: Kurs-Fortschritt (geschafft von gesamt, aktuelle Lektion mit Stufe)
    assert top.index('data-block="kurs"') < top.index('data-block="fokus-verlauf"')
    assert ">1 von 12</div>" in top and "Gerade dran ist <b>Erst Utility, dann Duell</b> aus der Stufe Granaten." in top
    for detail in ("Eure größten Hebel", "Fehler im Verlauf", 'id="maps"', "Letzte Matches"):
        assert detail not in top
    det = c.get(f"/progress/details?p={ME}").text
    assert det.count('class="gnav"') == 1 and "Alle Details" in det
    for detail in ('id="impact"', "Fehler im Verlauf", 'id="maps"', "Letzte Matches", "Todes-Karte"):
        assert detail in det, detail
    assert "Das Wichtigste" in det and f'href="/progress?p={ME}#fokus"' in det  # Fokus steht auf der Übersicht


def test_strength_and_weakness_only_with_solid_data():
    rows = lambda won, n: {"label": "Mehr Spieler", "n": n, "won": won, "won_pct": round(100 * won / n)}  # noqa: E731
    side = {"side": "t", "fb": {"own": {"rows": {}}, "pro": {"rows": {}}},
            "pp": {"own": {"rows": {"up": rows(9, 10)}}, "pro": {"rows": {"up": rows(60, 100)}}},
            "buys": {"own": {"buys": {"eco": {**rows(1, 4), "label": "Eco"}}},
                     "pro": {"buys": {"eco": {**rows(30, 100), "label": "Eco"}}}}}
    sw = api._strength_weakness({"sid": ME, "sides": [side], "levers": [], "impact": None})
    assert sw["strong"]["title"] == "T: Nach dem Plant, Mehr Spieler" and "9 von 10" in sw["strong"]["text"]
    assert sw["weak"] is None  # Eco: nur 4 eigene Runden, zu wenig für eine Aussage
    lever = {"title": "Trades", "gain_s": "1,2", "text": "Mehr zu zweit.", "link": "/x"}
    sw = api._strength_weakness({"sid": ME, "sides": [], "levers": [lever], "impact": None})
    assert sw["strong"] is None and sw["weak"]["title"] == "Trades" and sw["weak"]["src"]
    assert api._strength_weakness({"sid": ME, "sides": [], "levers": [], "impact": None}) == {"strong": None,
                                                                                            "weak": None}
