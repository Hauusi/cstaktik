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
