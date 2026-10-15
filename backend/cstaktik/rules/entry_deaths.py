"""Muster: Fokus-Spieler stirbt oft als Erster der Runde (Opening-Duell verloren)."""

from __future__ import annotations

from collections import Counter

from cstaktik.model import Finding, MatchData

RULE_ID = "entry_deaths"
TITLE = "Oft erster Tod"


def run(match: MatchData, cfg: dict) -> list[Finding]:
    first_kill: dict[int, object] = {}
    for k in sorted(match.kills, key=lambda k: k.tick):
        first_kill.setdefault(k.round, k)
    findings = []
    for sid in sorted(match.focus_ids()):
        lost = sorted(r for r, k in first_kill.items() if k.victim_steamid == sid)
        won = sorted(r for r, k in first_kill.items() if k.attacker_steamid == sid)
        if len(lost) < cfg["min_count"]:
            continue
        places = [first_kill[r].victim_place for r in lost if first_kill[r].victim_place]
        mc = Counter(places).most_common(2)
        # "meist" nur, wenn ein Ort klar vorn liegt (mindestens 2x und häufiger als der zweite)
        top_place = mc[0][0] if mc and mc[0][1] >= 2 and (len(mc) == 1 or mc[0][1] > mc[1][1]) else None
        findings.append(
            Finding(
                rule_id=RULE_ID,
                title=TITLE,
                round=None,
                tick=None,
                steamid=sid,
                player_name=match.name_of(sid),
                severity="hoch" if len(lost) > len(won) else "mittel",
                text=(
                    f"{len(lost)}x als Erster gestorben, {len(won)}x den ersten Kill geholt"
                    f"{f'; meist in {top_place}' if top_place else ''}."
                ),
                tip="Nicht als Erster ohne Info oder Flash peeken. Lieber den zweiten Platz nehmen und traden.",
                evidence={"erste_tode_runden": lost, "erste_kills_runden": won, "haeufigster_ort": top_place},
                rounds=lost,
            )
        )
    return findings
