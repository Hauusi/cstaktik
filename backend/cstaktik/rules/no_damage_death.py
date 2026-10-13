"""Muster: Tode, bei denen der Fokus-Spieler in der Runde vorher keinen Schaden gemacht hat."""

from __future__ import annotations

from cstaktik.model import Finding, MatchData
from cstaktik.rules.base import NotEvaluable

RULE_ID = "no_damage_death"
TITLE = "Tod ohne Schaden"


def run(match: MatchData, cfg: dict) -> list[Finding]:
    if not match.damages:
        raise NotEvaluable("Keine Schadensdaten in der Demo")
    findings = []
    for sid in sorted(match.focus_ids()):
        rounds = []
        for k in match.kills:
            if k.victim_steamid != sid:
                continue
            rnd = match.round_by_num(k.round)
            sides = rnd.sides if rnd else {}
            dealt = sum(  # nur Schaden an Gegnern (Teamschaden zählt nicht)
                d.dmg for d in match.damages
                if d.round == k.round and d.attacker_steamid == sid and d.tick <= k.tick
                and sides.get(d.victim_steamid) not in (None, k.victim_side)
            )
            if dealt == 0:
                rounds.append(k.round)
        deaths = sum(1 for k in match.kills if k.victim_steamid == sid)
        if len(rounds) < cfg["min_count"]:
            continue
        findings.append(
            Finding(
                rule_id=RULE_ID,
                title=TITLE,
                round=None,
                tick=None,
                steamid=sid,
                player_name=match.name_of(sid),
                severity="hoch" if deaths and len(rounds) / deaths >= 0.5 else "mittel",
                text=f"{len(rounds)} von {deaths} Toden ohne vorher Schaden zu machen.",
                tip="Duelle nur mit Vorteil nehmen: vorgezielt auf Kopfhöhe, kurz peeken, nach Info zurück.",
                evidence={"runden": sorted(rounds), "tode_gesamt": deaths},
                rounds=sorted(rounds),
            )
        )
    return findings
