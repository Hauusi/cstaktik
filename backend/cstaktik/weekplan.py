"""Wochenplan je Spieler: ein Thema (der laufende Auftrag), feste Aufgaben, Wochen-Check am Ende.

Aufgaben kommen nur aus vorhandenen Bausteinen: Übungsroutine des Auftrags (curriculum), schwächster Spot im
Map-Buch, ein Pro-Lineup, Situations-Training, Matches. Abhaken speichert data/coaching.json
(players[sid]["weeks"][Woche]). Der Wochen-Check rechnet aus dem Verlauf: Matches dieser Woche und die Rate des
Auftrags-Fehlers pro 10 Runden.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

MATCHES_PER_WEEK = 2


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
        out.append({"id": f"spot:{m}:{s['side']}:{s['place']}", "kind": "Map-Buch",
                    "title": f"{ctx['map_label']} {s['side'].upper()}: {s['place']} klären",
                    "steps": s["why"] + ["Im Map-Buch ansehen, was Pros an diesem Spot anders machen."],
                    "link": f"/mapbook/{m}?p={sid}#spot-{s['side']}-{s['place']}"})
    elif m:
        out.append({"id": f"mapbook:{m}", "kind": "Map-Buch", "title": f"Map-Buch {ctx['map_label']} durchsehen",
                    "steps": ["Deine Spots und ihre Bewertung ansehen."], "link": f"/mapbook/{m}?p={sid}"})
    if m and ctx.get("lineup"):
        lu = ctx["lineup"]
        out.append({"id": f"lineup:{lu['id']}", "kind": "Lineup",
                    "title": f"{lu['kind_de']} lernen: {lu['from'] or '?'} → {lu['to'] or '?'}",
                    "steps": ["Eigener Server, sv_cheats 1, Position mit dem Befehl setzen.",
                              "10x werfen, bis sie jedes Mal sitzt. Dann 5x ohne Befehl von Hand anstellen."],
                    "link": f"/lineups/{m}?l={lu['id']}"})
    if ctx.get("scenes"):
        out.append({"id": "quiz", "kind": "Situationen", "title": "Situations-Training: eigene Szenen entscheiden",
                    "steps": ["Jede Szene: erst entscheiden, dann auflösen."], "link": f"/training/situationen?p={sid}"})
    out.append({"id": f"routine2:{ctx['lesson']}", "kind": "Übung", "title": f"{r['title']} (Wiederholung)",
                "minutes": r["minutes"], "steps": r["steps"]})
    return out


def ensure(slot: dict, ctx: dict, today: date | None = None) -> tuple[str, dict, bool]:
    """Plan der aktuellen Woche; neu bauen, wenn er fehlt oder der Auftrag gewechselt hat (Häkchen bleiben,
    soweit die Aufgabe gleich ist). Rückgabe: (Woche, Plan, geändert)."""
    key = week_key(today or date.today())
    weeks = slot.setdefault("weeks", {})
    plan = weeks.get(key)
    if plan and plan.get("lesson") == ctx["lesson"]:
        return key, plan, False
    done = (plan or {}).get("done", {})
    tasks = tasks_for(ctx)
    weeks[key] = plan = {"lesson": ctx["lesson"], "created": datetime.now().isoformat(timespec="minutes"),
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
    plan["done"][task_id] = datetime.now().isoformat(timespec="minutes")
    return True


def check(key: str, plan: dict, hist: list[dict], sid: str, focus: dict | None) -> dict:
    """Wochen-Check: Aufgaben, Matches dieser Woche, Rate des Auftrags-Fehlers gegen Start und Ziel."""
    start, end = week_range(key)
    ms = [h for h in hist if sid in h.get("players", {}) and h.get("analyzed_at")
          and start <= datetime.fromisoformat(h["analyzed_at"]).date() <= end]
    lesson = plan["lesson"]
    n = sum((h.get("lessons", {}).get(sid) or {}).get(lesson, 0) for h in ms)
    rounds = sum(h.get("rounds") or 0 for h in ms)
    rate = round(10 * n / rounds, 1) if rounds else None
    out = {"key": key, "from": start.strftime("%d.%m."), "to": end.strftime("%d.%m."),
           "done": len(plan["done"]), "total": len(plan["tasks"]), "matches": len(ms), "need": MATCHES_PER_WEEK,
           "count": n, "rate": rate}
    if focus and focus.get("lesson") == lesson:
        out["target"], out["baseline"] = focus["target"], focus["baseline"]
        out["met"] = None if rate is None else rate <= focus["target"]
    return out
