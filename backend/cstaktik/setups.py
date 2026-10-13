"""Positionen und Ausführungen gegen Pros.

CT-Positionen: Wo stand ein Fokus-Spieler nach ``at_s`` Sekunden (Callout, 5-s-Raster aus reference.timeline)?
Je Ort: Runden, eigene Tode in diesen Runden, Siege. Pros auf derselben Map und Seite: Anteil an Ort und Siegquote.

T-Ausführungen: Je Runde der erste Zeitpunkt (5-s-Raster), an dem ein T-Spieler an einem Bombsite-Ort steht
(Callout beginnt mit "Bombsite"). Dazu: wie viele T dort zu diesem Zeitpunkt und 5 s später, wie viele T-Granaten
in den 15 s davor auf diesen Ort gelandet sind, ob die Runde gewonnen wurde. Gleiche Messung für Pro-Demos.
Nur Demo-Daten; das 5-s-Raster ist bewusst grob.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict

from cstaktik.model import MatchData
from cstaktik.reference import STEP_S, timeline


def _bucket(s: float) -> int:
    return int(round(s / STEP_S))


def ct_positions(match: MatchData, pro: list[dict], at_s: int = 20, min_pro: int = 10) -> list[dict]:
    b = _bucket(at_s)
    tl = timeline(match)
    deaths = {(k.round, k.victim_steamid) for k in match.kills}
    per: dict[tuple, dict] = {}
    for t in tl:
        if t["side"] != "ct" or b >= len(t["places"]) or not t["places"][b]:
            continue
        key = (t["sid"], t["places"][b])
        e = per.setdefault(key, {"rounds": 0, "deaths": 0, "won": 0, "list": []})
        e["rounds"] += 1
        e["deaths"] += (t["round"], t["sid"]) in deaths
        e["won"] += t["won"]
        e["list"].append(t["round"])
    pc = Counter()
    pwon = Counter()
    for d in pro:
        if d.get("map") != match.map_name:
            continue
        for t in d.get("timeline", []):
            if t["side"] == "ct" and b < len(t["places"]) and t["places"][b]:
                pc[t["places"][b]] += 1
                pwon[t["places"][b]] += t["won"]
    total = sum(pc.values())
    out = []
    for (sid, place), e in sorted(per.items(), key=lambda kv: -kv[1]["rounds"]):
        row = {"who": match.name_of(sid), "place": place, **{k: e[k] for k in ("rounds", "deaths", "won")},
               "round_list": e["list"]}
        if total >= min_pro:
            row["pro_share"] = round(100 * pc[place] / total)
            row["pro_won"] = round(100 * pwon[place] / pc[place]) if pc[place] >= 3 else None
        out.append(row)
    pro_top = [{"place": p, "share": round(100 * n / total), "won": round(100 * pwon[p] / n)}
               for p, n in pc.most_common(4)] if total >= min_pro else []
    return out, pro_top


def executes_from(tl: list[dict], nades: list[dict], rounds_won: dict[int, bool] | None = None) -> list[dict]:
    """T-Ausführungen aus timeline (alle Spieler) und Granaten (side, r, t, to)."""
    by_round: dict[int, list] = defaultdict(list)
    for t in tl:
        if t["side"] == "t":
            by_round[t["round"]].append(t)
    out = []
    for r, ts in by_round.items():
        n = max(len(t["places"]) for t in ts)
        hit = None
        for b in range(n):
            here = [t["places"][b] for t in ts if b < len(t["places"]) and (t["places"][b] or "").startswith("Bombsite")]
            if here:
                hit = (b, Counter(here).most_common(1)[0][0])
                break
        if not hit:
            continue
        b, site = hit
        now = sum(1 for t in ts if b < len(t["places"]) and t["places"][b] == site)
        later = sum(1 for t in ts if b + 1 < len(t["places"]) and t["places"][b + 1] == site)
        sec = b * STEP_S
        util = sum(1 for g in nades if g["r"] == r and g["side"] == "t" and g.get("to") == site
                   and sec - 15 <= g["t"] <= sec + 2)
        won = ts[0]["won"] if rounds_won is None else rounds_won.get(r)
        out.append({"round": r, "site": site, "at": sec, "players": max(now, later), "util": util, "won": won})
    return out


def _summ(rows: list[dict]) -> dict:
    return {"n": len(rows), "at": round(statistics.mean(r["at"] for r in rows)),
            "players": round(statistics.mean(r["players"] for r in rows), 1),
            "util": round(statistics.mean(r["util"] for r in rows), 1),
            "won": round(100 * sum(bool(r["won"]) for r in rows) / len(rows))}


def t_executes(match: MatchData, pro: list[dict], min_pro: int = 5) -> list[dict]:
    """Je Bombsite: eure T-Ausführungen gegen Pro-Ausführungen derselben Map."""
    from cstaktik.utility_cmp import nade_rows

    tl = timeline(match, all_players=True)
    own_rounds = {r.num for r in match.rounds if match.focus_side(r.num) == "t"}
    tl = [t for t in tl if t["round"] in own_rounds]
    own = executes_from(tl, nade_rows(match))
    pro_rows = []
    for d in pro:
        if d.get("map") == match.map_name:
            pro_rows += executes_from(d.get("timeline", []), d.get("nades", []))
    out = []
    for site in sorted({r["site"] for r in own}):
        mine = [r for r in own if r["site"] == site]
        theirs = [r for r in pro_rows if r["site"] == site]
        out.append({"site": site, "own": _summ(mine), "pro": _summ(theirs) if len(theirs) >= min_pro else None,
                    "rounds": [r["round"] for r in mine]})
    return out
