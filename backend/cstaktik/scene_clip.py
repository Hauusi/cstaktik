"""Szenen-Clip: die letzten Sekunden vor einem Tod als kleine Wiederholung für den Coach.

Alles aus der Demo: Positionen aller Spieler (so oft, wie der Parser sie liefert), Kills und Granaten im Fenster.
Gespeichert in Weltkoordinaten (Units, ganzzahlig) und Sekunden relativ zum Tod (0 = Tod, negativ = davor).
Die Seite rechnet die Koordinaten auf das Radarbild um.
"""

from __future__ import annotations

from collections import defaultdict

from cstaktik.model import MatchData

BEFORE_S = 8.0  # so weit vor dem Tod beginnt der Clip (höchstens; nie vor Rundenstart)
LEAD_S = 2.0  # mindestens so viel vor dem Entscheidungsmoment
AFTER_S = 1.0  # nach dem Tod noch kurz weiter (Trade sichtbar)
TEAM_ME, TEAM_MATE, TEAM_FOE = 0, 1, 2


def _by_round(match: MatchData) -> dict[int, list]:
    out = defaultdict(list)
    for p in match.positions:
        out[p.round].append(p)
    return out


def clip(match: MatchData, sid: str, rnd_num: int, death_tick: int, from_tick: int | None = None,
         by_round: dict | None = None) -> dict | None:
    """Clip eines Todes oder None, wenn es zu wenige Positionen gibt."""
    rnd = match.round_by_num(rnd_num)
    if rnd is None or sid not in rnd.sides:
        return None
    tr = match.tickrate
    start = death_tick - int(BEFORE_S * tr)
    if from_tick is not None:
        start = min(start, from_tick - int(LEAD_S * tr))
        start = max(start, death_tick - int(12 * tr))  # nie länger als 12 s
    start = max(start, rnd.freeze_end_tick or rnd.start_tick)
    end = death_tick + int(AFTER_S * tr)
    samples = [p for p in (by_round or _by_round(match)).get(rnd_num, []) if start <= p.tick <= end]
    if not samples:
        return None
    side = rnd.sides[sid]
    ids = [sid] + sorted(s for s in rnd.sides if s != sid and rnd.sides[s] == side) + \
        sorted(s for s in rnd.sides if rnd.sides[s] != side)
    index = {s: i for i, s in enumerate(ids)}
    rel = lambda t: round((t - death_tick) / tr, 2)  # noqa: E731
    frames: dict[int, list] = defaultdict(list)
    for p in samples:
        if p.steamid in index and p.alive:
            frames[p.tick].append([index[p.steamid], int(p.pos.x), int(p.pos.y)])
    if len(frames) < 4:
        return None
    kills = [[rel(k.tick), index.get(k.attacker_steamid), index[k.victim_steamid]]
             for k in match.kills if k.round == rnd_num and start <= k.tick <= end and k.victim_steamid in index]
    nades = []
    for u in match.utility:
        if u.round != rnd_num:
            continue
        u_end = u.end_tick if u.end_tick is not None else u.start_tick
        if u.start_tick > end or u_end < start:
            continue
        nades.append([rel(u.start_tick), rel(u_end) if u.kind in ("smoke", "molotov") else rel(u.start_tick),
                      u.kind, int(u.pos.x), int(u.pos.y), index.get(u.thrower_steamid)])
    team = lambda s: TEAM_ME if s == sid else TEAM_MATE if rnd.sides[s] == side else TEAM_FOE  # noqa: E731
    return {"ids": [{"n": match.name_of(s), "t": team(s)} for s in ids],
            "frames": [[rel(t), pts] for t, pts in sorted(frames.items())],
            "kills": kills, "nades": nades}


def attach(match: MatchData, scenes: list[dict]) -> None:
    """Clip an jede Szene hängen (Feld ``clip``), soweit die Demo Positionen hat."""
    if not match.positions:
        return
    by_round = _by_round(match)
    for sc in scenes:
        if sc.get("sid") and sc.get("round") is not None and sc.get("tick") is not None:
            c = clip(match, sc["sid"], sc["round"], sc["tick"], sc.get("from"), by_round)
            if c:
                sc["clip"] = c
