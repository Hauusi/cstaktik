"""Duell-Analyse: Was passiert in den Sekunden, in denen ein Duell entschieden wird?

Je Kill zwischen zwei Gegnern (Waffe, kein Granaten-/Weltschaden):
- Kontakt = Beginn des Schusswechsels zwischen genau diesen beiden: erster Schuss des Killers im Fenster
  ``window_s`` vor dem Kill. Schüsse des Opfers zählen nur, wenn es den Killer getroffen hat (ab 1 s vor dem
  ersten Treffer); Schüsse auf andere Gegner beginnen kein Duell mit dem Killer.
- Fadenkreuz-Abweichung (Grad) je Spieler im Kontakt-Tick: Winkel zwischen Blickrichtung (yaw/pitch) und
  der Richtung zum Kopf des Gegners (Augenhöhe = Position + ``eye_height``, Näherung für stehend).
- Reaktion (ms): eigener erster Schuss minus Kontakt (0 = hat zuerst geschossen).
- Erste Kugel getroffen: Schaden am Gegner bis 3 Ticks nach dem eigenen ersten Schuss.
- Tempo beim ersten Schuss (Units/s) aus den Schuss-Daten.

Alle Werte aus der Demo; fehlen Blickwinkel, bleibt die Abweichung None.
"""

from __future__ import annotations

import math

from cstaktik.mechanics import is_gun
from cstaktik.model import Duel, MatchData

EYE_HEIGHT = 64.0  # Augenhöhe stehend (Spieleinheiten), Näherung


def contacts(match: MatchData, window_s: float = 3.0) -> list[tuple]:
    """(kill, contact_tick) für alle Kills mit Schüssen der beiden Beteiligten im Fenster."""
    tr = match.tickrate
    by_round: dict[int, list] = {}
    for s in match.shots:
        if is_gun(s.weapon):
            by_round.setdefault(s.round, []).append(s)
    dmg_round: dict[int, list] = {}
    for d in match.damages:
        dmg_round.setdefault(d.round, []).append(d)
    out = []
    for k in match.kills:
        if not k.attacker_steamid or k.attacker_side == k.victim_side or not is_gun(k.weapon):
            continue
        lo = k.tick - int(window_s * tr)
        sh = [s for s in by_round.get(k.round, []) if lo <= s.tick <= k.tick]
        starts = [s.tick for s in sh if s.steamid == k.attacker_steamid]
        hits = [d.tick for d in dmg_round.get(k.round, []) if d.attacker_steamid == k.victim_steamid
                and d.victim_steamid == k.attacker_steamid and lo <= d.tick <= k.tick]
        if hits:  # Opfer hat den Killer getroffen: seine Schüsse ab kurz vor dem ersten Treffer gehören dazu
            first_hit = min(hits)
            starts += [s.tick for s in sh if s.steamid == k.victim_steamid and first_hit - tr <= s.tick <= first_hit]
        if starts:
            out.append((k, min(starts)))
    return out


def angle_error(view: tuple, target: tuple, eye: float = EYE_HEIGHT) -> float | None:
    """Winkel (Grad) zwischen Blickrichtung und Richtung zum Kopf. view/target: (x, y, z, yaw, pitch)."""
    x, y, z, yaw, pitch = view
    tx, ty, tz = target[:3]
    if yaw is None or pitch is None:
        return None
    dx, dy, dz = tx - x, ty - y, (tz + eye) - (z + eye)
    n = math.sqrt(dx * dx + dy * dy + dz * dz)
    if n < 1:
        return None
    yr, pr = math.radians(yaw), math.radians(pitch)
    vx, vy, vz = math.cos(pr) * math.cos(yr), math.cos(pr) * math.sin(yr), -math.sin(pr)  # pitch > 0 = nach unten
    dot = max(-1.0, min(1.0, (vx * dx + vy * dy + vz * dz) / n))
    return round(math.degrees(math.acos(dot)), 1)


def compute(match: MatchData, views: dict[tuple[int, str], tuple], window_s: float = 3.0) -> list[Duel]:
    """``views``: (tick, steamid) -> (x, y, z, yaw, pitch) im Kontakt-Tick (aus parse_ticks)."""
    tr = match.tickrate
    out = []
    for k, c in contacts(match, window_s):
        a, v = k.attacker_steamid, k.victim_steamid
        res = {}
        for me, opp in ((a, v), (v, a)):
            mine = sorted((s for s in match.shots if s.steamid == me and s.round == k.round and is_gun(s.weapon)
                           and c <= s.tick <= k.tick), key=lambda s: s.tick)
            first = mine[0] if mine else None
            err = None
            if (c, me) in views and (c, opp) in views:
                err = angle_error(views[(c, me)], views[(c, opp)])
            hit = None
            if first is not None and match.damages:
                hit = any(d.attacker_steamid == me and d.victim_steamid == opp and first.tick <= d.tick <= first.tick + 3
                          for d in match.damages)
            res[me] = {"err": err, "react": round((first.tick - c) * 1000 / tr) if first else None, "hit": hit,
                       "speed": round(first.speed) if first and first.speed is not None else None,
                       "shots": len(mine)}
        out.append(Duel(round=k.round, tick=k.tick, contact=c, winner=a, loser=v,
                        w_err=res[a]["err"], l_err=res[v]["err"], w_react_ms=res[a]["react"],
                        l_react_ms=res[v]["react"], w_first_hit=res[a]["hit"], l_first_hit=res[v]["hit"],
                        w_speed=res[a]["speed"], l_speed=res[v]["speed"], w_shots=res[a]["shots"],
                        l_shots=res[v]["shots"]))
    return out


def side_of(d: Duel, sid: str) -> dict | None:
    """Werte eines Spielers in einem Duell (aus seiner Sicht)."""
    if sid == d.winner:
        return {"won": True, "err": d.w_err, "react": d.w_react_ms, "hit": d.w_first_hit, "speed": d.w_speed,
                "opp_err": d.l_err, "opp_react": d.l_react_ms, "opp": d.loser}
    if sid == d.loser:
        return {"won": False, "err": d.l_err, "react": d.l_react_ms, "hit": d.l_first_hit, "speed": d.l_speed,
                "opp_err": d.w_err, "opp_react": d.w_react_ms, "opp": d.winner}
    return None


def stats(rows: list[dict]) -> dict:
    """Kennzahlen aus Duell-Sichten: Median Abweichung/Reaktion, Erste-Kugel-Treffer, Zuerst-geschossen, Siegquote."""
    import statistics

    def med(key):
        v = [r[key] for r in rows if r.get(key) is not None]
        return round(statistics.median(v), 1) if v else None

    hits = [r["hit"] for r in rows if r.get("hit") is not None]
    first = [r["react"] == 0 for r in rows if r.get("react") is not None]
    # nur Duelle, in denen der Gegner zuerst schoss; über 1,5 s meist Schuss auf einen anderen Gegner
    reacts = [r["react"] for r in rows if r.get("react") and r["react"] <= 1500]
    errs = [r["err"] for r in rows if r.get("err") is not None]
    speeds = [r["speed"] for r in rows if r.get("speed") is not None]
    return {"n": len(rows), "err": med("err"), "react": round(statistics.median(reacts)) if reacts else None,
            "first_hit": round(100 * sum(hits) / len(hits)) if hits else None,
            "shot_first": round(100 * sum(first) / len(first)) if first else None,
            "won": round(100 * sum(r["won"] for r in rows) / len(rows)) if rows else None,
            # Fallzahlen je Wert (jeder Wert stützt sich auf andere Duelle)
            "err_n": len(errs), "react_n": len(reacts), "hit_n": len(hits), "first_n": len(first),
            # erster Schuss aus der Bewegung (über 80 Units/s), nur wo das Tempo bekannt ist
            "moving_pct": round(100 * sum(v > 80 for v in speeds) / len(speeds)) if speeds else None,
            "moving_n": len(speeds)}
