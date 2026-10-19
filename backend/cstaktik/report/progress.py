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


def _player_rounds(h: dict, sid: str) -> int:
    return int((h.get("players", {}).get(sid) or {}).get("rounds") or h.get("rounds") or 0)


def count_trend(counts: list[tuple[int, int]], recent_n: int = 2) -> dict:
    """Trend aus (Anzahl, Runden) je Match: die letzten ``recent_n`` Matches zusammen gegen alle davor zusammen."""
    from cstaktik.coaching import compare_rates

    if len(counts) <= recent_n:
        return {"state": "wenig", "text": f"Trend ab {recent_n + 1} Matches ({len(counts)} bisher)"}
    before, recent = counts[:-recent_n], counts[-recent_n:]
    return compare_rates(sum(n for n, _ in before), sum(r for _, r in before),
                         sum(n for n, _ in recent), sum(r for _, r in recent))


def _lessons(histories: list[dict], sid: str) -> list[dict]:
    """Coach-Lektionen eines Spielers: Rate pro 10 Runden je Match (Trend) und je Map (Durchschnitt).
    Nur Matches mit Lektionsdaten zählen (ältere Einträge: ``cstaktik pro-update`` rüstet nach)."""
    from cstaktik.coach_voice import LESSONS

    hs = [h for h in histories if "lessons" in h and sid in h.get("players", {}) and h.get("rounds")]
    ids = {lid for h in hs for lid in h["lessons"].get(sid, {}) if lid in LESSONS} - {"duel"}
    in_hs = {id(h) for h in hs}  # Identität statt Vergleich ganzer Verlaufs-Einträge (langsam)
    out = []
    for lid in ids:
        rates, counts = [], []
        for h in histories:
            if id(h) in in_hs:
                n, rd = h["lessons"].get(sid, {}).get(lid, 0), _player_rounds(h, sid)
                rates.append(round(10 * n / rd, 2) if rd else None)
                counts.append((n, rd))
            else:
                rates.append(None)
        by_map: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for h in hs:
            m = h.get("map") or "?"
            by_map[m][0] += h["lessons"].get(sid, {}).get(lid, 0)
            by_map[m][1] += _player_rounds(h, sid)
        total = sum(h["lessons"].get(sid, {}).get(lid, 0) for h in hs)
        last = {"count": counts[-1][0], "rounds": counts[-1][1]} if counts else None
        out.append({"id": lid, "title": LESSONS[lid][0], "drill": LESSONS[lid][2], "total": total, "rates": rates,
                    "rounds": sum(r for _n, r in counts), "last": last,
                    "trend": count_trend(counts),
                    "by_map": {m: {"rate": round(10 * c / r, 1), "count": c, "rounds": r} for m, (c, r) in by_map.items()}})
    out.sort(key=lambda x: -x["total"])
    return out


def build(histories: list[dict], sids: list[str] | None = None, me: str | None = None) -> dict:
    """Daten für die Todes-Karte. ``sids``: nur diese Spieler, in dieser Reihenfolge (None = alle). ``me``: der
    eingeloggte Spieler; er steht immer vorn, damit die Seite mit seinen Daten öffnet."""
    matches = [
        {"label": _label(h), "map": h.get("map"), "won": h.get("won", 0), "lost": h.get("lost", 0),
         "rounds": h.get("rounds", 0), "report": h.get("report_file")}
        for h in histories
    ]
    names: dict[str, str] = {}
    for h in histories:
        for sid, p in h.get("players", {}).items():
            names[sid] = p["name"]

    order = [s for s in (sids if sids is not None else list(names)) if s in names]
    if me in order:
        order.remove(me)
        order.insert(0, me)
    players = []
    for sid in order:
        name = names[sid]
        series = defaultdict(list)
        titles: set[str] = set()
        for h in histories:
            p = h.get("players", {}).get(sid)
            if p is None:
                for key in ("kd", "adr", "opening", "traded", "moving", "hit"):
                    series[key].append(None)
                continue
            k, d = p.get("kills"), p.get("deaths")  # fehlende Werte bleiben Lücken statt Fehler
            series["kd"].append(round(k / d, 2) if k is not None and d else None)
            series["adr"].append(p.get("adr"))
            ok, od = p.get("opening_kills"), p.get("opening_deaths")
            series["opening"].append(ok - od if ok is not None and od is not None else None)
            td = p.get("traded_deaths")
            series["traded"].append(round(100 * td / d) if td is not None and d else None)
            mech = (h.get("mech") or {}).get(sid) or {}
            series["moving"].append(mech.get("moving_pct"))
            series["hit"].append(mech.get("hit_pct"))
            titles.update(h.get("issues", {}).get(sid, {}).keys())
        issues = []
        for t in titles:
            rates, counts = [], []
            for h in histories:
                if sid not in h.get("players", {}) or not _player_rounds(h, sid):
                    rates.append(None)
                    continue
                n, rd = h.get("issues", {}).get(sid, {}).get(t, 0), _player_rounds(h, sid)
                rates.append(round(10 * n / rd, 2))
                counts.append((n, rd))
            total = sum(h.get("issues", {}).get(sid, {}).get(t, 0) for h in histories)
            issues.append({"title": t, "rates": rates, "total": total, "trend": count_trend(counts)})
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
        deaths = [d for h in hs for d in h.get("deaths", []) if d.get("sid") in order]
        places = Counter((d["sid"], d["place"]) for d in deaths if d.get("place"))
        top = [{"name": names.get(s, s), "sid": s, "place": p, "count": c} for (s, p), c in places.most_common(8)]
        maps.append({"map": m, "label": m.removeprefix("de_").capitalize(), "matches": len(hs),
                     "floor": [[i, j, c] for (i, j), c in floor.items()], "deaths": deaths, "top": top})
    from cstaktik.history import FLOOR_UNITS

    return {"matches": matches, "players": players, "maps": maps, "floorUnits": FLOOR_UNITS, "me": me}


def karte_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def render_progress(histories: list[dict]) -> str:
    """Export als eigene HTML-Datei (cli progress), alle Spieler. In der App: Route /progress/karte."""
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    data = build(histories)
    from cstaktik.callouts import JS
    from cstaktik.fonts import font_css

    return env.get_template("progress.html").render(data=data, data_json=karte_json(data), font_css=font_css(),
                                                    callouts_js=JS)


# ---------------------------------------------------------------- Spielerprofil (Seite "Fortschritt")

def _pooled_duels(hs: list[dict], sid: str) -> dict | None:
    """Duell-Werte über mehrere Matches: je Wert das nach Fallzahl gewichtete Mittel der Match-Werte."""
    rows = [(h.get("duel_stats") or {}).get(sid) for h in hs]
    rows = [r for r in rows if r and r.get("n")]
    if not rows:
        return None
    out = {"n": sum(r["n"] for r in rows), "matches": len(rows)}
    for key, nkey in (("err", "err_n"), ("react", "react_n"), ("first_hit", "hit_n"), ("shot_first", "first_n"),
                      ("won", "n"), ("moving_pct", "moving_n"), ("seen_me", "seen_n"), ("seen_opp", "seen_n"),
                      ("won_seen_me", "seen_me_n"), ("won_seen_opp", "seen_opp_n"), ("err_side", "aim_n"),
                      ("err_height", "aim_n"), ("low_pct", "aim_n"), ("tts", "tts_n")):
        pairs = [(r[key], r.get(nkey) or r["n"]) for r in rows if r.get(key) is not None]
        w = sum(n for _v, n in pairs)
        out[key] = (round(sum(v * n for v, n in pairs) / w) if key not in ("err", "err_side", "err_height") else
                    round(sum(v * n for v, n in pairs) / w, 1)) if w else None
        if nkey != "n":  # "n" ist die Gesamtzahl der Duelle, nicht das Gewicht eines einzelnen Werts
            out[nkey] = w
    return out


def _spark(values: list[float | None], target: float | None = None) -> dict:
    """Punkte für eine kleine Linie (SVG 0..100 x 0..30)."""
    vals = [v for v in values if v is not None]
    if not vals:
        return {"points": "", "target_y": None, "last": None}
    top = max(vals + ([target] if target is not None else [])) * 1.15 or 1
    pts = [(i, v) for i, v in enumerate(values) if v is not None]
    n = max(1, len(values) - 1)
    return {"points": " ".join(f"{100 * i / n:.1f},{30 - 28 * v / top:.1f}" for i, v in pts),
            "dots": [{"x": round(100 * i / n, 1), "y": round(30 - 28 * v / top, 1)} for i, v in pts],
            "target_y": None if target is None else round(30 - 28 * target / top, 1), "last": vals[-1]}


def profile(histories: list[dict], sid: str, pro_duels: dict | None, focus: dict | None = None) -> dict:
    """Alles, was der Coach über einen Spieler weiß, auf einer Seite: Auftrag, Duell-Profil, Fehler-Trends, Maps."""
    from cstaktik.coach_voice import duel_reading

    hs = [h for h in histories if sid in h.get("players", {})]
    name = next((h["players"][sid].get("name") for h in reversed(hs)), sid)
    recent = hs[-5:]
    duels = _pooled_duels(recent, sid)
    lessons = _lessons(histories, sid)
    for l in lessons:
        l["spark"] = _spark([r for r in l["rates"]][-10:])
        l["total_rounds"] = sum(_player_rounds(h, sid) for h in hs if "lessons" in h)
    maps = []
    for m in sorted({h.get("map") for h in hs if h.get("map")}):
        mh = [h for h in hs if h.get("map") == m]
        worst = max(lessons, key=lambda l: (l["by_map"].get(m) or {}).get("rate", -1), default=None)
        wm = (worst or {}).get("by_map", {}).get(m)
        maps.append({"map": m, "label": m.removeprefix("de_").capitalize(), "matches": len(mh),
                     "won": sum(1 for h in mh if h.get("won", 0) > h.get("lost", 0)),
                     "worst": {"title": worst["title"], **wm} if worst and wm and wm["count"] >= 3 else None})
    maps.sort(key=lambda m: -m["matches"])
    matches = [{"label": _label(h), "won": h.get("won", 0), "lost": h.get("lost", 0), "report": h.get("report_file")}
               for h in reversed(hs[-8:])]
    return {"sid": sid, "name": name, "n_matches": len(hs), "duels": duels, "pro": pro_duels,
            "reading": duel_reading(duels, pro_duels) if duels else None, "lessons": lessons[:6],
            "maps": maps, "matches": matches, "focus": focus}
