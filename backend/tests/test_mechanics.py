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


def test_weapon_label():
    from cstaktik.mechanics import weapon_label

    assert weapon_label("weapon_usp_silencer") == "USP-S"
    assert weapon_label("m4a1_silencer") == "M4A1-S"
    assert weapon_label("unbekannt_x") == "unbekannt_x"


def test_duel_angle_and_compute():
    from synth import ENEMIES, ME, build_match

    from cstaktik.duels import angle_error, compute, side_of, stats
    from cstaktik.model import Damage, Shot

    assert angle_error((0, 0, 0, 0.0, 0.0), (100, 0, 0)) == 0.0
    assert angle_error((0, 0, 0, 90.0, 0.0), (100, 0, 0)) == 90.0
    assert angle_error((0, 0, 0, 0.0, 0.0), (100, 100, 0)) == 45.0
    assert angle_error((0, 0, 0, None, 0.0), (1, 0, 0)) is None

    m = build_match()
    k = next(k for k in m.kills if k.victim_steamid == ME)
    m.shots += [Shot(round=k.round, tick=k.tick - 40, steamid=k.attacker_steamid, weapon="weapon_ak47", speed=0.0),
                Shot(round=k.round, tick=k.tick - 20, steamid=ME, weapon="weapon_m4a1", speed=150.0)]
    m.damages.append(Damage(round=k.round, tick=k.tick - 39, attacker_steamid=k.attacker_steamid, victim_steamid=ME,
                            dmg=27, weapon="ak47"))
    c = k.tick - 40
    views = {(c, k.attacker_steamid): (600, 0, 0, 180.0, 0.0), (c, ME): (0, 0, 0, 30.0, 0.0)}
    d = next(x for x in compute(m, views) if x.loser == ME)
    me = side_of(d, ME)
    assert me["err"] == 30.0 and me["react"] == round(20 * 1000 / 64) and me["won"] is False and me["speed"] == 150
    assert d.w_err == 0.0 and d.w_react_ms == 0 and d.w_first_hit is True
    st = stats([me, side_of(d, k.attacker_steamid)])
    assert st["n"] == 2 and st["shot_first"] == 50 and st["won"] == 50


def test_crosshair_lesson_and_duel_sentence():
    from cstaktik.coach_voice import _duel_sentence, lesson_id

    fx = {"label": "Duell verloren", "attacker": "Blackwell", "duel": {"err": 31.0, "opp_err": 4.0, "react": 250,
                                                                      "hit": False, "speed": 160}}
    assert lesson_id(fx) == "crosshair"
    assert _duel_sentence(fx) == ("Im Moment des ersten Schusses zeigte dein Fadenkreuz 31° neben Blackwell, seins 4° "
                                  "neben dich. Dein erster Schuss kam 250 ms nach seinem, bei 160 Units/s.")
    fx["duel"]["err"] = 8.0
    assert lesson_id(fx) == "duel"


def test_angle_lesson_for_wrong_direction():
    from cstaktik.coach_voice import lesson_id

    assert lesson_id({"label": "Duell verloren", "duel": {"err": 120.0}}) == "angle"
    assert lesson_id({"label": "Ohne Gegenwehr", "a_dist": 300, "duel": {"err": 95.0}}) == "angle"
    assert lesson_id({"label": "Duell verloren", "duel": {"err": 35.0}}) == "crosshair"


def test_duel_contact_ignores_shots_at_other_enemies():
    """Opfer sprüht vorher auf Gegner X; Y tötet es von der Seite: Kontakt = Ys erster Schuss."""
    from synth import ENEMIES, ME, build_match

    from cstaktik.duels import contacts
    from cstaktik.model import Damage, Shot

    m = build_match()
    k = next(k for k in m.kills if k.victim_steamid == ME and k.attacker_steamid in ENEMIES)
    m.shots = [s for s in m.shots if s.round != k.round]
    m.damages = [d for d in m.damages if d.round != k.round]
    m.shots += [Shot(round=k.round, tick=k.tick - 150, steamid=ME, weapon="ak47"),  # auf jemand anderen
                Shot(round=k.round, tick=k.tick - 40, steamid=k.attacker_steamid, weapon="ak47")]
    c = dict((kk.tick, t) for kk, t in contacts(m))
    assert c[k.tick] == k.tick - 40
    # Trifft das Opfer den Killer, beginnt das Duell mit seinem Schuss davor
    m.shots.append(Shot(round=k.round, tick=k.tick - 60, steamid=ME, weapon="ak47"))
    m.damages.append(Damage(round=k.round, tick=k.tick - 58, attacker_steamid=ME, victim_steamid=k.attacker_steamid, dmg=27))
    c = dict((kk.tick, t) for kk, t in contacts(m))
    assert c[k.tick] == k.tick - 60


def test_death_review_other_deaths_blind_and_duel_damage():
    from synth import BRO, ENEMIES, ME, build_match

    from cstaktik.config import load_rules_config
    from cstaktik.model import Blind, Damage
    from cstaktik.rules import death_review

    cfg = {**load_rules_config()["rules"]["death_review"], "mech": load_rules_config()["mechanics"]}
    m = build_match()
    k = next(k for k in m.kills if k.victim_steamid == ME and k.attacker_steamid in ENEMIES)
    k.weapon = "ak47"
    r = k.round
    m.damages = [d for d in m.damages if d.round != r]
    m.damages += [Damage(round=r, tick=k.tick - 900, attacker_steamid=ME, victim_steamid=ENEMIES[4], dmg=100),  # früher Kill
                  Damage(round=r, tick=k.tick - 20, attacker_steamid=ME, victim_steamid=k.attacker_steamid, dmg=27)]
    m.blinds = [Blind(round=r, tick=k.tick - 150, victim_steamid=ME, attacker_steamid=BRO, duration=3.0),  # eigene Flash
                Blind(round=r, tick=k.tick - 180, victim_steamid=ME, attacker_steamid=ENEMIES[3], duration=0.6)]  # vorbei
    f = next(f for f in death_review.run(m, cfg) if f.tick == k.tick)
    fx = f.evidence["f"]
    assert fx["dealt"] == 27  # nur Schaden am Killer im Duell
    assert "Geblendet" not in fx["issues"]  # Teamflash und abgelaufene Gegner-Flash zählen nicht
    assert any("eigene Flash" in x for x in f.evidence["lage"])
    k.weapon = "hegrenade"
    f = next(f for f in death_review.run(m, cfg) if f.tick == k.tick)
    assert f.rule_id == "death_other" and f.title == "Tod: HE"
