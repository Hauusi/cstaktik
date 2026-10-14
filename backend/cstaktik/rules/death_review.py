"""Tod-Analyse für jeden Tod eines Fokus-Spielers.

Ausgabe wie ein Coach: ein Satz, was passiert ist (``text``), ein konkreter Tipp mit den echten
Namen/Orten der Situation (``tip``), weitere Punkte kurz (``weitere_punkte``) und die Rohdaten
eingeklappt (``lage``). Jeder Fakt stammt aus den geparsten Daten; fehlt eine Datenart, wird der
Fakt weggelassen statt geschätzt.

Prioritäten der Probleme (das erste wird Titel + Tipp):
Geblendet > Ohne Gegenwehr > Allein ohne Trade > Utility nicht genutzt > Wenig HP > Im Laufen > Unterzahl.
"Unterzahl" zählt nur, wenn sie in der Runde entstanden ist (nicht bei 4 gegen 5 von Anfang an).
"""

from __future__ import annotations

from cstaktik.mechanics import is_gun, weapon_key, weapon_label
from cstaktik.model import Finding, MatchData
from cstaktik.rules.base import PositionIndex, dist, round_time_s

RULE_ID = "death_review"
TITLE = "Tod-Analyse"
_NADE_DE = {"smoke": "Smoke", "molotov": "Molotov", "flash": "Flash", "he": "HE"}
_PRIORITY = ["Geblendet", "Ohne Gegenwehr", "Allein, kein Trade", "Utility nicht genutzt", "Wenig HP",
             "Im Laufen geschossen", "Im Laufen", "Unterzahl"]


def _speed(idx: PositionIndex, rnd: int, sid: str, tick: int, tickrate: int) -> float | None:
    """Laufgeschwindigkeit (Units/s) aus den letzten zwei Positions-Samples vor dem Tod."""
    pts = [p for p in idx.path(rnd, sid) if p.tick <= tick]
    if len(pts) < 2:
        return None
    a, b = pts[-2], pts[-1]
    if b.tick - a.tick <= 0 or tick - b.tick > tickrate:
        return None
    return dist(a.pos, b.pos) / ((b.tick - a.tick) / tickrate)


def _clock(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    s = max(0, int(seconds))
    return f"{s // 60}:{s % 60:02d}"


def _nade_name(item: str) -> str:
    low = item.lower()
    for key, de in (("smoke", "Smoke"), ("flash", "Flash"), ("molotov", "Molotov"), ("incend", "Molotov"),
                    ("explosive", "HE"), ("hegrenade", "HE")):
        if key in low:
            return de
    return item


def _list_de(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " und " + items[-1]


def _duel(match: MatchData, k) -> dict | None:
    """Duell-Werte aus Sicht des Opfers (duels.py), falls die Demo sie hergibt."""
    from cstaktik.duels import side_of

    d = next((d for d in match.duels if d.tick == k.tick and d.loser == k.victim_steamid), None)
    return side_of(d, k.victim_steamid) if d else None


def _other_death(match: MatchData, k, sid: str, name: str) -> Finding:
    """Tod ohne Waffen-Duell: Bombe, Granate, Welt (Fall), Teamkill. Keine Duell-Tipps, keine Lektion."""
    w = weapon_key(k.weapon) or ""
    what = {"inferno": "Molotov", "molotov": "Molotov", "incgrenade": "Molotov", "hegrenade": "HE",
            "planted_c4": "Bombe", "c4": "Bombe", "world": "Fallschaden", "trigger_hurt": "Fallschaden"}.get(w)
    what = what or (weapon_label(k.weapon) if k.weapon else "unbekannte Ursache")
    by = k.attacker_name if k.attacker_steamid else None
    if any(x in w for x in ("knife", "bayonet", "taser")):
        what = "Zeus" if "taser" in w else "Messer"
    if k.attacker_steamid == sid:
        title, tip = "Eigener Schaden", f"Durch die eigene {what} gestorben: Abstand zur eigenen Granate halten."
    elif k.attacker_steamid and k.attacker_side == k.victim_side:
        title, tip = "Teamschaden", f"Getötet von Mitspieler {by} ({what})."
    elif what in ("Messer", "Zeus"):
        title, tip = what, f"{by} kam unbemerkt bis auf Nahkampf-Distanz: Rücken und Sound im Blick behalten."
    elif what in ("Molotov", "HE"):
        title, tip = what, (f"{what} von {by}: aus der Wurflinie und dem Bereich raus, "
                                            "nicht im Feuer oder an bekannten HE-Spots warten.")
    else:
        title, tip = what, f"Kein Duell ({what})."
    place = k.victim_place or "unbekanntem Ort"
    when = _clock(round_time_s(match, k.round, k.tick))
    return Finding(rule_id="death_other", title=f"Tod: {title}", round=k.round, tick=k.tick, steamid=sid,
                   player_name=name, severity="niedrig",
                   text=f"{name} stirbt" + (f" bei {when}" if when else "") + f" in {place} durch {what}"
                        + (f" von {by}" if by else "") + ".",
                   tip=tip, evidence={"ursache": what, "tick": k.tick})


def run(match: MatchData, cfg: dict) -> list[Finding]:
    focus = match.focus_ids()
    idx = PositionIndex(match.positions)
    tr = match.tickrate
    mech = cfg.get("mech", {})
    findings: list[Finding] = []
    kills = sorted(match.kills, key=lambda k: k.tick)

    for k in kills:
        sid = k.victim_steamid
        rnd = match.round_by_num(k.round)
        if sid not in focus or rnd is None:
            continue
        side = rnd.sides.get(sid)
        name = match.name_of(sid)
        if not k.attacker_steamid or k.attacker_side == k.victim_side or (k.weapon and not is_gun(k.weapon)):
            findings.append(_other_death(match, k, sid, name))  # Bombe, Granate, Welt, Teamkill: kein Duell
            continue
        contact = next((d.contact for d in match.duels if d.tick == k.tick and d.loser == sid), None)
        duel_from = contact if contact is not None else k.tick - int(cfg["trade_window_s"] * tr)
        unchecked: list[str] = []
        before = [x for x in kills if x.round == k.round and x.tick < k.tick]
        dead = {x.victim_steamid for x in before}
        team = [s for s, sd in rnd.sides.items() if sd == side]
        opp = [s for s, sd in rnd.sides.items() if sd != side]
        mates = [s for s in team if s != sid and s not in dead]
        enemies = [s for s in opp if s not in dead]
        opening = not before
        start_diff = len(team) - len(opp)
        now_diff = (len(mates) + 1) - len(enemies)
        attacker = k.attacker_name or "?"
        a_dist = round(dist(k.attacker_pos, k.victim_pos)) if k.attacker_pos and k.victim_pos else None
        place = k.victim_place or "unbekanntem Ort"

        facts: list[str] = []
        issues: dict[str, str] = {}  # Label -> konkreter Tipp

        size = f"{len(mates) + 1} gegen {len(enemies)}" + (" (erstes Duell der Runde)" if opening else "")
        if len(team) != len(opp):
            size += f", Teams {len(team)} gegen {len(opp)} von Anfang an"
        facts.append(size)

        # Blendung
        # Blendung zählt nur, wenn ein Gegner geflasht hat und sie beim Duell-Beginn noch wirkte
        ref = contact if contact is not None else k.tick
        recent = [b for b in match.blinds if b.round == k.round and b.victim_steamid == sid
                  and k.tick - cfg["blind_window_s"] * tr <= b.tick <= k.tick and b.duration >= cfg["blind_min_s"]
                  and b.tick + b.duration * tr >= ref]
        blind = next((b for b in recent if b.attacker_steamid and rnd.sides.get(b.attacker_steamid) not in (None, side)),
                     None)
        team_blind = next((b for b in recent if b is not blind and b.attacker_steamid
                           and rnd.sides.get(b.attacker_steamid) == side), None)
        if team_blind and not blind:
            by = "dir selbst" if team_blind.attacker_steamid == sid else match.name_of(team_blind.attacker_steamid)
            facts.append(f"geblendet {team_blind.duration}s von {by} (eigene Flash)")
        if blind:
            ago = round((k.tick - blind.tick) / tr, 1)
            by = match.name_of(blind.attacker_steamid) if blind.attacker_steamid else "?"
            facts.append(f"geblendet {blind.duration}s von {by}, {ago}s vor dem Tod")
            issues["Geblendet"] = (f"Flash von {by} kam {ago}s vorher: sofort wegdrehen oder hinter Deckung, "
                                   "nicht geblendet im Winkel bleiben.")

        # HP vor dem Duell + Herkunft des Schadens
        hp = None
        if match.damages:
            # HP VOR dem Duell: Schaden ab Duell-Beginn (erster Schuss) bzw. vom Killer in den 3 s davor zählt nicht
            cut = contact if contact is not None else k.tick
            prior = [d for d in match.damages if d.round == k.round and d.victim_steamid == sid and d.tick < cut
                     and not (d.attacker_steamid == k.attacker_steamid and d.tick >= k.tick - 3 * tr)]
            hp = max(0, 100 - sum(d.dmg for d in prior))
            if prior:
                src: dict[str, int] = {}
                for d in prior:
                    w = weapon_key(d.weapon) or "?"
                    label = {"inferno": "Molotov", "molotov": "Molotov", "hegrenade": "HE"}.get(w, w)
                    who = match.name_of(d.attacker_steamid) if d.attacker_steamid else "Welt"
                    if who == match.name_of(sid):
                        key = f"{label} (eigener Schaden)" if label != "?" else "eigenen Schaden"
                    else:
                        key = f"{label} von {who}" if label != "?" else f"Schaden von {who}"
                    src[key] = src.get(key, 0) + d.dmg
                src_txt = ", ".join(f"{v} durch {k_}" if not k_.startswith(("Schaden", "eigenen")) else f"{v} {k_}"
                                    for k_, v in sorted(src.items(), key=lambda x: -x[1]))
                facts.append(f"{hp} HP vor dem Duell (vorher {src_txt})")
            if hp < cfg["hp_low"] and not opening:
                issues["Wenig HP"] = (f"Mit {hp} HP nicht das nächste Duell suchen: zurückfallen, Info geben, "
                                      "auf den Trade deiner Mitspieler spielen.")

        # Schüsse / Bewegung
        my_shots = [s for s in match.shots if s.steamid == sid and s.round == k.round and is_gun(s.weapon)
                    and k.tick - mech.get("no_shot_window_s", 3.0) * tr <= s.tick <= k.tick]
        dealt = None
        if match.damages:
            # nur Schaden am Killer in diesem Duell (nicht die ganze Runde)
            dealt = sum(d.dmg for d in match.damages
                        if d.round == k.round and d.attacker_steamid == sid and d.victim_steamid == k.attacker_steamid
                        and duel_from - tr <= d.tick <= k.tick)
        else:
            unchecked.append("Schaden/HP")
        unused: list[str] = []
        if k.victim_inventory is not None:
            unused = [i for i in k.victim_inventory
                      if any(w in i.lower() for w in cfg["grenade_keywords"])
                      and not any(w in i.lower() for w in cfg["ignore_keywords"])]
        nade_names = sorted({_nade_name(i) for i in unused})

        if match.shots:
            if not my_shots:
                facts.append("kein eigener Schuss vor dem Tod")
                if a_dist is not None and a_dist < cfg["close_units"]:
                    tip = (f"{k.attacker_place or 'Der Gegner'} war nah ({a_dist} Units): Ecke vorher vorzielen "
                           "oder mit Flash/Molotov prüfen, nicht hineinlaufen.")
                else:
                    src_place = k.attacker_place or "dieser Position"
                    tip = (f"Langer Blick aus {src_place}" + (f" ({a_dist} Units)" if a_dist else "")
                           + ": diese Linie nicht offen kreuzen, Smoke setzen oder anderen Weg nehmen.")
                if {"Smoke", "Flash"} & set(nade_names):
                    tip += f" Du hattest {_list_de([n for n in nade_names if n in ('Smoke', 'Flash')])} dabei."
                issues["Ohne Gegenwehr"] = tip
            else:
                facts.append(f"{len(my_shots)} eigene Schüsse" + (f", {dealt} Schaden am Killer" if dealt is not None else ""))
                last = my_shots[-1]
                if (last.speed is not None and mech.get("moving_shot_speed_units_s", 80) < last.speed
                        <= cfg["max_plausible_speed_units_s"]):
                    facts.append(f"letzter Schuss im Laufen ({round(last.speed)} Units/s)")
                    issues["Im Laufen geschossen"] = (f"Letzter Schuss bei {round(last.speed)} Units/s: "
                                                      "vor dem Schuss stoppen (Counter-Strafe), dann schießen.")
        else:
            unchecked.append("Schüsse")
            speed = _speed(idx, k.round, sid, k.tick, tr)
            if speed is not None and cfg["moving_speed_units_s"] < speed <= cfg["max_plausible_speed_units_s"]:
                facts.append(f"in Bewegung ({round(speed)} Units/s)")
                issues["Im Laufen"] = "Vor dem Schuss stoppen (Counter-Strafe), nicht offen in Winkel laufen."

        # Mitspieler / Trade
        traded = bool(k.attacker_steamid) and any(
            x.round == k.round and x.victim_steamid == k.attacker_steamid and x.attacker_steamid in mates
            and k.tick < x.tick <= k.tick + cfg["trade_window_s"] * tr for x in kills)
        overlay: dict = {}
        near = []
        for m in mates:
            smp = idx.nearest(k.round, m, k.tick, tr)
            if smp is not None and k.victim_pos is not None:
                near.append((dist(k.victim_pos, smp.pos), m, smp))
        near_m = near_d = near_place = None
        if near:
            d, m, smp = min(near, key=lambda x: x[0])
            near_m, near_d, near_place = m, round(d), smp.place
            facts.append(f"nächster Mitspieler {match.name_of(m)}: {round(d)} Units" + (f" in {smp.place}" if smp.place else ""))
            overlay = {"line": [[k.victim_pos.x, k.victim_pos.y], [smp.pos.x, smp.pos.y]],
                       "label": f"{round(d)} Units zu {match.name_of(m)}"}
            if d > cfg["trade_distance_units"] and not traded:
                issues["Allein, kein Trade"] = (f"{match.name_of(m)} war {round(d)} Units weg"
                                                + (f" ({smp.place})" if smp.place else "")
                                                + " und konnte nicht nachziehen. Duelle nur dort nehmen oder halten, wo ein Mitspieler nachziehen kann.")
        if mates and not near:
            unchecked.append("Mitspieler-Positionen")
        if traded:
            facts.append("wurde getradet")

        # Utility
        thrown = {}
        for g in match.grenades:
            if g.round == k.round and g.thrower_steamid == sid and g.points and g.points[0][0] < k.tick and g.kind in _NADE_DE:
                thrown[g.kind] = thrown.get(g.kind, 0) + 1
        if match.grenades:
            facts.append("Utility geworfen: " + (", ".join(f"{n}x {_NADE_DE[t]}" for t, n in thrown.items()) or "keine"))
        if k.victim_inventory is None:
            unchecked.append("Inventar")
        # Fehler nur bei Granaten, die das Duell entscheiden (Flash, Molotov). Smoke/HE für später aufzuheben ist
        # oft richtig: steht als Fakt in der Lage, zählt aber nicht als Fehler.
        duel_nades = [n for n in nade_names if n in ("Flash", "Molotov")]
        if unused:
            facts.append("beim Tod im Inventar: " + ", ".join(unused))
        if duel_nades:
            issues["Utility nicht genutzt"] = (f"Du bist mit {_list_de(duel_nades)} gestorben: "
                                               "vor dem Duell werfen, genau dafür ist sie da.")
        elif match.grenades and opening and not thrown and k.victim_inventory is None:  # Inventar unbekannt
            issues["Utility nicht genutzt"] = "Erstes Duell ganz ohne Utility: Flash oder Molotov vor dem ersten Kontakt."

        # Unterzahl nur, wenn sie in der Runde entstanden ist
        if not opening and now_diff < start_diff and now_diff < 0:
            issues["Unterzahl"] = (f"{len(mates) + 1} gegen {len(enemies)}: nicht allein Duelle suchen, "
                                   "mit dem nächsten Mitspieler zusammen gehen oder Zeit spielen.")

        ordered = [lbl for lbl in _PRIORITY if lbl in issues]
        if ordered:
            label, tip = ordered[0], issues[ordered[0]]
        elif unchecked:
            label, tip = "Duell verloren", ("Keine klare Ursache in den Daten. Nicht prüfbar: " + ", ".join(unchecked)
                                            + ". Vorzielen auf Kopfhöhe und Peek-Timing prüfen.")
        else:
            label, tip = "Duell verloren", "Die Lage war in Ordnung. Vorzielen auf Kopfhöhe und Peek-Timing prüfen."
        sev = "hoch" if len(ordered) >= 2 else "mittel" if ordered else "niedrig"

        # Ein Satz, was passiert ist
        when = _clock(round_time_s(match, k.round, k.tick))
        parts = [f"{name} stirbt" + (f" bei {when}" if when else "") + f" in {place}"]
        if hp is not None and hp < 100:
            parts[0] += f" mit {hp} HP"
        if blind:
            parts[0] += ", geblendet,"
        parts.append(f"gegen {attacker}" + (f" ({weapon_label(k.weapon)})" if k.weapon else "")
                     + (f" aus {k.attacker_place}" if k.attacker_place else "")
                     + (f", {a_dist} Units" if a_dist is not None else ""))
        if match.shots and not my_shots:
            parts.append("ohne einen Schuss abzugeben")
        text = " ".join(parts[:2]) + (f", {parts[2]}" if len(parts) > 2 else "") + "."

        findings.append(
            Finding(
                rule_id=RULE_ID,
                title=f"Tod: {label}",
                round=k.round,
                tick=k.tick,
                steamid=sid,
                player_name=name,
                severity=sev,
                text=text,
                tip=tip,
                evidence={"lage": facts, "weitere_punkte": ordered[1:], "tick": k.tick,
                          **({"ungenutzt": unused} if unused else {}),
                          # strukturierte Fakten für die Coach-Texte (coach_voice.py)
                          "f": {"label": label, "issues": ordered, "place": k.victim_place, "when": when,
                                "attacker": k.attacker_name, "aplace": k.attacker_place, "a_dist": a_dist,
                                "weapon": weapon_label(k.weapon) if k.weapon else None, "hp": hp,
                                "no_shot": bool(match.shots) and not my_shots, "shots": len(my_shots),
                                "dealt": dealt, "traded": traded, "unchecked": unchecked, "opening": opening,
                                "own": len(mates) + 1, "enemy": len(enemies),
                                "mate": match.name_of(near_m) if near_m else None, "mate_dist": near_d,
                                "mate_place": near_place, "nades": nade_names,
                                "blind_by": (match.name_of(blind.attacker_steamid) if blind and blind.attacker_steamid
                                             else None), "blind_ago": round((k.tick - blind.tick) / tr, 1) if blind else None,
                                "shot_speed": round(my_shots[-1].speed) if my_shots and my_shots[-1].speed else None,
                                "vpos": [round(k.victim_pos.x), round(k.victim_pos.y)] if k.victim_pos else None,
                                "duel": _duel(match, k)}},
                overlay=overlay,
            )
        )
    return findings
