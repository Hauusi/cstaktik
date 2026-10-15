"""Economy: uneinheitlicher Kauf im Team und Force-Buy, der die Folgerunde kostet."""

from __future__ import annotations

from cstaktik.model import Finding, MatchData, PlayerEconomy, Round
from cstaktik.rules.base import NotEvaluable

RULE_ID = "economy"
TITLE = "Economy"


def _team(r: Round, side: str) -> list[PlayerEconomy]:
    return [e for e in r.economy if e.side == side and e.equip_value is not None]


def _avg(team: list[PlayerEconomy]) -> int:
    return round(sum(e.equip_value for e in team) / len(team))


def _skip(num: int, cfg: dict) -> bool:
    return num in cfg["pistol_rounds"] or num >= cfg["overtime_from_round"]


def run(match: MatchData, cfg: dict) -> list[Finding]:
    if not any(r.economy for r in match.rounds):
        raise NotEvaluable("Keine Geld-/Equipment-Daten in der Demo")
    focus = match.focus_ids()
    eco_max, full_min = cfg["eco_max_equip"], cfg["full_buy_min_equip"]
    findings: list[Finding] = []

    for r in match.rounds:
        side = match.focus_side(r.num)
        if side is None or _skip(r.num, cfg):
            continue
        team = _team(r, side)
        if len(team) < 2:
            continue

        full = [e for e in team if e.equip_value >= full_min]
        eco = [e for e in team if e.equip_value <= eco_max]
        if full and eco and any(e.steamid in focus for e in full + eco):
            findings.append(
                Finding(
                    rule_id=RULE_ID,
                    title="Uneinheitlicher Kauf",
                    round=r.num,
                    tick=r.economy_tick,
                    steamid=None,
                    player_name=None,
                    severity="mittel",
                    text=(
                        f"Full-Buy: {', '.join(match.name_of(e.steamid) for e in full)}. "
                        f"Save: {', '.join(match.name_of(e.steamid) for e in eco)}."
                    ),
                    tip="Sprecht euch vor der Runde ab: alle kaufen oder alle sparen. Plant Drops ein.",
                    evidence={
                        "tick": r.economy_tick,
                        "equip": {match.name_of(e.steamid): e.equip_value for e in team},
                        "geld_vor_kauf": {match.name_of(e.steamid): e.money_before_buy for e in team},
                        "grenzen": {"eco_max": eco_max, "full_min": full_min},
                    },
                )
            )

        avg = _avg(team)
        lost = r.winner is not None and r.winner != side
        nxt = match.round_by_num(r.num + 1)
        if not (eco_max < avg < full_min and lost and nxt) or _skip(nxt.num, cfg):
            continue
        if match.focus_side(nxt.num) != side:
            continue  # Halbzeitwechsel
        next_team = _team(nxt, side)
        if len(next_team) < 2:
            continue
        next_avg = _avg(next_team)
        if next_avg >= full_min:
            continue
        findings.append(
            Finding(
                rule_id=RULE_ID,
                title="Force-Buy kostet Folgerunde",
                round=r.num,
                tick=r.economy_tick,
                steamid=None,
                player_name=None,
                severity="mittel",
                text=f"Force mit Ø Equip {avg} verloren. In Runde {nxt.num} blieb nur Ø Equip {next_avg}.",
                tip="Forced nur, wenn die Runde danach trotzdem ein Full-Buy wird. Sonst spart sauber.",
                evidence={
                    "tick": r.economy_tick,
                    "runde_equip_avg": avg,
                    "folgerunde": nxt.num,
                    "folgerunde_equip_avg": next_avg,
                    "grenzen": {"eco_max": eco_max, "full_min": full_min},
                },
                rounds=[r.num, nxt.num],
            )
        )
    return findings
