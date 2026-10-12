"""Gemeinsame Bausteine für Regeln."""

from __future__ import annotations

import bisect
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
        self._ticks = {k: [s.tick for s in v] for k, v in self._by_key.items()}

    def nearest(self, round_num: int, steamid: str, tick: int, max_gap: int) -> PositionSample | None:
        key = (round_num, steamid)
        samples = self._by_key.get(key)
        if not samples:
            return None
        ticks = self._ticks[key]
        i = bisect.bisect_left(ticks, tick)
        best = None
        for j in (i - 1, i):  # bei gleichem Abstand gewinnt das frühere Sample (wie zuvor)
            if 0 <= j < len(samples):
                gap = abs(ticks[j] - tick)
                if gap <= max_gap and (best is None or gap < abs(best.tick - tick)):
                    best = samples[j]
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
