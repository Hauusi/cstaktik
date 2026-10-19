"""Spieler-Statistik je Fokus-Spieler, alles aus den geparsten Demo-Daten."""

from __future__ import annotations

from collections import Counter

from cstaktik.mechanics import is_teamkill, kill_sides
from cstaktik.model import MatchData, PlayerStats


def player_stats(match: MatchData, trade_window_s: float) -> list[PlayerStats]:
    window = int(trade_window_s * match.tickrate)
    kills = sorted(match.kills, key=lambda k: k.tick)
    first: dict[int, object] = {}
    for k in kills:  # erstes DUELL der Runde: Teamkills, Bombe, Fallschaden zählen nicht als Opening
        if k.attacker_steamid and kill_sides(match, k)[0] and not is_teamkill(match, k):
            first.setdefault(k.round, k)
    out = []
    for sid in sorted(match.focus_ids()):
        rounds = sum(1 for r in match.rounds if sid in r.sides)
        # K/D wie die Scoreboards von Valve und FACEIT: auch Kills nach Rundenende (Exit-Frags) sind echte Kills
        scoreboard = kills + list(match.post_round_kills)
        my_kills = [k for k in scoreboard if k.attacker_steamid == sid and not is_teamkill(match, k)]
        my_deaths = [k for k in scoreboard if k.victim_steamid == sid]
        my_deaths_in_round = [k for k in kills if k.victim_steamid == sid]
        traded = 0
        for d in my_deaths_in_round:
            # Trade = der Killer stirbt kurz danach durch das Team des Opfers (wie history.death_rows, pro.deaths)
            if d.attacker_steamid and any(
                x.round == d.round and x.victim_steamid == d.attacker_steamid and x.attacker_side == d.victim_side
                and d.tick < x.tick <= d.tick + window
                for x in kills
            ):
                traded += 1
        adr = None
        if match.damages and rounds:
            dealt = sum(
                dmg.dmg for dmg in match.damages
                if dmg.attacker_steamid == sid and dmg.victim_steamid != sid
                and match.round_by_num(dmg.round) is not None
                and match.round_by_num(dmg.round).sides.get(dmg.victim_steamid) != match.round_by_num(dmg.round).sides.get(sid)
            )
            adr = round(dealt / rounds, 1)
        thrown = Counter(g.kind for g in match.grenades if g.thrower_steamid == sid)
        out.append(
            PlayerStats(
                steamid=sid,
                name=match.name_of(sid),
                rounds=rounds,
                kills=len(my_kills),
                deaths=len(my_deaths),
                adr=adr,
                opening_kills=sum(1 for k in first.values() if k.attacker_steamid == sid),
                opening_deaths=sum(1 for k in first.values() if k.victim_steamid == sid),
                traded_deaths=traded,
                utility_thrown=dict(thrown),
            )
        )
    return out
