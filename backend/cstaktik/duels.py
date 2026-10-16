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
- Wer sah wen zuerst: aus ``approximate_spotted_by`` (das Spiel markiert je Spieler, welche Gegner ihn sehen). Je
  Spieler der Beginn der letzten durchgehenden Sichtung des Gegners (Lücken bis ``SEEN_GAP_S`` überbrückt) zwischen
  ``SEEN_BEFORE_S`` vor dem Kontakt und dem Kill. Unter ``SEEN_TIE_S`` Abstand gilt es als gleichzeitig.

Alle Werte aus der Demo; fehlen Blickwinkel, bleibt die Abweichung None.
"""

from __future__ import annotations

import math

from cstaktik.mechanics import is_gun, is_teamkill
from cstaktik.model import Duel, MatchData

EYE_HEIGHT = 64.0  # Augenhöhe stehend (Spieleinheiten), Näherung
SEEN_BEFORE_S = 3.0  # so weit vor dem Kontakt wird die Sichtung gesucht
SEEN_STEP = 4  # Abtastung der Sichtung in Ticks (64 Tick: alle 62,5 ms)
SEEN_GAP_S = 0.5  # kürzere Sichtlücken zählen als durchgehend gesehen
SEEN_TIE_S = 0.15  # kleinerer Abstand = gleichzeitig gesehen


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
        if not k.attacker_steamid or is_teamkill(match, k) or not is_gun(k.weapon):
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


def seen_ticks(match: MatchData, window_s: float = 3.0) -> list[int]:
    """Ticks, an denen die Sichtung für alle Duelle abgetastet wird (Kontakt - SEEN_BEFORE_S bis Kill)."""
    tr = match.tickrate
    out: set[int] = set()
    for k, c in contacts(match, window_s):
        lo = max(0, c - int(SEEN_BEFORE_S * tr))
        out.update(range(lo - lo % SEEN_STEP, k.tick + 1, SEEN_STEP))
    return sorted(out)


def first_seen(seen: dict[tuple[int, str], frozenset], ticks: list[int], viewer: str, target: str,
               tickrate: int) -> int | None:
    """Beginn der letzten durchgehenden Sichtung: ab welchem Tick ``viewer`` ``target`` sah (None = gar nicht)."""
    gap = int(SEEN_GAP_S * tickrate)
    start = last = None
    for t in ticks:
        if viewer in seen.get((t, target), ()):
            if last is None or t - last > gap:
                start = t
            last = t
    return start


def angle_parts(view: tuple, target: tuple, eye: float = EYE_HEIGHT) -> tuple[float, float] | None:
    """Fadenkreuz-Abweichung zerlegt: (seitlich in Grad, Betrag; Höhe in Grad, + = unter dem Kopf, - = darüber)."""
    x, y, z, yaw, pitch = view
    tx, ty, tz = target[:3]
    if yaw is None or pitch is None:
        return None
    dx, dy, dz = tx - x, ty - y, tz - z
    flat = math.hypot(dx, dy)
    if flat < 1:
        return None
    side = abs((yaw - math.degrees(math.atan2(dy, dx)) + 180) % 360 - 180)
    want_pitch = -math.degrees(math.atan2(dz, flat))  # pitch > 0 = nach unten (wie im Spiel)
    return round(side, 1), round(pitch - want_pitch, 1)


def compute(match: MatchData, views: dict[tuple[int, str], tuple], window_s: float = 3.0,
            seen: dict[tuple[int, str], frozenset] | None = None) -> list[Duel]:
    """``views``: (tick, steamid) -> (x, y, z, yaw, pitch) im Kontakt-Tick (aus parse_ticks).
    ``seen``: (tick, steamid) -> Steam-IDs der Gegner, die diesen Spieler in dem Tick sehen (None = unbekannt)."""
    tr = match.tickrate
    out = []
    all_ticks = sorted({t for t, _s in seen}) if seen else []
    for k, c in contacts(match, window_s):
        a, v = k.attacker_steamid, k.victim_steamid
        res = {}
        for me, opp in ((a, v), (v, a)):
            mine = sorted((s for s in match.shots if s.steamid == me and s.round == k.round and is_gun(s.weapon)
                           and c <= s.tick <= k.tick), key=lambda s: s.tick)
            first = mine[0] if mine else None
            err = parts = None
            if (c, me) in views and (c, opp) in views:
                err = angle_error(views[(c, me)], views[(c, opp)])
                parts = angle_parts(views[(c, me)], views[(c, opp)])
            hit = None
            if first is not None and match.damages:
                hit = any(d.attacker_steamid == me and d.victim_steamid == opp and first.tick <= d.tick <= first.tick + 3
                          for d in match.damages)
            res[me] = {"err": err, "react": round((first.tick - c) * 1000 / tr) if first else None, "hit": hit,
                       "speed": round(first.speed) if first and first.speed is not None else None,
                       "shots": len(mine), "side": parts[0] if parts else None,
                       "height": parts[1] if parts else None}
        out.append(Duel(round=k.round, tick=k.tick, contact=c, winner=a, loser=v,
                        w_err=res[a]["err"], l_err=res[v]["err"], w_react_ms=res[a]["react"],
                        l_react_ms=res[v]["react"], w_first_hit=res[a]["hit"], l_first_hit=res[v]["hit"],
                        w_speed=res[a]["speed"], l_speed=res[v]["speed"], w_shots=res[a]["shots"],
                        l_shots=res[v]["shots"], w_side=res[a]["side"], l_side=res[v]["side"],
                        w_height=res[a]["height"], l_height=res[v]["height"]))
        if seen:
            import bisect

            lo = c - int(SEEN_BEFORE_S * tr)
            win = all_ticks[bisect.bisect_left(all_ticks, lo):bisect.bisect_right(all_ticks, k.tick)]
            if any((t, a) in seen or (t, v) in seen for t in win):
                out[-1].seen_known = True
                out[-1].w_seen = first_seen(seen, win, a, v, tr)
                out[-1].l_seen = first_seen(seen, win, v, a, tr)
    return out


def shot_before_contact(match: MatchData, d: Duel, sid: str, window_s: float = 3.0) -> bool:
    """Hat ``sid`` im Fenster vor dem Kill schon VOR dem Kontakt geschossen? Der Kontakt beginnt nur mit Schüssen,
    die getroffen haben; ein früherer Fehlschuss des Opfers fehlt dort. Dann ist "Reaktion" nach dem Kontakt
    keine Reaktion, sondern ein zweiter Versuch."""
    lo = d.tick - int(window_s * match.tickrate)
    return any(s.steamid == sid and s.round == d.round and is_gun(s.weapon) and lo <= s.tick < d.contact
               for s in match.shots)


def seen_first(mine: int | None, theirs: int | None, known: bool, tickrate: int) -> str | None:
    """'ich' / 'gegner' / 'gleich' aus den Sichtungs-Ticks; None = unbekannt oder keiner sah den anderen."""
    if not known or (mine is None and theirs is None):
        return None
    if theirs is None:
        return "ich"
    if mine is None:
        return "gegner"
    if abs(mine - theirs) < SEEN_TIE_S * tickrate:
        return "gleich"
    return "ich" if mine < theirs else "gegner"


def side_of(d: Duel, sid: str, tickrate: int = 64) -> dict | None:
    """Werte eines Spielers in einem Duell (aus seiner Sicht). ``seen``: wer sah zuerst (seen_first)."""
    if sid == d.winner:
        return {"won": True, "err": d.w_err, "react": d.w_react_ms, "hit": d.w_first_hit, "speed": d.w_speed,
                "opp_err": d.l_err, "opp_react": d.l_react_ms, "opp": d.loser,
                "seen": seen_first(d.w_seen, d.l_seen, d.seen_known, tickrate),
                "seen_ms": _lead_ms(d.w_seen, d.l_seen, tickrate), "side": d.w_side, "height": d.w_height,
                "tts": _tts(d, d.w_seen, d.w_react_ms, tickrate)}
    if sid == d.loser:
        return {"won": False, "err": d.l_err, "react": d.l_react_ms, "hit": d.l_first_hit, "speed": d.l_speed,
                "opp_err": d.w_err, "opp_react": d.w_react_ms, "opp": d.winner,
                "seen": seen_first(d.l_seen, d.w_seen, d.seen_known, tickrate),
                "seen_ms": _lead_ms(d.l_seen, d.w_seen, tickrate), "side": d.l_side, "height": d.l_height,
                "tts": _tts(d, d.l_seen, d.l_react_ms, tickrate)}
    return None


TTS_MAX_MS = 2000  # länger: meist kein echtes Duell ab Sichtung (z. B. erst andere Gegner, dann dieser)


def _tts(d: Duel, seen: int | None, react_ms: int | None, tickrate: int) -> int | None:
    """Vom Sehen zum Schuss (ms): eigene Sichtung des Gegners bis zum eigenen ersten Schuss im Duell.
    None, wenn nicht gesehen, nicht geschossen, vor der Sichtung geschossen (Prefire) oder über TTS_MAX_MS."""
    if seen is None or react_ms is None or not d.seen_known:
        return None
    ms = round((d.contact - seen) * 1000 / tickrate) + react_ms
    return ms if 0 <= ms <= TTS_MAX_MS else None


def _lead_ms(mine: int | None, theirs: int | None, tickrate: int) -> int | None:
    """Wie viel früher (ms, positiv) oder später (negativ) ich den Gegner sah; None, wenn einer ihn nie sah."""
    return None if mine is None or theirs is None else round((theirs - mine) * 1000 / tickrate)


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
            "moving_n": len(speeds), **seen_stats(rows), **aim_parts(rows), **tts_stats(rows)}


def tts_stats(rows: list[dict]) -> dict:
    """Median 'vom Sehen zum Schuss' (ms) über die Duelle, in denen man den Gegner sah und schoss."""
    import statistics

    v = [r["tts"] for r in rows if r.get("tts") is not None]
    return {"tts": round(statistics.median(v)) if v else None, "tts_n": len(v)}


AIM_NEAR_DEG = 20.0  # Zerlegung nur, wenn das Fadenkreuz ungefähr auf den Gegner zeigte (sonst ist es nur "Seite")


def aim_parts(rows: list[dict]) -> dict:
    """Woraus der Fadenkreuz-Fehler besteht: Median seitlich (Grad) und Median Höhe (Grad, + = zu tief), nur
    Duelle mit Fadenkreuz unter ``AIM_NEAR_DEG`` am Gegner."""
    import statistics

    near = [r for r in rows if r.get("err") is not None and r["err"] <= AIM_NEAR_DEG
            and r.get("side") is not None and r.get("height") is not None]
    if not near:
        return {"aim_n": 0, "err_side": None, "err_height": None, "low_pct": None}
    return {"aim_n": len(near), "err_side": round(statistics.median(r["side"] for r in near), 1),
            "err_height": round(statistics.median(r["height"] for r in near), 1),
            # Anteil der Duelle, in denen das Fadenkreuz mehr als 2 Grad unter dem Kopf lag
            "low_pct": round(100 * sum(r["height"] > 2 for r in near) / len(near))}


def seen_stats(rows: list[dict]) -> dict:
    """Wer sah zuerst: Anteile und Siegquote je Fall. Nur Duelle mit bekannter Sichtung."""
    known = [r for r in rows if r.get("seen")]

    def pct(part, whole):
        return round(100 * len(part) / len(whole)) if whole else None

    me = [r for r in known if r["seen"] == "ich"]
    opp = [r for r in known if r["seen"] == "gegner"]
    return {"seen_n": len(known), "seen_me": pct(me, known), "seen_opp": pct(opp, known),
            "seen_me_n": len(me), "seen_opp_n": len(opp),
            "won_seen_me": pct([r for r in me if r["won"]], me),
            "won_seen_opp": pct([r for r in opp if r["won"]], opp)}
