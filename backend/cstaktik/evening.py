"""Spielabend und Ermüdung: Wie entwickelt sich dein Rating mit jedem weiteren Match an einem Tag?

Mentale Ermüdung verschlechtert sportspezifische Reaktion und Genauigkeit (Habay u. a. 2021). Für Esports ist die
Studienlage noch dünn, deshalb rechnet der Coach nur mit den eigenen Matches: Rating je Match-Nummer des Tages
(1., 2., 3., 4. und mehr), über alle Tage zusammengezählt wie HLTV-Karrierewerte. Ein Rat kommt erst, wenn genug
Abende da sind und der Abfall deutlich ist.

Zeitpunkt ist die Auswertung (analyzed_at). Matches kommen automatisch wenige Minuten nach Spielende, das passt meist.
"""

from __future__ import annotations

from collections import defaultdict

MIN_DAYS = 3  # so viele Tage mit mindestens zwei Matches braucht ein Rat
MIN_MATCHES_AT = 3  # so viele Matches braucht eine Match-Nummer, damit sie zählt
DROP = 0.10  # ab diesem Abfall gegenüber dem ersten Match eines Tages gibt es den Rat


def _days(hist: list[dict], sid: str) -> dict[str, list[dict]]:
    days: dict[str, list[dict]] = defaultdict(list)
    for h in sorted(hist, key=lambda h: h.get("analyzed_at") or ""):
        if sid in (h.get("board") or {}) and (h.get("analyzed_at") or "")[:10]:
            days[h["analyzed_at"][:10]].append(h)
    return days


def index_today(hist: list[dict], sid: str, h: dict) -> int | None:
    """Das wievielte Match des Tages ``h`` für den Spieler war (1 = erstes)."""
    day = (h.get("analyzed_at") or "")[:10]
    same = [x for x in _days(hist, sid).get(day, [])]
    ids = [x.get("id") for x in same]
    return ids.index(h.get("id")) + 1 if h.get("id") in ids else None


def curve(hist: list[dict], sid: str) -> dict:
    """Rating je Match-Nummer des Tages und, wenn die Daten reichen, ab welcher Nummer es deutlich sinkt."""
    from cstaktik import scoreboard

    days = _days(hist, sid)
    by_idx: dict[int, list[dict]] = defaultdict(list)
    for ms in days.values():
        for i, h in enumerate(ms, start=1):
            by_idx[min(i, 4)].append(h["board"][sid])
    rows = []
    for i in sorted(by_idx):
        d = scoreboard.derive(scoreboard.totals(by_idx[i]))
        if d:
            rows.append({"idx": i, "label": f"{i}." if i < 4 else "4.+", "n": len(by_idx[i]),
                         "rating": d["rating2"] if d["rating2"] is not None else d["rating1"]})
    multi = sum(1 for ms in days.values() if len(ms) >= 2)
    out = {"rows": rows, "days": len(days), "multi_days": multi, "stop_after": None, "drop": None}
    first = next((r for r in rows if r["idx"] == 1), None)
    if first and multi >= MIN_DAYS:
        for r in rows:
            if r["idx"] > 1 and r["n"] >= MIN_MATCHES_AT and first["rating"] - r["rating"] >= DROP:
                out["stop_after"] = r["idx"] - 1
                out["drop"] = (first["rating"], r["rating"], r["idx"])
                break
    return out
