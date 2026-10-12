"""Tod ohne Trade-Partner: kein lebender Mitspieler in der Nähe und kein Gegen-Kill auf den Killer."""

from __future__ import annotations

from cstaktik.model import Finding, MatchData
from cstaktik.rules.base import NotEvaluable, PositionIndex, dist, round_time_s

RULE_ID = "untraded_death"
TITLE = "Tod ohne Trade"


def run(match: MatchData, cfg: dict) -> list[Finding]:
    if not match.positions:
        raise NotEvaluable("Keine Positionsdaten in der Demo")
    focus = match.focus_ids()
    idx = PositionIndex(match.positions)
    window = int(cfg["trade_window_s"] * match.tickrate)
    max_gap = int(cfg["max_sample_gap_s"] * match.tickrate)
    findings: list[Finding] = []

    for k in match.kills:
        if k.victim_steamid not in focus or k.victim_pos is None:
            continue
        rnd = match.round_by_num(k.round)
        side = k.victim_side or (rnd.sides.get(k.victim_steamid) if rnd else None)
        if rnd is None or side is None:
            continue

        dead_before = {x.victim_steamid for x in match.kills if x.round == k.round and x.tick < k.tick}
        mates = [s for s, sd in rnd.sides.items() if sd == side and s != k.victim_steamid and s not in dead_before]
        if not mates:
            continue  # letzter Lebender: kein Trade möglich, keine Aussage

        mate_dists = []
        mate_pos = {}
        for m in mates:
            sample = idx.nearest(k.round, m, k.tick, max_gap)
            if sample is not None:
                mate_dists.append((dist(k.victim_pos, sample.pos), m))
                mate_pos[m] = sample.pos
        if not mate_dists:
            continue  # keine Positionsdaten der Mitspieler zum Zeitpunkt -> nicht raten

        traded_by = None
        if k.attacker_steamid:
            for x in match.kills:
                if (
                    x.round == k.round
                    and x.victim_steamid == k.attacker_steamid
                    and k.tick < x.tick <= k.tick + window
                    and x.attacker_steamid in mates
                ):
                    traded_by = x
                    break
        nearest_d, nearest_id = min(mate_dists)
        if traded_by is not None or nearest_d <= cfg["trade_distance_units"]:
            continue

        first_death = not any(x.round == k.round and x.tick < k.tick for x in match.kills)
        place = k.victim_place or "unbekannter Ort"
        t = round_time_s(match, k.round, k.tick)
        findings.append(
            Finding(
                rule_id=RULE_ID,
                title=TITLE,
                round=k.round,
                tick=k.tick,
                steamid=k.victim_steamid,
                player_name=match.name_of(k.victim_steamid),
                severity="hoch" if first_death else "mittel",
                text=(
                    f"{'Erster Tod der Runde' if first_death else 'Tod'} in {place}"
                    f"{f' ({t}s)' if t is not None else ''} gegen {k.attacker_name or '?'}"
                    f"{f' ({k.weapon})' if k.weapon else ''}. Nächster Mitspieler "
                    f"{match.name_of(nearest_id)}: {round(nearest_d)} Units weg, kein Trade."
                ),
                tip="Nur peeken, wenn ein Mitspieler direkt nachziehen kann. Sonst Info geben und zurückfallen.",
                overlay={
                    "line": [[k.victim_pos.x, k.victim_pos.y], [mate_pos[nearest_id].x, mate_pos[nearest_id].y]],
                    "label": f"{round(nearest_d)} Units zu {match.name_of(nearest_id)}",
                },
                evidence={
                    "tick": k.tick,
                    "ort": place,
                    "naechster_mitspieler": match.name_of(nearest_id),
                    "abstand_units": round(nearest_d),
                    "grenze_units": cfg["trade_distance_units"],
                    "trade_fenster_s": cfg["trade_window_s"],
                },
            )
        )
    return findings
