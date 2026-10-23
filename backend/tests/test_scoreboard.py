"""Stats-Reiter: Scoreboard je Match (K/D/A, KAST, Multi-Kills, Openings, Rating) und Summen über Matches."""

from fastapi.testclient import TestClient

from cstaktik import accounts, api, history, pipeline, scoreboard
from cstaktik.model import Damage, Kill, MatchData, Player, Round

ME, MATE, E1, E2 = "1", "2", "8", "9"
O = {"Origin": "http://testserver"}


def _k(tick, rnd, a, v, hs=False, assist=None):
    return Kill(tick=tick, round=rnd, attacker_steamid=a, victim_steamid=v, victim_name=v, headshot=hs,
                assister_steamid=assist, weapon="ak47")


def _match(assists=True):
    sides = {ME: "t", MATE: "t", E1: "ct", E2: "ct"}
    rounds = [Round(num=i, start_tick=i * 1000, end_tick=i * 1000 + 900, sides=sides, winner="t") for i in (1, 2, 3, 4)]
    kills = [_k(1100, 1, ME, E1, hs=True), _k(1200, 1, ME, E2),            # R1: 2 Kills (Opening), überlebt
             _k(2100, 2, E1, ME), _k(2200, 2, MATE, E1, assist=ME),       # R2: Opening-Tod, getradet, Assist
             _k(3100, 3, E2, ME), _k(3900, 3, MATE, E2)]                    # R3: Tod, nicht getradet (zu spät)
    m = MatchData(map_name="de_mirage", tickrate=64, tickrate_source="t", rounds=rounds, kills=kills,
                  players=[Player(steamid=s, name=s, is_focus=s == ME) for s in sides],
                  damages=[Damage(round=1, tick=1100, attacker_steamid=ME, victim_steamid=E1, dmg=100),
                           Damage(round=1, tick=1200, attacker_steamid=ME, victim_steamid=E2, dmg=100),
                           Damage(round=3, tick=3050, attacker_steamid=ME, victim_steamid=MATE, dmg=50)],
                  assists_parsed=assists)
    return m


def test_counts_and_derived():
    c = scoreboard.match_counts(_match())[ME]
    assert (c["rounds"], c["kills"], c["deaths"], c["assists"], c["hs"]) == (4, 2, 2, 1, 1)
    assert (c["k2"], c["ok"], c["od"], c["traded"], c["survived"]) == (1, 1, 2, 1, 2)  # R2 und R3: erster Tod
    assert c["kast"] == 3 and c["dmg"] == 200  # R1 Kill, R2 Assist/Trade, R4 überlebt; Teamschaden zählt nicht
    d = scoreboard.derive(c)
    assert d["kd"] == 1.0 and d["adr"] == 50.0 and d["kast"] == 75 and d["hs_pct"] == 50
    assert d["rating1"] == round((0.5 / 0.679 + 0.7 * 0.5 / 0.317 + 1.0 / 1.277) / 2.7, 2)
    imp = 2.13 * 0.5 + 0.42 * 0.25 - 0.41
    assert d["rating2"] == round(0.0073 * 75 + 0.3591 * 0.5 - 0.5329 * 0.5 + 0.2372 * imp + 0.0032 * 50 + 0.1587, 2)


def test_without_assists_no_kast_or_rating2():
    d = scoreboard.derive(scoreboard.match_counts(_match(assists=False))[ME])
    assert d["assists"] is None and d["kast"] is None and d["rating2"] is None and d["rating1"] is not None
    t = scoreboard.totals([scoreboard.match_counts(_match())[ME], scoreboard.match_counts(_match(False))[ME]])
    assert t["kills"] == 4 and t["matches"] == 2 and not t["assists_known"]  # gemischt: KAST nicht hochrechnen


def test_stats_page():
    board = scoreboard.match_counts(_match())
    for i, at in enumerate(("2026-01-01T10:00", "2026-01-02T10:00")):
        history.save({"id": f"s{i}", "map": "de_mirage", "rounds": 4, "analyzed_at": at, "report_file": f"s{i}.html",
                      "players": {ME: {"name": "Ich"}}, "score_by": {ME: [13, 7]}, "board": board,
                      "clutch": [{"sid": ME, "round": 3, "vs": 1, "won": True}]}, pipeline.HISTORY_DIR)
    accounts.add_user("Hausi", "Geheim-12345")
    accounts.link_steamid("Hausi", ME)
    c = TestClient(api.app)
    c.post("/login", data={"name": "Hausi", "password": "Geheim-12345"}, headers=O)
    page = c.get("/stats").text
    r2 = scoreboard.derive(scoreboard.totals([board[ME], board[ME]]))["rating2"]
    assert f"{r2:.2f}".replace(".", ",") in page and "Rating 2.0 (Näherung)" in page
    assert "<b>1,00</b><span>K/D</span>" in page and "<b>50,0</b><span>ADR</span>" in page
    assert "75<small> %</small></b><span>KAST" in page and "2</b> Siege" in page and "0</b> Niederlagen" in page
    assert "<b>2<small> / 2</small></b><span>Clutches gewonnen" in page
    assert page.count('href="/m/s') >= 4  # Balken und Tabelle verlinken die Matches
    assert "2-2-1" in page
