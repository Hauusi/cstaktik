"""CS-Wissen: Themen, Wissens-Check und Lernstand je Spieler.

Lernprinzipien (Quellen auf /mehr#wissenschaft):
- Abrufüben statt Nochmal-Lesen: Jede Frage wird beantwortet, dann erklärt (Adesope u. a. 2017, Meta-Analyse).
- Verteilt wiederholen: Richtig beantwortete Fragen kommen nach 1, 3, 7 und 21 Tagen wieder, falsche am nächsten Tag
  (Cepeda u. a. 2006), wie die Szenen im Warm-up (drills.SPACING_DAYS).
- Gemischt üben: Der Wissens-Check im Warm-up mischt Bereiche (Brunmair & Richter 2019), zuerst aber die Themen zur
  aktuellen Lektion.
- Ausgearbeitete Beispiele vor dem eigenen Lösen (van Gog & Rummel 2010): Jedes Thema hat ein Beispiel in Schritten.

Gespeichert im Drills-Speicher des Spielers (data/drills/<steamid>.json) unter "quiz" und "read".
"""

from __future__ import annotations

from datetime import datetime, timedelta

from cstaktik import drills
from cstaktik.academy_texts import AREAS, TOPICS, topics_for_lesson

__all__ = ["AREAS", "TOPICS", "topics_for_lesson", "questions", "answer", "due", "overview", "topic_state",
           "mark_read", "related"]


def questions() -> dict[str, tuple[str, dict]]:
    """Alle Fragen: Frage-ID -> (Thema, Frage)."""
    return {q["id"]: (tid, q) for tid, t in TOPICS.items() for q in t.get("quiz") or []}


def _now() -> datetime:
    return datetime.now()


def answer(sid: str, qid: str, pick: int) -> dict:
    """Antwort auf eine Frage werten und den Abstand bis zur nächsten Wiederholung setzen.

    Richtig: eine Stufe weiter (1, 3, 7, 21 Tage). Falsch: zurück auf Stufe 0, morgen wieder fällig."""
    qs = questions()
    if qid not in qs:
        raise KeyError(qid)
    tid, q = qs[qid]
    if not (0 <= pick < len(q["options"])):
        raise ValueError("unbekannte Antwort")
    ok = pick == q["a"]
    now = _now()
    with drills.LOCK:
        d = drills.load(sid)
        st = (d.setdefault("quiz", {})).get(qid) or {"box": 0, "right": 0, "wrong": 0}
        st["box"] = min(st.get("box", 0) + 1, len(drills.SPACING_DAYS)) if ok else 0
        days = drills.SPACING_DAYS[max(st["box"] - 1, 0)] if ok else 1
        st["due"] = (now + timedelta(days=days)).isoformat(timespec="seconds")
        st["right" if ok else "wrong"] = st.get("right" if ok else "wrong", 0) + 1
        st["last"] = ok
        st["at"] = now.isoformat(timespec="seconds")
        d["quiz"][qid] = st
        drills._save(sid, d)
    return {"ok": ok, "a": q["a"], "why": q["why"], "topic": tid, "box": st["box"], "days": days}


def mark_read(sid: str, tid: str) -> None:
    """Thema geöffnet: für den Lernstand (gelesen, aber noch nicht geprüft)."""
    if tid not in TOPICS:
        return
    with drills.LOCK:
        d = drills.load(sid)
        read = d.setdefault("read", {})
        if tid in read:
            return
        read[tid] = _now().isoformat(timespec="seconds")
        drills._save(sid, d)


def topic_state(tid: str, d: dict) -> str:
    """Stand eines Themas aus dem Speicher eines Spielers: neu, gelesen, ueben (eine Antwort zuletzt falsch),
    sitzt (alle Fragen zuletzt richtig)."""
    qs = [q["id"] for q in TOPICS[tid].get("quiz") or []]
    quiz = d.get("quiz") or {}
    seen = [quiz[q] for q in qs if q in quiz]
    if seen and any(not s.get("last") for s in seen):
        return "ueben"
    if qs and len(seen) == len(qs):
        return "sitzt"
    if seen or tid in (d.get("read") or {}):
        return "gelesen"
    return "neu"


STATE_LABEL = {"neu": "Neu", "gelesen": "Gelesen", "ueben": "Noch üben", "sitzt": "Sitzt"}


def overview(sid: str | None) -> dict:
    """Bereiche mit ihren Themen und dem Stand des Spielers, dazu Summen."""
    d = drills.load(sid) if sid else {}
    areas, counts = [], {k: 0 for k in STATE_LABEL}
    for a in AREAS:
        rows = []
        for tid, t in TOPICS.items():
            if t["area"] != a["key"]:
                continue
            s = topic_state(tid, d)
            counts[s] += 1
            rows.append({"id": tid, "title": t["title"], "key": t["key"], "state": s, "label": STATE_LABEL[s]})
        areas.append({**a, "topics": rows, "done": sum(1 for r in rows if r["state"] == "sitzt")})
    return {"areas": areas, "counts": counts, "total": len(TOPICS), "due": len(due(sid, 99)) if sid else 0}


def due(sid: str, n: int = 2, prefer: list[str] | None = None) -> list[dict]:
    """Fällige Fragen für den Wissens-Check: zuerst falsch beantwortete und fällige, dann neue Fragen.

    Neue Fragen kommen nur aus Themen, die der Spieler schon geöffnet hat oder die zu ``prefer`` gehören (die
    aktuelle Lektion), damit niemand Fragen zu Themen bekommt, die er nie gesehen hat. Innerhalb einer Gruppe
    wechseln die Bereiche ab (gemischtes Üben)."""
    d = drills.load(sid)
    quiz, read = d.get("quiz") or {}, d.get("read") or {}
    now = _now().isoformat(timespec="seconds")
    prefer = list(prefer or [])
    due_old, new = [], []
    for qid, (tid, q) in questions().items():
        st = quiz.get(qid)
        if st:
            if (st.get("due") or "") <= now:
                due_old.append((0 if not st.get("last") else 1, st.get("due") or "", tid, q))
        elif tid in read or tid in prefer:
            new.append((0 if tid in prefer else 1, prefer.index(tid) if tid in prefer else 99, tid, q))
    due_old.sort(key=lambda x: (x[0], x[1]))
    new.sort(key=lambda x: (x[0], x[1]))
    out, areas_used = [], []
    for group in (due_old, new):
        rest = list(group)
        while rest and len(out) < n:
            # gemischt: zuerst ein Bereich, der noch nicht dran war
            i = next((k for k, x in enumerate(rest) if TOPICS[x[2]]["area"] not in areas_used), 0)
            _, _, tid, q = rest.pop(i)
            areas_used.append(TOPICS[tid]["area"])
            out.append({"id": q["id"], "q": q["q"], "options": q["options"], "topic": tid,
                        "topic_title": TOPICS[tid]["title"]})
    return out


def related(lesson: str | None) -> list[dict]:
    """Themen im CS-Wissen zu einer Kurs-Lektion (für Session, Lektion und Warm-up)."""
    if not lesson:
        return []
    return [{"id": tid, "title": TOPICS[tid]["title"], "key": TOPICS[tid]["key"]} for tid in topics_for_lesson(lesson)]
