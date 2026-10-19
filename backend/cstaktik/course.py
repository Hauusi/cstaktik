"""Der Kurs: Lernpfad (course_texts) plus Einstufung aus den eigenen Matches, je Spieler.

- ``placement``: je Lektion "sitzt" / "baustelle" / "offen" aus den gezählten Fehlern (Verlauf ``lessons[sid]``) der
  letzten Matches. Grenzen in rules.yaml (``course``).
- ``current``: die aktuelle Lektion. Läuft ein Auftrag (coaching.json ``focus``), ist er die Lektion; sonst die erste
  Baustelle in Kursreihenfolge (Grundlagen zuerst). Auftrag und Kurs-Lektion sind dasselbe.
- ``overview``: Stufen mit Lektionen und Status für Startseite und Fortschritt.
- ``lesson_view``: alles für die Lektionsseite (Texte, eigene Szenen, Pro-Szenen, Verlauf).

Zahlen nur aus Demo-Daten; zu wenig Daten heißt "noch offen", nicht "gut".
"""

from __future__ import annotations

from datetime import datetime

from cstaktik import course_texts
from cstaktik.callouts import clock, place

STATUS_TEXT = {"geschafft": "geschafft", "aktuell": "aktuell", "sitzt": "sitzt schon", "baustelle": "kommt noch",
               "offen": "noch offen"}
UTILITY_LESSONS = {"utility", "blind", "no_shot_far"}  # Lektionen mit Granaten: Lineups und Map-Buch beim Üben


def settings(config: dict | None = None) -> dict:
    """Kurs-Grenzen aus rules.yaml (mit Vorgaben, falls ein Eintrag fehlt) plus goals.min_count."""
    from cstaktik.config import load_rules_config

    cfg = config or load_rules_config()
    c = dict(cfg.get("course") or {})
    g = cfg.get("goals") or {}
    return {"window_matches": int(c.get("window_matches", 5)), "min_rounds": int(c.get("min_rounds", 20)),
            "max_per_10": float(c.get("max_per_10", 1.0)), "per_lesson": dict(c.get("per_lesson") or {}),
            "min_count": int(g.get("min_count", 3)), "done_after": int(g.get("done_after", 2))}


def path() -> list[str]:
    return course_texts.path()


def threshold(lid: str, cfg: dict) -> float:
    return float(cfg["per_lesson"].get(lid, cfg["max_per_10"]))


def _de(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def player_matches(hist: list[dict], sid: str) -> list[dict]:
    """Matches des Spielers mit gezählten Lektionen, älteste zuerst."""
    return [h for h in hist if sid in (h.get("players") or {}) and "lessons" in h]


def match_rate(h: dict, lid: str, sid: str) -> tuple[int, int] | None:
    """(Anzahl, gespielte Runden) einer Lektion in einem Match, None ohne Runden."""
    from cstaktik.coaching import _rate

    r = _rate(h, lid, sid)
    return None if r is None else (r[1], r[2])


def placement(hist: list[dict], sid: str, cfg: dict | None = None) -> dict[str, dict]:
    """Je Lektion des Kurses: status (sitzt | baustelle | offen), Rate pro 10 Runden, Anzahl, Runden, Matches,
    Grenze. Über die letzten ``window_matches`` Matches zusammen (Summe Fehler / Summe Runden)."""
    cfg = cfg or settings()
    mine = player_matches(hist, sid)[-cfg["window_matches"]:]
    out = {}
    for lid in path():
        n = rounds = used = 0
        for h in mine:
            r = match_rate(h, lid, sid)
            if r and r[1]:
                n += r[0]
                rounds += r[1]
                used += 1
        thr = threshold(lid, cfg)
        rate = 10 * n / rounds if rounds else None
        if rounds < cfg["min_rounds"]:
            status = "offen"
        elif rate > thr:
            status = "baustelle" if n >= cfg["min_count"] else "offen"
        else:
            status = "sitzt"
        out[lid] = {"status": status, "rate": None if rate is None else round(rate, 1), "n": n, "rounds": rounds,
                    "matches": used, "threshold": thr}
    return out


def baustellen(hist: list[dict], sid: str, cfg: dict | None = None) -> list[str]:
    """Baustellen in Kursreihenfolge (die erste ist die nächste Lektion)."""
    pl = placement(hist, sid, cfg)
    return [lid for lid in path() if pl[lid]["status"] == "baustelle"]


def settled(hist: list[dict], sid: str, cfg: dict | None = None) -> set[str]:
    """Lektionen, die laut den letzten Matches sitzen."""
    return {lid for lid, p in placement(hist, sid, cfg).items() if p["status"] == "sitzt"}


def plan_for(summary: dict, past: list[dict], cfg: dict | None = None) -> tuple[dict, dict]:
    """Für coaching.update_all nach einem Match: je Spieler die Baustellen in Kursreihenfolge und was sitzt."""
    cfg = cfg or settings()
    mid = summary.get("id")
    hist = [h for h in past if h.get("id") != mid] + [summary]
    tops, ok = {}, {}
    for sid in sorted(set((summary.get("lessons") or {})) | set(summary.get("players") or {})):
        pl = placement(hist, sid, cfg)
        tops[sid] = [lid for lid in path() if pl[lid]["status"] == "baustelle"]
        ok[sid] = {lid for lid in path() if pl[lid]["status"] == "sitzt"}
    return tops, ok


def current(slot: dict | None, pl: dict[str, dict]) -> str | None:
    """Aktuelle Lektion: laufender Auftrag, sonst die erste Baustelle in Kursreihenfolge."""
    f = (slot or {}).get("focus")
    if f and f.get("lesson") in course_texts.LESSONS:
        return f["lesson"]
    return next((lid for lid in path() if pl.get(lid, {}).get("status") == "baustelle"), None)


def streak(f: dict | None) -> int:
    """Matches in Folge im Ziel (zu kurze Matches zählen nicht, wie coaching.update)."""
    s = 0
    for m in reversed((f or {}).get("matches") or []):
        if m.get("met") is None:
            continue
        if not m["met"]:
            break
        s += 1
    return s


def texts(lid: str) -> dict:
    """Texte einer Lektion aus course_texts; fehlende Felder aus dem bisherigen Lehrplan (curriculum.TEACH) oder leer.
    So bleibt die Seite lesbar, solange die Kurstexte noch entstehen."""
    from cstaktik.coach_voice import LESSONS
    from cstaktik.curriculum import TEACH

    c = course_texts.LESSONS.get(lid) or {}
    t = TEACH.get(lid) or {}
    drill = c.get("drill") or {}
    if not drill.get("steps") and t.get("routine"):
        r = t["routine"]
        drill = {"name": r.get("title"), "where": "", "minutes": r.get("minutes"), "steps": list(r.get("steps") or []),
                 "done": ""}
    how = [x for x in (c.get("how") or []) if x] or ([t["in_game"]] if t.get("in_game") else [])
    stage = next((s for s in course_texts.STAGES if s["key"] == c.get("stage")), None)
    return {"id": lid, "title": c.get("title") or (LESSONS.get(lid) or ("?",))[0], "goal": c.get("goal") or "",
            "measure_fault": not c.get("measure") and bool(t.get("fault")),  # alter Lehrplan: nur der Fehler
            "what": c.get("what") or "", "why": c.get("why") or t.get("principle") or "",
            "spot": c.get("spot") or "", "how": how, "drill": drill if drill.get("steps") else None,
            "measure": c.get("measure") or t.get("fault") or "", "mantra": t.get("mantra") or "",
            "stage": stage["title"] if stage else "", "stage_key": stage["key"] if stage else ""}


def overview(hist: list[dict], sid: str, slot: dict | None, cfg: dict | None = None) -> dict:
    """Lernpfad eines Spielers: Stufen mit Lektionen (Status), aktuelle Lektion, wie viele geschafft sind."""
    cfg = cfg or settings()
    pl = placement(hist, sid, cfg)
    cur = current(slot, pl)
    mastered = {d.get("lesson") for d in (slot or {}).get("done") or [] if d.get("status", "gemeistert") == "gemeistert"}
    stages = []
    counts = {k: 0 for k in STATUS_TEXT}
    for s in course_texts.STAGES:
        rows = []
        for lid in path():
            if course_texts.LESSONS[lid]["stage"] != s["key"]:
                continue
            p = pl[lid]
            status = "aktuell" if lid == cur else "geschafft" if lid in mastered else p["status"]
            counts[status] += 1
            rows.append({"id": lid, "title": texts(lid)["title"], "status": status, "chip": STATUS_TEXT[status],
                         "rate": p["rate"], "n": p["n"], "rounds": p["rounds"]})
        stages.append({"key": s["key"], "title": s["title"], "intro": s.get("intro") or "", "lessons": rows,
                       "on": any(r["status"] == "aktuell" for r in rows)})
    cur_v = None
    if cur:
        f = (slot or {}).get("focus") if ((slot or {}).get("focus") or {}).get("lesson") == cur else None
        t = texts(cur)
        cur_v = {"id": cur, "title": t["title"], "goal": t["goal"], "stage": t["stage"], "focus": bool(f),
                 "streak": streak(f) if f else 0, "need": cfg["done_after"],
                 "target": f.get("target") if f else None, "checked": len((f or {}).get("matches") or []),
                 "rueckfall": (f or {}).get("rueckfall"), "progress": progress_sentence(f, cfg["done_after"])}
    rounds = sum(1 for _ in player_matches(hist, sid))
    return {"stages": stages, "current": cur_v, "counts": counts, "total": len(path()),
            "done": counts["geschafft"], "settled": counts["sitzt"], "matches": rounds, "placement": pl}


def _matches_word(n: int) -> str:
    return "einem Match" if n == 1 else f"{n} Matches"


def progress_sentence(f: dict | None, need: int) -> str:
    """Ein Satz zum Stand der aktuellen Lektion."""
    if not f:
        return "Das Ziel setzt der Coach nach deinem nächsten Match."
    s = streak(f)
    if not f.get("matches"):
        return (f"Schaffst du das Ziel in {need} Matches in Folge, ist die Lektion geschafft. "
                "Dein nächstes Match ist das erste, das zählt.")
    if s == 0:
        return f"Noch keins von {need} Matches in Folge geschafft. Das nächste Match zählt wieder."
    return f"{s} von {need} Matches in Folge geschafft."


def _when(h: dict) -> str:
    try:
        return datetime.fromisoformat(h["analyzed_at"]).strftime("%d.%m.")
    except (KeyError, ValueError, TypeError):
        return ""


def _map(h_or_name) -> str:
    name = h_or_name.get("map") if isinstance(h_or_name, dict) else h_or_name
    return (name or "?").removeprefix("de_").capitalize()


def scene_sentence(sc: dict, map_name: str | None) -> str:
    """Ein Satz, wo und wann die Szene war: "Runde 7 auf Mirage, bei 1:05 auf der Uhr in Apartments."."""
    snap = sc.get("snap") or {}
    when = clock(snap.get("secs")) if snap.get("secs") is not None and not snap.get("planted") else ""
    where = place(snap.get("place"))
    out = f"Runde {sc['round']} auf {_map(map_name)}"
    if when:
        out += f", bei {when} auf der Uhr"
    if where:
        out += f" in {where}"
    return out + "."


def _first_sentences(text: str | None, n: int = 2) -> str:
    """Die ersten ``n`` Sätze eines Szenen-Textes (der volle Text steht im Report)."""
    if not text:
        return ""
    import re

    parts = re.split(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ])", text.strip())
    return " ".join(parts[:n])


def own_scenes(hist: list[dict], sid: str, lid: str, limit: int = 3) -> list[dict]:
    """Eigene Szenen zur Lektion aus den Matches (neueste Matches zuerst): Hauptfehler vor Nebenfehler, teure zuerst."""
    cands = []
    for age, h in enumerate(reversed(hist)):
        if sid not in (h.get("players") or {}) or not h.get("report_file"):
            continue
        for x in h.get("scenes") or []:
            if x.get("sid") != sid or x.get("round") is None or x.get("tick") is None:
                continue
            main = x.get("lesson") == lid
            if not main and lid not in (x.get("lessons") or []):
                continue
            cands.append((not main, age, -(x.get("cost") or 0), x, h))
    cands.sort(key=lambda c: c[:3])
    out = []
    for _main, _age, _cost, x, h in cands[:limit]:
        rf = h["report_file"]
        text = _first_sentences(x.get("happened"), 3)
        # beginnt der Text schon mit Uhr und Ort ("Bei 1:05 gehst du in Palace los"), nicht doppelt nennen
        where = f"Runde {x['round']} auf {_map(h.get('map'))}." if text.startswith("Bei ") else \
            scene_sentence(x, h.get("map"))
        out.append({"where": where, "text": text,
                    "next": x.get("next"), "round": x["round"], "date": _when(h),
                    "href": f"/reports/{rf}#s{x['round']}-{x.get('from') or x['tick']}"})
    return out


def pro_scenes(hist: list[dict], sid: str, lid: str, limit: int = 2) -> list[dict]:
    """Pro-Szenen zu eigenen Toden dieser Lektion: dieselbe Lage in einer Pro-Demo (reference.pro_clips, im Report
    abspielbar) oder was Pros in dieser Lage am häufigsten tun (situation.compare). Nur was in den Daten steht."""
    from cstaktik.coach_voice import _pro_line

    out = []
    for h in reversed(hist):
        if sid not in (h.get("players") or {}) or not h.get("report_file"):
            continue
        for x in h.get("scenes") or []:
            if x.get("sid") != sid or (x.get("lesson") != lid and lid not in (x.get("lessons") or [])):
                continue
            text = x.get("pro_clip") or _pro_line(x)
            if not text:
                continue
            out.append({"text": text, "clip": bool(x.get("pro_clip")), "where": scene_sentence(x, h.get("map")),
                        "href": f"/reports/{h['report_file']}#s{x['round']}-{x.get('from') or x['tick']}"})
            if len(out) >= limit:
                return out
    return out


def trend(hist: list[dict], sid: str, lid: str, target: float, limit: int = 6) -> list[dict]:
    """Je Match (älteste zuerst): Fehler, Runden, Rate pro 10 Runden und ob das Ziel erreicht war."""
    rows = []
    for h in player_matches(hist, sid)[-limit:]:
        r = match_rate(h, lid, sid)
        if not r or not r[1]:
            continue
        rate = 10 * r[0] / r[1]
        rows.append({"map": _map(h), "date": _when(h), "count": r[0], "rounds": r[1], "rate": round(rate, 1),
                     "met": rate <= target})
    return rows


def _times(n: int) -> str:
    return "einmal" if n == 1 else "keinmal" if n == 0 else f"{n} Mal"


def check_sentences(rows: list[dict], target: float, f: dict | None, need: int) -> list[str]:
    """Ein bis zwei Sätze zum Prüfen: letztes Match gegen das Ziel, dann die Serie bis zur Lektion."""
    if not rows:
        return ["Für diese Lektion gibt es noch kein Match mit gezählten Fehlern. Spiel ein Match, dann prüft der "
                "Coach sie hier."]
    last = rows[-1]
    allowed = int(target * last["rounds"] / 10)
    s1 = f"Im letzten Match auf {last['map']} kam der Fehler {_times(last['count'])} in {last['rounds']} Runden vor"
    if f:
        s1 += f", erlaubt waren höchstens {allowed}."
        s = streak(f)
        left = need - s
        if s and left > 0:
            s2 = (f"Damit hast du {s} von {need} Matches in Folge geschafft. Noch "
                  f"{'ein Match' if left == 1 else f'{left} Matches'}, dann ist die Lektion geschafft.")
        elif s >= need:
            s2 = "Die Serie ist voll. Mit dem nächsten Match mit genug Runden ist die Lektion geschafft."
        else:
            s2 = f"Die Lektion ist geschafft, wenn du das Ziel in {need} Matches in Folge erreichst."
    else:
        s1 += "."
        good = sum(1 for r in rows if r["met"])
        if len(rows) == 1:
            s2 = f"Damit lagst du {'unter' if good else 'über'} der Grenze von {_de(target)} pro 10 Runden. "
        else:
            s2 = f"In {good} von {len(rows)} Matches lagst du unter der Grenze von {_de(target)} pro 10 Runden. "
        s2 += "Ein Ziel mit Serie bekommt die Lektion, sobald der Kurs bei ihr ankommt."
    return [s1, s2]
