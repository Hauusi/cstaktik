"""Wochenrückblick: Der Coach meldet sich einmal pro Woche, auch ohne neues Match.

Letzte 7 Tage gegen die 28 Tage davor: Ergebnisse, Rating, was klar besser oder schlechter wurde (Kennzahlen und
Abstände wie im Spielerprofil), Stand der Lektion, Warm-ups und Sessions, ein Muster aus deinen Entscheidungen, und
was nächste Woche dran ist. Vergleiche erst ab MIN_PREV Matches davor. Push sonntags (reminder.weekly_check).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from cstaktik import scoreboard

MIN_PREV = 3


def _at(h: dict) -> datetime | None:
    try:
        return datetime.fromisoformat((h.get("analyzed_at") or "")[:19])
    except ValueError:
        return None


def _rating(rows: list[dict]) -> float | None:
    d = scoreboard.derive(scoreboard.totals(rows))
    return None if not d else (d["rating2"] if d.get("rating2") is not None else d["rating1"])


def _de(x: float, d: int = 2) -> str:
    return f"{x:.{d}f}".replace(".", ",")


def build(hist: list[dict], sid: str, now: datetime, slot: dict | None = None) -> dict | None:
    from cstaktik import coach_memory, course_texts, drills, history, spielerprofil

    start, prev_start = now - timedelta(days=7), now - timedelta(days=35)
    mine = [h for h in hist if sid in (h.get("players") or {}) and _at(h)]
    week = sorted((h for h in mine if start <= _at(h) <= now), key=_at)
    prev = [h for h in mine if prev_start <= _at(h) < start]
    lines: list[str] = []
    if not week:
        lines.append("Diese Woche gab es kein Match. Kein Problem: Das Warm-up hält Plan und Wissen frisch.")
    else:
        res = [history.score(h, sid) for h in week]
        w = sum(1 for r in res if r and r[0] > r[1])
        l = sum(1 for r in res if r and r[1] > r[0])
        d = sum(1 for r in res if r and r[0] == r[1])
        lines.append(f"Diese Woche: {len(week)} {'Match' if len(week) == 1 else 'Matches'}, {w} "
                     f"{'Sieg' if w == 1 else 'Siege'}, {l} {'Niederlage' if l == 1 else 'Niederlagen'}"
                     + (f", {d} unentschieden" if d else "") + ".")
        rw = _rating([(h.get("board") or {}).get(sid) for h in week if (h.get("board") or {}).get(sid)])
        rp = _rating([(h.get("board") or {}).get(sid) for h in prev if (h.get("board") or {}).get(sid)])
        if rw is not None and rp is not None and len(prev) >= MIN_PREV:
            if rw - rp >= 0.05:
                lines.append(f"Dein Rating lag bei {_de(rw)}, besser als in den Wochen davor ({_de(rp)}).")
            elif rp - rw >= 0.05:
                lines.append(f"Dein Rating lag bei {_de(rw)}, unter den Wochen davor ({_de(rp)}).")
            else:
                lines.append(f"Dein Rating lag bei {_de(rw)}, etwa wie in den Wochen davor.")
        if len(prev) >= MIN_PREV:
            better, worse = [], []
            for key, _area, title, unit, dec, up, clear, _ref, f in spielerprofil.METRICS:
                a, _n = f(week, sid)
                b, _m = f(prev, sid)
                if a is None or b is None or abs(a - b) < clear:
                    continue
                u = " %" if unit == "%" else ""
                txt = f"{title} ({_de(b, dec)}{u} auf {_de(a, dec)}{u})"
                ((better if (a > b) == (up == "up") else worse)).append((abs(a - b) / clear, txt))
            if better:
                lines.append("Besser geworden: " + ", ".join(t for _, t in sorted(better, reverse=True)[:2]) + ".")
            if worse:
                lines.append("Schlechter geworden: " + ", ".join(t for _, t in sorted(worse, reverse=True)[:2]) + ".")
    f = (slot or {}).get("focus") or {}
    if f.get("lesson") in course_texts.LESSONS:
        title = course_texts.LESSONS[f["lesson"]]["title"]
        ms = [m for m in f.get("matches") or [] if m.get("met") is not None
              and start.isoformat() <= (m.get("date") or "") <= now.isoformat()]
        if ms:
            ok = sum(1 for m in ms if m["met"])
            lines.append(f"An „{title}“: {ok} von {len(ms)} {'Match' if len(ms) == 1 else 'Matches'} im Ziel.")
    done = [x for x in (slot or {}).get("done") or [] if start.isoformat() <= (x.get("done_at") or "") <= now.isoformat()
            and x.get("lesson") in course_texts.LESSONS]
    for x in done:
        lines.append(f"Geschafft diese Woche: „{course_texts.LESSONS[x['lesson']]['title']}“.")
    dd = drills.load(sid)
    warm = len({w[:10] for w in dd.get("warmups") or [] if start.isoformat() <= w <= now.isoformat()})
    sess = sum(1 for v in (dd.get("sessions") or {}).values() if start.isoformat() <= v <= now.isoformat())
    if week or warm:
        lines.append(f"Warm-up an {warm} {'Tag' if warm == 1 else 'Tagen'}, {sess} "
                     f"{'Session' if sess == 1 else 'Sessions'} nach dem Match."
                     + (" Genau so bleibt es hängen." if warm >= 3 else ""))
    dec = coach_memory.lines(hist, sid)
    if dec:
        lines.append(dec[0])
    if f.get("lesson") in course_texts.LESSONS:
        lines.append(f"Nächste Woche bleiben wir bei „{course_texts.LESSONS[f['lesson']]['title']}“.")
    return {"lines": lines, "matches": len(week), "from": start.date().isoformat(), "to": now.date().isoformat()}


def message(r: dict) -> dict:
    body = " ".join(r["lines"][:2])
    return {"title": "Dein Wochenrückblick", "body": body[:220], "url": "/woche"}
