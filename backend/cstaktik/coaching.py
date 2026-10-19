"""Coaching-Kreislauf über mehrere Matches: Auftrag (Fokus-Lektion) -> Match -> Auftrag-Check -> nächster Auftrag.

- Ein Auftrag ist eine Coach-Lektion (coach_voice.LESSONS) mit Erfolgskriterium: höchstens ``target`` Mal
  pro 10 Runden. Ausgangswert = Rate im Match, aus dem der Auftrag entstand.
- Gemeistert, wenn das Kriterium ``done_after`` Matches in Folge erfüllt ist. Dann wird der größte Fehler des
  aktuellen Matches (ohne gerade gemeisterte) der neue Auftrag.
- Gezählt wird für die Fokus-Spieler zusammen (Duo).

Dazu "So geht's richtig": Szenen aus dem Match, in denen ihr das Prinzip einer Lektion umgesetzt habt
(Kill mit Mitspieler in Trade-Reichweite, Kill nach eigener Flash/Molotov, ...). Nur aus Demo-Daten.

Gespeichert in data/coaching.json.
"""

from __future__ import annotations

from cstaktik.fsutil import write_atomic

import json
from datetime import datetime
from pathlib import Path

from cstaktik.callouts import meters, place
from cstaktik.model import MatchData
from cstaktik.rules.base import PositionIndex, dist


# ---------------------------------------------------------------- Auftrag (Fokus) über Matches

COUNT_VERSION = 4  # 2: jede Lektion eines Todes zählt; 3: 'Utility' nur bei ungenutzter Flash/Molotov;
#                   4: neue Lektion 'Zuerst gesehen' (aus Duell-Sichtung)


def now_local() -> str:
    """Jetzt in deutscher Zeit (Wochengrenzen und Datumsangaben wie bei euch, nicht wie auf dem Server)."""
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Europe/Berlin")).replace(tzinfo=None).isoformat(timespec="seconds")


def _de(x: float) -> str:
    return str(round(x, 1)).replace(".", ",")


def compare_rates(n0: int, r0: int, n1: int, r1: int, min_rounds: int = 40) -> dict:
    """Vorher (n0 in r0 Runden) gegen jetzt (n1 in r1 Runden): ehrlicher Trend statt Zufall.

    Eine Richtung gibt es nur, wenn beide Seiten genug Runden haben und der Unterschied größer ist als das übliche
    Schwanken bei so wenigen Fällen (Poisson: mindestens 2 Standardabweichungen vom Erwarteten).
    ``state``: besser | schlechter | gleich | wenig; ``text`` nennt immer die Zahlen."""
    nums = f"{n0}x in {r0} Runden → {n1}x in {r1} Runden"
    if r0 < min_rounds or r1 < min_rounds or n0 + n1 < 3:
        return {"state": "wenig", "text": f"{nums}. Zu wenig für einen Trend."}
    expected = n0 / r0 * r1
    sd = max(expected, 1.0) ** 0.5
    rate0, rate1 = 10 * n0 / r0, 10 * n1 / r1
    if n1 <= expected - 2 * sd:
        return {"state": "besser", "text": f"Besser: {_de(rate0)} → {_de(rate1)} pro 10 Runden. Gezählt: {nums}."}
    if n1 >= expected + 2 * sd:
        return {"state": "schlechter", "text": f"Schlechter: {_de(rate0)} → {_de(rate1)} pro 10 Runden. Gezählt: {nums}."}
    return {"state": "gleich", "text": f"Kein klarer Unterschied. Gezählt: {nums}."}


import threading

# Laden -> ändern -> speichern von coaching.json nur unter diesem Lock: Seiten (Übung abhaken, Wochenplan) und die
# Auswertung im Hintergrund schreiben dieselbe Datei; ohne Lock überschreibt der eine die Änderung des anderen.
LOCK = threading.RLock()


def load(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            pass
    return {"players": {}}


def save(state: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, json.dumps(state, ensure_ascii=False, indent=1))


def _rounds(summary: dict, sid: str | None) -> int:
    """Gespielte Runden: die des Spielers (wer später einsteigt, hat weniger), sonst die des Matches."""
    if sid is not None:
        r = (summary.get("players", {}).get(sid) or {}).get("rounds")
        if r:
            return int(r)
    return int(summary.get("rounds") or 0)


def _rate(summary: dict, lid: str, sid: str | None = None) -> tuple[float, int, int] | None:
    """(Rate pro 10 Runden ungerundet, Anzahl, Runden) für einen Spieler (sid) oder alle Fokus-Spieler."""
    if "lessons" not in summary:
        return None
    if sid is not None:
        if sid not in summary.get("players", {}) and sid not in summary["lessons"]:
            return None  # Spieler war in diesem Match nicht dabei
        n = summary["lessons"].get(sid, {}).get(lid, 0)
    else:
        n = sum(d.get(lid, 0) for d in summary["lessons"].values())
    rounds = _rounds(summary, sid)
    if not rounds:
        return None
    return 10 * n / rounds, n, rounds


def _pooled(matches: list[dict], lid: str, sid: str | None) -> tuple[float, int, int] | None:
    """Rate über mehrere Matches zusammen (Summe Vorkommen / Summe Runden): ruhiger als ein einzelnes Match."""
    n = rounds = 0
    for h in matches:
        r = _rate(h, lid, sid)
        if r:
            n += r[1]
            rounds += r[2]
    return (10 * n / rounds, n, rounds) if rounds else None


def update(state: dict, summary: dict, top_lessons: list[str], target_factor: float = 0.6,
           done_after: int = 2, sid: str | None = None, past: list[dict] | None = None,
           min_check_rounds: int = 12, min_master_rounds: int = 40, min_count: int = 3,
           pool_matches: int = 5) -> dict:
    """Prüft den laufenden Auftrag gegen dieses Match und setzt bei Bedarf einen neuen.

    Statistisch ehrlich, damit "gemeistert" nicht Glück ist:
    - Ausgangswert = Rate über die letzten ``pool_matches`` Matches des Spielers (nicht nur das schlechte Match,
      das den Auftrag ausgelöst hat); ein Auftrag braucht dort mindestens ``min_count`` Vorkommen.
    - Gezählt wird pro gespielter Runde des Spielers; Matches unter ``min_check_rounds`` Runden zählen nicht
      (weder für noch gegen die Serie).
    - Gemeistert: ``done_after`` Matches in Folge unter dem Ziel und zusammen mindestens ``min_master_rounds`` Runden.
    - Ein gemeisterter Auftrag kommt zurück, wenn die Rate wieder auf den alten Ausgangswert steigt (Rückfall).
    ``past``: frühere Verlaufs-Einträge (ohne dieses Match), älteste zuerst.
    Rückgabe (für den Report): {"check": {...} | None, "focus": {...} | None, "new": bool, "mastered": str | None}.
    Dieselbe Demo zweimal auszuwerten zählt nicht doppelt."""
    mid = summary.get("id")
    from cstaktik.coach_voice import LESSONS

    past = [h for h in (past or []) if h.get("id") != mid]
    mine = [h for h in past + [summary] if sid is None or sid in h.get("players", {})]
    out = {"check": None, "focus": None, "new": False, "mastered": None}
    f = state.get("focus")
    if f and f.get("lesson") not in LESSONS:  # Lektion gibt es nicht mehr (alte Datei): Auftrag neu wählen
        state["focus"] = f = None
    if f and f.get("created_from") != mid and (summary.get("analyzed_at") or "") >= (f.get("created_at") or ""):
        r = _rate(summary, f["lesson"], sid)
        if r is not None:
            rate, n, rounds = r
            enough = rounds >= min_check_rounds
            # Übungen seit dem letzten geprüften Match (bzw. seit dem Auftrag) bis zu diesem Match
            prev_dates = [m.get("date") or "" for m in f.get("matches", []) if m["match"] != mid
                          and (m.get("date") or "") < (summary.get("analyzed_at") or "")]
            since = max(prev_dates, default=f.get("created_at") or "")
            drills = sum(1 for d in state.get("drills", []) if d["lesson"] == f["lesson"]
                         and since <= d["date"] <= (summary.get("analyzed_at") or "9999"))
            entry = {"match": mid, "date": summary.get("analyzed_at"), "map": summary.get("map"),
                     "rate": round(rate, 1), "count": n, "rounds": rounds, "drills": drills,
                     "met": (rate <= f["target"]) if enough else None, "report": summary.get("report_file")}
            f["matches"] = sorted([m for m in f.get("matches", []) if m["match"] != mid] + [entry],
                                  key=lambda m: m.get("date") or "")
            streak = streak_rounds = 0
            for m in reversed(f["matches"]):
                if m["met"] is None:
                    continue  # zu kurz gespielt: zählt weder für noch gegen die Serie
                if not m["met"]:
                    break
                streak += 1
                streak_rounds += m.get("rounds") or 0
            out["check"] = {**entry, "lesson": f["lesson"], "title": LESSONS[f["lesson"]][0], "target": f["target"],
                            "baseline": f["baseline"], "streak": streak, "need": done_after,
                            "streak_rounds": streak_rounds, "need_rounds": min_master_rounds}
            if streak >= done_after and streak_rounds >= min_master_rounds:
                f["status"] = "gemeistert"
                f["done_at"] = summary.get("analyzed_at")
                state.setdefault("done", []).append(f)
                out["mastered"] = f["lesson"]
                state["focus"] = f = None
    if not state.get("focus"):
        recent = state.get("done", [])[-3:]
        for lid in top_lessons:
            if lid == "duel" or lid not in LESSONS:
                continue
            base = _pooled(mine[-pool_matches:], lid, sid)
            if not base or base[1] < min_count:
                continue  # zu selten für einen belastbaren Auftrag
            relapse = None
            done_same = [d for d in recent if d["lesson"] == lid]
            if done_same:
                # gerade gemeistert: nur zurück, wenn die letzten Matches wieder so schlecht sind wie früher
                last3 = _pooled(mine[-3:], lid, sid)
                if not last3 or last3[0] < done_same[-1]["baseline"]:
                    continue
                relapse = done_same[-1].get("done_at")
            state["focus"] = {"lesson": lid, "baseline": round(base[0], 1),
                              "target": round(max(0.3, base[0] * target_factor), 1),
                              "baseline_n": base[1], "baseline_rounds": base[2],
                              "created_at": summary.get("analyzed_at") or now_local(),
                              "created_from": mid, "matches": [], "status": "aktiv",
                              **({"rueckfall": relapse} if relapse else {})}
            out["new"] = True
            break
    if state.get("focus"):
        fo = state["focus"]
        out["focus"] = {"lesson": fo["lesson"], "title": LESSONS[fo["lesson"]][0], "target": fo["target"],
                        "baseline": fo["baseline"], "matches": fo.get("matches", []), "need": done_after,
                        "baseline_n": fo.get("baseline_n"), "baseline_rounds": fo.get("baseline_rounds"),
                        "rueckfall": fo.get("rueckfall")}
    return out


def update_all(state: dict, summary: dict, tops: dict[str, list[str]], target_factor: float = 0.6,
               done_after: int = 2, past: list[dict] | None = None, **kw) -> dict[str, dict]:
    """Eigener Auftrag je Fokus-Spieler. ``tops``: steamid -> Lektionen dieses Spielers, wichtigste zuerst.
    Alter gemeinsamer Auftrag (Version davor) wird beim ersten Mal für jeden Spieler übernommen."""
    players = state.setdefault("players", {})
    legacy = state.get("focus")
    out = {}
    for sid in sorted(set(tops) | set(summary.get("players", {}))):
        if sid not in players:
            players[sid] = {"focus": json.loads(json.dumps(legacy)) if legacy else None,
                            "done": list(state.get("done", [])), "drills": []}
        res = update(players[sid], summary, tops.get(sid, []), target_factor, done_after, sid=sid, past=past, **kw)
        res["name"] = (summary.get("players", {}).get(sid) or {}).get("name", sid)
        out[sid] = res
    if legacy is not None:
        state.pop("focus", None)
        state.pop("done", None)
    return out


def drill_done(slot: dict, lesson: str, when: str | None = None) -> None:
    slot.setdefault("drills", []).append({"lesson": lesson, "date": when or now_local()})


def drill_undo(slot: dict, lesson: str) -> None:
    """Letzte erledigte Übung dieser Lektion zurücknehmen (Haken im Wochenplan entfernt)."""
    d = slot.get("drills", [])
    for i in range(len(d) - 1, -1, -1):
        if d[i]["lesson"] == lesson:
            del d[i]
            return


def drills_since(slot: dict, since: str | None) -> int:
    f = slot.get("focus")
    return sum(1 for d in slot.get("drills", []) if f and d["lesson"] == f["lesson"] and (not since or d["date"] >= since))


# ---------------------------------------------------------------- "So geht's richtig" aus dem Match

BRIGHT_LESSONS = {"alone", "outnumbered", "utility", "no_shot_close", "moving", "moving_shot", "no_shot_far",
                  "crosshair", "seen_first"}  # nur für diese sucht der Coach Gegenbeispiele


def bright_spots(match: MatchData, lid: str, trade_units: float = 1000, max_n: int = 3,
                 sid: str | None = None) -> list[dict] | None:
    """Szenen, in denen ein Fokus-Spieler das Prinzip der Lektion umgesetzt hat. Je Szene: Runde, Tick, Text.
    ``sid``: nur dieser Spieler (sein Auftrag). None = für diese Lektion gibt es keine Suche (nicht "nichts gefunden")."""
    if lid not in BRIGHT_LESSONS:
        return None
    focus = {sid} if sid else match.focus_ids()
    tr = match.tickrate
    idx = PositionIndex(match.positions)
    out: list[dict] = []

    def clock(r, tick):
        rnd = match.round_by_num(r)
        if rnd is None or rnd.freeze_end_tick is None:
            return ""
        from cstaktik.callouts import clock as gclock

        # Uhr im Spiel (1:55 abwärts, nach dem Plant Bombentimer)
        plant = next((x.tick for x in sorted(match.bomb, key=lambda x: x.tick) if x.round == r and x.event == "plant"), None)
        return gclock((tick - rnd.freeze_end_tick) / tr,
                      None if plant is None else (plant - rnd.freeze_end_tick) / tr)

    my_kills = [k for k in match.kills if k.attacker_steamid in focus and k.victim_side != k.attacker_side]
    for k in sorted(my_kills, key=lambda k: (k.round, k.tick)):
        rnd = match.round_by_num(k.round)
        if rnd is None:
            continue
        name = match.name_of(k.attacker_steamid)
        text = None
        if lid in ("alone", "outnumbered"):
            me = idx.nearest(k.round, k.attacker_steamid, k.tick, tr)
            side = rnd.sides.get(k.attacker_steamid)
            dead = {x.victim_steamid for x in match.kills if x.round == k.round and x.tick < k.tick}
            mates = [s for s, sd in rnd.sides.items() if sd == side and s != k.attacker_steamid and s not in dead]
            best = None
            for m in mates:
                p = idx.nearest(k.round, m, k.tick, tr)
                if me is not None and p is not None:
                    d = dist(me.pos, p.pos)
                    if best is None or d < best[0]:
                        best = (d, m)
            if best and best[0] <= trade_units:
                text = (f"{name} nimmt das Duell mit {match.name_of(best[1])} {meters(best[0])} daneben "
                        f"und gewinnt es.")
        elif lid == "utility":
            nade = next((g for g in match.grenades if g.round == k.round and g.thrower_steamid == k.attacker_steamid
                         and g.kind in ("flash", "molotov") and g.points
                         and 0 <= k.tick - g.points[0][0] <= 4 * tr), None)
            if nade:
                kind = {"flash": "Flash", "molotov": "Molotov"}[nade.kind]
                secs = f"{(k.tick - nade.points[0][0]) / tr:.1f}".replace(".", ",")
                text = f"{name} wirft eine {kind} und holt {secs} s später den Kill."
        elif lid in ("no_shot_close", "crosshair", "moving"):
            # aus den Duell-Daten: vorgezielt (kleine Abweichung) bzw. gestoppt beim ersten Schuss
            d = next((d for d in match.duels if d.tick == k.tick and d.winner == k.attacker_steamid), None)
            if d is not None and lid in ("no_shot_close", "crosshair") and d.w_err is not None and d.w_err < 10:
                text = (f"{name} hat {place(k.victim_place) or 'den Spot'} vorgezielt: Fadenkreuz {str(d.w_err).replace('.', ',')}° "
                        f"neben dem Gegner" + (", zuerst geschossen" if d.w_react_ms == 0 else "") + ". Kill.")
            elif d is not None and lid == "moving" and d.w_speed is not None and d.w_speed < 40:
                text = f"{name} steht beim ersten Schuss still und gewinnt das Duell."
        elif lid == "seen_first":
            from cstaktik.duels import side_of

            d = next((d for d in match.duels if d.tick == k.tick and d.winner == k.attacker_steamid), None)
            v = side_of(d, k.attacker_steamid, tr) if d is not None else None
            if v and v["seen"] == "ich" and (v["seen_ms"] is None or v["seen_ms"] >= 300):
                lead = f" ({str(round(v['seen_ms'] / 1000, 1)).replace('.', ',')} s früher)" if v["seen_ms"] else ""
                text = (f"{name} sieht {match.name_of(k.victim_steamid)} zuerst{lead}"
                        + (f" in {place(k.victim_place)}" if k.victim_place else "") + " und gewinnt das Duell.")
        elif lid == "moving_shot":
            last = max((s for s in match.shots if s.steamid == k.attacker_steamid and s.round == k.round
                        and s.tick <= k.tick), key=lambda s: s.tick, default=None)
            if last is not None and last.speed is not None and last.speed < 40:
                text = f"{name} steht beim Schuss still und trifft."
        elif lid == "no_shot_far":
            def near_line(u) -> bool:  # Smoke liegt zwischen Schütze und Opfer (Abstand zur Schusslinie)
                a, v = k.attacker_pos, k.victim_pos
                if a is None or v is None:
                    return False
                dx, dy = v.x - a.x, v.y - a.y
                L = dx * dx + dy * dy or 1
                t = max(0.0, min(1.0, ((u.pos.x - a.x) * dx + (u.pos.y - a.y) * dy) / L))
                return ((a.x + t * dx - u.pos.x) ** 2 + (a.y + t * dy - u.pos.y) ** 2) ** .5 <= 150

            sm = next((u for u in match.utility if u.round == k.round and u.kind == "smoke" and u.end_known
                       and u.end_tick is not None and u.thrower_steamid in focus
                       and u.start_tick <= k.tick <= u.end_tick and near_line(u)), None)
            if sm:
                text = f"Unter eurer Smoke holt {name} den Kill" + (f" in {k.victim_place}." if k.victim_place else ".")
        if text:
            out.append({"round": k.round, "tick": k.tick, "from": max(rnd.freeze_end_tick or 0, k.tick - 4 * tr),
                        "when": clock(k.round, k.tick), "text": text})
        if len(out) >= max_n:
            break
    return out
