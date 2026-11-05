"""Duo über mehrere Matches: Wie oft spielt ihr zusammen, und gewinnt ihr dann mehr?

Grundlage je Match ist ``h["duo"]`` (coach.duo, gespeichert ab diesem Update): Runden, in denen beide auf derselben
Seite lebten, getrennt nach mittlerem Abstand (zusammen = unter ``duo_close_units``), gegenseitige Trades, wer
zuerst starb. Ältere Matches haben das Feld nicht; sie kommen nach der Neuberechnung dazu.

Aussagen nur bei klarer Datenlage: Siegquote zusammen gegen getrennt erst ab MIN_ROUNDS je Gruppe und mit
mindestens CLEAR_PTS Prozentpunkten Abstand. Ein Zusammenhang ist kein Beweis, so steht es auch im Text.
"""

from __future__ import annotations

MIN_ROUNDS = 20
CLEAR_PTS = 10
WINDOW = 10


def _pct(won: int, n: int) -> int | None:
    return round(100 * won / n) if n else None


def summary(hist: list[dict], sid: str, names: dict | None = None) -> dict | None:
    """Duo des Spielers über die letzten WINDOW Matches mit Duo-Daten (immer mit demselben Partner: dem häufigsten)."""
    rows = [h for h in hist if (h.get("duo") or {}).get("sids") and sid in h["duo"]["sids"]]
    rows.sort(key=lambda h: h.get("analyzed_at") or "")
    if not rows:
        return None
    from collections import Counter

    mate = Counter(next(s for s in h["duo"]["sids"] if s != sid) for h in rows).most_common(1)[0][0]
    rows = [h for h in rows if mate in h["duo"]["sids"]][-WINDOW:]
    tog = {"rounds": 0, "won": 0}
    apart = {"rounds": 0, "won": 0}
    trades = {sid: 0, mate: 0}
    first = {sid: 0, mate: 0}
    dists, series = [], []
    for h in rows:
        d = h["duo"]
        for k in ("rounds", "won"):
            tog[k] += (d.get("together") or {}).get(k, 0)
            apart[k] += (d.get("apart") or {}).get(k, 0)
        for s in (sid, mate):
            trades[s] += (d.get("trades_by") or {}).get(s, 0)
            first[s] += (d.get("first_by") or {}).get(s, 0)
        if d.get("avg_distance") is not None:
            dists.append(d["avg_distance"])
        n = (d.get("together") or {}).get("rounds", 0) + (d.get("apart") or {}).get("rounds", 0)
        series.append({"map": (h.get("map") or "?").removeprefix("de_").capitalize(), "date": (h.get("analyzed_at") or "")[:10],
                       "together_pct": _pct((d.get("together") or {}).get("rounds", 0), n), "file": h.get("report_file")})
    total = tog["rounds"] + apart["rounds"]
    tw, aw = _pct(tog["won"], tog["rounds"]), _pct(apart["won"], apart["rounds"])
    enough = tog["rounds"] >= MIN_ROUNDS and apart["rounds"] >= MIN_ROUNDS
    if enough and tw - aw >= CLEAR_PTS:
        reading = (f"Zusammen gewinnt ihr {tw} % eurer Runden, getrennt nur {aw} %. Das ist ein Zusammenhang, kein Beweis, "
                   "aber ein deutlicher: Spielt mehr Runden zusammen.")
        tone = "good"
    elif enough and aw - tw >= CLEAR_PTS:
        reading = (f"Getrennt gewinnt ihr mehr ({aw} %) als zusammen ({tw} %). Vielleicht steht ihr zusammen zu eng "
                   "oder im selben Winkel. Abstand für Trades: nah genug zum Nachziehen, nicht direkt nebeneinander.")
        tone = "bad"
    elif enough:
        reading = f"Zusammen ({tw} %) und getrennt ({aw} %) gewinnt ihr etwa gleich oft."
        tone = ""
    else:
        reading = (f"Für einen Vergleich braucht der Coach mindestens {MIN_ROUNDS} Runden zusammen und {MIN_ROUNDS} getrennt "
                   f"(bisher {tog['rounds']} und {apart['rounds']}).")
        tone = ""
    nm = names or {}
    return {"mate": mate, "mate_name": nm.get(mate, "Mitspieler"), "me_name": nm.get(sid, "Du"), "matches": len(rows),
            "together": {**tog, "pct": tw}, "apart": {**apart, "pct": aw}, "total": total,
            "together_share": _pct(tog["rounds"], total), "avg_m": round(sum(dists) / len(dists) * 0.0254) if dists else None,
            "trades_me": trades[sid], "trades_mate": trades[mate], "first_me": first[sid], "first_mate": first[mate],
            "reading": reading, "tone": tone, "enough": enough, "series": series}


# --- Gemeinsame Abmachung (Verbundenheit: ihr arbeitet zu zweit an einer Sache) -------------------------------------
# Wenn-dann-Sätze in der Wir-Form; welche passt, schlägt der Coach aus euren Duo-Zahlen vor.
PLANS = {
    "together": "Wenn wir auf T den ersten Kontakt haben, dann gehen wir zu zweit dorthin und nicht getrennt.",
    "trade": "Wenn einer von uns peekt, dann steht der andere so nah, dass er sofort traden kann.",
    "call": "Wenn einer von uns stirbt, dann sagt er sofort Ort und HP des Gegners, und der andere tradet genau dorthin.",
    "reset": "Wenn wir zwei Runden in Folge verlieren, dann spielen wir die nächste Runde fest zusammen auf einer Seite.",
}


def _file(a: str, b: str):
    import re

    from cstaktik import pipeline

    x, y = sorted((a, b))
    return pipeline.DRILLS_DIR / f"duo_{re.sub(r'[^0-9A-Za-z]', '_', x)}_{re.sub(r'[^0-9A-Za-z]', '_', y)}.json"


def get_plan(a: str, b: str) -> dict | None:
    import json

    try:
        d = json.loads(_file(a, b).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d.get("plan") if isinstance(d, dict) else None


def set_plan(a: str, b: str, key: str, by: str, at: str) -> dict:
    import json

    from cstaktik import drills
    from cstaktik.fsutil import write_atomic

    if key not in PLANS:
        raise ValueError("unbekannte Abmachung")
    with drills.LOCK:
        f = _file(a, b)
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        plan = {"key": key, "text": PLANS[key], "by": by, "at": at}
        d["plan"] = plan
        d["plans"] = (d.get("plans") or [])[-19:] + [plan]
        write_atomic(f, json.dumps(d, ensure_ascii=False, indent=1))
        return plan


def recommend(s: dict | None) -> str:
    """Vorschlag aus euren Zahlen: getrennt deutlich schlechter -> zusammen; kaum Trades -> Calls; sonst Trade-Abstand."""
    if not s:
        return "trade"
    if s.get("enough") and (s["together"]["pct"] or 0) - (s["apart"]["pct"] or 0) >= CLEAR_PTS:
        return "together"
    died = (s.get("first_me") or 0) + (s.get("first_mate") or 0)
    if died >= 6 and (s.get("trades_me") or 0) + (s.get("trades_mate") or 0) < died / 3:
        return "call"
    return "trade"


def plan_check(hist: list[dict], sid: str, mate: str, plan: dict | None) -> str | None:
    """Seit der Abmachung: Anteil der Runden zusammen und Trades je Match, gegen die Matches davor (je min. 1)."""
    if not plan:
        return None
    rows = sorted((h for h in hist if {sid, mate} <= set((h.get("duo") or {}).get("sids") or [])),
                  key=lambda h: h.get("analyzed_at") or "")
    after = [h for h in rows if (h.get("analyzed_at") or "") > (plan.get("at") or "")]
    before = [h for h in rows if (h.get("analyzed_at") or "") <= (plan.get("at") or "")][-5:]
    if not after or not before:
        return None

    def share(hs):
        t = sum((h["duo"].get("together") or {}).get("rounds", 0) for h in hs)
        a = sum((h["duo"].get("apart") or {}).get("rounds", 0) for h in hs)
        return _pct(t, t + a)

    def trades(hs):
        return sum(sum((h["duo"].get("trades_by") or {}).values()) for h in hs) / len(hs)

    s_after, s_before = share(after), share(before)
    out = f"Seit eurer Abmachung ({len(after)} {'Match' if len(after) == 1 else 'Matches'}): "
    out += f"zusammen in {s_after} % der Runden, davor {s_before} %. " if s_after is not None and s_before is not None else ""
    de = lambda x: f"{x:.1f}".replace(".", ",")  # noqa: E731
    out += f"Gegenseitige Trades je Match: {de(trades(after))} statt {de(trades(before))}."
    return out


def partner(hist: list[dict], sid: str) -> str | None:
    """Duo-Partner: aus den Duo-Daten, sonst der andere eingestellte Fokus-Spieler (players.yaml)."""
    s = summary(hist, sid)
    if s:
        return s["mate"]
    from cstaktik.config import load_focus_steamids

    others = sorted(set(load_focus_steamids()) - {sid})
    return others[0] if len(others) == 1 else None
