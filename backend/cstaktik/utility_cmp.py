"""Utility gegen Pros: Lineups, Flash-Wirkung, Utility vor dem ersten Duell.

- Lineup: Jede eigene Smoke/Molotov mit Landeort (Callout). Pro-Würfe derselben Art, Seite und desselben
  Landeorts ergeben die Pro-Stelle (Mittelwert der Landepunkte). Abstand deiner Landung zur Pro-Stelle in Units,
  dazu der häufigste Pro-Wurfort. Ab ``min_pro`` Pro-Würfen.
- Flash-Wirkung: je Flash die Summe der Blendzeit (player_blind, Werfer = du, bis 0,5 s nach der Zündung)
  bei Gegnern und Mitspielern. "Wirkt" ab ``good_blind_s`` Sekunden bei Gegnern.
- Utility vor dem ersten Duell: Granaten je Spieler und Runde, geworfen vor dem ersten Kill der Runde.
"""

from __future__ import annotations

import statistics
from collections import Counter

from cstaktik.model import MatchData

NADE_DE = {"smoke": "Smoke", "molotov": "Molotov", "flash": "Flash", "he": "HE"}


def nade_rows(match: MatchData, sids: set[str] | None = None) -> list[dict]:
    """Granaten (Smoke/Molotov/Flash/HE) mit Seite, Wurf-/Landeort, Landepunkt."""
    from cstaktik.pro import place_lookup

    find = place_lookup(match)
    tr = match.tickrate
    out = []
    for g in match.grenades:
        if g.kind not in NADE_DE or len(g.points) < 2 or (sids is not None and g.thrower_steamid not in sids):
            continue
        rnd = match.round_by_num(g.round)
        side = rnd.sides.get(g.thrower_steamid or "") if rnd else None
        if rnd is None or side is None or rnd.freeze_end_tick is None:
            continue
        (t0, fx, fy, fz), (_t1, tx, ty, tz) = g.points[0], g.points[-1]
        out.append({"r": g.round, "tick": t0, "sid": g.thrower_steamid, "side": side, "kind": g.kind,
                    "t": round((t0 - rnd.freeze_end_tick) / tr, 1), "from": find(fx, fy, fz), "to": find(tx, ty, tz),
                    "tx": round(tx), "ty": round(ty)})
    return out


def lineups(match: MatchData, pro: list[dict], min_pro: int = 3, good_units: float = 150) -> list[dict]:
    """Eigene Smokes/Molotovs gegen die Pro-Stelle desselben Landeorts."""
    own = [n for n in nade_rows(match, match.focus_ids()) if n["kind"] in ("smoke", "molotov") and n["to"]]
    pnades = [n for d in pro if d.get("map") == match.map_name for n in d.get("nades", [])]
    out = []
    for n in own:
        same = [p for p in pnades if p["kind"] == n["kind"] and p["side"] == n["side"] and p["to"] == n["to"]]
        if len(same) < min_pro:
            continue
        mx, my = statistics.mean(p["tx"] for p in same), statistics.mean(p["ty"] for p in same)
        d = round(((n["tx"] - mx) ** 2 + (n["ty"] - my) ** 2) ** 0.5)
        spread = round(statistics.median(((p["tx"] - mx) ** 2 + (p["ty"] - my) ** 2) ** 0.5 for p in same))
        frm = Counter(p["from"] for p in same if p["from"]).most_common(1)
        out.append({**n, "who": match.name_of(n["sid"]), "dist": d, "spread": spread, "n_pro": len(same),
                    "pro_from": frm[0][0] if frm else None, "ok": d <= max(good_units, spread * 1.5)})
    return out


def flash_effect(match: MatchData, sids: set[str] | None = None, window_s: float = 0.5) -> list[dict]:
    """Je Flash: Blendzeit bei Gegnern und Mitspielern (aus player_blind)."""
    tr = match.tickrate
    out = []
    for u in match.utility:
        if u.kind != "flash" or not u.thrower_steamid or (sids is not None and u.thrower_steamid not in sids):
            continue
        rnd = match.round_by_num(u.round)
        if rnd is None:
            continue
        side = rnd.sides.get(u.thrower_steamid)
        en = tm = 0.0
        for b in match.blinds:
            if b.attacker_steamid != u.thrower_steamid or not (u.start_tick <= b.tick <= u.start_tick + window_s * tr):
                continue
            if b.victim_steamid == u.thrower_steamid or rnd.sides.get(b.victim_steamid) == side:
                tm += b.duration
            else:
                en += b.duration
        out.append({"r": u.round, "tick": u.start_tick, "sid": u.thrower_steamid, "enemy_s": round(en, 2),
                    "team_s": round(tm, 2)})
    return out


def flash_stats(rows: list[dict], good_blind_s: float = 1.5) -> dict | None:
    if not rows:
        return None
    return {"n": len(rows), "good": sum(r["enemy_s"] >= good_blind_s for r in rows),
            "good_pct": round(100 * sum(r["enemy_s"] >= good_blind_s for r in rows) / len(rows)),
            "avg_enemy_s": round(statistics.mean(r["enemy_s"] for r in rows), 1),
            "team": sum(r["team_s"] >= 1.0 for r in rows)}


def pre_contact(match: MatchData, sids: set[str] | None = None) -> tuple[int, int]:
    """(Granaten vor dem ersten Kill, Spieler-Runden) für die Spieler ``sids`` (None = alle)."""
    nades = 0
    pr = 0
    first = {}
    for k in sorted(match.kills, key=lambda k: k.tick):
        first.setdefault(k.round, k.tick)
    for rnd in match.rounds:
        if rnd.num not in first or not rnd.sides:
            continue
        players = [s for s in rnd.sides if sids is None or s in sids]
        pr += len(players)
        nades += sum(1 for g in match.grenades if g.round == rnd.num and g.thrower_steamid in players and g.points
                     and g.kind in NADE_DE and g.points[0][0] < first[rnd.num])
    return nades, pr


def compare(match: MatchData, pro: list[dict], cfg: dict | None = None) -> dict:
    """Alles für den Report-Abschnitt "Utility gegen Pros"."""
    cfg = cfg or {}
    focus = match.focus_ids()
    own_flash = flash_effect(match, focus)
    pro_flash = [{"enemy_s": f[0], "team_s": f[1]} for d in pro for f in d.get("flashes", [])]
    n, pr = pre_contact(match, focus)
    pn = sum(d.get("pre_util", [0, 0])[0] for d in pro)
    ppr = sum(d.get("pre_util", [0, 0])[1] for d in pro)
    return {
        "lineups": lineups(match, pro, cfg.get("lineup_min_pro", 3), cfg.get("lineup_good_units", 150)),
        "flash": flash_stats(own_flash, cfg.get("flash_good_blind_s", 1.5)),
        "flash_pro": flash_stats(pro_flash, cfg.get("flash_good_blind_s", 1.5)) if len(pro_flash) >= 10 else None,
        "pre": round(n / pr, 2) if pr else None,
        "pre_pro": round(pn / ppr, 2) if ppr >= 50 else None,
        "has_blinds": bool(match.blinds),
    }
