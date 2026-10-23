"""Scoreboard je Fokus-Spieler und Match: K/D/A, ADR, KAST, Headshots, Multi-Kills, Opening-Duelle, Rating.

Alles aus den geparsten Demo-Daten. Zwei Ratings:
- HLTV Rating 1.0: öffentliche Formel von HLTV (Kills, Überleben, Multi-Kill-Runden je Runde).
- Rating 2.0 (Näherung): die Formel aus awpy (awpy.stats.rating), eine Regression auf HLTV-Werte. HLTV selbst hat
  die Formel für 2.0 nie veröffentlicht; die Zahl liegt nah dran, ist aber nicht der offizielle Wert.
Rating 2.0, KAST und Impact brauchen Assists. Fehlen sie (Match vor dem Update geparst), bleiben diese Werte leer.

``totals`` und ``derive`` rechnen dieselben Werte auch über mehrere Matches (Summen, nicht Durchschnitt der Ratings),
so wie HLTV Karrierewerte bildet.
"""

from __future__ import annotations

from cstaktik.mechanics import is_teamkill
from cstaktik.model import MatchData

KAST_TRADE_S = 5.0  # wie awpy.stats.kast: Tod zählt als getradet, wenn der Killer binnen 5 s fällt
COUNTS = ("rounds", "kills", "deaths", "assists", "dmg", "hs", "kast", "survived", "k1", "k2", "k3", "k4", "k5",
          "ok", "od", "traded")


def match_counts(match: MatchData) -> dict[str, dict]:
    """Rohzahlen je Fokus-Spieler (summierbar über Matches)."""
    tr = match.tickrate
    scoreboard = sorted(list(match.kills) + list(match.post_round_kills), key=lambda k: k.tick)
    in_round = sorted(match.kills, key=lambda k: k.tick)
    first = {}
    for k in in_round:
        if k.attacker_steamid and not is_teamkill(match, k) and k.attacker_steamid != k.victim_steamid:
            first.setdefault(k.round, k)
    out = {}
    for sid in sorted(match.focus_ids()):
        rnds = [r for r in match.rounds if sid in r.sides]
        if not rnds:
            continue
        c = dict.fromkeys(COUNTS, 0)
        c["rounds"] = len(rnds)
        known_a = match.assists_parsed
        for r in rnds:
            side = r.sides[sid]
            enemy = lambda s: s in r.sides and r.sides[s] != side  # noqa: E731
            ks = [k for k in scoreboard if k.round == r.num and k.attacker_steamid == sid and not is_teamkill(match, k)]
            ds = [k for k in scoreboard if k.round == r.num and k.victim_steamid == sid]
            died = [k for k in in_round if k.round == r.num and k.victim_steamid == sid]
            assists = [k for k in scoreboard if k.round == r.num and k.assister_steamid == sid
                       and enemy(k.victim_steamid)] if known_a else []
            c["kills"] += len(ks)
            c["deaths"] += len(ds)
            c["assists"] += len(assists)
            c["hs"] += sum(1 for k in ks if k.headshot)
            if 1 <= len(ks) <= 5:
                c[f"k{len(ks)}"] += 1
            traded = False
            for d in died:
                if d.attacker_steamid and any(x.round == r.num and x.victim_steamid == d.attacker_steamid
                                              and r.sides.get(x.attacker_steamid) == side
                                              and d.tick < x.tick <= d.tick + KAST_TRADE_S * tr for x in in_round):
                    traded = True
            c["traded"] += traded
            c["survived"] += not died
            c["kast"] += bool(ks or assists or not died or traded)
            f = first.get(r.num)
            if f is not None:
                c["ok"] += f.attacker_steamid == sid
                c["od"] += f.victim_steamid == sid
        c["dmg"] = sum(d.dmg for d in match.damages if d.attacker_steamid == sid and d.victim_steamid != sid
                       and (rr := match.round_by_num(d.round)) is not None and sid in rr.sides
                       and rr.sides.get(d.victim_steamid) not in (None, rr.sides[sid]))
        c["assists_known"] = known_a
        c["dmg_known"] = bool(match.damages)
        out[sid] = c
    return out


def totals(rows: list[dict]) -> dict | None:
    """Summe mehrerer Matches. Assists/KAST nur, wenn sie in allen Matches bekannt sind."""
    rows = [r for r in rows if r and r.get("rounds")]
    if not rows:
        return None
    t = {k: sum(r.get(k, 0) for r in rows) for k in COUNTS}
    t["assists_known"] = all(r.get("assists_known") for r in rows)
    t["dmg_known"] = all(r.get("dmg_known") for r in rows)
    t["matches"] = len(rows)
    return t


def derive(c: dict | None) -> dict | None:
    """Kennzahlen aus Rohzahlen. Werte ohne Grundlage bleiben None."""
    if not c or not c.get("rounds"):
        return None
    n = c["rounds"]
    kpr, dpr = c["kills"] / n, c["deaths"] / n
    adr = c["dmg"] / n if c.get("dmg_known") else None
    rmk = (c["k1"] + 4 * c["k2"] + 9 * c["k3"] + 16 * c["k4"] + 25 * c["k5"]) / n
    r1 = (kpr / 0.679 + 0.7 * ((n - c["deaths"]) / n) / 0.317 + rmk / 1.277) / 2.7
    out = {"rounds": n, "kills": c["kills"], "deaths": c["deaths"], "kd": round(c["kills"] / c["deaths"], 2) if c["deaths"] else None,
           "diff": c["kills"] - c["deaths"], "kpr": round(kpr, 2), "dpr": round(dpr, 2),
           "adr": None if adr is None else round(adr, 1),
           "hs_pct": round(100 * c["hs"] / c["kills"]) if c["kills"] else None,
           "survival_pct": round(100 * c["survived"] / n), "multi": c["k2"] + c["k3"] + c["k4"] + c["k5"],
           "k3plus": c["k3"] + c["k4"] + c["k5"], "aces": c["k5"], "ok": c["ok"], "od": c["od"],
           "traded": c["traded"], "rating1": round(r1, 2), "matches": c.get("matches", 1),
           "assists": None, "kast": None, "impact": None, "rating2": None}
    if c.get("assists_known"):
        apr = c["assists"] / n
        kast = 100 * c["kast"] / n
        impact = 2.13 * kpr + 0.42 * apr - 0.41
        out.update(assists=c["assists"], kast=round(kast), impact=round(impact, 2))
        if adr is not None:
            out["rating2"] = round(0.0073 * kast + 0.3591 * kpr - 0.5329 * dpr + 0.2372 * impact + 0.0032 * adr + 0.1587, 2)
    return out
