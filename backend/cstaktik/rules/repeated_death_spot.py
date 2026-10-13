"""Mehrfach am selben Ort gestorben (pro Spieler, über das ganze Match)."""

from __future__ import annotations

from collections import defaultdict

from cstaktik.model import Finding, Kill, MatchData
from cstaktik.rules.base import dist

RULE_ID = "repeated_death_spot"
TITLE = "Gleicher Todesort"


def _clusters(deaths: list[Kill], radius: float) -> list[tuple[str, list[Kill]]]:
    by_place: dict[str, list[Kill]] = defaultdict(list)
    no_place: list[Kill] = []
    for k in deaths:
        if k.victim_place:
            by_place[k.victim_place].append(k)
        elif k.victim_pos is not None:
            no_place.append(k)
    groups = list(by_place.items())
    # Fallback: räumliches Clustering ohne Place-Name
    used: set[int] = set()
    for i, k in enumerate(no_place):
        if i in used:
            continue
        group = [k]
        used.add(i)
        for j in range(i + 1, len(no_place)):
            if j not in used and dist(k.victim_pos, no_place[j].victim_pos) <= radius:
                group.append(no_place[j])
                used.add(j)
        x, y = round(k.victim_pos.x), round(k.victim_pos.y)
        groups.append((f"Umkreis {round(radius)} Units um ({x}, {y})", group))
    return groups


def run(match: MatchData, cfg: dict) -> list[Finding]:
    findings: list[Finding] = []
    for sid in sorted(match.focus_ids()):
        deaths = [k for k in match.kills if k.victim_steamid == sid]
        # je Seite getrennt: als CT-Anker und als T-Entry am selben Ort sterben ist nicht "gelesen"
        groups = [(pl, side, g) for side in ("ct", "t")
                  for pl, g in _clusters([k for k in deaths if k.victim_side == side], cfg["radius_units"])]
        for place, side, group in groups:
            if len(group) < cfg["min_deaths"]:
                continue
            rounds = sorted({k.round for k in group})
            killers = sorted({k.attacker_name for k in group if k.attacker_name})
            findings.append(
                Finding(
                    rule_id=RULE_ID,
                    title=TITLE,
                    round=None,
                    tick=None,
                    steamid=sid,
                    player_name=match.name_of(sid),
                    severity="hoch" if len(group) >= 3 else "mittel",
                    text=f"{len(group)}x als {side.upper()} gestorben in {place} (Runden {', '.join(map(str, rounds))}).",
                    tip="Die Position ist gelesen: Spot wechseln, anders timen oder nur mit Utility spielen.",
                    evidence={
                        "ort": place,
                        "tode": len(group),
                        "runden": rounds,
                        "ticks": [k.tick for k in group],
                        "killer": killers,
                    },
                    rounds=rounds,
                )
            )
    return findings
