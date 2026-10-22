"""KI-Coach: Fakten nur aus dem Verlauf, Kosten und Limits, Seite nur für den eigenen Spieler. Nie die echte API."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from synth import BRO, ME

from cstaktik import accounts, ai_coach, api, history, pipeline

O = {"Origin": "http://testserver"}


DEBRIEF = {
    "headline": "Setz dich, wir schauen uns Mirage an.", "summary": "Gewonnen, aber Runde 3 war teuer.",
    "good": [{"round": 1, "text": "Zwei Kills und überlebt."}, {"round": 42, "text": "Erfunden."}],
    "topic": {"lesson": "utility", "title": "Erst Utility, dann Duell", "principle": "Eine Flash nimmt dem Gegner den Schuss.",
              "scenes": [{"round": 3, "what": "Ohne Flash nach A.", "better": "Erst Flash, dann peeken."},
                         {"round": 77, "what": "Gibt es nicht.", "better": "-"}]},
    "agreement": {"text": "Vor jedem Peek auf A eine Flash.", "check": "Die App zählt Utility-Fehler."},
    "question": {"round": 3, "text": "Was hattest du in Runde 3 vor?"},
}


class FakeClient:
    def __init__(self, text="Gute Frage: in Runde 3 fehlte die Flash.", inp=10_000, out=1_000):
        self.calls, self.text, self.inp, self.out = [], text, inp, out
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        text = json.dumps(DEBRIEF) if "output_config" in kw else self.text
        return SimpleNamespace(content=[SimpleNamespace(type="thinking", thinking=""),
                                        SimpleNamespace(type="text", text=text)],
                               usage=SimpleNamespace(input_tokens=self.inp, output_tokens=self.out,
                                                     cache_creation_input_tokens=0, cache_read_input_tokens=0),
                               stop_reason="end_turn")


def _entry(**extra):
    sc = {"lesson": "utility", "sid": ME, "round": 3, "tick": 500, "from": 400,
          "happened": "Bei 1:20 läufst du ohne Flash nach A.", "next": "Erst Flash, dann Peek."}
    h = {"id": "m1", "map": "de_mirage", "rounds": 20, "analyzed_at": "2999-01-01T10:00", "report_file": "m1.html",
         "won": 13, "lost": 7, "players": {ME: {"name": "Ich", "kills": 18, "deaths": 12, "adr": 81.4}},
         "seq": {ME: []}, "score_by": {ME: [13, 7]}, "lessons": {ME: {"utility": 3}},
         "by_round": {ME: [[1, "t", True, 2, 0, 150], [3, "t", False, 0, 1, 20]]},
         "duel_stats": {ME: {"n": 20, "won": 55, "react": 240}},
         "scenes": [sc, {**sc, "sid": BRO, "round": 9, "happened": "Fremde Szene des Bruders."}], **extra}
    return h


def test_facts_only_own_data():
    t = ai_coach.facts(_entry(), ME, lesson={"title": "Erst Utility, dann Duell", "says": ["Ziel verfehlt."]})
    assert "Ergebnis aus seiner Sicht: 13:7 (Sieg)" in t
    assert "Kills 18, Tode 12" in t and "ADR 81" in t
    assert "Runde 1: T, gewonnen, 2 Kills, überlebt, 150 Schaden" in t
    assert "### Runde 3: Erst Utility, dann Duell" in t and "ohne Flash nach A" in t
    assert "Duelle gewonnen: 55 %" in t and "Median 240 ms" in t
    assert "Aktuelle Kurs-Lektion: Erst Utility, dann Duell" in t and "Ziel verfehlt." in t
    assert "Bruders" not in t and "Runde 9" not in t  # Szenen anderer Spieler nie
    assert "Clutches" not in t  # fehlende Teile fallen weg statt leer zu stehen


def test_cost_from_usage():
    prices = {"claude-haiku-5-5": {"input": 0.10, "output": 0.50}, "claude-sonnet-5-5": {"input": 2, "output": 10}}
    u = SimpleNamespace(input_tokens=20_000, output_tokens=3_000, cache_creation_input_tokens=0,
                        cache_read_input_tokens=0)
    assert ai_coach.cost(u, "claude-haiku-5-5", prices) == pytest.approx(0.0035)
    cached = SimpleNamespace(input_tokens=100, output_tokens=0, cache_creation_input_tokens=0,
                             cache_read_input_tokens=20_000)
    assert ai_coach.cost(cached, "claude-haiku-5-5", prices) == pytest.approx(0.00021)
    assert ai_coach.cost(u, "unbekannt", prices) == pytest.approx(0.07)  # unbekannt: teuerster Preis
    assert ai_coach.cents(0.0035) == "0,35" and ai_coach.cents(0.07) == "7,0"


def test_ask_flow_costs_limits_and_memory(monkeypatch):
    with pytest.raises(ai_coach.CoachError, match="nicht eingerichtet"):
        ai_coach.ask("m1.html", ME, "FAKTEN")
    c = FakeClient()
    chat = ai_coach.ask("m1.html", ME, "FAKTEN", client=c, rounds={1, 3}, meta={"map": "Mirage"})
    kw = c.calls[0]
    # Nachbesprechung: Sonnet, strukturiert (JSON-Schema), Fakten vorne
    assert kw["model"] == "claude-sonnet-5-5" and kw["system"] == ai_coach.SYSTEM
    assert kw["output_config"]["effort"] == "medium" and kw["output_config"]["format"]["type"] == "json_schema"
    assert kw["messages"][0]["content"].startswith("FAKTEN\n\n" + ai_coach.DEBRIEF)
    assert kw["cache_control"] == {"type": "ephemeral"}
    d = chat["debrief"]
    # erfundene Runden fliegen raus
    assert [g["round"] for g in d["good"]] == [1] and [x["round"] for x in d["topic"]["scenes"]] == [3]
    assert ai_coach.spent() == pytest.approx(0.03)  # Sonnet: 10k x 2 $ + 1k x 10 $ je Million
    # Gedächtnis: Abmachung und Frage stehen in den Notizen, für das nächste Match als Text
    n = ai_coach.notes(ME)[0]
    assert n["agreement"] == DEBRIEF["agreement"]["text"] and n["lesson"] == "utility" and n["map"] == "Mirage"
    assert ai_coach.notes_text(ME, "m1.html") == ""  # das aktuelle Match zählt nicht als frühere Notiz
    assert "Abmachung: Vor jedem Peek auf A eine Flash." in ai_coach.notes_text(ME, "m2.html")
    # Nachbesprechung gibt es schon: kein zweiter Aufruf
    ai_coach.ask("m1.html", ME, "FAKTEN", client=c)
    assert len(c.calls) == 1
    # Antwort auf die Frage des Coaches: Haiku, ganzes Gespräch, landet in den Notizen
    chat = ai_coach.ask("m1.html", ME, "FAKTEN", "Ich wollte schnell rein.", client=c, answer=True)
    kw = c.calls[1]
    assert kw["model"] == "claude-haiku-5-5" and "output_config" not in kw
    assert [m["role"] for m in kw["messages"]] == ["user", "assistant", "user"]
    assert kw["messages"][2]["content"] == ai_coach.ANSWER + "Ich wollte schnell rein."
    assert ai_coach.notes(ME)[0]["answer"] == "Ich wollte schnell rein."
    assert "Seine Antwort: Ich wollte schnell rein." in ai_coach.notes_text(ME, "m2.html")
    assert chat["cost_usd"] == pytest.approx(0.03 + 0.0015)
    with pytest.raises(ai_coach.CoachError, match="zu lang"):
        ai_coach.ask("m1.html", ME, "FAKTEN", "x" * 501, client=c)
    with pytest.raises(ai_coach.CoachError, match="Erst die Nachbesprechung"):
        ai_coach.ask("m2.html", ME, "FAKTEN", "Frage", client=c)
    cfg = {**ai_coach.settings(), "max_questions": 1}
    monkeypatch.setattr(ai_coach, "settings", lambda config=None: cfg)
    with pytest.raises(ai_coach.CoachError, match="aufgebraucht"):
        ai_coach.ask("m1.html", ME, "FAKTEN", "Noch eine?", client=c)
    cfg["max_questions"], cfg["monthly_limit_usd"] = 15, 0.01
    with pytest.raises(ai_coach.CoachError, match="Monatslimit"):
        ai_coach.ask("m1.html", ME, "FAKTEN", "Noch eine?", client=c)
    assert len(c.calls) == 2


def test_schema_is_strict():
    sch = ai_coach.schema(["utility", "none"])

    def walk(o):
        if isinstance(o, dict):
            if o.get("type") == "object":
                assert o["additionalProperties"] is False and set(o["required"]) == set(o["properties"])
            for v in o.values():
                walk(v)

    walk(sch)
    assert sch["properties"]["topic"]["properties"]["lesson"]["enum"] == ["utility", "none"]


def test_to_html_is_safe():
    out = str(ai_coach.to_html("## Kurz gesagt\n<script>x</script> **fett**\n- eins\n- zwei"))
    assert out == ("<h3>Kurz gesagt</h3><p>&lt;script&gt;x&lt;/script&gt; <b>fett</b></p>"
                   "<ul><li>eins</li><li>zwei</li></ul>")


def test_coach_page_own_player_only(monkeypatch):
    history.save(_entry(), pipeline.HISTORY_DIR)
    pipeline.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (pipeline.REPORTS_DIR / "m1.html").write_text("<html></html>")
    accounts.add_user("Hausi", "Geheim-12345")
    accounts.add_user("Bruder", "Geheim-12345")
    accounts.link_steamid("Hausi", ME)
    accounts.link_steamid("Bruder", BRO)
    a = TestClient(api.app)
    a.post("/login", data={"name": "Hausi", "password": "Geheim-12345"}, headers=O)
    assert "noch nicht eingerichtet" in a.get("/coach/m1.html").text
    assert a.post("/coach/m1.html", json={}, headers=O).json()["error"].startswith("Der KI-Coach ist")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    c = FakeClient(text="Runde 3 <b>war</b> teuer.")
    monkeypatch.setattr(ai_coach, "_client", lambda: c)
    page = a.get("/coach/m1.html").text
    assert 'data-start="1"' in page and "eine halbe Minute" in page
    home = a.get("/").text  # Startseite: der Coach startet das Gespräch zum letzten Match selbst
    assert 'data-block="coach"' in home and 'data-start="1"' in home and 'data-file="m1.html"' in home
    v = a.post("/coach/m1.html", json={"p": BRO}, headers=O).json()  # fremde SteamID: es bleibt der eigene Spieler
    assert v["ok"] and v["cost"] == "3,0"
    sent = c.calls[0]["messages"][0]["content"]
    assert "Match-Daten für Ich" in sent and "Bruders" not in sent
    for page in (a.get("/coach/m1.html").text, a.get("/").text):
        assert 'data-start="1"' not in page  # gespeichert, kein neuer Aufruf
        assert DEBRIEF["headline"] in page and "Runde 1." in page and "Erfunden" not in page
        assert "Dein Thema heute: Erst Utility, dann Duell" in page and "Ohne Flash nach A." in page
        assert 'href="/reports/m1.html#s3-400"' in page  # Szene im 2D-Replay
        assert "Unsere Abmachung" in page and DEBRIEF["agreement"]["text"] in page
        assert "Dein Coach fragt · Runde 3" in page and 'data-answer="1"' in page
    v = a.post("/coach/m1.html", json={"q": "Ich wollte schnell rein.", "answer": True}, headers=O).json()
    assert v["ok"]
    page = a.get("/").text
    assert "Ich wollte schnell rein." in page and "&lt;b&gt;war&lt;/b&gt;" in page and 'data-answer="1"' not in page
    assert 'href="/coach/m1.html"' in page  # weiter im Gespräch
    a.post("/coach/m1.html", json={"q": "Und Runde 1?"}, headers=O)
    page = a.get("/coach/m1.html").text
    assert "Und Runde 1?" in page and "Noch 13 Fragen" in page
    # Story verlinkt den Coach
    assert 'href="/coach/m1.html"' in a.get("/m/m1.html").text

    b = TestClient(api.app)
    b.post("/login", data={"name": "Bruder", "password": "Geheim-12345"}, headers=O)
    assert b.get("/coach/m1.html").status_code == 404  # nicht mitgespielt
    assert b.post("/coach/m1.html", json={}, headers=O).status_code == 404
    assert a.post("/coach/m1.html", json={}, headers={"Origin": "http://evil.example"}).status_code == 403


def test_old_text_chat_is_rewritten(monkeypatch):
    ai_coach._write(ai_coach._chat_file("m1.html", ME), {"model": "claude-haiku-5-5", "cost_usd": 0.001, "messages": [
        {"role": "user", "text": ai_coach.START}, {"role": "assistant", "text": "## Kurz gesagt\nAlt."}]})
    view = api._coach_view(_entry(), ME, ai_coach.load_chat("m1.html", ME))
    assert view["legacy"] is not None and view["has"]  # ohne Schlüssel: bleibt lesbar
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    view = api._coach_view(_entry(), ME, ai_coach.load_chat("m1.html", ME))
    assert view["legacy"] is None and not view["has"]  # mit Schlüssel: neu starten
    c = FakeClient()
    chat = ai_coach.ask("m1.html", ME, "FAKTEN", client=c, rounds={1, 3})
    assert chat["debrief"]["headline"] == DEBRIEF["headline"] and len(c.calls) == 1
