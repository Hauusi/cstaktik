"""Wochenplan je Spieler: ein Thema (der laufende Auftrag), feste Aufgaben, Wochen-Check am Ende.

Aufgaben kommen nur aus vorhandenen Bausteinen: Übungsroutine des Auftrags (curriculum), schwächster Spot im
Map-Buch, ein Pro-Lineup, Situations-Training, Matches. Abhaken speichert data/coaching.json
(players[sid]["weeks"][Woche]). Der Wochen-Check rechnet aus dem Verlauf: Matches dieser Woche und die Rate des
Auftrags-Fehlers pro 10 Runden.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from cstaktik.coaching import now_local

MATCHES_PER_WEEK = 2


def local_today() -> date:
    """Heutiges Datum in deutscher Zeit (Server läuft oft in UTC: Montag 0-2 Uhr wäre sonst noch Vorwoche)."""
    return datetime.fromisoformat(now_local()).date()


def week_key(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def week_range(key: str) -> tuple[date, date]:
    y, w = key.split("-W")
    start = date.fromisocalendar(int(y), int(w), 1)
    return start, start + timedelta(days=6)


def tasks_for(ctx: dict) -> list[dict]:
    """ctx: lesson, routine, map, map_label, spot (Map-Buch-Zeile + side) | None, lineup | None, scenes, sid."""
    r = ctx["routine"]
    sid, m = ctx["sid"], ctx.get("map")
    out = [{"id": f"routine1:{ctx['lesson']}", "kind": "Übung", "title": r["title"], "minutes": r["minutes"],
            "steps": r["steps"]}]
    if m and ctx.get("spot"):
        s = ctx["spot"]
        do = []
        if s.get("alt"):
            a = s["alt"]
            do.append(f"Nächste {s['side'].upper()}-Runden: nach {s.get('at') or '0:20'} statt {s['place']} in {a['place']} "
                      f"stehen (Pros dort: {a['won_pct']} % Siege, {a['share']} % der Runden).")
        if s.get("lineups"):
            lu = s["lineups"][0]
            do.append(f"Oder bleiben, aber vorher die Pro-{lu['kind_de']} von {s['place']} nach {lu['to'] or '?'} werfen.")
        if not do:
            do.append("Im Map-Buch ansehen, was an diesem Spot schiefgeht, und Timing oder Position ändern.")
        check = f"Erfolg: 'als Erster tot' von {s['place']} aus steigt nicht weiter (jetzt {s['first']} von {s['n']} Runden)."
        out.append({"id": f"spot:{m}:{s['side']}:{s['place']}", "kind": "Map-Buch",
                    "title": f"{ctx['map_label']} {s['side'].upper()}: {s['place']} klären",
                    "steps": s["why"] + do + [check],
                    "link": f"/mapbook/{m}?p={sid}#spot-{s['side']}-{s['place']}"})
    elif m:
        out.append({"id": f"mapbook:{m}", "kind": "Map-Buch", "title": f"Map-Buch {ctx['map_label']} durchsehen",
                    "steps": ["Deine Spots und ihre Bewertung ansehen."], "link": f"/mapbook/{m}?p={sid}"})
    if m and ctx.get("lineup"):
        lu = ctx["lineup"]
        out.append({"id": f"lineup:{lu['id']}", "kind": "Lineup",
                    "title": f"{lu['kind_de']} lernen: {lu['from'] or '?'} → {lu['to'] or '?'}",
                    "steps": ["Eigener Server, sv_cheats 1, Position mit dem Befehl setzen.",
                              f"10x werfen. Sitzt = landet im Kreis auf der Karte (Pros streuen höchstens {lu['spread']} Units).",
                              "Dann 5x ohne Befehl von Hand anstellen.",
                              f"Im Match: Pros werfen sie meist bei {lu['t'] // 60}:{lu['t'] % 60:02d} Rundenzeit."],
                    "link": f"/lineups/{m}?l={lu['id']}&p={sid}"})
    if ctx.get("scenes"):
        out.append({"id": "quiz", "kind": "Situationen", "title": "Situations-Training: eigene Szenen entscheiden",
                    "steps": ["Jede Szene: erst entscheiden, dann auflösen."], "link": f"/training/situationen?p={sid}"})
    out.append({"id": f"routine2:{ctx['lesson']}", "kind": "Übung", "title": f"{r['title']} (Wiederholung)",
                "minutes": r["minutes"],
                "steps": ["Wie die erste Übung oben.",
                          "Diesmal direkt danach ein Match spielen: Der Auftrag-Check zeigt, ob es dort klappt."]})
    return out


def ensure(slot: dict, ctx: dict, today: date | None = None) -> tuple[str, dict, bool]:
    """Plan der aktuellen Woche; neu bauen, wenn er fehlt oder der Auftrag gewechselt hat (Häkchen bleiben,
    soweit die Aufgabe gleich ist). Rückgabe: (Woche, Plan, geändert)."""
    key = week_key(today or local_today())
    weeks = slot.setdefault("weeks", {})
    plan = weeks.get(key)
    if plan and plan.get("lesson") == ctx["lesson"]:
        return key, plan, False
    done = (plan or {}).get("done", {})
    tasks = tasks_for(ctx)
    weeks[key] = plan = {"lesson": ctx["lesson"], "created": now_local(),
                         "tasks": tasks, "done": {t["id"]: done[t["id"]] for t in tasks if t["id"] in done}}
    return key, plan, True


def toggle(slot: dict, key: str, task_id: str) -> bool | None:
    """Aufgabe abhaken oder Haken entfernen. Rückgabe: neuer Zustand (None = unbekannte Aufgabe)."""
    plan = slot.get("weeks", {}).get(key)
    if not plan or task_id not in {t["id"] for t in plan["tasks"]}:
        return None
    if task_id in plan["done"]:
        del plan["done"][task_id]
        return False
    plan["done"][task_id] = now_local()
    return True


def check(key: str, plan: dict, hist: list[dict], sid: str, focus: dict | None, min_rounds: int = 40) -> dict:
    """Wochen-Check: Aufgaben, Matches dieser Woche, Rate des Auftrags-Fehlers gegen das Ziel.

    Gezählt werden die Matches dieser Woche nach dem Start des Auftrags (dieselben wie im Auftrag-Check), pro
    gespielter Runde des Spielers. Unter ``min_rounds`` Runden gibt es kein Urteil, nur die Zahlen."""
    start, end = week_range(key)

    def in_week(stamp: str | None) -> bool:
        return bool(stamp) and start <= datetime.fromisoformat(stamp).date() <= end

    lesson = plan["lesson"]
    if focus and focus.get("lesson") == lesson:
        rows = [m for m in focus.get("matches", []) if in_week(m.get("date"))]
        n, rounds = sum(m.get("count") or 0 for m in rows), sum(m.get("rounds") or 0 for m in rows)
        n_matches = len(rows)
    else:  # vergangene Wochen: aus dem Verlauf
        ms = [h for h in hist if sid in h.get("players", {}) and in_week(h.get("analyzed_at"))]
        n = sum((h.get("lessons", {}).get(sid) or {}).get(lesson, 0) for h in ms)
        rounds = sum((h["players"][sid].get("rounds") or h.get("rounds") or 0) for h in ms)
        n_matches = len(ms)
    rate = round(10 * n / rounds, 1) if rounds else None
    out = {"key": key, "from": start.strftime("%d.%m."), "to": end.strftime("%d.%m."),
           "done": len(plan["done"]), "total": len(plan["tasks"]), "matches": n_matches, "need": MATCHES_PER_WEEK,
           "count": n, "rounds": rounds, "rate": rate}
    if focus and focus.get("lesson") == lesson:
        out["target"], out["baseline"] = focus["target"], focus["baseline"]
        out["met"] = None if rate is None or rounds < min_rounds else 10 * n / rounds <= focus["target"]
    return out
