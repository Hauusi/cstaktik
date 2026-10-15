"""Muster: Tode, bei denen der Fokus-Spieler in der Runde vorher keinen Schaden gemacht hat."""

from __future__ import annotations

from cstaktik.mechanics import is_gun
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
        duel_deaths = [k for k in match.kills if k.victim_steamid == sid and k.attacker_steamid
                       and k.attacker_steamid != sid and k.attacker_side != k.victim_side and is_gun(k.weapon)]
        for k in duel_deaths:  # Bombe, Fallschaden, Granaten, Teamkills sind kein verlorenes Duell
            rnd = match.round_by_num(k.round)
            sides = rnd.sides if rnd else {}
            dealt = sum(  # nur Schaden an Gegnern (Teamschaden zählt nicht)
                d.dmg for d in match.damages
                if d.round == k.round and d.attacker_steamid == sid and d.tick <= k.tick
                and sides.get(d.victim_steamid) not in (None, k.victim_side)
            )
            if dealt == 0:
                rounds.append(k.round)
        deaths = len(duel_deaths)
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
                text=f"In {len(rounds)} von {deaths} Duell-Toden hast du vorher keinen Schaden gemacht.",
                tip="Nimm Duelle nur mit Vorteil. Ziel auf Kopfhöhe vor, peek kurz und geh nach der Info zurück.",
                evidence={"runden": sorted(rounds), "tode_gesamt": deaths},
                rounds=sorted(rounds),
            )
        )
    return findings
