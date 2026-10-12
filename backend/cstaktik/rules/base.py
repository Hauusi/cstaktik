"""Gemeinsame Bausteine für Regeln."""

from __future__ import annotations

import math
from collections import defaultdict

from cstaktik.model import Kill, MatchData, PositionSample, Vec


class NotEvaluable(Exception):
    """Regel kann mit den vorhandenen Daten nicht ausgewertet werden."""


def dist(a: Vec, b: Vec) -> float:
    return math.dist((a.x, a.y, a.z), (b.x, b.y, b.z))


class PositionIndex:
    """Schneller Zugriff auf Positions-Samples je (Runde, Spieler)."""

    def __init__(self, positions: list[PositionSample]):
        self._by_key: dict[tuple[int, str], list[PositionSample]] = defaultdict(list)
        for p in positions:
            self._by_key[(p.round, p.steamid)].append(p)
        for samples in self._by_key.values():
            samples.sort(key=lambda s: s.tick)

    def nearest(self, round_num: int, steamid: str, tick: int, max_gap: int) -> PositionSample | None:
        best = None
        for s in self._by_key.get((round_num, steamid), []):
            gap = abs(s.tick - tick)
            if gap <= max_gap and (best is None or gap < abs(best.tick - tick)):
                best = s
        return best

    def path(self, round_num: int, steamid: str) -> list[PositionSample]:
        return self._by_key.get((round_num, steamid), [])


def death_tick(match: MatchData, round_num: int, steamid: str) -> int | None:
    for k in match.kills:
        if k.round == round_num and k.victim_steamid == steamid:
            return k.tick
    return None


def kills_in_round(match: MatchData, round_num: int) -> list[Kill]:
    return [k for k in match.kills if k.round == round_num]


def seconds(ticks: int, tickrate: int) -> float:
    return round(ticks / tickrate, 1)


def round_time_s(match: MatchData, round_num: int, tick: int) -> float | None:
    """Sekunden seit Freeze-Ende (None, wenn Freeze-Ende fehlt)."""
    r = match.round_by_num(round_num)
    if r is None or r.freeze_end_tick is None:
        return None
    return seconds(tick - r.freeze_end_tick, match.tickrate)
