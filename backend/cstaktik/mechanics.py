"""Mechanik je Fokus-Spieler aus Schüssen (weapon_fire), Schaden (player_hurt) und Kills.

- bewegt geschossen: horizontale Geschwindigkeit im Schuss-Tick > Schwelle (Heuristik, rules.yaml)
- Treffer pro Schuss: Schuss gilt als Treffer, wenn derselbe Spieler mit derselben Waffe im Schuss-Tick
  oder bis zu ``hit_window_ticks`` danach Schaden macht (Schrotflinten: mehrere Kugeln = 1 Treffer)
- Spray: Trefferquote der ersten 3 Schüsse einer Salve vs. ab Schuss 4
- Tode ohne eigenen Schuss im Zeitfenster vor dem Tod
Nur Schusswaffen; Messer, Granaten, C4 und Taser zählen nicht.
"""

from __future__ import annotations

from cstaktik.model import MatchData

_NO_GUN = ("knife", "bayonet", "grenade", "flashbang", "smoke", "molotov", "incgrenade", "decoy", "c4", "taser",
           "inferno")


def weapon_key(name: str | None) -> str:
    return (name or "").lower().removeprefix("weapon_")


def is_gun(name: str | None) -> bool:
    w = weapon_key(name)
    return bool(w) and not any(x in w for x in _NO_GUN)


def mechanics(match: MatchData, cfg: dict) -> list[dict]:
    tr = match.tickrate
    gap = int(cfg["burst_gap_s"] * tr)
    out = []
    for sid in sorted(match.focus_ids()):
        shots = sorted((s for s in match.shots if s.steamid == sid and is_gun(s.weapon)), key=lambda s: s.tick)
        dmg = sorted((d for d in match.damages if d.attacker_steamid == sid and d.victim_steamid != sid
                      and is_gun(d.weapon)), key=lambda d: d.tick)
        used = set()
        hit_flags = []
        for s in shots:
            hit = False
            for i, d in enumerate(dmg):
                if i in used or d.round != s.round:
                    continue
                if s.tick <= d.tick <= s.tick + cfg["hit_window_ticks"] and weapon_key(d.weapon) == weapon_key(s.weapon):
                    used.add(i)
                    hit = True
                elif d.tick > s.tick + cfg["hit_window_ticks"]:
                    break
            hit_flags.append(hit)

        early = [0, 0]  # Schüsse, Treffer bei Schuss 1-3 einer Salve
        late = [0, 0]
        idx_in_burst = 0
        for i, s in enumerate(shots):
            prev = shots[i - 1] if i else None
            if prev and prev.round == s.round and prev.weapon == s.weapon and s.tick - prev.tick <= gap:
                idx_in_burst += 1
            else:
                idx_in_burst = 1
            bucket = early if idx_in_burst <= 3 else late
            bucket[0] += 1
            bucket[1] += hit_flags[i]

        with_speed = [s for s in shots if s.speed is not None]
        moving = [s for s in with_speed if s.speed > cfg["moving_shot_speed_units_s"]]
        my_kills = [k for k in match.kills if k.attacker_steamid == sid and k.victim_side != k.attacker_side
                    and is_gun(k.weapon)]
        deaths = [k for k in match.kills if k.victim_steamid == sid]
        window = int(cfg["no_shot_window_s"] * tr)
        no_shot = [k for k in deaths
                   if not any(s.round == k.round and k.tick - window <= s.tick <= k.tick for s in shots)]

        def pct(a: int, b: int) -> float | None:
            return round(100 * a / b, 1) if b else None

        out.append({
            "steamid": sid,
            "name": match.name_of(sid),
            "shots": len(shots),
            "moving_shots": len(moving),
            "moving_pct": pct(len(moving), len(with_speed)),
            "hits": sum(hit_flags),
            "hit_pct": pct(sum(hit_flags), len(shots)) if match.damages else None,
            "hs_pct": pct(sum(1 for k in my_kills if k.headshot), len(my_kills)),
            "kills": len(my_kills),
            "deaths": len(deaths),
            "deaths_no_shot": len(no_shot),
            "deaths_no_shot_pct": pct(len(no_shot), len(deaths)) if shots or deaths else None,
            "no_shot_rounds": sorted({k.round for k in no_shot}),
            "spray_early_pct": pct(early[1], early[0]) if match.damages else None,
            "spray_late_pct": pct(late[1], late[0]) if match.damages else None,
            "spray_late_shots": late[0],
            "has_shot_data": bool(match.shots),
        })
    return out
