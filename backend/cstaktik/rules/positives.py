"""Lob: was gut lief (Trade gegeben, Multi-Kill, Clutch gewonnen). Severity "gut"."""

from __future__ import annotations

from cstaktik.model import Finding, MatchData

RULE_ID = "positives"
TITLE = "Stark"


def run(match: MatchData, cfg: dict) -> list[Finding]:
    focus = match.focus_ids()
    window = int(cfg["trade_window_s"] * match.tickrate)
    findings: list[Finding] = []
    kills = sorted(match.kills, key=lambda k: k.tick)

    for k in kills:
        # Trade: Fokus-Spieler tötet den Killer eines Mitspielers kurz danach
        if k.attacker_steamid not in focus:
            continue
        for prev in kills:
            if (
                prev.round == k.round
                and prev.attacker_steamid == k.victim_steamid
                and prev.victim_side == k.attacker_side
                and prev.victim_steamid != k.attacker_steamid
                and 0 < k.tick - prev.tick <= window
            ):
                secs = round((k.tick - prev.tick) / match.tickrate, 1)
                overlay = {}
                if k.attacker_pos and k.victim_pos:
                    overlay = {"line": [[k.attacker_pos.x, k.attacker_pos.y], [k.victim_pos.x, k.victim_pos.y]],
                               "label": f"Trade nach {str(secs).replace('.', ',')} s"}
                findings.append(Finding(
                    rule_id=RULE_ID, title="Trade gegeben", round=k.round, tick=k.tick, steamid=k.attacker_steamid,
                    player_name=match.name_of(k.attacker_steamid), severity="gut",
                    text=f"{prev.victim_name} gerächt. {k.victim_name} fiel {str(secs).replace('.', ',')} s nach seinem Kill.",
                    tip="Genau so. Bleib nah am Mitspieler und zieh sofort nach.",
                    evidence={"tick": k.tick, "getradeter_mitspieler": prev.victim_name, "sekunden": secs},
                    overlay=overlay,
                ))
                break

    for sid in sorted(focus):
        for r in match.rounds:
            rk = [k for k in kills if k.round == r.num and k.attacker_steamid == sid and k.victim_side != r.sides.get(sid)]
            if len(rk) >= cfg["multi_kill_min"]:
                findings.append(Finding(
                    rule_id=RULE_ID, title=f"{len(rk)} Kills", round=r.num, tick=rk[-1].tick, steamid=sid,
                    player_name=match.name_of(sid), severity="gut",
                    text=f"{len(rk)} Kills in Runde {r.num}: {', '.join(k.victim_name for k in rk)}.",
                    tip="Starke Runde. Schau dir an, was die Duelle hier leicht gemacht hat.",
                    evidence={"ticks": [k.tick for k in rk]},
                ))
            # Clutch: Fokus-Spieler letzter Lebender, Gegner noch am Leben, Runde gewonnen
            side = r.sides.get(sid)
            if side is None or r.winner != side:
                continue
            mates = [s for s, sd in r.sides.items() if sd == side and s != sid]
            enemies = [s for s, sd in r.sides.items() if sd != side]
            rkills = [k for k in kills if k.round == r.num]
            dead: set[str] = set()
            for k in rkills:
                dead.add(k.victim_steamid)
                if sid in dead:
                    break
                if all(m in dead for m in mates):
                    alive_enemies = [e for e in enemies if e not in dead]
                    if alive_enemies:
                        findings.append(Finding(
                            rule_id=RULE_ID, title=f"Clutch 1v{len(alive_enemies)}", round=r.num, tick=k.tick,
                            steamid=sid, player_name=match.name_of(sid), severity="gut",
                            text=f"Allein gegen {len(alive_enemies)} und die Runde geholt.",
                            tip="Ruhe bewahrt. Merk dir, wie du die Gegner einzeln isoliert hast.",
                            evidence={"tick": k.tick, "gegner_am_leben": len(alive_enemies)},
                        ))
                    break
    return findings
