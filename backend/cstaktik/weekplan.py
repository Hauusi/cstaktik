"""Wochenplan je Spieler: ein Thema (der laufende Auftrag), feste Aufgaben, Wochen-Check am Ende.

Aufgaben kommen nur aus vorhandenen Bausteinen: Übungsroutine des Auftrags (curriculum), schwächster Spot im
Map-Buch, ein Pro-Lineup, Situations-Training, Matches. Abhaken speichert data/coaching.json
(players[sid]["weeks"][Woche]). Der Wochen-Check rechnet aus dem Verlauf: Matches dieser Woche und die Rate des
Auftrags-Fehlers pro 10 Runden.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from cstaktik import callouts
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
    """ctx: lesson, routine, map, map_label, spot (Map-Buch-Zeile + side) | None, lineup | None, scenes, sid,
    tactic (Pro-Empfehlung aus dem Playbook) | None, positions (eigene Standard-Spots je Seite aus dem Map-Buch),
    pos_lineups (Pro-Lineups von diesen Spots), fault (was als Fehler zählt), in_game (Ansage fürs Match).

    Die Übung kommt einmal vor (kein "Wiederholung"-Eintrag, kein zweites Aufwärmen): konkret mit deinen Spots."""
    r = ctx["routine"]
    sid, m = ctx["sid"], ctx.get("map")
    pos = ctx.get("positions") or []
    pls = ctx.get("pos_lineups") or []
    steps = list(r["steps"])
    if pos:
        where = ", ".join(f"{p['side'].upper()} {callouts.place(p['place'])} ({p['n']} Runden)" for p in pos)
        steps.append(f"Deine Standard-Spots auf {ctx.get('map_label')} laut Map-Buch: {where}. Übe genau dort.")
    if pls:
        steps.append("Offline-Server mit sv_cheats 1 und Bots aus. Pro-Lineup unten kopieren, in die Konsole, "
                     "werfen. Danach 5x ohne Befehl von Hand anstellen.")
    routine = {"id": f"routine1:{ctx['lesson']}", "kind": "Übung", "title": r["title"], "minutes": r["minutes"],
               "steps": steps}
    if m and pos:
        routine["positions"] = [{"side": p["side"].upper(), "place": callouts.place(p["place"]), "n": p["n"],
                                 "link": f"/mapbook/{m}?p={sid}#spot-{p['side']}-{p['place']}"} for p in pos]
    if ctx.get("fault"):
        routine["fault"] = ctx["fault"]
    if ctx.get("in_game"):
        routine["in_game"] = ctx["in_game"]
    if m and pls:
        routine["lineups"] = [{"label": f"{lu['kind_de']} von {lu['from_c']} auf {lu['to_c']}", "cmd": lu["cmd"],
                               "tech": lu["tech"]["label"], "clock": lu["clock"], "n": lu["n"],
                               "link": f"/lineups/{m}?l={lu['id']}&p={sid}"} for lu in pls[:2]]
    out = [routine]
    if m and ctx.get("spot"):
        s = ctx["spot"]
        place = callouts.place(s["place"])
        at = s.get("at") or "1:35"
        do = []
        if s.get("alt"):
            a = s["alt"]
            do.append(f"Stell dich in den nächsten {s['side'].upper()}-Runden bei {at} auf der Uhr nach "
                      f"{callouts.place(a['place'])} statt {place}. Pros stehen dort in {a['share']} % der Runden "
                      f"({a['n']} Runden) und gewinnen {a['won_pct']} %.")
        if s.get("lineups"):
            lu = s["lineups"][0]
            do.append(f"Oder bleib dort. Wirf aber vorher die Pro-{lu['kind_de']} von {place} auf "
                      f"{callouts.place(lu.get('to')) or '?'}.")
        if not do:
            do.append("Schau im Map-Buch, was an diesem Spot schiefgeht. Ändere dann Timing oder Position.")
        # Erfolgskriterium nach dem Auslöser: als Erster gestorben oder ohne Trade gestorben
        if (s.get("untraded") or 0) > s["first"]:
            check = (f"Erfolg: Tode ohne Trade von {place} aus steigen nicht weiter. "
                     f"Jetzt sind es {s['untraded']} von {s['n']} Runden.")
        else:
            check = (f"Erfolg: Tode als Erster von {place} aus steigen nicht weiter. "
                     f"Jetzt sind es {s['first']} von {s['n']} Runden.")
        out.append({"id": f"spot:{m}:{s['side']}:{s['place']}", "kind": "Map-Buch",
                    "title": f"{ctx['map_label']} {s['side'].upper()}: {place} klären",
                    "steps": s["why"] + do + [check],
                    "link": f"/mapbook/{m}?p={sid}#spot-{s['side']}-{s['place']}"})
    elif m:
        out.append({"id": f"mapbook:{m}", "kind": "Map-Buch", "title": f"Map-Buch {ctx['map_label']} durchsehen",
                    "steps": ["Sieh dir deine Spots und ihre Bewertung an.",
                              *(["Am wichtigsten sind deine Standard-Spots: "
                                 + ", ".join(f"{p['side'].upper()} {callouts.place(p['place'])}" for p in pos)
                                 + ". Lies dort, von wo du erschossen wirst."] if pos else [])],
                    "link": f"/mapbook/{m}?p={sid}"})
    lu = ctx.get("lineup")
    if m and lu and not any(lu["id"] == x["id"] for x in pls[:2]):
        out.append({"id": f"lineup:{lu['id']}", "kind": "Lineup",
                    "title": f"{lu['kind_de']} lernen: {callouts.place(lu.get('from')) or '?'} → "
                             f"{callouts.place(lu.get('to')) or '?'}",
                    "steps": ["Starte einen eigenen Server mit sv_cheats 1. Setz die Position mit dem Befehl.",
                              (f"Wirf 10x. Sie sitzt, wenn sie im Kreis auf der Karte landet. Pros streuen "
                               f"höchstens {callouts.meters(lu['spread'])}."),
                              "Stell dich dann 5x ohne Befehl von Hand an.",
                              f"Im Match werfen Pros sie meist bei {callouts.clock(lu['t'])} auf der Uhr."],
                    "link": f"/lineups/{m}?l={lu['id']}&p={sid}"})
    if m and ctx.get("tactic"):
        t = ctx["tactic"]
        nades = ", ".join(f"{ {'smoke': 'Smoke', 'flash': 'Flash', 'molotov': 'Molotov'}.get(c['kind'], c['kind'])} "
                          f"auf {callouts.place(c['to'])}" for c in t.get("common", [])[:4])
        out.append({"id": f"tactic:{m}:{t['id']}", "kind": "Playbook", "title": f"Pro-Taktik: {t['name']}",
                    "steps": [(f"Spielt sie im Playbook ab. Pros gewinnen damit {t['won_pct']} %, {t['won']} von "
                               f"{t['n']} Runden."),
                              *([f"Granaten-Set: {nades}. Die Lineups dazu sind dort verlinkt."] if nades else []),
                              ("Jeder übernimmt eine Rolle. Unter der Karte steht je Spieler sein Weg und seine "
                               "Granaten mit Uhrzeit."),
                              ("Spielt sie im nächsten Match auf T mindestens einmal genau so. Der Report zeigt sie "
                               "dann unter 'Eure Taktiken heute'.")],
                    "link": f"/playbook/{m}#{t['id']}"})
    if ctx.get("scenes"):
        out.append({"id": "quiz", "kind": "Situationen", "title": "Situations-Training", "auto": True,
                    "steps": ["Entscheide bei jeder Szene zuerst. Löse sie erst danach auf.",
                              "Hakt sich von selbst ab, sobald alle Szenen entschieden sind."],
                    "link": f"/training/situationen?p={sid}"})
    return out


PLAN_V = 3  # Version der Aufgaben-Texte: ältere Pläne derselben Woche werden neu gebaut, Häkchen bleiben


def ensure(slot: dict, ctx: dict, today: date | None = None) -> tuple[str, dict, bool]:
    """Plan der aktuellen Woche; neu bauen, wenn er fehlt, der Auftrag gewechselt hat oder die Aufgaben veraltet
    sind (Häkchen bleiben, soweit die Aufgabe gleich ist). Rückgabe: (Woche, Plan, geändert)."""
    key = week_key(today or local_today())
    weeks = slot.setdefault("weeks", {})
    plan = weeks.get(key)
    if plan and plan.get("lesson") == ctx["lesson"] and plan.get("v") == PLAN_V:
        # Taktik-Aufgabe nachreichen, wenn es beim Anlegen des Plans noch keine Pro-Empfehlung gab
        new = [t for t in tasks_for(ctx) if t["kind"] == "Playbook"]
        if new and not any(t["id"].startswith("tactic:") for t in plan["tasks"]):
            plan["tasks"].append(new[0])
            return key, plan, True
        return key, plan, False
    done = (plan or {}).get("done", {})
    same = plan and plan.get("lesson") == ctx["lesson"]
    tasks = tasks_for(ctx)
    if same:  # nur neue Texte: Taktik-Aufgaben behalten, die nicht mehr empfohlen sind, aber schon gespielt wurden
        tasks += [t for t in plan["tasks"] if t["id"].startswith("tactic:") and t["id"] not in {x["id"] for x in tasks}
                  and t.get("played")]
    weeks[key] = plan = {"lesson": ctx["lesson"], "created": (plan or {}).get("created") if same else now_local(),
                         "v": PLAN_V, "tasks": tasks,
                         "done": {t["id"]: done[t["id"]] for t in tasks if t["id"] in done}}
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


def tactic_progress(key: str, plan: dict, hist: list[dict], cfg: dict | None = None, sid: str | None = None) -> bool:
    """Taktik-Aufgabe prüfen: In den Matches dieser Woche auf der Map die Runden zählen, die zur empfohlenen Taktik
    gehören (gleiche Erkennung wie im Playbook). Ab einer gespielten Runde wird die Aufgabe automatisch abgehakt.
    Schreibt ``played`` (Runden, Siege) in die Aufgabe. Rückgabe: Plan geändert."""
    from cstaktik.playbook import tactic_id

    start, end = week_range(key)
    changed = False
    for t in plan["tasks"]:
        if not t["id"].startswith("tactic:"):
            continue
        _kind, m, tid = t["id"].split(":", 2)
        rounds = [p for h in hist if h.get("map") == m and h.get("analyzed_at")
                  and (sid is None or sid in h.get("players", {}))
                  and start <= datetime.fromisoformat(h["analyzed_at"]).date() <= end
                  for p in h.get("plays") or [] if tactic_id(p, cfg) == tid]
        played = {"n": len(rounds), "won": sum(p["won"] for p in rounds)}
        before = (t.get("played") or {}).get("n", 0)
        if t.get("played") != played:
            t["played"], changed = played, True
        # nur beim ersten Mal automatisch abhaken: nimmt der Spieler den Haken raus, bleibt er draußen
        if played["n"] and not before and t["id"] not in plan["done"]:
            plan["done"][t["id"]] = now_local()
            changed = True
    return changed
