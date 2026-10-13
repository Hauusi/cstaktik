"""Echtdaten-Check: prüft eine geparste Demo auf Plausibilität und zeigt, wo die Schwellen der Regeln liegen.

Ausgabe ist reiner Text zum Kopieren (cstaktik diagnose <demo>). Damit lassen sich die Heuristiken in
rules.yaml an echten Daten kalibrieren, statt sie zu raten.
"""

from __future__ import annotations

import statistics
from collections import Counter

from cstaktik.model import MatchData
from cstaktik.rules.base import PositionIndex, dist


def _pct(a: int, b: int) -> str:
    return f"{round(100 * a / b)} %" if b else "–"


def _q(vals: list[float]) -> str:
    """Median, 10/90-Perzentil."""
    v = sorted(x for x in vals if x is not None)
    if not v:
        return "keine Werte"
    q = lambda p: v[min(len(v) - 1, int(p * (len(v) - 1) + .5))]  # noqa: E731
    return f"Median {round(statistics.median(v), 1)} · 10 % {round(q(.1), 1)} · 90 % {round(q(.9), 1)} · n={len(v)}"


def report(match: MatchData, findings: list, config: dict) -> str:
    L: list[str] = []
    add = L.append
    focus = match.focus_ids()
    tr = match.tickrate
    add(f"== cstaktik diagnose · {match.map_name} · {len(match.rounds)} Runden · Tickrate {tr} ({match.tickrate_source})")
    add(f"Spieler: {len(match.players)} · Fokus gefunden: {', '.join(match.name_of(s) for s in focus) or 'KEINER (players.yaml prüfen)'}")
    if match.missing:
        add("Fehlende Daten: " + " | ".join(match.missing))

    add("\n-- Datenfelder")
    pos = match.positions
    add(f"Positionen: {len(pos)} · mit Blickrichtung {_pct(sum(p.yaw is not None for p in pos), len(pos))}"
        f" · mit Waffe {_pct(sum(bool(p.weapon) for p in pos), len(pos))} · mit Ort {_pct(sum(bool(p.place) for p in pos), len(pos))}")
    sp = [p.spotted for p in pos if p.spotted is not None]
    add(f"spotted: {'FEHLT' if not sp else f'{len(sp)} Werte, davon sichtbar {_pct(sum(sp), len(sp))}'}")
    add(f"Kills {len(match.kills)} (mit Positionen {_pct(sum(bool(k.victim_pos and k.attacker_pos) for k in match.kills), len(match.kills))}, "
        f"mit Inventar {_pct(sum(k.victim_inventory is not None for k in match.kills), len(match.kills))}) · "
        f"Schaden {len(match.damages)} · Schüsse {len(match.shots)} · Blendungen {len(match.blinds)} · "
        f"Granaten {len(match.grenades)} · Utility-Flächen {len(match.utility)} · Bombe {len(match.bomb)}")
    ut = [u for u in match.utility if u.kind in ("smoke", "molotov")]
    add(f"Smoke/Molotov mit echtem Ende: {_pct(sum(u.end_known for u in ut), len(ut))}"
        f" · Dauer Smoke s: {_q([(u.end_tick - u.start_tick) / tr for u in ut if u.kind == 'smoke' and u.end_known and u.end_tick])}")
    eco = [e for r in match.rounds for e in r.economy]
    add(f"Economy-Werte: {len(eco)} (Runden mit Economy {_pct(sum(bool(r.economy) for r in match.rounds), len(match.rounds))})")

    add("\n-- Schwellen (rules.yaml) gegen echte Werte")
    speeds = [s.speed for s in match.shots if s.steamid in focus and s.speed is not None]
    mech = config.get("mechanics", {})
    add(f"Laufgeschw. beim Schuss (Fokus) Units/s: {_q(speeds)}")
    add(f"  Schwelle 'im Laufen' = {mech.get('moving_shot_speed_units_s')} → betroffen {_pct(sum(s > mech.get('moving_shot_speed_units_s', 80) for s in speeds), len(speeds))}"
        f" · über 400 (unplausibel): {sum(s > 400 for s in speeds)}")
    idx = PositionIndex(match.positions)
    mate_d, a_d, hp = [], [], []
    for k in match.kills:
        if k.victim_steamid not in focus:
            continue
        rnd = match.round_by_num(k.round)
        if rnd is None:
            continue
        if k.attacker_pos and k.victim_pos:
            a_d.append(dist(k.attacker_pos, k.victim_pos))
        side = rnd.sides.get(k.victim_steamid)
        dead = {x.victim_steamid for x in match.kills if x.round == k.round and x.tick < k.tick}
        ds = []
        for m in [s for s, sd in rnd.sides.items() if sd == side and s != k.victim_steamid and s not in dead]:
            p = idx.nearest(k.round, m, k.tick, tr)
            if p is not None and k.victim_pos is not None:
                ds.append(dist(p.pos, k.victim_pos))
        if ds:
            mate_d.append(min(ds))
    hp = [(f.evidence.get("f") or {}).get("hp") for f in findings if f.rule_id == "death_review"]
    dr = config["rules"]["death_review"]
    add(f"Abstand zum Killer bei eigenen Toden: {_q(a_d)} (Schwelle nah = {dr.get('close_units')})")
    add(f"Abstand nächster Mitspieler bei eigenen Toden: {_q(mate_d)} (Schwelle Trade = {dr.get('trade_distance_units')})")
    add(f"HP vor dem tödlichen Duell: {_q(hp)} (Schwelle wenig = {dr.get('hp_low')})")

    add("\n-- Ergebnis der Analyse")
    dec = [f for f in findings if f.rule_id == "death_review"]
    add(f"Tod-Analysen: {len(dec)} · Titel: " + ", ".join(f"{t} {n}x" for t, n in Counter(f.title for f in dec).most_common()))
    lessons = Counter((f.evidence.get("coach") or {}).get("id") for f in dec)
    add("Lektionen: " + ", ".join(f"{k} {n}x" for k, n in lessons.most_common() if k))
    secs = [(f.tick - f.overlay["decision"][2]) / tr for f in dec if f.overlay.get("decision")]
    add(f"Entscheidung vor dem Tod (s): {_q(secs)}")
    add(f"Aktion im Entscheidungsmoment: " + ", ".join(f"{k} {n}x" for k, n in Counter(f.evidence.get('aktion') for f in dec).most_common()))
    costs = [f.evidence.get("cost_pct") for f in dec if f.evidence.get("cost_pct") is not None]
    add(f"Kosten Rundenchance (Prozentpunkte): {_q(costs)}")
    add(f"Duelle erkannt: {len(match.duels)} · mit Fadenkreuz-Wert {_pct(sum(d.w_err is not None for d in match.duels), len(match.duels))}")
    duels = [(f.evidence.get("f") or {}).get("duel") for f in dec if (f.evidence.get("f") or {}).get("duel")]
    from cstaktik.duels import side_of

    allv = [side_of(d, sid) for d in match.duels for sid in (d.winner, d.loser) if sid in focus]
    if allv:
        add(f"Alle Duelle der Fokus-Spieler: Fadenkreuz Grad {_q([v['err'] for v in allv])}")
        add(f"  Reaktion ms (Gegner schoss zuerst) {_q([v['react'] for v in allv if v['react'] and v['react'] <= 1500])}")
        add(f"  Erste Kugel trifft {_pct(sum(bool(v['hit']) for v in allv), sum(v['hit'] is not None for v in allv))}"
            f" · zuerst geschossen {_pct(sum(v['react'] == 0 for v in allv), sum(v['react'] is not None for v in allv))}")
    if duels:
        add(f"Duell: Fadenkreuz-Abweichung Grad {_q([d.get('err') for d in duels])}")
        add(f"Duell: Reaktion ms {_q([d.get('react') for d in duels if d.get('react') and d['react'] <= 1500])}")
    add("\nBitte diese Ausgabe komplett an Claude schicken.")
    return "\n".join(L)
