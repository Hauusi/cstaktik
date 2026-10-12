"""Lage-Analyse für jeden Tod eines Fokus-Spielers: Fakten aus der Demo + passender Tipp.

Jeder Fakt stammt aus den geparsten Daten (Kills, Positionen, Schaden, Blendungen, Granaten).
Fehlt eine Datenart, wird der zugehörige Fakt weggelassen statt geschätzt.
"""

from __future__ import annotations

from collections import Counter

from cstaktik.model import Finding, MatchData
from cstaktik.mechanics import is_gun
from cstaktik.rules.base import PositionIndex, dist, round_time_s

RULE_ID = "death_review"
TITLE = "Tod-Analyse"
_NADE_DE = {"smoke": "Smoke", "molotov": "Molotov", "flash": "Flash", "he": "HE"}


def _speed(idx: PositionIndex, rnd: int, sid: str, tick: int, tickrate: int) -> float | None:
    """Laufgeschwindigkeit (Units/s) aus den letzten zwei Positions-Samples vor dem Tod."""
    pts = [p for p in idx.path(rnd, sid) if p.tick <= tick]
    if len(pts) < 2:
        return None
    a, b = pts[-2], pts[-1]
    if b.tick - a.tick <= 0 or tick - b.tick > tickrate:
        return None
    return dist(a.pos, b.pos) / ((b.tick - a.tick) / tickrate)


def run(match: MatchData, cfg: dict) -> list[Finding]:
    focus = match.focus_ids()
    idx = PositionIndex(match.positions)
    tr = match.tickrate
    findings: list[Finding] = []
    kills = sorted(match.kills, key=lambda k: k.tick)

    for k in kills:
        sid = k.victim_steamid
        rnd = match.round_by_num(k.round)
        if sid not in focus or rnd is None:
            continue
        side = rnd.sides.get(sid)
        before = [x for x in kills if x.round == k.round and x.tick < k.tick]
        dead = {x.victim_steamid for x in before}
        mates = [s for s, sd in rnd.sides.items() if sd == side and s != sid and s not in dead]
        enemies = [s for s, sd in rnd.sides.items() if sd != side and s not in dead]
        opening = not before

        facts: list[str] = []
        issues: list[tuple[str, str]] = []  # (Kurzlabel, Tipp) in Prioritätsreihenfolge

        facts.append(f"{len(mates) + 1} gegen {len(enemies)}" + (" (Opening-Duell)" if opening else ""))

        blind = next(
            (b for b in match.blinds
             if b.round == k.round and b.victim_steamid == sid and k.tick - cfg["blind_window_s"] * tr <= b.tick <= k.tick
             and b.duration >= cfg["blind_min_s"]),
            None,
        )
        if blind:
            ago = round((k.tick - blind.tick) / tr, 1)
            facts.append(f"geblendet ({blind.duration}s) {ago}s vor dem Tod")
            issues.append(("Geblendet", "Bei Gegner-Flash sofort wegdrehen oder hinter Deckung, nicht blind weiterhalten."))

        hp = None
        if match.damages:
            taken = sum(d.dmg for d in match.damages if d.round == k.round and d.victim_steamid == sid and d.tick < k.tick)
            hp = max(0, 100 - taken)
            if hp < 100:
                facts.append(f"mit {hp} HP ins Duell")
            if hp < cfg["hp_low"] and not opening:
                issues.append(("Wenig HP", f"Mit {hp} HP nicht das nächste Duell suchen: Info geben, auf Trade oder Mitspieler warten."))

        if len(mates) + 1 < len(enemies):
            issues.append(("Unterzahl", "In Unterzahl nicht allein Duelle suchen: Zeit spielen, mit Mitspielern gemeinsam gehen."))

        mech = cfg.get("mech", {})
        my_shots = [s for s in match.shots if s.steamid == sid and s.round == k.round and is_gun(s.weapon)
                    and k.tick - mech.get("no_shot_window_s", 3.0) * tr <= s.tick <= k.tick]
        if match.shots:
            if not my_shots:
                facts.append("kein eigener Schuss vor dem Tod")
                issues.append(("Ohne Gegenwehr",
                               "Vorzielen: Fadenkreuz auf Kopfhöhe dorthin, wo der Gegner auftauchen kann. Nicht unvorbereitet in Winkel laufen."))
            else:
                last = my_shots[-1]
                facts.append(f"{len(my_shots)} eigene Schüsse vor dem Tod")
                if last.speed is not None and last.speed > mech.get("moving_shot_speed_units_s", 80):
                    facts.append(f"letzter Schuss im Laufen ({round(last.speed)} Units/s)")
                    issues.append(("Im Laufen geschossen", "Vor dem Schuss stoppen (Counter-Strafe), dann schießen."))
        else:  # ohne Schuss-Daten: Näherung aus den Positionen
            speed = _speed(idx, k.round, sid, k.tick, tr)
            if speed is not None and speed <= cfg["max_plausible_speed_units_s"] and speed > cfg["moving_speed_units_s"]:
                facts.append(f"in Bewegung ({round(speed)} Units/s)")
                issues.append(("Im Laufen", "Vor dem Schuss stoppen (Counter-Strafe), nicht offen in Winkel laufen."))

        traded = bool(k.attacker_steamid) and any(
            x.round == k.round and x.victim_steamid == k.attacker_steamid and x.attacker_steamid in mates
            and k.tick < x.tick <= k.tick + cfg["trade_window_s"] * tr
            for x in kills
        )
        overlay: dict = {}
        mate_d = []
        for m in mates:
            s = idx.nearest(k.round, m, k.tick, tr)
            if s is not None:
                mate_d.append((dist(k.victim_pos, s.pos), m, s.place) if k.victim_pos else None)
        mate_d = [x for x in mate_d if x]
        if mate_d:
            d, m, place = min(mate_d)
            facts.append(f"nächster Mitspieler {match.name_of(m)} {round(d)} Units weg" + (f" ({place})" if place else ""))
            ms = idx.nearest(k.round, m, k.tick, tr)
            overlay = {"line": [[k.victim_pos.x, k.victim_pos.y], [ms.pos.x, ms.pos.y]],
                       "label": f"{round(d)} Units zu {match.name_of(m)}"}
            if d > cfg["trade_distance_units"] and not traded:
                issues.append(("Allein, kein Trade",
                               "Nur peeken, wenn ein Mitspieler direkt nachziehen kann. Sonst Info geben und zurückfallen."))
            where = Counter(x[2] for x in mate_d if x[2])
            if where:
                facts.append("Mitspieler: " + ", ".join(f"{n}x {p}" for p, n in where.most_common(3)))

        dealt = None
        if match.damages:
            dealt = sum(d.dmg for d in match.damages
                        if d.round == k.round and d.attacker_steamid == sid and d.victim_steamid in rnd.sides
                        and rnd.sides.get(d.victim_steamid) != side and d.tick <= k.tick)
            facts.append(f"{dealt} Schaden davor gemacht")

        thrown = Counter(g.kind for g in match.grenades if g.round == k.round and g.thrower_steamid == sid
                         and g.points and g.points[0][0] < k.tick and g.kind in _NADE_DE)
        if match.grenades:
            facts.append("Utility geworfen: " + (", ".join(f"{n}x {_NADE_DE[t]}" for t, n in thrown.items()) or "keine"))
            if opening and not thrown:
                issues.append(("Ohne Utility", "Ersten Kontakt nicht trocken nehmen: Flash oder Molotov vor dem Peek."))

        unused = []
        if k.victim_inventory is not None:
            for item in k.victim_inventory:
                low = item.lower()
                if any(w in low for w in cfg["grenade_keywords"]) and not any(w in low for w in cfg["ignore_keywords"]):
                    unused.append(item)
            if unused:
                facts.append("nicht genutzt: " + ", ".join(unused))
                issues.append(("Utility nicht genutzt",
                               "Utility vor dem Duell werfen: Flash für den Peek, Molotov/Smoke gegen die Position."))
        if traded:
            facts.append("wurde getradet")

        if k.attacker_pos and k.victim_pos:
            facts.append(f"Gegner {k.attacker_name or '?'} aus {round(dist(k.attacker_pos, k.victim_pos))} Units"
                         + (f" ({k.attacker_place})" if k.attacker_place else ""))

        if issues:
            label, tip = issues[0]
        else:
            label, tip = "Duell verloren", "Lage war ok. Vorzielen auf Kopfhöhe und Peek-Timing prüfen."
        sev = "hoch" if len(issues) >= 2 else "mittel" if issues else "niedrig"
        t = round_time_s(match, k.round, k.tick)
        findings.append(
            Finding(
                rule_id=RULE_ID,
                title=f"Tod: {label}",
                round=k.round,
                tick=k.tick,
                steamid=sid,
                player_name=match.name_of(sid),
                severity=sev,
                text=(f"In {k.victim_place or 'unbekanntem Ort'}" + (f" bei {t}s" if t is not None else "")
                      + f" gegen {k.attacker_name or '?'}" + (f" ({k.weapon})" if k.weapon else "") + "."),
                tip=tip,
                evidence={"lage": facts, "weitere_punkte": [lbl for lbl, _ in issues[1:]], "tick": k.tick,
                          **({"ungenutzt": unused} if unused else {})},
                overlay=overlay,
            )
        )
    return findings
