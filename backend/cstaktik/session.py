"""Spielabend ("Heute") und Übungs-Kreislauf.

- ``session``: die Matches eines Spielers am selben Tag (deutsche Zeit) zusammen: Ergebnisse aus seiner Sicht,
  Auftrags-Rate über alle Matches des Tages, Impact zusammen, Tilt-Hinweis. Erst ab dem zweiten Match des Tages.
- ``practice``: Auftrags-Rate in Matches nach einer abgehakten Übung gegen Matches ohne Übung.

Nur Werte aus dem Verlauf und aus coaching.json. Fehlt etwas oder sind es zu wenige Runden, fehlt die Zeile.
Alles hier ist ein Zusammenhang, kein Beweis.
"""

from __future__ import annotations

from datetime import date

MIN_MATCHES = 2  # "Heute" erst ab dem zweiten Match des Tages


def _min_rounds() -> int:
    """Runden, ab denen eine gepoolte Rate zählt (wie beim Meistern eines Auftrags, rules.yaml goals)."""
    from cstaktik.config import load_rules_config

    try:
        return int(load_rules_config()["goals"].get("min_master_rounds", 40))
    except (KeyError, TypeError, ValueError):
        return 40


def _de1(x: float) -> str:
    return str(round(x, 1)).replace(".", ",")


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _check(h: dict, sid: str) -> dict | None:
    """Auftrag-Check dieses Spielers im Match (neues Format je Spieler, altes gemeinsames Format)."""
    fc = h.get("focus_check") or {}
    v = fc if "check" in fc else fc.get(sid)
    c = v.get("check") if isinstance(v, dict) else None
    return c if c and c.get("lesson") and c.get("target") is not None else None


def day_matches(hist: list[dict], sid: str, day: date, until: str | None = None) -> list[dict]:
    """Matches des Spielers an diesem Tag, optional nur bis zu diesem Auswertungszeitpunkt (einschließlich)."""
    key = day.isoformat()
    return [h for h in hist if sid in (h.get("players") or {}) and (h.get("analyzed_at") or "")[:10] == key
            and (until is None or (h.get("analyzed_at") or "") <= until)]


def session(hist: list[dict], sid: str, day: date, until: str | None = None) -> dict | None:
    """Spielabend eines Spielers. None bei weniger als ``MIN_MATCHES`` Matches an diesem Tag."""
    from cstaktik import history, tilt
    from cstaktik.coach_voice import LESSONS
    from cstaktik.coaching import _pooled

    ms = sorted(day_matches(hist, sid, day, until), key=lambda h: h.get("analyzed_at") or "")
    if len(ms) < MIN_MATCHES:
        return None
    won = lost = draw = 0
    for h in ms:
        w, lo = history.score(h, sid)
        won += w > lo
        lost += lo > w
        draw += w == lo
    res = [_count(won, "Sieg", "Siege"), _count(lost, "Niederlage", "Niederlagen")]
    if draw:
        res.append(_count(draw, "Unentschieden", "Unentschieden"))
    out = {"n": len(ms), "won": won, "lost": lost, "draw": draw,
           "line": f"Heute {len(ms)} Matches: " + ", ".join(res) + ".",
           "auftrag": None, "impact": None, "tilt": None}

    # Auftrag: der zuletzt geprüfte Auftrag des Tages, Rate über alle Matches des Tages zusammen
    c = next((x for x in (_check(h, sid) for h in reversed(ms)) if x), None)
    if c and c["lesson"] in LESSONS:
        pooled = _pooled(ms, c["lesson"], sid)
        if pooled and pooled[2] >= _min_rounds():
            rate, n, rounds = pooled
            ok = rate <= float(c["target"])
            out["auftrag"] = {"title": LESSONS[c["lesson"]][0], "rate": _de1(rate), "target": _de1(float(c["target"])),
                              "count": n, "rounds": rounds, "met": ok,
                              "text": (f"{_de1(rate)} pro 10 Runden, Ziel höchstens {_de1(float(c['target']))}. "
                                       f"{n}x in {rounds} Runden. " + ("Im Ziel." if ok else "Über dem Ziel."))}

    # Impact nur, wenn jedes Match des Tages einen Wert hat (sonst wäre die Summe zu klein)
    imps = [((h.get("impact") or {}).get(sid) or {}).get("total") for h in ms]
    if all(x is not None for x in imps):
        from cstaktik.impact import de

        total = sum(imps)
        out["impact"] = {"total": de(total / 100), "pos": total > 0}

    # Tilt nur, wenn die Matches des Tages nach den festen Schwellen klar schlechter nach Serien zeigen
    t = tilt.summary(ms, sid)
    if t and t.get("bad") and t.get("reading"):
        out["tilt"] = t["reading"]
    return out


def practice(slot: dict | None, min_rounds: int | None = None) -> dict | None:
    """Auftrags-Fehler pro 10 Runden in Matches nach einer abgehakten Übung gegen Matches ohne Übung davor.

    Gezählt aus den Auftrag-Checks (laufender und gemeisterte Aufträge): ``drills`` = Übungen derselben Lektion
    seit dem Match davor. Nur mit genug Runden auf beiden Seiten (``coaching.compare_rates``), sonst None."""
    from cstaktik.coaching import compare_rates

    if not slot:
        return None
    min_rounds = _min_rounds() if min_rounds is None else min_rounds
    focuses = list(slot.get("done") or []) + ([slot["focus"]] if slot.get("focus") else [])
    seen = set()
    n = {True: 0, False: 0}
    r = {True: 0, False: 0}
    for f in focuses:
        for m in f.get("matches") or []:
            key = (f.get("lesson"), m.get("match"))
            if key in seen or "drills" not in m or not m.get("rounds") or m.get("count") is None:
                continue  # ältere Einträge ohne Übungs-Zahl: unbekannt, nicht "ohne Übung"
            seen.add(key)
            side = bool(m["drills"])
            n[side] += int(m["count"])
            r[side] += int(m["rounds"])
    v = compare_rates(n[False], r[False], n[True], r[True], min_rounds)
    if v["state"] == "wenig":
        return None
    reading = {"besser": "Nach Übungen seltener. Ein Zusammenhang, kein Beweis.",
               "schlechter": "Nach Übungen nicht seltener, eher häufiger.",
               "gleich": "Kein klarer Unterschied."}[v["state"]]
    return {"state": v["state"],
            "text": (f"In Matches nach einer Übung: {_de1(10 * n[True] / r[True])} Auftrags-Fehler pro 10 Runden "
                     f"({n[True]}x in {r[True]} Runden). Ohne: {_de1(10 * n[False] / r[False])} "
                     f"({n[False]}x in {r[False]} Runden). {reading}")}
