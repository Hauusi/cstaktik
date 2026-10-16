"""Startseite mit einem roten Faden (neues Match, Fokus), drei Tabs plus Einstellungen, Fortschritt mit Details."""

import re

from fastapi.testclient import TestClient
from synth import ME

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


def test_home_shows_only_new_match_and_focus():
    _entry("m1", "2999-01-01T10:00")
    _entry("m2", "2999-01-02T10:00")
    _focus()
    home = _login().get("/").text
    blocks = re.findall(r'data-block="([a-z-]+)"', home)
    assert blocks == ["new", "fokus"]  # genau zwei Blöcke, in dieser Reihenfolge
    assert "Neues Match ansehen" in home and "2 neue Matches" in home
    assert home.index('href="/m/m2.html"') < home.index('href="/m/m1.html"')  # neuestes oben, das andere kompakt
    assert "Dein Fokus fürs nächste Match" in home and LESSONS["utility"][0] in home
    assert TEACH["utility"]["mantra"] in home and TEACH["utility"]["in_game"] in home
    assert "Übungen für deinen Fokus" in home and "/training/plan?p=" in home and "&back=home" in home
    assert "1 gemeistert" in home and "1 von 2 Matches in Folge geschafft" in home
    assert 'href="/training#vorbereitung"' in home and "Alle Übungen" in home
    # nicht mehr auf der Startseite: Hebel, Kabine, Situations-Training, Heute-Karte, Auftrag-Begriffe
    body = re.sub(r"<style>.*?</style>|<script>.*?</script>", "", home, flags=re.S)  # nur sichtbarer Inhalt
    for gone in ("Größter Hebel", "/briefing/", "Situations-Training", "Heute ·", "Auftrag", "Wochenplan", "Thema:"):
        assert gone not in body, gone
    assert "Demo hochladen" in home  # ohne automatischen Download bleibt das Hochladen (eingeklappt)


def test_home_without_new_match_shows_last_line():
    _entry("m1", "2026-01-01T10:00")  # vor dem ersten Login: gilt als gesehen
    _focus()
    home = _login().get("/").text
    assert re.findall(r'data-block="([a-z-]+)"', home) == ["last", "fokus"]
    assert "Letztes Match:" in home and 'href="/m/m1.html"' in home and "Neues Match ansehen" not in home


def test_nav_has_three_tabs_and_settings_icon():
    for path in ("/", "/matches", "/progress", "/training", "/mehr"):
        page = TestClient(api.app).get(path).text
        nav = re.search(r'<nav class="gnav".*?</nav>', page, re.S).group(0)
        tabs = re.findall(r'<a href="([^"]+)"[^>]*>.*?</svg>([^<]+)</a>', nav, re.S)
        assert tabs == [("/", "Coach"), ("/matches", "Matches"), ("/progress", "Fortschritt")], path
        assert 'href="/mehr" aria-label="Einstellungen"' in page, path
    nav = re.search(r'<nav class="gnav".*?</nav>', TestClient(api.app).get("/training").text, re.S).group(0)
    assert re.search(r'href="/"\s+class="on"', nav)  # Training gehört zum Coach
    assert 'hset on' in TestClient(api.app).get("/mehr").text


def test_progress_top_cards_and_details_page():
    _entry("m1", "2026-01-01T10:00")
    _focus()
    c = TestClient(api.app)
    top = c.get(f"/progress?p={ME}").text
    assert "Fokus-Verlauf" in top and LESSONS["utility"][0] in top and "Gemeistert: <b>" + LESSONS["alone"][0] in top
    assert "Impact-Trend" in top and "Alle Details" in top
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
