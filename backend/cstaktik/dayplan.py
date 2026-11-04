"""Tagesplan der Startseite: was heute dran ist, in der Reihenfolge, in der ein Coach es machen würde.

1. Session zum letzten Match (falls noch offen)
2. Übung der aktuellen Lektion (gezieltes Üben, Hausaufgabe mit Kontrolle)
3. Ein Thema im CS-Wissen (zur Lektion passend, sonst eins mit fälligen Fragen, sonst das nächste neue)
4. Warm-up vor dem Match

"Erledigt" kommt nur aus gespeicherten Daten: Session markiert, Übung heute eingetragen, Thema heute geöffnet oder
eine Frage dazu heute beantwortet, Warm-up heute erledigt.
"""

from __future__ import annotations

from datetime import datetime

from cstaktik import academy, course_texts, drills


def _today_local() -> str:
    from cstaktik.coaching import now_local

    return now_local()[:10]


def _topic_today(sid: str, lesson: str | None, d: dict) -> str | None:
    """Thema des Tages: zur Lektion und noch nicht sitzend, sonst mit fälligen Fragen, sonst das nächste neue."""
    for r in academy.related(lesson):
        if academy.topic_state(r["id"], d) != "sitzt":
            return r["id"]
    due = academy.due(sid, 1)
    if due:
        return due[0]["topic"]
    return next((tid for tid in academy.TOPICS if academy.topic_state(tid, d) == "neu"), None)


def build(sid: str, coach: dict | None, slot: dict | None, q: str = "", now: datetime | None = None) -> dict | None:
    """Schritte für heute. ``coach`` = api._home_coach (letztes Match), ``slot`` = Coaching-Stand des Spielers."""
    if not sid:
        return None
    now = now or datetime.now()
    day = now.date().isoformat()
    d = drills.load(sid)
    lesson = ((slot or {}).get("focus") or {}).get("lesson") or (d.get("plan") or {}).get("lesson")
    steps = []
    if coach and coach.get("file"):
        steps.append({"id": "session", "title": f"Session zum letzten Match ({coach.get('map_label')})",
                      "time": "4 Min", "href": f"/m/{coach['file']}{q}", "done": bool(coach.get("done")),
                      "why": "Erst verstehen, was passiert ist, dann einen Plan fassen."})
    if lesson in course_texts.LESSONS:
        dr = course_texts.LESSONS[lesson]["drill"]
        local = _today_local()
        done = any((x.get("date") or "")[:10] == local and x.get("lesson") == lesson for x in (slot or {}).get("drills") or [])
        steps.append({"id": "drill", "title": f"Übung: {dr['name']}", "time": f"{dr['minutes']} Min",
                      "href": f"/kurs/{lesson}{q}#ueben", "done": done,
                      "why": f"Gezielt an deiner Lektion „{course_texts.LESSONS[lesson]['title']}“, mit klarem Ziel."})
    tid = _topic_today(sid, lesson, d)
    if tid:
        qids = {x["id"] for x in academy.TOPICS[tid]["quiz"]}
        done = (d.get("read") or {}).get(tid, "")[:10] == day or any(
            (st.get("at") or "")[:10] == day for k, st in (d.get("quiz") or {}).items() if k in qids)
        steps.append({"id": "wissen", "title": f"CS-Wissen: {academy.TOPICS[tid]['title']}", "time": "5 Min",
                      "href": f"/wissen/{tid}{q}", "done": done, "why": academy.TOPICS[tid]["key"]})
    warm_today = any(w[:10] == day for w in d.get("warmups") or [])
    steps.append({"id": "warmup", "title": "Warm-up vor dem Match", "time": "2 Min", "href": f"/warmup{q}",
                  "done": warm_today, "why": "Plan, Kopfkino, Szenen und Wissensfragen, direkt bevor du spielst."})
    nxt = next((s for s in steps if not s["done"]), None)
    return {"steps": steps, "done": sum(1 for s in steps if s["done"]), "total": len(steps),
            "next": nxt["id"] if nxt else None}
