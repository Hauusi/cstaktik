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
    assert "letzter Schuss im Laufen (5,1 m/s)" in f[2].evidence["lage"]
    assert "Im Laufen geschossen" in [f[2].title.removeprefix("Tod: ")] + f[2].evidence["weitere_punkte"]
    assert "kein eigener Schuss vor dem Tod" in f[3].evidence["lage"]


def test_mechanics_goal_created_per_player():
    st = {"active": [], "done": []}
    summary = {"id": "1", "rounds": 24, "cause_rounds": {}, "cause_order": [],
               "players": {ME: {"name": "Ich", "deaths": 15}},
               "mech": {ME: {"moving_pct": 50.0, "deaths_no_shot_pct": 10.0, "shots": 120}}}
    goals.update(st, summary, CFG["goals"], M)
    assert [g["title"] for g in st["active"]] == ["Stehend schießen (Ich)"]
    assert st["active"][0]["target_pct"] == 30.0
    nxt = {**summary, "id": "2", "mech": {ME: {"moving_pct": 20.0, "shots": 90}}}
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
    assert _duel_sentence(fx) == ("Beim Duellstart lag dein Fadenkreuz 31° neben Blackwell. Seins lag 4° neben dir. "
                                  "Dein erster Schuss kam 250 ms nach seinem. Du warst dabei mit 4,1 m/s unterwegs.")
    # eigener (verfehlter) Schuss vor dem Kontakt: keine Reaktionszeit, kein "nach seinem"
    early = {**fx, "duel": {**fx["duel"], "early_shot": True}}
    assert "nach seinem" not in _duel_sentence(early) and "zuerst geschossen" not in _duel_sentence(early)
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


def test_lesson_ids_count_every_issue_once():
    from cstaktik.coach_voice import lesson_ids

    fx = {"label": "Geblendet", "issues": ["Geblendet", "Allein, kein Trade", "Utility nicht genutzt", "Allein, kein Trade"]}
    assert lesson_ids(fx, "blind") == ["blind", "alone", "utility"]
    assert lesson_ids({"issues": []}, "duel") == ["duel"]


def test_focus_prefers_recurring_pattern_over_one_off():
    from cstaktik.coach_voice import focus, recurrence
    from cstaktik.model import Finding

    def f(lid, cost, issues):
        return Finding(rule_id="death_review", title="t", round=1, tick=1, steamid="a", player_name="A", severity="hoch",
                       text="", tip="", evidence={"coach": {"id": lid}, "cost_pct": cost, "f": {"issues": issues}})

    fs = [f("blind", 60, ["Geblendet"]), f("blind", 0, ["Geblendet"]),
          f("alone", 10, ["Allein, kein Trade", "Utility nicht genutzt"]),
          f("alone", 5, ["Allein, kein Trade"])]
    assert focus(fs)[0]["id"] == "blind"  # ohne Gedächtnis: teuerster zuerst
    past = [{"lessons": {"a": {"alone": 2}}, "players": {"a": {}}}, {"lessons": {"a": {"alone": 1}}, "players": {"a": {}}}]
    top = focus(fs, recur=recurrence(past, "a"))
    assert top[0]["id"] == "alone" and top[0]["seen_in"] == 3 and top[0]["of_matches"] == 3
    util = next(x for x in focus(fs) if x["id"] == "utility")
    assert util["count"] == 1 and util["main"] == 0  # beteiligt, aber nicht Hauptfehler
    assert not util["lead"]


def test_one_off_lesson_never_leads():
    from cstaktik.coach_voice import focus, headline, intro, recurrence
    from cstaktik.model import Finding

    def f(lid, cost, issues):
        return Finding(rule_id="death_review", title="t", round=1, tick=1, steamid="a", player_name="A", severity="hoch",
                       text="", tip="", evidence={"coach": {"id": lid}, "cost_pct": cost, "f": {"issues": issues}})

    fs = [f("blind", 80, ["Geblendet"]), f("alone", 5, ["Allein, kein Trade"]), f("alone", 5, ["Allein, kein Trade"])]
    assert focus(fs)[0]["id"] == "alone"  # einmal teuer schlägt kein Muster
    past = [{"lessons": {"a": {"blind": 3}}, "players": {"a": {}}}] * 3
    assert focus(fs, recur=recurrence(past, "a"))[0]["id"] == "alone"  # Gedächtnis hilft nur bei Muster heute
    one = focus([f("blind", 80, ["Geblendet"])])
    assert headline(one) is None and intro(10, 13, "Mirage", one) == ["Ich hab mir euer 10:13 auf Mirage angesehen."]


def test_why_follows_the_data_not_assumed_intent():
    from cstaktik.coach_voice import _next, _why

    fx = {"attacker": "G1", "aplace": "Palace", "mate": "Bruder", "mate_dist": 1400}
    held = {"kind": "gehalten"}
    assert _why("alone", fx, held, "gehalten").startswith("Du hast allein gehalten. Bruder war 36 m weg.")
    # steht der Abstand schon im Lage-Satz, wird er nicht wiederholt
    assert _why("alone", fx, {**held, "mate_d": 1400}, "gehalten").startswith("Du hast allein gehalten. Nach")
    assert "peeken" not in _next("alone", fx, held, "gehalten")
    assert _why("alone", fx, {"kind": "bewegt"}, "Richtung Gegner").startswith("Du bist ins Duell gegangen")
    w = _why("no_shot_close", {**fx, "duel": {"err": 4.0}}, held, "gehalten")
    assert w.startswith("Dein Fadenkreuz lag richtig, nur 4,0° neben ihm.")
    assert _why("no_shot_close", fx, {"kind": "bewegt"}, "Richtung Gegner") is None  # allgemeiner Satz passt


def test_strengths_against_own_baseline_with_n():
    from cstaktik.coach_voice import strengths

    past = [{"duel_stats": {"a": {"n": 20, "first_hit": 40, "won": 50, "err": 8.0}}} for _ in range(3)]
    s = strengths({"a": {"n": 22, "first_hit": 55, "won": 52, "err": 7.5}}, {"a": "Ich"}, past)
    assert s == ["Ich: Erste Kugel trifft 55 % in 22 Duellen. Dein Schnitt der letzten 3 Matches: 40 %."]
    assert strengths({"a": {"n": 9, "first_hit": 90}}, {"a": "Ich"}, past) == []  # zu wenige Duelle
    assert strengths({"a": {"n": 22, "first_hit": 55}}, {"a": "Ich"}, past[:1]) == []  # zu wenig Vergleich


def test_mantra_is_not_just_the_lesson_title():
    import re

    from cstaktik.coach_voice import LESSONS
    from cstaktik.curriculum import TEACH

    norm = lambda s: re.sub(r"[^a-zäöüß]", "", s.lower())  # noqa: E731
    assert all(norm(TEACH[k]["mantra"]) != norm(LESSONS[k][0]) for k in TEACH)


def test_utility_issue_only_for_flash_or_molotov():
    from synth import ENEMIES, ME, build_match

    from cstaktik.config import load_rules_config
    from cstaktik.rules import death_review

    cfg = {**load_rules_config()["rules"]["death_review"], "mech": load_rules_config()["mechanics"]}
    m = build_match()
    k = next(k for k in m.kills if k.victim_steamid == ME and k.attacker_steamid in ENEMIES)
    k.weapon = "ak47"
    k.victim_inventory = ["AK-47", "Smoke Grenade", "High Explosive Grenade"]
    f = next(f for f in death_review.run(m, cfg) if f.tick == k.tick)
    assert "Utility nicht genutzt" not in f.evidence["f"]["issues"]  # Smoke/HE aufheben ist kein Fehler
    assert any("Smoke Grenade" in x for x in f.evidence["lage"])  # steht aber als Fakt da
    k.victim_inventory = ["AK-47", "Flashbang"]
    f = next(f for f in death_review.run(m, cfg) if f.tick == k.tick)
    assert "Utility nicht genutzt" in f.evidence["f"]["issues"] and "Flash" in f.tip + str(f.evidence["f"])


def test_duel_reading_connects_the_numbers():
    from cstaktik.coach_voice import duel_reading

    pro = {"err": 4.9, "shot_first": 59, "first_hit": 30, "react": 250}
    me = {"n": 36, "err": 5.1, "shot_first": 50, "first_hit": 29}  # Werte aus einem echten Match
    assert duel_reading(me, pro).startswith("Dein Zielen ist auf Pro-Niveau. Aber du schießt seltener zuerst: 50 %, Pros 59 %.")
    assert duel_reading({**me, "err": 8.0}, pro).startswith("Dein Fadenkreuz liegt im Duell weiter neben dem Kopf")
    moving = {**me, "shot_first": 58, "first_hit": 18, "moving_pct": 40, "moving_n": 20}
    assert "40 % deiner ersten Schüsse kamen aus der Bewegung" in duel_reading(moving, pro)
    assert duel_reading({**me, "shot_first": 57}, pro).startswith("Im Duell selbst bist du auf Pro-Niveau")
    assert duel_reading({**me, "n": 8}, pro) is None  # zu wenige Duelle
    assert duel_reading(me, None) is None


def test_victim_missed_first_shot_is_not_a_late_reaction():
    from cstaktik.duels import compute, shot_before_contact
    from cstaktik.rules.death_review import _duel

    m = build_match()
    k = next(k for k in m.kills if k.victim_steamid == ME)
    # ME schießt zuerst und verfehlt, dann schießt der Killer und trifft, dann ME erneut
    m.shots += [Shot(round=k.round, tick=k.tick - 60, steamid=ME, weapon="weapon_m4a1", speed=0.0),
                Shot(round=k.round, tick=k.tick - 40, steamid=k.attacker_steamid, weapon="weapon_ak47", speed=0.0),
                Shot(round=k.round, tick=k.tick - 20, steamid=ME, weapon="weapon_m4a1", speed=0.0)]
    m.duels = compute(m, {})
    d = next(x for x in m.duels if x.loser == ME)
    assert d.contact == k.tick - 40 and shot_before_contact(m, d, ME)
    v = _duel(m, k)
    assert v["early_shot"] and v["react"] is not None  # Rohwert bleibt, der Text lässt ihn weg


def test_unknown_sides_are_not_a_teamkill():
    from cstaktik.mechanics import is_teamkill

    m = build_match()
    k = next(k for k in m.kills if k.victim_steamid == ME)
    k2 = k.model_copy(update={"attacker_side": None, "victim_side": None})
    assert not is_teamkill(m, k2)  # Seiten aus der Runde: verschieden
    m.round_by_num(k.round).sides.pop(k.attacker_steamid, None)
    assert not is_teamkill(m, k2)  # eine Seite unbekannt: kein Teamkill
    assert is_teamkill(m, k.model_copy(update={"attacker_side": "ct", "victim_side": "ct"}))
    f = next(x for x in death_review.run(m, {**CFG["rules"]["death_review"], "mech": M}) if x.tick == k.tick)
    assert f.rule_id == "death_review"
    m.kills = [k2 if x is k else x for x in m.kills]
    f = next(x for x in death_review.run(m, {**CFG["rules"]["death_review"], "mech": M}) if x.tick == k.tick)
    assert f.title != "Tod: Teamschaden"
