"""KI-Coach: Fakten nur aus dem Verlauf, Kosten und Limits, Seite nur für den eigenen Spieler. Nie die echte API."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from synth import BRO, ME

from cstaktik import accounts, ai_coach, api, history, pipeline

O = {"Origin": "http://testserver"}


class FakeClient:
    def __init__(self, text="## Kurz gesagt\nGut gespielt in Runde 3.", inp=10_000, out=1_000):
        self.calls, self.text, self.inp, self.out = [], text, inp, out
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="thinking", thinking=""),
                                        SimpleNamespace(type="text", text=self.text)],
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


def test_ask_flow_costs_and_limits(monkeypatch):
    with pytest.raises(ai_coach.CoachError, match="nicht eingerichtet"):
        ai_coach.ask("m1.html", ME, "FAKTEN")
    c = FakeClient()
    chat = ai_coach.ask("m1.html", ME, "FAKTEN", client=c)
    kw = c.calls[0]
    assert kw["model"] == "claude-haiku-5-5" and kw["system"] == ai_coach.SYSTEM
    assert kw["messages"] == [{"role": "user", "content": f"FAKTEN\n\n{ai_coach.START}"}]
    assert kw["cache_control"] == {"type": "ephemeral"}
    assert chat["messages"][-1] == {"role": "assistant", "text": c.text, "at": chat["messages"][-1]["at"]}
    assert ai_coach.spent() == pytest.approx(0.0015)
    # Nachbesprechung gibt es schon: kein zweiter Aufruf
    ai_coach.ask("m1.html", ME, "FAKTEN", client=c)
    assert len(c.calls) == 1
    # Frage: ganzes Gespräch, Fakten bleiben vorne (gecachter Teil)
    chat = ai_coach.ask("m1.html", ME, "FAKTEN", "Warum Runde 3?", client=c)
    msgs = c.calls[1]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"] and msgs[2]["content"] == "Warum Runde 3?"
    assert msgs[0]["content"].startswith("FAKTEN")
    assert chat["cost_usd"] == pytest.approx(0.003)
    with pytest.raises(ai_coach.CoachError, match="zu lang"):
        ai_coach.ask("m1.html", ME, "FAKTEN", "x" * 501, client=c)
    with pytest.raises(ai_coach.CoachError, match="Erst die Nachbesprechung"):
        ai_coach.ask("m2.html", ME, "FAKTEN", "Frage", client=c)
    # Fragen-Limit je Match
    cfg = {**ai_coach.settings(), "max_questions": 1}
    monkeypatch.setattr(ai_coach, "settings", lambda config=None: cfg)
    with pytest.raises(ai_coach.CoachError, match="aufgebraucht"):
        ai_coach.ask("m1.html", ME, "FAKTEN", "Noch eine?", client=c)
    # Monatslimit
    cfg["max_questions"], cfg["monthly_limit_usd"] = 15, 0.002
    with pytest.raises(ai_coach.CoachError, match="Monatslimit"):
        ai_coach.ask("m1.html", ME, "FAKTEN", "Noch eine?", client=c)
    assert len(c.calls) == 2


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
    c = FakeClient(text="## Kurz gesagt\nRunde 3 <b>war</b> teuer.")
    monkeypatch.setattr(ai_coach, "_client", lambda: c)
    page = a.get("/coach/m1.html").text
    assert 'data-start="1"' in page and 'id="ask"' in page
    v = a.post("/coach/m1.html", json={"p": BRO}, headers=O).json()  # fremde SteamID: es bleibt der eigene Spieler
    assert v["msgs"][0]["html"] == "<h3>Kurz gesagt</h3><p>Runde 3 &lt;b&gt;war&lt;/b&gt; teuer.</p>"
    sent = c.calls[0]["messages"][0]["content"]
    assert "Match-Daten für Ich" in sent and "Bruders" not in sent
    assert v["left"] == 15 and v["cost"] == "0,15"
    page = a.get("/coach/m1.html").text
    assert 'data-start="1"' not in page and "&lt;b&gt;war&lt;/b&gt;" in page  # gespeichert, kein neuer Aufruf
    v = a.post("/coach/m1.html", json={"q": "Was in Runde 3?"}, headers=O).json()
    assert [m["role"] for m in v["msgs"]] == ["assistant", "user", "assistant"] and v["left"] == 14
    # Story verlinkt den Coach
    assert 'href="/coach/m1.html"' in a.get("/m/m1.html").text

    b = TestClient(api.app)
    b.post("/login", data={"name": "Bruder", "password": "Geheim-12345"}, headers=O)
    assert b.get("/coach/m1.html").status_code == 404  # nicht mitgespielt
    assert b.post("/coach/m1.html", json={}, headers=O).status_code == 404
    assert a.post("/coach/m1.html", json={}, headers={"Origin": "http://evil.example"}).status_code == 403
