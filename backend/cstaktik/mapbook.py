"""Map-Buch: deine Spots je Map und Seite, bewertet aus euren Demos und gegen Pro-Demos gestellt.

Spot = Ort (Callout) eines Spielers nach ``at_s`` Sekunden Rundenzeit (Verlauf: timeline, 5-s-Raster).
Je Spot: Runden, Siegquote, gestorben, als Erster gestorben, ohne Trade gestorben (Verlauf: deaths).
Pros (gleiche Map und Seite): wie oft sie dort stehen, ihre Siegquote dort, wie oft sie dort als Erster sterben,
und welche Lineups sie von dort werfen. Bewertung nach festen Schwellen aus rules.yaml (mapbook).
"""

from __future__ import annotations

from collections import Counter

from cstaktik import lineups as lu
from cstaktik.reference import STEP_S

SIDE_DE = {"ct": "CT", "t": "T"}


def _pct(a: int, b: int) -> int | None:
    return round(100 * a / b) if b else None


def _own(hist: list[dict], map_name: str, sid: str, b: int) -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = {"ct": {}, "t": {}}
    for h in hist:
        if h.get("map") != map_name:
            continue
        deaths = {(d["round"], d["sid"]): d for d in h.get("deaths", [])}
        for t in h.get("timeline", []):
            if t["sid"] != sid or t["side"] not in out or b >= len(t["places"]) or not t["places"][b]:
                continue
            e = out[t["side"]].setdefault(t["places"][b], {"n": 0, "won": 0, "died": 0, "first": 0, "untraded": 0,
                                                           "trade_known": 0, "death_places": Counter(), "rounds": []})
            e["n"] += 1
            e["won"] += bool(t["won"])
            d = deaths.get((t["round"], sid))
            if d:
                e["died"] += 1
                e["first"] += bool(d.get("first"))
                if "traded" in d:
                    e["trade_known"] += 1
                    e["untraded"] += not d["traded"]
                if d.get("place"):
                    e["death_places"][d["place"]] += 1
            e["rounds"].append({"report": h.get("report_file"), "round": t["round"], "won": bool(t["won"]),
                                "date": (h.get("analyzed_at") or "")[:10]})
    return out


def _pro(pro: list[dict], map_name: str, b: int) -> dict[str, dict]:
    out = {"ct": {"total": 0, "spots": {}}, "t": {"total": 0, "spots": {}}}
    for d in pro:
        if d.get("map") != map_name:
            continue
        first = {(x["r"], x.get("sid")) for x in d.get("deaths", []) if x.get("first") and x.get("sid")}
        has_sid = any(x.get("sid") for x in d.get("deaths", []))
        for t in d.get("timeline", []):
            if t["side"] not in out or b >= len(t["places"]) or not t["places"][b]:
                continue
            o = out[t["side"]]
            o["total"] += 1
            e = o["spots"].setdefault(t["places"][b], {"n": 0, "won": 0, "first": 0, "first_known": 0})
            e["n"] += 1
            e["won"] += bool(t["won"])
            if has_sid:
                e["first_known"] += 1
                e["first"] += (t["round"], t["sid"]) in first
    return out


def build(hist: list[dict], pro: list[dict], map_name: str, sid: str, cfg: dict) -> dict:
    b = round(cfg.get("at_s", 20) / STEP_S)
    own = _own(hist, map_name, sid, b)
    pros = _pro(pro, map_name, b)
    lines = lu.build(pro, map_name)
    sides = {}
    for side in ("ct", "t"):
        po = pros[side]
        pro_ok = po["total"] >= cfg.get("min_pro_rounds", 10)
        spots = []
        for place, e in sorted(own[side].items(), key=lambda kv: -kv[1]["n"]):
            row = {"place": place, "n": e["n"], "won_pct": _pct(e["won"], e["n"]), "died_pct": _pct(e["died"], e["n"]),
                   "first_pct": _pct(e["first"], e["n"]), "first": e["first"], "died": e["died"],
                   "untraded": e["untraded"] if e["trade_known"] else None,
                   "untraded_pct": _pct(e["untraded"], e["n"]) if e["trade_known"] else None,
                   "death_places": e["death_places"].most_common(3),
                   "rounds": e["rounds"][-6:][::-1]}
            row.update(_verdict(row, cfg))
            ps = po["spots"].get(place)
            if pro_ok:
                row["pro"] = {"share": _pct(ps["n"] if ps else 0, po["total"]),
                              "won_pct": _pct(ps["won"], ps["n"]) if ps and ps["n"] >= 3 else None,
                              "first_pct": _pct(ps["first"], ps["first_known"]) if ps and ps["first_known"] >= 3 else None,
                              "n": ps["n"] if ps else 0}
            row["lineups"] = [l for l in lines if l["side"] == side and l["from"] == place][:3]
            spots.append(row)
        alt = []
        if pro_ok:
            for place, ps in sorted(po["spots"].items(), key=lambda kv: -kv[1]["n"])[:5]:
                alt.append({"place": place, "share": _pct(ps["n"], po["total"]),
                            "won_pct": _pct(ps["won"], ps["n"]) if ps["n"] >= 3 else None,
                            "first_pct": _pct(ps["first"], ps["first_known"]) if ps["first_known"] >= 3 else None,
                            "lineups": sum(1 for l in lines if l["side"] == side and l["from"] == place)})
        sides[side] = {"label": SIDE_DE[side], "spots": spots, "pro_spots": alt, "pro_rounds": po["total"],
                       "rounds": sum(s["n"] for s in spots)}
    return {"map": map_name, "label": map_name.removeprefix("de_").capitalize(), "at": lu.clock(b * STEP_S),
            "sides": sides, "matches": sum(1 for h in hist if h.get("map") == map_name),
            "n_lineups": len(lines)}


def _verdict(row: dict, cfg: dict) -> dict:
    """Bewertung nach festen Schwellen; ``why`` nennt die Zahlen dahinter."""
    n = row["n"]
    if n < cfg.get("min_rounds", 3):
        return {"verdict": "offen", "why": [f"Erst {n} Runde{'n' if n != 1 else ''} hier, zu wenig für eine Bewertung."]}
    why = []
    bad = False
    min_bad = cfg.get("min_bad_count", 3)  # Prozent allein reicht nicht: 2 von 4 ist noch Zufall
    if row["first_pct"] >= cfg.get("first_death_bad_pct", 40) and row["first"] >= min_bad:
        bad = True
        why.append(f"In {row['first']} von {n} Runden von diesem Spot aus als Erster gestorben.")
    if (row["untraded_pct"] is not None and row["untraded_pct"] >= cfg.get("untraded_bad_pct", 40)
            and row["untraded"] >= min_bad):
        bad = True
        why.append(f"In {row['untraded']} von {n} Runden von diesem Spot aus ohne Trade gestorben.")
    if n < cfg.get("verdict_rounds", 8):
        # wenige Runden: nur eine Tendenz zeigen, damit die Bewertung nicht mit jeder Runde kippt
        lean = "eher Problem" if bad else "eher gut" if row["won_pct"] >= cfg.get("win_good_pct", 55) else "offen"
        return {"verdict": "tendenz", "why": [f"Tendenz {lean}, erst {n} Runden (Bewertung ab "
                                              f"{cfg.get('verdict_rounds', 8)})."] + why}
    if bad:
        return {"verdict": "problem", "why": why}
    if row["won_pct"] >= cfg.get("win_good_pct", 55) and row["first_pct"] <= cfg.get("first_death_good_pct", 25):
        return {"verdict": "stark", "why": [(f"{row['won_pct']} % der Runden gewonnen, selten als Erster gestorben "
                                              f"({row['first']} von {n}).")]}
    return {"verdict": "okay", "why": [f"{row['won_pct']} % gewonnen, {row['first']} von {n} Runden als Erster gestorben."]}


def worst_spot(book: dict) -> dict | None:
    """Spot mit dem größten Handlungsbedarf (für den Wochenplan): Problem-Spots, meiste Runden zuerst."""
    cand = [(s, side) for side, sd in book["sides"].items() for s in sd["spots"] if s["verdict"] == "problem"]
    if not cand:
        return None
    s, side = max(cand, key=lambda c: (c[0]["first"] + (c[0]["untraded"] or 0), c[0]["n"]))
    return {**s, "side": side}
