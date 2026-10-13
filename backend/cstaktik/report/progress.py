"""Fortschritts-Seite über alle ausgewerteten Matches (aus data/history)."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES = Path(__file__).parent / "templates"
# Trend-Schwellen (Heuristik): letzte 2 Matches gegen die davor, Rate pro 10 Runden.
TREND_MIN_MATCHES = 4
BETTER_RATIO, WORSE_RATIO = 0.8, 1.25


def _label(h: dict) -> str:
    try:
        d = datetime.fromisoformat(h["analyzed_at"]).strftime("%d.%m.")
    except (KeyError, ValueError):
        d = "?"
    return f"{d} {(h.get('map') or '?').removeprefix('de_').capitalize()}"


def _trend(values: list[float | None]) -> dict:
    vals = [v for v in values if v is not None]
    if len(vals) < TREND_MIN_MATCHES:
        return {"state": "wenig", "text": f"Trend ab {TREND_MIN_MATCHES} Matches ({len(vals)} bisher)"}
    recent, before = vals[-2:], vals[:-2]
    a, b = sum(recent) / len(recent), sum(before) / len(before)
    if b == 0:
        return {"state": "gleich" if a == 0 else "schlechter", "text": "neu aufgetreten" if a else "weiter bei 0"}
    ratio = a / b
    if ratio <= BETTER_RATIO:
        return {"state": "besser", "text": f"besser ({round(b, 1)} → {round(a, 1)} pro 10 Runden)"}
    if ratio >= WORSE_RATIO:
        return {"state": "schlechter", "text": f"schlechter ({round(b, 1)} → {round(a, 1)} pro 10 Runden)"}
    return {"state": "gleich", "text": f"etwa gleich (~{round(a, 1)} pro 10 Runden)"}


def _lessons(histories: list[dict], sid: str) -> list[dict]:
    """Coach-Lektionen eines Spielers: Rate pro 10 Runden je Match (Trend) und je Map (Durchschnitt).
    Nur Matches mit Lektionsdaten zählen (ältere Einträge: ``cstaktik pro-update`` rüstet nach)."""
    from cstaktik.coach_voice import LESSONS

    hs = [h for h in histories if "lessons" in h and sid in h.get("players", {}) and h.get("rounds")]
    ids = {lid for h in hs for lid in h["lessons"].get(sid, {})} - {"duel"}
    out = []
    for lid in ids:
        rates = []
        for h in histories:
            if h in hs:
                rates.append(round(10 * h["lessons"].get(sid, {}).get(lid, 0) / h["rounds"], 2))
            else:
                rates.append(None)
        by_map: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for h in hs:
            m = h.get("map") or "?"
            by_map[m][0] += h["lessons"].get(sid, {}).get(lid, 0)
            by_map[m][1] += h["rounds"]
        total = sum(h["lessons"].get(sid, {}).get(lid, 0) for h in hs)
        out.append({"id": lid, "title": LESSONS[lid][0], "drill": LESSONS[lid][2], "total": total, "rates": rates,
                    "trend": _trend(rates),
                    "by_map": {m: {"rate": round(10 * c / r, 1), "count": c, "rounds": r} for m, (c, r) in by_map.items()}})
    out.sort(key=lambda x: -x["total"])
    return out


def build(histories: list[dict]) -> dict:
    matches = [
        {"label": _label(h), "map": h.get("map"), "won": h.get("won", 0), "lost": h.get("lost", 0),
         "rounds": h.get("rounds", 0), "report": h.get("report_file")}
        for h in histories
    ]
    names: dict[str, str] = {}
    for h in histories:
        for sid, p in h.get("players", {}).items():
            names[sid] = p["name"]

    players = []
    for sid, name in names.items():
        series = defaultdict(list)
        titles: set[str] = set()
        for h in histories:
            p = h.get("players", {}).get(sid)
            if p is None:
                for key in ("kd", "adr", "opening", "traded", "moving", "hit"):
                    series[key].append(None)
                continue
            series["kd"].append(round(p["kills"] / p["deaths"], 2) if p["deaths"] else None)
            series["adr"].append(p.get("adr"))
            series["opening"].append(p["opening_kills"] - p["opening_deaths"])
            series["traded"].append(round(100 * p["traded_deaths"] / p["deaths"]) if p["deaths"] else None)
            mech = (h.get("mech") or {}).get(sid) or {}
            series["moving"].append(mech.get("moving_pct"))
            series["hit"].append(mech.get("hit_pct"))
            titles.update(h.get("issues", {}).get(sid, {}).keys())
        issues = []
        for t in titles:
            rates = []
            for h in histories:
                if sid not in h.get("players", {}) or not h.get("rounds"):
                    rates.append(None)
                    continue
                n = h.get("issues", {}).get(sid, {}).get(t, 0)
                rates.append(round(10 * n / h["rounds"], 2))
            total = sum(h.get("issues", {}).get(sid, {}).get(t, 0) for h in histories)
            issues.append({"title": t, "rates": rates, "total": total, "trend": _trend(rates)})
        issues.sort(key=lambda i: -i["total"])
        players.append({"sid": sid, "name": name, "series": dict(series), "issues": issues,
                        "lessons": _lessons(histories, sid)})

    maps = []
    by_map = defaultdict(list)
    for h in histories:
        by_map[h.get("map") or "?"].append(h)
    for m, hs in by_map.items():
        floor = Counter()
        for h in hs:
            for i, j, c in h.get("floor", []):
                floor[(i, j)] += c
        deaths = [d for h in hs for d in h.get("deaths", [])]
        places = Counter((d["sid"], d["place"]) for d in deaths if d.get("place"))
        top = [{"name": names.get(s, s), "sid": s, "place": p, "count": c} for (s, p), c in places.most_common(8)]
        maps.append({"map": m, "label": m.removeprefix("de_").capitalize(), "matches": len(hs),
                     "floor": [[i, j, c] for (i, j), c in floor.items()], "deaths": deaths, "top": top})
    from cstaktik.history import FLOOR_UNITS

    return {"matches": matches, "players": players, "maps": maps, "floorUnits": FLOOR_UNITS}


def render_progress(histories: list[dict]) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    data = build(histories)
    data_json = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return env.get_template("progress.html").render(data=data, data_json=data_json)
