from cstaktik import impact
from cstaktik.model import AnalysisResult, BombEvent, Kill, MatchData, Player, Round
from cstaktik.situation import WinModel


def _model():
    """Gezählte Quoten zum Testen: CT gewinnt ct/(ct+t) der Runden, mit Bombe die Hälfte davon."""
    rows = []
    for ct in range(6):
        for t in range(6):
            for p in (0, 1):
                if ct + t == 0:
                    continue
                wins = round(10 * ct / (ct + t) * (0.5 if p else 1))
                rows += [{"w": "ct" if i < wins else "t", "s": [[ct, t, p]]} for i in range(10)]
    return WinModel(rows, 8)


def _match():
    sides = {"a": "ct", "b": "ct", "x": "t", "y": "t"}
    return MatchData(
        tickrate=64, tickrate_source="t", players=[Player(steamid=s, name=s.upper(), is_focus=s in "ab") for s in sides],
        rounds=[Round(num=1, start_tick=0, freeze_end_tick=100, end_tick=5000, winner="ct", sides=sides)],
        kills=[Kill(tick=500, round=1, attacker_steamid="x", victim_steamid="a", victim_name="A", victim_side="ct"),
               Kill(tick=900, round=1, attacker_steamid="b", victim_steamid="x", victim_name="X", victim_side="t")],
        bomb=[BombEvent(round=1, tick=700, event="plant", steamid="y"),
              BombEvent(round=1, tick=1500, event="defuse", steamid="b")])


def test_credits_follow_win_probability():
    imp = impact.build(_match(), _model())
    pl = imp["players"]
    # 2v2 -> 1v2: CT von 50 % auf 30 %; Schütze x +20, Opfer a -20
    assert pl["x"]["kill"] == 20.0 and pl["a"]["death"] == -20.0
    # Plant 1v2 -> 1v2 gelegt: 30 % -> 20 %, Leger y +10
    assert pl["y"]["plant"] == 10.0
    # b: Kill 1v2 gelegt -> 1v1 gelegt (20 -> 20) und Defuse (20 -> 100)
    assert pl["b"]["kill"] == 0.0 and pl["b"]["defuse"] == 80.0
    line = imp["rounds"][1]["line"]
    assert line[0] == [100, 50.0] and line[-1] == [1500, 100.0]
    assert imp["moments"][0]["sid"] == "b" and imp["moments"][0]["kind"] == "defuse"
    assert set(impact.history_row(imp, {"a", "b"})) == {"a", "b"}


def test_unknown_situation_gets_no_value():
    imp = impact.build(_match(), WinModel([], 8))
    assert imp["players"] == {} and imp["rounds"][1]["line"][0] == [100, None]
    assert imp["rounds"][1]["line"][-1] == [1500, 100.0]


def test_bomb_death_and_table_mix():
    m = _match()
    m.kills.append(Kill(tick=900, round=1, attacker_steamid=None, victim_steamid="b", victim_name="B",
                        victim_side="ct", weapon="planted_c4"))
    m.bomb = [BombEvent(round=1, tick=700, event="plant", steamid="y")]
    m.rounds[0].winner = "t"
    pl = impact.build(m, _model())["players"]
    assert pl.get("b", {}).get("death", 0) == 0  # Explosion: niemandem zugeschrieben
    # Eco-Tabelle nur für 2v2: vorher/nachher müssen aus derselben Tabelle kommen
    rows = [{"w": "ct", "s": [[2, 2, 0]], "eq": -1}] * 2 + [{"w": "t", "s": [[2, 2, 0]], "eq": -1}] * 8
    model = WinModel(rows + [{"w": "ct" if i < 8 else "t", "s": [[1, 2, 0]]} for i in range(10)]
                     + [{"w": "ct" if i < 5 else "t", "s": [[2, 2, 0]]} for i in range(10)], 8)
    assert model.prob_pair((2, 2, False), (1, 2, False), -1) == (0.35, 0.8)  # beide exakt, nicht 0.2 -> 0.8 gemischt


def test_report_shows_impact_and_line():
    from cstaktik.report import render

    m = _match()
    res = AnalysisResult(findings=[], rule_status=[], impact=impact.build(m, _model()))
    html = render.render_report(m, res)
    assert "Wer die Runden entschied" in html and "Entschärft" in html
    assert '"wp":[[100,50.0]' in html


def test_profile_over_matches():
    hist = [{"rounds": 20, "impact": {"a": {"total": t, "kill": t + 100, "death": -100, "plant": 0, "defuse": 0,
                                            "rank": r, "of": 10}}} for t, r in
            [(-200, 8), (-100, 6), (0, 5), (100, 3), (200, 2), (300, 1)]]
    pr = impact.profile(hist, "a")
    assert pr["n"] == 6 and pr["per_round_s"] == "+2,5" and pr["trend"] == "besser"
    assert pr["top1"] == 1 and pr["avg_rank"] == 4.2 and pr["death_s"] == "-1,0"
    assert impact.profile(hist, "zz") is None


def test_contexts_opening_trade_clutch():
    m = _match()
    m.kills = [Kill(tick=500, round=1, attacker_steamid="x", victim_steamid="a", victim_name="A", victim_side="ct"),
               Kill(tick=600, round=1, attacker_steamid="b", victim_steamid="x", victim_name="X", victim_side="t"),
               Kill(tick=950, round=1, attacker_steamid="y", victim_steamid="b", victim_name="B", victim_side="ct")]
    m.bomb = []
    m.rounds[0].winner = "t"
    pl = impact.build(m, _model())["players"]
    assert set(pl["x"]["ctx"]) == {"opening", "up"} and set(pl["a"]["ctx"]) == {"opening"}
    assert set(pl["b"]["ctx"]) == {"clutch"}  # letzter CT: Clutch hat Vorrang vor Trade
    assert set(pl["y"]["ctx"]) == {"clutch"}
    m.rounds[0].sides["c"] = "ct"  # mit drittem CT: b rächt a sofort (Trade), stirbt in Überzahl
    pl = impact.build(m, _model())["players"]
    assert set(pl["b"]["ctx"]) == {"trade", "up"}
    rows = [({"rounds": 1}, {"ctx": {"opening": [-300.0, 12], "trade": [200.0, 12]},
                             "ctx_avg": {"opening": [0.0, 1.2], "trade": [0.0, 1.0], "down": [-50.0, 2]}})]
    ctx, txt = impact.contexts(rows)
    assert ctx[0]["ctx"] == "opening" and "in Opening-Duellen. Das sind -3,0" in txt and "bei Trades" in txt


def test_kabine_mind_uses_impact_context():
    from cstaktik import api

    hist = [{"rounds": 20, "players": {"a": {}},
             "impact": {"a": {"total": -100, "ctx": {"opening": [-60.0, 4], "up": [-40.0, 3]},
                              "ctx_avg": {"opening": [0.0, 1], "up": [20.0, 1]}}}}] * 3
    lines = api._mind(hist, "a")
    assert lines and lines[0].startswith("Opening-Duell kostet dich 0,6 Runden pro Match")
    assert not any("Überzahl" in x for x in lines)
    assert api._mind([{"rounds": 20, "players": {"a": {}}}], "a") == []


def test_noisy_table_never_rewards_a_death():
    # Tabelle aus wenigen Runden: CT gewinnt 2v2 selten, 1v2 oft (Rauschen) -> Tod darf kein Plus bekommen
    rows = ([{"w": "t", "s": [[2, 2, 0]]}] * 8 + [{"w": "ct", "s": [[2, 2, 0]]}] * 2
            + [{"w": "ct", "s": [[1, 2, 0]]}] * 8 + [{"w": "t", "s": [[1, 2, 0]]}] * 2)
    m = _match()
    m.kills = m.kills[:1]
    m.bomb = []
    pl = impact.build(m, WinModel(rows, 8))["players"]
    assert pl.get("a", {}).get("death", 0) <= 0 and pl.get("x", {}).get("kill", 0) >= 0
