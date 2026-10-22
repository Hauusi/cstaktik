"""Wirkung der eigenen Granaten aus den Demo-Ereignissen: Schaden von HE und Molotov an Gegnern und Mitspielern,
Blendzeit der Flashes, Kills an geblendeten Gegnern (Flash-Assist), Granaten, die beim Tod noch in der Tasche waren.

awpy liefert keine fertige "Effektivität", nur Rohdaten (Würfe, Detonationen, player_blind mit Dauer, Schaden mit
Waffe, Inventar beim Tod). Smokes haben darin keine messbare Wirkung; für sie zählt nur die Anzahl.
"""

from __future__ import annotations

from cstaktik.model import MatchData

GOOD_BLIND_S = 1.5  # ab so langer Blendzeit eines Gegners zählt eine Flash als wirksam
DMG_WEAPON = {"he": ("hegrenade",), "molotov": ("inferno", "molotov", "incgrenade")}
INV = (("smoke", "Smoke"), ("flash", "Flash"), ("molotov", "Molotov"), ("incendiary", "Molotov"), ("he grenade", "HE"),
       ("hegrenade", "HE"))


def _inv_nades(inv: list[str] | None) -> list[str]:
    out = []
    for item in inv or []:
        low = item.lower()
        name = next((de for key, de in INV if key in low), None)
        if name:
            out.append(name)
    return out


def stats(match: MatchData, sid: str) -> dict:
    """Je Spieler: Summen je Granatenart und eine Zeile je Runde mit Würfen."""
    tr = match.tickrate
    side = {r.num: r.sides for r in match.rounds}
    enemy = lambda rnd, v: bool(side.get(rnd)) and v in side[rnd] and side[rnd][v] != side[rnd].get(sid)  # noqa: E731
    out = {k: {"n": 0} for k in ("flash", "he", "molotov", "smoke")}
    per: dict[int, dict] = {}

    def row(rnd: int) -> dict:
        return per.setdefault(rnd, {"r": rnd, "thrown": {}, "he_dmg": 0, "molo_dmg": 0, "blind": 0, "blind_s": 0.0,
                                    "assists": 0, "team_blind": 0})

    for g in match.grenades:
        if g.thrower_steamid == sid and g.kind in out:
            out[g.kind]["n"] += 1
            t = row(g.round)["thrown"]
            t[g.kind] = t.get(g.kind, 0) + 1
    for kind, weapons in DMG_WEAPON.items():
        en = tm = kills = 0
        for d in match.damages:
            if d.attacker_steamid != sid or (d.weapon or "") not in weapons or d.victim_steamid == sid:
                continue
            if enemy(d.round, d.victim_steamid):
                en += d.dmg
                row(d.round)["he_dmg" if kind == "he" else "molo_dmg"] += d.dmg
            else:
                tm += d.dmg
        kills = sum(1 for k in match.kills if k.attacker_steamid == sid and (k.weapon or "") in weapons
                    and enemy(k.round, k.victim_steamid))
        out[kind].update(enemy_dmg=en, team_dmg=tm, kills=kills)
    # Flashes: Blendzeit je Wurf (Detonation), Gegner vs. eigenes Team
    good = team = 0
    blinded = []
    for u in match.utility:
        if u.kind != "flash" or u.thrower_steamid != sid:
            continue
        en_s, tm_s = 0.0, 0.0
        for b in match.blinds:
            if b.attacker_steamid != sid or not (u.start_tick <= b.tick <= u.start_tick + tr // 2):
                continue
            if enemy(u.round, b.victim_steamid):
                en_s += b.duration
                blinded.append(b)
                row(u.round)["blind"] += 1
                row(u.round)["blind_s"] += b.duration
            else:
                tm_s += b.duration
        good += en_s >= GOOD_BLIND_S
        if tm_s >= 1.0:
            team += 1
            row(u.round)["team_blind"] += 1
    assists = 0
    for k in match.kills:
        if not k.attacker_steamid or k.attacker_steamid == k.victim_steamid:
            continue
        if not enemy(k.round, k.victim_steamid) or enemy(k.round, k.attacker_steamid) is True:
            continue
        if any(b.victim_steamid == k.victim_steamid and b.round == k.round and b.tick <= k.tick <= b.tick + b.duration * tr
               for b in blinded):
            assists += 1
            row(k.round)["assists"] += 1
    out["flash"].update(good=good, team=team, assists=assists, enemies=len(blinded),
                        avg_blind_s=round(sum(b.duration for b in blinded) / len(blinded), 1) if blinded else None)
    # beim Tod noch in der Tasche
    unused = []
    for k in match.kills:
        if k.victim_steamid == sid and k.victim_inventory is not None:
            n = _inv_nades(k.victim_inventory)
            if n:
                unused.append({"r": k.round, "nades": n})
    deaths_known = sum(1 for k in match.kills if k.victim_steamid == sid and k.victim_inventory is not None)
    for r in per.values():
        r["blind_s"] = round(r["blind_s"], 1)
    return {**out, "unused": unused, "deaths_known": deaths_known,
            "rounds": [per[r] for r in sorted(per)]}


def by_player(match: MatchData) -> dict:
    return {sid: stats(match, sid) for sid in sorted(match.focus_ids())}
