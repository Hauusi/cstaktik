"""Coaching-Session und Warm-up: Wenn-dann-Plan, eigene Entscheidungen in Szenen, erledigte Sessions je Spieler.

Lernprinzipien dahinter (Quellen auf der Seite /mehr#wissenschaft):
- Entscheiden statt Zuschauen: Die Szene stoppt im Entscheidungsmoment, der Spieler wählt, dann läuft sie weiter
  (Temporal-Occlusion-Training, Müller et al. 2024).
- Wenn-dann-Plan statt Zahlenziel (Durchführungsvorsätze, Gollwitzer & Sheeran 2006).
- Wiederholen mit Abstand: Szenen kommen in späteren Warm-ups wieder, falsch oder offen entschiedene zuerst
  (Abrufüben, Roediger & Karpicke 2006; verteiltes Üben, Cepeda et al. 2006).

Gespeichert in data/drills/<steamid>.json.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path

from cstaktik import pipeline
from cstaktik.fsutil import write_atomic

LOCK = threading.Lock()
ACTIONS = {"gehalten": "Position halten", "zurückgezogen": "Zurückziehen", "Richtung Gegner": "Peeken / Richtung Gegner"}
# Abstände bis zur nächsten Wiederholung einer Szene nach einer Entscheidung (Leitner-artig, in Tagen)
SPACING_DAYS = [1, 3, 7, 21]


def _file(sid: str) -> Path:
    return pipeline.DRILLS_DIR / f"{re.sub(r'[^0-9A-Za-z]', '_', sid)}.json"


def load(sid: str) -> dict:
    try:
        d = json.loads(_file(sid).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(sid: str, d: dict) -> None:
    write_atomic(_file(sid), json.dumps(d, ensure_ascii=False, indent=1))


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def scene_key(sc: dict) -> str:
    """Stabiler Schlüssel einer Szene über Matches hinweg."""
    return f"{sc.get('report') or ''}#{sc.get('round')}-{sc.get('tick')}"


# --- Plan ------------------------------------------------------------------------------------------------------

def set_plan(sid: str, lesson: str, text: str, report: str, match_at: str | None, obstacle: str | None = None) -> dict:
    """Plan fürs nächste Match. Gleicher Match-Bezug: ersetzt den Plan, statt einen zweiten anzulegen."""
    from cstaktik.course_texts import obstacle_line

    with LOCK:
        d = load(sid)
        plan = {"lesson": lesson, "text": text, "report": report, "match_at": match_at, "at": _now()}
        if obstacle and obstacle_line(obstacle, lesson):
            plan["obstacle"], plan["if_obstacle"] = obstacle, obstacle_line(obstacle, lesson)
        d["plans"] = [x for x in d.get("plans") or [] if x.get("report") != report]
        d["plan"] = plan
        d["plans"].append(plan)
        d["plans"] = d["plans"][-30:]
        _save(sid, d)
        return plan


def plan_before(sid: str, at: str | None) -> dict | None:
    """Plan, der für ein Match galt: der letzte, der nach einem früheren Match gefasst wurde."""
    plans = [p for p in load(sid).get("plans") or [] if (p.get("match_at") or "") < (at or "")]
    return plans[-1] if plans else None


def current_plan(sid: str) -> dict | None:
    return load(sid).get("plan")


RATINGS = {"ja": "Ja", "teils": "Teilweise", "nein": "Nein"}


def rate_plan(sid: str, report: str, rating: str) -> None:
    """Selbsteinschätzung nach dem Match: Hast du dich an den Plan gehalten? (zu dem Plan, der für ``report`` galt)."""
    if rating not in RATINGS:
        raise ValueError("unbekannte Einschätzung")
    with LOCK:
        d = load(sid)
        target = next((x for x in d.get("plans") or [] if x.get("checked_in") == report), None)
        if target is None:
            return
        target["self"] = rating
        _save(sid, d)


def attach_check(sid: str, plan_at: str, report: str) -> None:
    """Merkt sich, in welchem Match ein Plan geprüft wurde (für Selbsteinschätzung und Verlauf)."""
    with LOCK:
        d = load(sid)
        for x in d.get("plans") or []:
            if x.get("at") == plan_at and not x.get("checked_in"):
                x["checked_in"] = report
                _save(sid, d)
                return


def plan_log(sid: str, hist: list[dict], cfg: dict, n: int = 6) -> list[dict]:
    """Verlauf der Pläne: je Plan das Match danach mit gemessenen Fehlern der Lektion, Ziel und Selbsteinschätzung."""
    from cstaktik.course import threshold
    from cstaktik.course_texts import LESSONS

    mine = sorted((h for h in hist if sid in (h.get("players") or {})), key=lambda h: h.get("analyzed_at") or "")
    out = []
    for p in (load(sid).get("plans") or [])[-n:]:
        nxt = next((h for h in mine if (h.get("analyzed_at") or "") > (p.get("match_at") or "")), None)
        row = {"lesson": p.get("lesson"), "title": (LESSONS.get(p.get("lesson")) or {}).get("title"),
               "text": p.get("text"), "self": RATINGS.get(p.get("self") or ""), "map": None, "count": None,
               "rounds": None, "met": None}
        if nxt is not None:
            rounds = ((nxt.get("players") or {}).get(sid) or {}).get("rounds") or nxt.get("rounds")
            counted = sid in (nxt.get("lessons") or {})
            cnt = ((nxt.get("lessons") or {}).get(sid) or {}).get(p.get("lesson"), 0) if counted else None
            row.update(map=(nxt.get("map") or "?").removeprefix("de_").capitalize(), count=cnt, rounds=rounds)
            if cnt is not None and rounds:
                # Ziel wie in der Session: das des laufenden Auftrags, sonst die Kurs-Grenze der Lektion
                fo = (((nxt.get("focus_check") or {}).get(sid) or {}).get("focus") or {})
                lim = float(fo["target"]) if fo.get("lesson") == p.get("lesson") and fo.get("target") is not None \
                    else threshold(p.get("lesson"), cfg)
                row["allowed"] = int(lim * rounds / 10)
                row["met"] = cnt <= row["allowed"]
        out.append(row)
    return out[::-1]


# --- Entscheidungen --------------------------------------------------------------------------------------------

def record(sid: str, key: str, choice: str, actual: str | None, best: str | None, reason: str | None = None,
           cue: str | None = None) -> dict:
    """Entscheidung speichern. ``ok``: wie die Pros entschieden (nur mit Pro-Favorit), sonst None. Als "anders als
    in der Demo" zählt eine Wahl, die nicht der eigenen Aktion vor dem Tod entspricht."""
    if choice not in ACTIONS:
        raise ValueError("unbekannte Aktion")
    with LOCK:
        d = load(sid)
        ans = d.setdefault("answers", {}).setdefault(key, [])
        row = {"at": _now(), "choice": choice, "ok": (choice == best) if best else None,
               "same": choice == actual if actual else None}
        if reason:
            row["reason"], row["cue_ok"] = reason, (reason == cue) if cue else None
        ans.append(row)
        d["answers"][key] = ans[-6:]
        _save(sid, d)
        return row


def due(sid: str, scenes: list[dict], n: int = 3, now: datetime | None = None, focus: str | None = None) -> list[dict]:
    """Szenen fürs Warm-up: noch nie entschiedene und fällige zuerst, Lektion gemischt (verschachteltes Üben).
    Fällig: nach der k-ten Antwort SPACING_DAYS[k-1] Tage später; falsch (anders als Pros) setzt zurück auf 1 Tag."""
    now = now or datetime.now()
    answers = load(sid).get("answers") or {}

    def due_at(key: str) -> datetime | None:
        rows = answers.get(key) or []
        if not rows:
            return None  # nie entschieden: sofort
        streak = 0
        for r in rows:
            streak = 0 if r.get("ok") is False else streak + 1
        days = SPACING_DAYS[min(max(streak, 1), len(SPACING_DAYS)) - 1]
        try:
            return datetime.fromisoformat(rows[-1]["at"]) + timedelta(days=days)
        except (KeyError, ValueError):
            return None

    cands = []
    for sc in scenes:
        if not sc.get("clip") or not (sc["clip"].get("dec") is not None):
            continue
        d = due_at(scene_key(sc))
        if d is None or d <= now:
            cands.append((0 if d is None else 1, 0 if sc.get("lesson") == focus else 1, d or now, sc))
    cands.sort(key=lambda x: (x[0], x[1], x[2]))
    out, seen = [], set()
    for *_, sc in cands:  # höchstens zwei Szenen derselben Lektion, damit gemischt wird
        if sum(1 for x in out if x.get("lesson") == sc.get("lesson")) >= 2 and len(cands) > n:
            continue
        if scene_key(sc) in seen:
            continue
        seen.add(scene_key(sc))
        out.append(sc)
        if len(out) >= n:
            break
    return out


# --- Sessions --------------------------------------------------------------------------------------------------

def mark_session(sid: str, report: str) -> None:
    with LOCK:
        d = load(sid)
        d.setdefault("sessions", {})[report] = _now()
        _save(sid, d)


def session_done(sid: str, report: str) -> bool:
    return report in (load(sid).get("sessions") or {})


def mark_warmup(sid: str) -> None:
    with LOCK:
        d = load(sid)
        w = d.setdefault("warmups", [])
        w.append(_now())
        d["warmups"] = w[-60:]
        _save(sid, d)


def warmup_streak(sid: str, today: datetime | None = None) -> int:
    """Tage in Folge mit Warm-up (heute oder gestern als letzter Tag)."""
    days = sorted({w[:10] for w in load(sid).get("warmups") or []}, reverse=True)
    if not days:
        return 0
    t = (today or datetime.now()).date()
    cur = datetime.fromisoformat(days[0]).date()
    if (t - cur).days > 1:
        return 0
    n = 1
    for d in days[1:]:
        nd = datetime.fromisoformat(d).date()
        if (cur - nd).days == 1:
            n += 1
            cur = nd
        else:
            break
    return n
