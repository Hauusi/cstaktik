"""Spielerprofil: Wo stehst du in jedem Bereich des Spiels? Aus den eigenen Demos, letzte 10 Matches.

Bereiche wie im CS-Wissen (academy AREAS): Schießen, Duelle, Granaten, Zusammenspiel, Runden lesen, Economy, dazu
T/CT. Je Bereich:
- Urteil aus den Kurs-Lektionen des Bereichs (course.placement, gleiche Grenzen wie im Kurs): eine Lektion ist
  Baustelle -> "Baustelle"; alle Lektionen mit genug Runden sitzen -> "Stärke"; sonst "Im Rahmen" oder "Zu wenig
  Daten". Economy hat keine Lektion, dort steht nur die Zahl, kein Urteil.
- Kennzahlen mit Verlauf gegen die 10 Matches davor (Pfeil nur bei klarem Abstand und je mindestens 3 Matches).
- Neutrale Bezugswerte nur, wo sie sich aus dem Spiel ergeben (50 % bei Duellen: ausgeglichen). Keine erfundenen
  Rang-Durchschnitte.
"""

from __future__ import annotations

from cstaktik import course, course_texts, scoreboard

WINDOW = 10
MIN_CMP = 3

AREAS = [
    {"key": "aim", "title": "Schießen", "stage": "shoot"},
    {"key": "duel", "title": "Duelle", "stage": "duel"},
    {"key": "nades", "title": "Granaten", "stage": "utility"},
    {"key": "team", "title": "Zusammenspiel", "stage": "team"},
    {"key": "round", "title": "Runden lesen", "stage": "round"},
    {"key": "eco", "title": "Economy", "stage": None},
]


def _ratio(entries, sid, get):
    """Summe Zähler / Summe Nenner über Matches; get(h) -> (zähler, nenner) oder None."""
    num = den = 0
    for h in entries:
        x = get(h, sid)
        if x and x[1]:
            num += x[0]
            den += x[1]
    return (100 * num / den, den) if den else (None, 0)


def _weighted(entries, sid, part, key, nkey):
    """Mittel eines Prozentwerts, gewichtet mit der Fallzahl je Match (z. B. Duelle gewonnen)."""
    num = den = 0
    for h in entries:
        d = ((h.get(part) or {}).get(sid) or {})
        v, n = d.get(key), d.get(nkey) or 0
        if v is not None and n:
            num += v * n
            den += n
    return (num / den, den) if den else (None, 0)


def _per10(entries, sid, get):
    """Ereignisse pro 10 Runden; get(h) -> Anzahl oder None (nicht gezählt)."""
    n = rounds = 0
    for h in entries:
        c = get(h, sid)
        r = ((h.get("players") or {}).get(sid) or {}).get("rounds") or h.get("rounds")
        if c is not None and r:
            n += c
            rounds += r
    return (10 * n / rounds, rounds) if rounds else (None, 0)


def _board(h, sid):
    return (h.get("board") or {}).get(sid) or {}


def _deaths(h, sid):
    return [d for d in h.get("deaths") or [] if d.get("sid") == sid]


# Kennzahl: (Schlüssel, Bereich, Titel, Einheit, Nachkommastellen, besser = "up"/"down", klarer Abstand, Bezug, Rechnung)
METRICS = [
    ("hs", "aim", "Headshots", "%", 0, "up", 5, None,
     lambda e, s: _ratio(e, s, lambda h, s: (_board(h, s).get("hs", 0), _board(h, s).get("kills", 0)))),
    ("hit", "aim", "Erste Kugel trifft", "%", 0, "up", 5, None,
     lambda e, s: _weighted(e, s, "duel_stats", "first_hit", "hit_n")),
    ("moving", "aim", "Erster Schuss aus der Bewegung", "%", 0, "down", 5, None,
     lambda e, s: _weighted(e, s, "duel_stats", "moving_pct", "moving_n")),
    ("duel_won", "duel", "Duelle gewonnen", "%", 0, "up", 5, 50,
     lambda e, s: _weighted(e, s, "duel_stats", "won", "n")),
    ("seen_me", "duel", "Du siehst zuerst", "%", 0, "up", 5, 50,
     lambda e, s: _weighted(e, s, "duel_stats", "seen_me", "seen_n")),
    ("open", "duel", "Opening-Duelle gewonnen", "%", 0, "up", 8, 50,
     lambda e, s: _ratio(e, s, lambda h, s: (_board(h, s).get("ok", 0), _board(h, s).get("ok", 0) + _board(h, s).get("od", 0)))),
    ("flash", "nades", "Flashes wirksam", "%", 0, "up", 8, None,
     lambda e, s: _ratio(e, s, lambda h, s: ((((h.get("nade_eff") or {}).get(s) or {}).get("flash") or {}).get("good", 0),
                                              (((h.get("nade_eff") or {}).get(s) or {}).get("flash") or {}).get("n", 0)))),
    ("util_death", "nades", "Tod mit Granate in der Tasche", " pro 10 R.", 1, "down", 0.3, None,
     lambda e, s: _per10(e, s, lambda h, s: ((h.get("lessons") or {}).get(s) or {}).get("utility", 0)
                         if s in (h.get("lessons") or {}) else None)),
    ("traded", "team", "Deine Tode getradet", "%", 0, "up", 6, None,
     lambda e, s: _ratio(e, s, lambda h, s: (sum(1 for d in _deaths(h, s) if d.get("traded")), len(_deaths(h, s))))),
    ("kast", "team", "KAST", "%", 0, "up", 3, None,
     lambda e, s: _ratio(e, s, lambda h, s: (_board(h, s).get("kast", 0), _board(h, s).get("rounds", 0))
                         if _board(h, s).get("assists_known") else None)),
    ("clutch", "round", "Clutches gewonnen", "%", 0, "up", 10, None,
     lambda e, s: _ratio(e, s, lambda h, s: (sum(1 for c in h.get("clutch") or [] if c.get("sid") == s and c.get("won")),
                                              sum(1 for c in h.get("clutch") or [] if c.get("sid") == s)))),
    ("advantage", "round", "Überzahl verspielt (Team)", " pro 10 R.", 1, "down", 0.3, None,
     lambda e, s: _per10(e, s, lambda h, s: (h.get("cause_rounds") or {}).get("advantage") if "cause_rounds" in h else None)),
    ("economy", "eco", "Runden mit Economy-Fehler (Team)", " pro 10 R.", 1, "down", 0.3, None,
     lambda e, s: _per10(e, s, lambda h, s: (h.get("cause_rounds") or {}).get("economy") if "cause_rounds" in h else None)),
]


def _fmt(x, dec):
    return "–" if x is None else f"{x:.{dec}f}".replace(".", ",")


def _trend(cur, prev, better, clear):
    if cur is None or prev is None:
        return None
    d = cur - prev
    if abs(d) < clear:
        return "same"
    return "up" if (d > 0) == (better == "up") else "down"  # up = besser, down = schlechter


def build(hist: list[dict], sid: str, cfg: dict | None = None) -> dict | None:
    """Profil eines Spielers: Bereiche mit Urteil, Kennzahlen und Verlauf, nächster Schritt."""
    mine = sorted((h for h in hist if sid in (h.get("players") or {})), key=lambda h: h.get("analyzed_at") or "")
    if not mine:
        return None
    cur, prev = mine[-WINDOW:], mine[:-WINDOW][-WINDOW:]
    cfg = cfg or course.settings()
    pl = course.placement(hist, sid, cfg)
    stage_lessons = {}
    for lid in course.path():
        stage_lessons.setdefault(course_texts.LESSONS[lid]["stage"], []).append(lid)

    areas = []
    for a in AREAS:
        lids = stage_lessons.get(a["stage"], []) if a["stage"] else []
        rows = [{"id": lid, "title": course_texts.LESSONS[lid]["title"], **pl[lid]} for lid in lids]
        bad = [r for r in rows if r["status"] == "baustelle"]
        known = [r for r in rows if r["status"] != "offen" or r["rounds"] >= cfg["min_rounds"]]
        if not lids:
            verdict, why = None, "Kein Urteil: Für Economy gibt es keine Kurs-Lektion, nur die Zahl aus euren Runden."
        elif bad:
            w = max(bad, key=lambda r: r["rate"] / r["threshold"])
            verdict = "baustelle"
            why = (f"{w['title']}: {_fmt(w['rate'], 1)} Fehler pro 10 Runden, Grenze {_fmt(w['threshold'], 1)}.")
        elif rows and all(r["status"] == "sitzt" for r in rows):
            verdict, why = "staerke", "Alle Lektionen dieses Bereichs sitzen laut deinen letzten Matches."
        elif known:
            verdict, why = "rahmen", "Keine Baustelle. Für „sitzt“ braucht der Coach noch mehr Runden."
        else:
            verdict, why = "offen", "Noch zu wenige Runden für ein Urteil."
        mets = []
        for key, area, title, unit, dec, better, clear, ref, f in METRICS:
            if area != a["key"]:
                continue
            v, n = f(cur, sid)
            pv, pn = f(prev, sid) if len(prev) >= MIN_CMP and len(cur) >= MIN_CMP else (None, 0)
            if v is None:
                continue
            mets.append({"key": key, "title": title, "value": _fmt(v, dec) + (unit if unit != "%" else " %"),
                         "n": n, "trend": _trend(v, pv, better, clear), "prev": _fmt(pv, dec) if pv is not None else None,
                         "ref": ref, "vs_ref": None if ref is None else ("über" if v > ref + 2 else "unter" if v < ref - 2 else "bei")})
        areas.append({**a, "verdict": verdict, "why": why, "lessons": rows, "metrics": mets,
                      "worst": (max(bad, key=lambda r: r["rate"] / r["threshold"])["id"] if bad else None)})

    # T/CT: Sieg-Anteil je Seite aus by_round
    sides = {}
    for s in ("t", "ct"):
        rr = [row for h in cur for row in ((h.get("by_round") or {}).get(sid) or []) if str(row[1]).lower() == s]
        if len(rr) >= 10:
            sides[s] = {"rounds": len(rr), "won_pct": round(100 * sum(1 for r in rr if r[2]) / len(rr))}
    t = scoreboard.derive(scoreboard.totals([_board(h, sid) for h in cur if _board(h, sid).get("rounds")]))
    rating = None if not t else (t["rating2"] if t.get("rating2") is not None else t["rating1"])
    order = {"baustelle": 0, "rahmen": 1, "offen": 2, "staerke": 3, None: 4}
    return {"n": len(cur), "has_prev": len(prev) >= MIN_CMP and len(cur) >= MIN_CMP, "prev_n": len(prev),
            "areas": areas, "sides": sides, "rating": _fmt(rating, 2) if rating is not None else None,
            "strengths": [a["title"] for a in areas if a["verdict"] == "staerke"],
            "weak": [a["title"] for a in sorted(areas, key=lambda a: order[a["verdict"]]) if a["verdict"] == "baustelle"]}
