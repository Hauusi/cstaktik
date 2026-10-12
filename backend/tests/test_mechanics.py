from synth import ENEMIES, ME, build_match

from cstaktik import goals
from cstaktik.config import load_rules_config
from cstaktik.mechanics import is_gun, mechanics
from cstaktik.model import Damage, Shot
from cstaktik.rules import analyze, death_review

CFG = load_rules_config()
M = CFG["mechanics"]


def _match():
    """Runde 2: Salve aus 6 AK-Schüssen 1 s vor dem Tod; Schuss 1, 2, 6 im Laufen; Treffer bei 1, 2, 5."""
    m = build_match()
    r2 = m.round_by_num(2)
    t0 = r2.freeze_end_tick + 19 * 64
    speeds = [200, 200, 0, 0, 0, 200]
    m.shots = [Shot(round=2, tick=t0 + 6 * i, steamid=ME, weapon="weapon_ak47", speed=sp) for i, sp in enumerate(speeds)]
    m.shots.append(Shot(round=2, tick=t0 + 2, steamid=ME, weapon="weapon_knife", speed=250))  # zählt nicht
    m.damages = [Damage(round=2, tick=t0 + 6 * i, attacker_steamid=ME, victim_steamid=ENEMIES[0], dmg=20, weapon="ak47")
                 for i in (0, 1, 4)]
    return m


def test_gun_filter():
    assert is_gun("weapon_ak47") and is_gun("deagle")
    assert not any(is_gun(w) for w in ("weapon_knife", "hegrenade", "inferno", "weapon_c4", "", None))


def test_mechanics_metrics():
    me = next(x for x in mechanics(_match(), M) if x["steamid"] == ME)
    assert (me["shots"], me["moving_shots"], me["moving_pct"]) == (6, 3, 50.0)
    assert (me["hits"], me["hit_pct"]) == (3, 50.0)
    assert (me["spray_early_pct"], me["spray_late_pct"]) == (66.7, 33.3)
    assert (me["deaths"], me["deaths_no_shot"], me["no_shot_rounds"]) == (3, 2, [3, 4])
    assert me["hs_pct"] is None  # keine eigenen Kills -> keine Zahl erfinden


def test_death_review_uses_shot_facts():
    m = _match()
    cfg = {**CFG["rules"]["death_review"], "mech": M}
    f = {x.round: x for x in death_review.run(m, cfg)}
    assert "letzter Schuss im Laufen (200 Units/s)" in f[2].evidence["lage"]
    assert "Im Laufen geschossen" in [f[2].title.removeprefix("Tod: ")] + f[2].evidence["weitere_punkte"]
    assert "kein eigener Schuss vor dem Tod" in f[3].evidence["lage"]


def test_mechanics_goal_created_per_player():
    st = {"active": [], "done": []}
    summary = {"id": "1", "rounds": 24, "cause_rounds": {}, "cause_order": [],
               "players": {ME: {"name": "Ich"}}, "mech": {ME: {"moving_pct": 50.0, "deaths_no_shot_pct": 10.0}}}
    goals.update(st, summary, CFG["goals"], M)
    assert [g["title"] for g in st["active"]] == ["Stehend schießen (Ich)"]
    assert st["active"][0]["target_pct"] == 30.0
    nxt = {**summary, "id": "2", "mech": {ME: {"moving_pct": 20.0}}}
    r = goals.update(st, nxt, CFG["goals"], M)
    assert r["checks"][0]["met"] and r["checks"][0]["pct"] == 20.0


def test_report_shows_mechanics(tmp_path):
    from cstaktik.report.render import render_report

    m = _match()
    html = render_report(m, analyze(m, CFG), maps_dirs=[tmp_path])
    assert "Mechanik" in html and "Tode ohne Schuss" in html and "Spray" in html
