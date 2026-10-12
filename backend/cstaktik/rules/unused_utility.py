"""Gestorben mit ungenutzter Utility im Inventar."""

from __future__ import annotations

from cstaktik.model import Finding, MatchData
from cstaktik.rules.base import NotEvaluable

RULE_ID = "unused_utility"
TITLE = "Utility nicht genutzt"


def _utility(inventory: list[str], cfg: dict) -> list[str]:
    out = []
    for item in inventory:
        low = item.lower()
        if any(ig in low for ig in cfg["ignore_keywords"]):
            continue
        if any(kw in low for kw in cfg["grenade_keywords"]):
            out.append(item)
    return out


def run(match: MatchData, cfg: dict) -> list[Finding]:
    focus = match.focus_ids()
    deaths = [k for k in match.kills if k.victim_steamid in focus]
    if deaths and all(k.victim_inventory is None for k in deaths):
        raise NotEvaluable("Kein Inventar zum Todeszeitpunkt in den Daten")
    findings: list[Finding] = []
    for k in deaths:
        if k.victim_inventory is None:
            continue
        nades = _utility(k.victim_inventory, cfg)
        if len(nades) < cfg["min_unused"]:
            continue
        findings.append(
            Finding(
                rule_id=RULE_ID,
                title=TITLE,
                round=k.round,
                tick=k.tick,
                steamid=k.victim_steamid,
                player_name=match.name_of(k.victim_steamid),
                severity="mittel" if len(nades) >= 2 else "niedrig",
                text=f"Gestorben in {k.victim_place or 'unbekannter Ort'} mit {', '.join(nades)} im Inventar.",
                tip="Utility vor dem Duell werfen (Flash für den Peek, Molly/Smoke gegen die Position).",
                evidence={"tick": k.tick, "inventar": k.victim_inventory, "ungenutzt": nades},
            )
        )
    return findings
