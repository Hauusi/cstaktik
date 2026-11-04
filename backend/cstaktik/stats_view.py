"""Stats-Seite: Werte je Match als Verlauf, Vergleich mit dem Zeitraum davor, T gegen CT, Maps.

Alles aus den Verlauf-Einträgen (board = Scoreboard-Rohzahlen, by_round = Runden je Seite). Nichts geschätzt:
Fehlt ein Wert in einem Match (z. B. ADR ohne Schadensdaten), fehlt sein Punkt im Graphen.

Vergleich "besser / schlechter": aktueller Zeitraum gegen gleich viele Matches davor, erst ab 3 Matches auf jeder
Seite und nur bei klarem Abstand (CLEAR), sonst "etwa gleich" (Regel: Rot und Grün erst bei klarem Abstand).
"""

from __future__ import annotations

from cstaktik import history, scoreboard

# Kennzahlen: Schlüssel, Titel, Einheit, Nachkommastellen, klarer Abstand. Höher ist bei allen besser.
METRICS = [
    ("rating", "Rating", "", 2, 0.05),
    ("kd", "K/D", "", 2, 0.10),
    ("adr", "ADR", "", 1, 5.0),
    ("kast", "KAST", "%", 0, 3.0),
    ("hs_pct", "Headshots", "%", 0, 5.0),
    ("open_pct", "Opening-Duelle gewonnen", "%", 0, 8.0),
    ("survival_pct", "Runden überlebt", "%", 0, 4.0),
    ("kpr", "Kills je Runde", "", 2, 0.05),
]
MIN_CMP = 3   # Matches je Zeitraum für einen Vergleich
ROLL = 5      # Schnitt über so viele Matches im Graphen
MIN_SIDE_ROUNDS = 10


def values(d: dict | None) -> dict:
    """Kennzahlen eines Matches oder Zeitraums (derive-Ergebnis) inkl. Rating und Opening-Quote."""
    if not d:
        return {}
    r = d["rating2"] if d.get("rating2") is not None else d.get("rating1")
    od = (d.get("ok") or 0) + (d.get("od") or 0)
    return {"rating": r, "kd": d.get("kd"), "adr": d.get("adr"), "kast": d.get("kast"), "hs_pct": d.get("hs_pct"),
            "open_pct": round(100 * d["ok"] / od) if od else None, "survival_pct": d.get("survival_pct"),
            "kpr": d.get("kpr")}


def fmt(x: float | None, dec: int) -> str:
    return "–" if x is None else f"{x:.{dec}f}".replace(".", ",")


def _cmp(cur: float | None, prev: float | None, clear: float) -> str | None:
    if cur is None or prev is None:
        return None
    return "up" if cur - prev >= clear else "down" if prev - cur >= clear else "same"


def side_split(entries: list[dict], sid: str) -> list[dict] | None:
    """T gegen CT aus by_round: Runden, Sieg-Anteil, Kills je Runde, ADR, Überleben. Erst ab 10 Runden je Seite."""
    acc = {s: {"rounds": 0, "won": 0, "kills": 0, "died": 0, "dmg": 0, "dmg_ok": True} for s in ("t", "ct")}
    for h in entries:
        for row in (h.get("by_round") or {}).get(sid) or []:
            _rnd, side, won, k, died, dmg = (list(row) + [None] * 6)[:6]
            side = str(side or "").lower()
            if side not in acc:
                continue
            a = acc[side]
            a["rounds"] += 1
            a["won"] += bool(won)
            a["kills"] += k or 0
            a["died"] += bool(died)
            if dmg is None:
                a["dmg_ok"] = False
            else:
                a["dmg"] += dmg
    if any(a["rounds"] < MIN_SIDE_ROUNDS for a in acc.values()):
        return None
    out = []
    for key, label, dec, f in (("win", "Runden gewonnen", 0, lambda a: 100 * a["won"] / a["rounds"]),
                               ("kpr", "Kills je Runde", 2, lambda a: a["kills"] / a["rounds"]),
                               ("adr", "Schaden je Runde", 0, lambda a: a["dmg"] / a["rounds"] if a["dmg_ok"] else None),
                               ("surv", "Runden überlebt", 0, lambda a: 100 * (a["rounds"] - a["died"]) / a["rounds"])):
        t, ct = f(acc["t"]), f(acc["ct"])
        if t is None or ct is None:
            continue
        unit = " %" if key in ("win", "surv") else ""
        top = max(t, ct) or 1
        out.append({"key": key, "label": label, "t": t, "ct": ct, "t_s": fmt(t, dec) + unit, "ct_s": fmt(ct, dec) + unit,
                    "t_w": round(100 * t / top, 1), "ct_w": round(100 * ct / top, 1)})
    return [{"rounds_t": acc["t"]["rounds"], "rounds_ct": acc["ct"]["rounds"]}] + out


def build(hist: list[dict], sid: str, n: str = "10", cur_map: str = "") -> dict:
    """Alles für die Stats-Seite. ``n``: "10" oder "all"; ``cur_map``: leer oder Map-Name."""
    mine = [h for h in hist if ((h.get("board") or {}).get(sid) or {}).get("rounds")]
    mine.sort(key=lambda h: h.get("analyzed_at") or "")
    maps = sorted({h.get("map") for h in mine if h.get("map")})
    pool = [h for h in mine if h.get("map") == cur_map] if cur_map in maps else mine
    sel = pool if n == "all" else pool[-10:]
    before = pool[:len(pool) - len(sel)]
    prev = before[-min(len(sel), 10):] if before else []

    tot = scoreboard.derive(scoreboard.totals([h["board"][sid] for h in sel]))
    cur_v = values(tot)
    prev_v = values(scoreboard.derive(scoreboard.totals([h["board"][sid] for h in prev]))) \
        if len(prev) >= MIN_CMP and len(sel) >= MIN_CMP else {}

    # Verlauf: ein Punkt je Match über den ganzen Pool (Schnitt rollt über die letzten ROLL Matches)
    series = []
    for h in pool:
        d = scoreboard.derive(h["board"][sid])
        sc = history.score(h, sid)
        series.append({"file": h.get("report_file"), "map": (h.get("map") or "?").removeprefix("de_").capitalize(),
                       "date": (h.get("analyzed_at") or "")[:10], "res": None if not sc else
                       "w" if sc[0] > sc[1] else "l" if sc[1] > sc[0] else "d",
                       "score": f"{sc[0]}:{sc[1]}" if sc else None, "v": values(d),
                       "kda": f"{d['kills']}-{d['deaths']}-{d['assists'] if d['assists'] is not None else '?'}",
                       "diff": d["diff"], "r1only": d["rating2"] is None})
    shown = series if n == "all" else series[-max(len(sel), 1):]

    tiles = []
    for key, title, unit, dec, clear in METRICS:
        pts = [s["v"].get(key) for s in shown]
        c = _cmp(cur_v.get(key), prev_v.get(key), clear)
        delta = None if c is None else cur_v[key] - prev_v[key]
        tiles.append({"key": key, "title": title, "unit": unit, "value": fmt(cur_v.get(key), dec), "raw": cur_v.get(key),
                      "cmp": c, "delta": None if delta is None else ("+" if delta > 0 else "−" if delta < 0 else "±")
                      + fmt(abs(delta), dec), "spark": _spark(pts)})

    chart = {"metrics": [{"key": k, "title": t, "unit": u, "dec": d} for k, t, u, d, _ in METRICS],
             "points": [{"map": s["map"], "date": s["date"], "res": s["res"], "score": s["score"], "file": s["file"],
                         **{k: s["v"].get(k) for k, *_ in METRICS}} for s in shown], "roll": ROLL}

    res = [s["res"] for s in series[-len(sel):]] if sel else []
    by_map = []
    for m in maps:
        hs = [h for h in mine if h.get("map") == m]
        v = values(scoreboard.derive(scoreboard.totals([h["board"][sid] for h in hs])))
        rs = [history.score(h, sid) for h in hs]
        won = sum(1 for r in rs if r and r[0] > r[1])
        decided = sum(1 for r in rs if r and r[0] != r[1])
        by_map.append({"map": m, "label": m.removeprefix("de_").capitalize(), "n": len(hs), "won": won,
                       "win_pct": round(100 * won / decided) if decided else None,
                       "rating": v.get("rating"), "rating_s": fmt(v.get("rating"), 2), "kd_s": fmt(v.get("kd"), 2),
                       "adr_s": fmt(v.get("adr"), 0)})
    by_map.sort(key=lambda x: -x["n"])

    multi = None
    if tot:
        t = scoreboard.totals([h["board"][sid] for h in sel])
        ks = [t[f"k{i}"] for i in range(1, 6)]
        multi = {"bars": [{"label": f"{i}K", "n": k, "w": round(100 * k / max(max(ks), 1), 1)} for i, k in enumerate(ks, 1)],
                 "rounds": t["rounds"]}
    return {"tot": tot, "cur": cur_v, "tiles": tiles, "chart": chart, "has_prev": bool(prev_v),
            "prev_n": len(prev) if prev_v else 0, "sel_n": len(sel), "won": res.count("w"), "lost": res.count("l"),
            "form": res[-5:], "maps": maps, "by_map": by_map, "sides": side_split(sel, sid), "multi": multi,
            "matches": series[-len(sel):][::-1] if sel else [], "pool_n": len(pool), "fmt": fmt}


def _spark(pts: list[float | None], w: float = 100, h: float = 28) -> dict | None:
    """Kleiner Verlauf als SVG-Pfad (Lücken bei fehlenden Werten). Mindestens 2 Werte."""
    xs = [(i, p) for i, p in enumerate(pts) if p is not None]
    if len(xs) < 2:
        return None
    lo, hi = min(p for _, p in xs), max(p for _, p in xs)
    span = (hi - lo) or 1
    step = w / max(len(pts) - 1, 1)
    coords = [(round(i * step, 1), round(h - 2 - (p - lo) / span * (h - 4), 1)) for i, p in xs]
    return {"d": "M" + " L".join(f"{x},{y}" for x, y in coords), "end": coords[-1], "w": w, "h": h}
