"""Der Coach spricht: eine Geschichte pro Match, ohne KI, aus den Demo-Daten.

Aufbau wie bei einem Trainer nach dem Spiel:
1. Eröffnung: Ergebnis, Rating gegen deinen Schnitt.
2. Rückblick: Was hatten wir abgemacht, hat es gegriffen? (Gedächtnis)
3. Das eine Muster: was dich in diesem Match gekostet hat, mit Belegen aus deinen Runden (wie oft, wie viele davon
   verloren, welche Seite, wo, typische Lage).
4. Der Weg dahin: seit wann wir daran arbeiten, Start gegen heute, wie viele Matches noch bis "geschafft".
5. Szene: Ich halte an, du entscheidest.
6. Plan, Übung und was ich im nächsten Match prüfe.

Regeln: Jede Zahl stammt aus dem Verlauf-Eintrag oder dem Coaching-Stand. Fehlt etwas, fällt der Satz weg, statt
etwas zu behaupten. Rückmeldung zur Handlung, nicht zur Person. Der Coach spricht in der Ich-Form.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from cstaktik import course_texts

UNIT_M = 0.0254  # 1 Unit = 2,54 cm


def _de(x: float, d: int = 1) -> str:
    return f"{x:.{d}f}".replace(".", ",")


def pick(options: list[str], seed: str) -> str:
    """Eine von mehreren Formulierungen, fest je Match (gleiches Match = gleicher Satz, verschiedene Matches = Abwechslung)."""
    import hashlib

    return options[int(hashlib.sha1(seed.encode()).hexdigest(), 16) % len(options)]


def _cap(t: str) -> str:
    return t[:1].upper() + t[1:]


def times(n: int) -> str:
    return "keinmal" if n == 0 else "einmal" if n == 1 else f"{n} Mal"


def _date(iso: str | None) -> str | None:
    try:
        d = datetime.fromisoformat(iso or "")
    except ValueError:
        return None
    return f"{d.day}.{d.month}."


def _map(h: dict) -> str:
    return (h.get("map") or "?").removeprefix("de_").capitalize()


def _rounds(h: dict, sid: str) -> int | None:
    return ((h.get("players") or {}).get(sid) or {}).get("rounds") or h.get("rounds")


def _rating(row: dict | None) -> float | None:
    from cstaktik import scoreboard

    d = scoreboard.derive(row) if row and row.get("rounds") else None
    return None if not d else (d["rating2"] if d.get("rating2") is not None else d["rating1"])


def _join(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " und " + xs[-1]


def opening(h: dict, sid: str, before: list[dict]) -> list[str]:
    from cstaktik import history

    sc = history.score(h, sid)
    out = []
    first = f"{_map(h)}"
    if sc:
        word = "gewonnen" if sc[0] > sc[1] else "verloren" if sc[1] > sc[0] else "unentschieden"
        first += f", {sc[0]}:{sc[1]} {word}."
    else:
        first += "."
    n = _rounds(h, sid)
    seed = str(h.get("id") or h.get("report_file") or "")
    out.append(first + (" " + pick([f"Ich habe mir alle {n} Runden angesehen.", f"Ich bin alle {n} Runden durchgegangen.",
                                     f"Ich habe mir jede der {n} Runden angeschaut."], seed) if n else ""))
    me = _rating((h.get("board") or {}).get(sid))
    prev = [r for r in (_rating((x.get("board") or {}).get(sid)) for x in before[-10:]) if r is not None]
    if me is not None and len(prev) >= 3:
        avg = sum(prev) / len(prev)
        if me - avg >= 0.1:
            out.append(f"Dein Rating war {_de(me, 2)}, klar über deinem Schnitt von {_de(avg, 2)}. Starkes Match von dir.")
        elif avg - me >= 0.1:
            out.append(f"Dein Rating war {_de(me, 2)}, unter deinem Schnitt von {_de(avg, 2)}. Das schauen wir uns an.")
        else:
            out.append(f"Dein Rating war {_de(me, 2)}, ungefähr dein Schnitt ({_de(avg, 2)}).")
    elif me is not None:
        out.append(f"Dein Rating war {_de(me, 2)}.")
    return out


def callback(h: dict, sid: str, plan: dict | None, target: float | None) -> dict | None:
    """Rückblick auf den Plan, der für dieses Match galt: gemessen in diesem Match."""
    if not plan or plan.get("lesson") not in course_texts.LESSONS:
        return None
    lid = plan["lesson"]
    n = ((h.get("lessons") or {}).get(sid) or {}).get(lid) if sid in (h.get("lessons") or {}) else None
    r = _rounds(h, sid)
    lines = [f"Letztes Mal haben wir abgemacht: „{plan['text'].rstrip('.')}.“"]
    met = None
    if n is not None and r:
        allowed = int(target * r / 10) if target is not None else None
        line = f"Heute kam der Fehler dazu {times(n)} in {r} Runden vor"
        if allowed is not None:
            met = n <= allowed
            line += f", erlaubt waren {allowed}."
            line += " Das hat gegriffen. Gut gemacht." if met else " Das hat noch nicht gereicht. Wir bleiben dran."
        else:
            line += "."
        lines.append(line)
    return {"lines": lines, "met": met}


def evidence(h: dict, sid: str, lid: str) -> dict:
    """Belege für ein Muster in diesem Match: Runden, verlorene davon, Seite, Ort, Lage."""
    scenes = [s for s in h.get("scenes") or [] if s.get("sid") == sid and s.get("round") is not None
              and (s.get("lesson") == lid or lid in (s.get("lessons") or []))]
    rounds = sorted({s["round"] for s in scenes})
    br = {row[0]: row for row in (h.get("by_round") or {}).get(sid) or []}
    lost = [r for r in rounds if r in br and br[r][2] is False]
    sides = Counter(str(br[r][1]).upper() for r in rounds if r in br)
    places = Counter((s.get("snap") or {}).get("place") for s in scenes if (s.get("snap") or {}).get("place"))
    mate_d = [s["snap"]["mate_d"] for s in scenes if (s.get("snap") or {}).get("mate_d") is not None]
    nades = sum(1 for s in scenes if s.get("nades"))
    under = sum(1 for s in scenes if (s.get("snap") or {}).get("own") is not None
                and s["snap"]["own"] < (s["snap"].get("enemy") or 0))
    count = ((h.get("lessons") or {}).get(sid) or {}).get(lid)
    return {"rounds": rounds, "lost": lost, "sides": sides, "places": places, "mate_d": mate_d, "nades": nades,
            "under": under, "count": count, "scenes": scenes}


def pattern(h: dict, sid: str, lid: str, before: list[dict]) -> dict | None:
    """Das eine Muster des Matches mit Belegen in ganzen Sätzen."""
    from cstaktik.callouts import place

    if lid not in course_texts.LESSONS:
        return None
    t = course_texts.LESSONS[lid]
    ev = evidence(h, sid, lid)
    lines = []
    n = len(ev["rounds"])
    if n:
        rl = [str(r) for r in ev["rounds"][:6]] + (["…"] if n > 6 else [])
        lines.append(f"Das ist dir in {n} {'Runde' if n == 1 else 'Runden'} passiert ({'Runde' if n == 1 else 'Runden'} {_join(rl)}).")
        if ev["lost"]:
            lines.append("Die Runde habt ihr verloren." if n == 1 else
                         "Alle habt ihr verloren." if len(ev["lost"]) == n else f"{len(ev['lost'])} davon habt ihr verloren.")
        if n >= 3 and ev["sides"]:
            side, k = ev["sides"].most_common(1)[0]
            if k * 3 >= n * 2:
                lines.append(f"Meistens als {side} ({k} von {n}).")
        if ev["places"]:
            pl, k = ev["places"].most_common(1)[0]
            if k >= 2 and place(pl):
                lines.append(f"{_cap(times(k))} in {place(pl)}.")
        if lid in ("alone", "outnumbered") and len(ev["mate_d"]) >= 2:
            m = sum(ev["mate_d"]) / len(ev["mate_d"]) * UNIT_M
            lines.append(f"Dein nächster Mitspieler war dabei im Schnitt {round(m)} m weg. Zum Traden zu weit.")
        if lid == "utility" and ev["nades"]:
            k = ev["nades"]
            lines.append("Du hattest dabei noch Granaten in der Tasche." if n == 1 else
                         f"In {'einer' if k == 1 else k} davon hattest du noch Granaten in der Tasche.")
        if lid == "outnumbered" and ev["under"]:
            k = ev["under"]
            lines.append("Dabei wart ihr in Unterzahl." if n == 1 else f"{'Eine' if k == 1 else k} davon in Unterzahl.")
    elif ev["count"]:
        lines.append(f"Gezählt habe ich es {times(ev['count'])} in diesem Match.")
    # Vergleich mit den Matches davor (pro 10 Runden)
    r = _rounds(h, sid)
    cnt = ev["count"]
    prev = [(((x.get("lessons") or {}).get(sid) or {}).get(lid, 0), _rounds(x, sid)) for x in before[-5:]
            if sid in (x.get("lessons") or {}) and _rounds(x, sid)]
    if cnt is not None and r and len(prev) >= 2:
        now = 10 * cnt / r
        avg = 10 * sum(a for a, _ in prev) / sum(b for _, b in prev)
        usual = round(avg * r / 10)  # so oft wäre es bei gleich vielen Runden in deinen Matches davor
        if now - avg >= 0.4 and cnt > usual:
            lines.append(f"Das ist mehr als sonst: Bei {r} Runden passiert es dir normalerweise etwa {times(usual)}.")
        elif avg - now >= 0.4 and cnt < usual:
            lines.append(f"Das ist schon weniger als sonst: Bei {r} Runden passiert es dir normalerweise etwa {times(usual)}.")
    if not lines:
        return None
    return {"id": lid, "title": t["title"], "lines": lines, "why": t["why"], "n": n or (cnt or 0),
            "headline": f"Heute geht es um eine Sache: {t['title']}."}


def journey(slot: dict | None, lid: str, need: int, rounds: int = 24) -> list[str]:
    """Gedächtnis: seit wann wir an der Lektion arbeiten, Start gegen zuletzt, was bis "geschafft" fehlt.
    Zahlen in Matches statt pro 10 Runden: Start umgerechnet auf ``rounds`` Runden, zuletzt die echte Anzahl."""
    f = (slot or {}).get("focus") or {}
    out = []
    if f.get("lesson") == lid:
        start = _date(f.get("created_at"))
        ms = [m for m in f.get("matches") or [] if m.get("rate") is not None]
        if start and f.get("baseline") is not None:
            line = (f"Daran arbeiten wir seit dem {start}, am Anfang passierte es dir etwa "
                    f"{times(round(f['baseline'] * rounds / 10))} pro Match")
            if ms and ms[-1].get("count") is not None and ms[-1].get("rounds"):
                line += f", zuletzt {times(ms[-1]['count'])} in {ms[-1]['rounds']} Runden."
            else:
                line += "."
            out.append(line)
        streak = 0
        for m in reversed(ms):
            if m.get("met") is None:
                continue
            if not m["met"]:
                break
            streak += 1
        if streak:
            left = max(need - streak, 0)
            out.append(f"{streak} {'Match' if streak == 1 else 'Matches'} in Folge im Ziel."
                       + (f" Noch {left} {'Match' if left == 1 else 'Matches'}, dann ist die Lektion geschafft." if left else ""))
        if f.get("rueckfall"):
            out.append(f"Wichtig: Am {_date(f['rueckfall'])} hattest du das schon gemeistert. Es ist zurückgekommen, "
                       "deshalb nehmen wir es noch einmal auf.")
    done = [d for d in (slot or {}).get("done") or [] if d.get("lesson") in course_texts.LESSONS]
    if done:
        last = done[-1]
        out.append(f"Geschafft hast du schon {len(done)} {'Lektion' if len(done) == 1 else 'Lektionen'}, "
                   f"zuletzt „{course_texts.LESSONS[last['lesson']]['title']}“.")
    return out


def milestones(h: dict, sid: str, before: list[dict], warm_streak: int = 0) -> list[str]:
    """Momente, die ein Coach ausdrücklich anspricht: Lektion geschafft, Rückfall, neues Thema, bestes Rating seit
    Langem, Warm-up-Serie. Nur aus gespeicherten Daten."""
    from cstaktik.coach_voice import LESSONS

    fc = (h.get("focus_check") or {}).get(sid) or {}
    if "check" not in fc and "focus" not in fc and ("check" in (h.get("focus_check") or {})):
        fc = h["focus_check"]  # altes Format: ein Auftrag für alle
    out = []
    seed = str(h.get("id") or "")
    if fc.get("mastered") in LESSONS:
        out.append(pick([f"Bevor wir anfangen: Du hast „{LESSONS[fc['mastered']][0]}“ geschafft. Das sitzt jetzt. Stark.",
                         f"Erst das Wichtigste: „{LESSONS[fc['mastered']][0]}“ ist geschafft. Daran haben wir lange gearbeitet.",
                         f"Lektion geschafft: „{LESSONS[fc['mastered']][0]}“. Darauf kannst du stolz sein."], seed))
    elif fc.get("settled") in LESSONS:
        out.append(f"„{LESSONS[fc['settled']][0]}“ sitzt laut deinen letzten Matches. Die Lektion ist abgehakt.")
    fo = fc.get("focus") or {}
    if fc.get("new") and fo.get("lesson") in LESSONS:
        if fo.get("rueckfall"):
            out.append(f"Ein Rückfall: „{LESSONS[fo['lesson']][0]}“ war schon geschafft und ist zurückgekommen. Das passiert, "
                       "wir nehmen es noch einmal auf.")
        else:
            out.append(f"Ab heute haben wir ein neues Thema: „{LESSONS[fo['lesson']][0]}“.")
    me = _rating((h.get("board") or {}).get(sid))
    prev = [r for r in (_rating((x.get("board") or {}).get(sid)) for x in before[-10:]) if r is not None]
    if me is not None and len(prev) >= 5 and me > max(prev):
        out.append(f"Dein bestes Rating seit {len(prev)} Matches.")
    if warm_streak in (3, 7, 14, 30):
        out.append(f"{warm_streak} Tage in Folge aufgewärmt. Genau so wird es zur Gewohnheit.")
    return out


def next_check(lid: str, target: float | None, rounds_hint: int | None) -> str | None:
    if target is None:
        return None
    r = rounds_hint or 24
    n = int(target * r / 10)
    return (f"Im nächsten Match zähle ich genau das. Ziel: bei etwa {r} Runden "
            + (f"höchstens {times(n)}." if n else "kein einziges Mal."))


def drill_line(lid: str) -> str | None:
    t = course_texts.LESSONS.get(lid)
    if not t:
        return None
    d = t["drill"]
    return f"Bevor du wieder spielst: {d['name']}, {d['minutes']} Minuten ({d['where']}). {d['done']}"


def match_story(h: dict, sid: str, lid: str | None, hist: list[dict], slot: dict | None, plan: dict | None,
                target: float | None, need: int = 2) -> dict:
    """Alles, was der Coach in der Session zu diesem Match sagt (Sätze je Schritt)."""
    at = h.get("analyzed_at") or ""
    before = sorted((x for x in hist if sid in (x.get("players") or {}) and (x.get("analyzed_at") or "") < at),
                    key=lambda x: x.get("analyzed_at") or "")
    plan_target = None
    if plan and plan.get("lesson"):
        fo = (slot or {}).get("focus") or {}
        from cstaktik import course

        plan_target = float(fo["target"]) if fo.get("lesson") == plan["lesson"] and fo.get("target") is not None \
            else course.threshold(plan["lesson"], course.settings())
    pat = pattern(h, sid, lid, before) if lid else None
    from cstaktik import coach_memory, drills

    seed = str(h.get("id") or "")
    return {"open": milestones(h, sid, before, drills.warmup_streak(sid)) + opening(h, sid, before),
            "decisions": coach_memory.lines(hist, sid),
            "callback": callback(h, sid, plan, plan_target), "pattern": pat,
            "journey": journey(slot, lid, need, _rounds(h, sid) or 24) if lid else [],
            "ask": pick(["Jetzt du. Ich spiele dir eine deiner Szenen ab und halte kurz vorher an. Was machst du?",
                         "Schau dir das an. Ich halte an, kurz bevor es passiert. Was würdest du tun?",
                         "Deine Szene. Ich stoppe im entscheidenden Moment, dann bist du dran."], seed),
            "plan": "Für das nächste Match machen wir genau eine Sache ab. Such dir den Satz aus, der zu deinen Runden passt.",
            "drill": drill_line(lid) if lid else None, "check": next_check(lid, target, _rounds(h, sid)) if lid else None,
            "close": pick(["Das war's für heute. Eine Sache, aber die, die dich gerade am meisten kostet.",
                           "Fertig. Nimm die eine Sache mit, mehr braucht es heute nicht.",
                           "Gut. Ein Thema, ein Plan, eine Übung. Wir sehen uns nach dem nächsten Match."], seed)}


def home_message(h: dict | None, sid: str, lid: str | None, hist: list[dict], slot: dict | None, done: bool,
                 plan: dict | None, name: str | None = None) -> dict | None:
    """Was der Coach auf der Startseite sagt: vor der Session ein Anreißer, danach die Erinnerung ans Match."""
    if h is None:
        return None
    hi = f"Hey {name}." if name else "Hey."
    at = h.get("analyzed_at") or ""
    before = sorted((x for x in hist if sid in (x.get("players") or {}) and (x.get("analyzed_at") or "") < at),
                    key=lambda x: x.get("analyzed_at") or "")
    if not done:
        lines = [hi] + milestones(h, sid, before)[:1] + opening(h, sid, before)[:1]
        pat = pattern(h, sid, lid, before) if lid else None
        if pat and pat["n"]:
            lines.append(f"Eine Sache ist mir aufgefallen: „{pat['title']}“, {times(pat['n'])}. "
                         "Lass uns das in vier Minuten durchgehen.")
        else:
            lines.append("Lass uns das Match in vier Minuten durchgehen.")
        return {"lines": lines, "mode": "session"}
    lines = [hi]
    if plan and plan.get("text"):
        lines.append(f"Vor dem nächsten Match: Denk an unsere Abmachung. „{plan['text'].rstrip('.')}.“")
        if plan.get("if_obstacle"):
            lines.append(f"Und falls es schwierig wird: {plan['if_obstacle']}")
    else:
        lines.append("Vor dem nächsten Match: Fass dir in der Session einen Plan, dann prüfe ich ihn.")
    j = journey(slot, lid, 2) if lid else []
    if j:
        lines.append(j[0])
    return {"lines": lines, "mode": "prep"}


def map_brief(hist: list[dict], sid: str, map_name: str, plan: dict | None = None, duo_plan: dict | None = None,
              cue: str | None = None) -> list[str]:
    """Ansprache vor dem Match auf einer Map: Bilanz, T/CT, dein häufigster Fehler und Todesort hier, Abmachungen."""
    from cstaktik.callouts import place

    label = map_name.removeprefix("de_").capitalize()
    ms = sorted((h for h in hist if h.get("map") == map_name and sid in (h.get("players") or {})),
                key=lambda h: h.get("analyzed_at") or "")[-10:]
    if not ms:
        out = [f"Auf {label} hast du noch kein Match, das ich kenne. Schau dir unten an, wie die Pros die Map spielen."]
    else:
        from cstaktik import history

        res = [history.score(h, sid) for h in ms]
        w = sum(1 for r in res if r and r[0] > r[1])
        out = [f"{label}. Deine letzten {len(ms)} {'Match' if len(ms) == 1 else 'Matches'} hier: {w} gewonnen, "
               f"{sum(1 for r in res if r and r[1] > r[0])} verloren."]
        sides = {}
        for s in ("t", "ct"):
            rr = [row for h in ms for row in ((h.get("by_round") or {}).get(sid) or []) if str(row[1]).lower() == s]
            if len(rr) >= 10:
                sides[s] = round(100 * sum(1 for r in rr if r[2]) / len(rr))
        if len(sides) == 2:
            weak = min(sides, key=sides.get)
            if abs(sides["t"] - sides["ct"]) >= 10:
                out.append(f"Als T gewinnt ihr hier {sides['t']} % der Runden, als CT {sides['ct']} %. "
                           f"Die {weak.upper()}-Seite ist eure Baustelle auf {label}.")
            else:
                out.append(f"Als T gewinnt ihr hier {sides['t']} % der Runden, als CT {sides['ct']} %.")
        les = Counter()
        for h in ms:
            les.update(((h.get("lessons") or {}).get(sid) or {}))
        les.pop("duel", None)
        if les:
            lid, k = les.most_common(1)[0]
            if k >= 3 and lid in course_texts.LESSONS:
                out.append(f"Dein häufigster Fehler hier: „{course_texts.LESSONS[lid]['title']}“, "
                           f"{k} Mal in {len(ms)} {'Match' if len(ms) == 1 else 'Matches'}.")
        deaths = [d for h in ms for d in h.get("deaths") or [] if d.get("sid") == sid and d.get("place")]
        if len(deaths) >= 8:
            pl, k = Counter(d["place"] for d in deaths).most_common(1)[0]
            if k * 5 >= len(deaths) and place(pl):
                out.append(f"Am häufigsten stirbst du in {place(pl)} ({k} von {len(deaths)} Toden). "
                           "Dort zuerst vorzielen oder Granate.")
    if plan and plan.get("text"):
        out.append(f"Deine Abmachung gilt auch hier: „{plan['text'].rstrip('.')}.“")
    if duo_plan and duo_plan.get("text"):
        out.append(f"Und zu zweit: „{duo_plan['text'].rstrip('.')}.“")
    if cue:
        out.append(f"Dein Schlüsselwort: „{cue}“. Viel Erfolg.")
    return out
