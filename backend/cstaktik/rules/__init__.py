"""Regel-Engine: führt alle aktivierten Regeln aus und protokolliert, was nicht auswertbar war."""

from __future__ import annotations

from cstaktik.model import AnalysisResult, MatchData, RuleStatus
from cstaktik.rules import (
    death_review,
    economy,
    entry_deaths,
    no_damage_death,
    positives,
    repeated_death_spot,
    unused_utility,
    untraded_death,
)
from cstaktik.rules.base import NotEvaluable
from cstaktik.stats import player_stats

RULES = [death_review, untraded_death, repeated_death_spot, unused_utility, economy, entry_deaths, no_damage_death, positives]
_SEV = {"hoch": 0, "mittel": 1, "niedrig": 2, "gut": 3}


def analyze(match: MatchData, config: dict) -> AnalysisResult:
    findings, status = [], []
    if not match.focus_ids():
        raise ValueError("Keine Fokus-Spieler gesetzt (SteamIDs in players.yaml oder --me).")
    for rule in RULES:
        cfg = {**config["rules"].get(rule.RULE_ID, {}), "mech": config.get("mechanics", {})}
        if not cfg.get("enabled", False):
            status.append(RuleStatus(rule_id=rule.RULE_ID, title=rule.TITLE, evaluated=False, reason="deaktiviert"))
            continue
        try:
            findings.extend(rule.run(match, cfg))
            status.append(RuleStatus(rule_id=rule.RULE_ID, title=rule.TITLE, evaluated=True))
        except NotEvaluable as exc:
            status.append(RuleStatus(rule_id=rule.RULE_ID, title=rule.TITLE, evaluated=False, reason=str(exc)))
    findings.sort(key=lambda f: (f.round if f.round is not None else 0, _SEV[f.severity], f.tick or 0))
    trade_window = config["rules"].get("untraded_death", {}).get("trade_window_s", 3.0)
    return AnalysisResult(findings=findings, rule_status=status, stats=player_stats(match, trade_window))
