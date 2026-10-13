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

import json
from datetime import datetime
from pathlib import Path

from cstaktik.model import MatchData
from cstaktik.rules.base import PositionIndex, dist


# ---------------------------------------------------------------- Auftrag (Fokus) über Matches

def load(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            pass
    return {"players": {}}


def save(state: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1))


def _rate(summary: dict, lid: str, sid: str | None = None) -> tuple[float, int] | None:
    """Rate pro 10 Runden: für einen Spieler (sid) oder alle Fokus-Spieler zusammen."""
    rounds = summary.get("rounds") or 0
    if not rounds or "lessons" not in summary:
        return None
    if sid is not None:
        if sid not in summary.get("players", {}) and sid not in summary["lessons"]:
            return None  # Spieler war in diesem Match nicht dabei
        n = summary["lessons"].get(sid, {}).get(lid, 0)
    else:
        n = sum(d.get(lid, 0) for d in summary["lessons"].values())
    return round(10 * n / rounds, 1), n


def update(state: dict, summary: dict, top_lessons: list[str], target_factor: float = 0.6,
           done_after: int = 2, sid: str | None = None) -> dict:
    """Prüft den laufenden Auftrag gegen dieses Match und setzt bei Bedarf einen neuen.

    ``top_lessons``: Lektionen dieses Matches, wichtigste zuerst (coach_voice.focus).
    Rückgabe (für den Report): {"check": {...} | None, "focus": {...} | None, "new": bool, "mastered": str | None}.
    Dieselbe Demo zweimal auszuwerten zählt nicht doppelt."""
    mid = summary.get("id")
    from cstaktik.coach_voice import LESSONS

    out = {"check": None, "focus": None, "new": False, "mastered": None}
    f = state.get("focus")
    if f and f.get("created_from") != mid:
        r = _rate(summary, f["lesson"], sid)
        if r is not None:
            rate, n = r
            entry = {"match": mid, "date": summary.get("analyzed_at"), "map": summary.get("map"), "rate": rate,
                     "count": n, "rounds": summary.get("rounds"), "met": rate <= f["target"],
                     "report": summary.get("report_file")}
            f["matches"] = [m for m in f.get("matches", []) if m["match"] != mid] + [entry]
            streak = 0
            for m in reversed(f["matches"]):
                if not m["met"]:
                    break
                streak += 1
            out["check"] = {**entry, "lesson": f["lesson"], "title": LESSONS[f["lesson"]][0], "target": f["target"],
                            "baseline": f["baseline"], "streak": streak, "need": done_after}
            if streak >= done_after:
                f["status"] = "gemeistert"
                f["done_at"] = summary.get("analyzed_at")
                state.setdefault("done", []).append(f)
                out["mastered"] = f["lesson"]
                state["focus"] = f = None
    if not state.get("focus"):
        recent_done = {d["lesson"] for d in state.get("done", [])[-3:]}
        for lid in top_lessons:
            if lid in recent_done or lid == "duel":
                continue
            r = _rate(summary, lid, sid)
            if not r or not r[1]:
                continue
            state["focus"] = {"lesson": lid, "baseline": r[0], "target": round(max(0.3, r[0] * target_factor), 1),
                              "created_at": summary.get("analyzed_at") or datetime.now().isoformat(timespec="minutes"),
                              "created_from": mid, "matches": [], "status": "aktiv"}
            out["new"] = True
            break
    if state.get("focus"):
        fo = state["focus"]
        out["focus"] = {"lesson": fo["lesson"], "title": LESSONS[fo["lesson"]][0], "target": fo["target"],
                        "baseline": fo["baseline"], "matches": fo.get("matches", []), "need": done_after}
    return out


def update_all(state: dict, summary: dict, tops: dict[str, list[str]], target_factor: float = 0.6,
               done_after: int = 2) -> dict[str, dict]:
    """Eigener Auftrag je Fokus-Spieler. ``tops``: steamid -> Lektionen dieses Spielers, wichtigste zuerst.
    Alter gemeinsamer Auftrag (Version davor) wird beim ersten Mal für jeden Spieler übernommen."""
    players = state.setdefault("players", {})
    legacy = state.get("focus")
    out = {}
    for sid in sorted(set(tops) | set(summary.get("players", {}))):
        if sid not in players:
            players[sid] = {"focus": json.loads(json.dumps(legacy)) if legacy else None,
                            "done": list(state.get("done", [])), "drills": []}
        res = update(players[sid], summary, tops.get(sid, []), target_factor, done_after, sid=sid)
        res["name"] = (summary.get("players", {}).get(sid) or {}).get("name", sid)
        out[sid] = res
    if legacy is not None:
        state.pop("focus", None)
        state.pop("done", None)
    return out


def drill_done(slot: dict, lesson: str, when: str | None = None) -> None:
    slot.setdefault("drills", []).append({"lesson": lesson, "date": when or datetime.now().isoformat(timespec="minutes")})


def drills_since(slot: dict, since: str | None) -> int:
    f = slot.get("focus")
    return sum(1 for d in slot.get("drills", []) if f and d["lesson"] == f["lesson"] and (not since or d["date"] >= since))


# ---------------------------------------------------------------- "So geht's richtig" aus dem Match

def bright_spots(match: MatchData, lid: str, trade_units: float = 800, max_n: int = 3) -> list[dict]:
    """Szenen, in denen ein Fokus-Spieler das Prinzip der Lektion umgesetzt hat. Je Szene: Runde, Tick, Text."""
    focus = match.focus_ids()
    tr = match.tickrate
    idx = PositionIndex(match.positions)
    out: list[dict] = []

    def clock(r, tick):
        rnd = match.round_by_num(r)
        if rnd is None or rnd.freeze_end_tick is None:
            return ""
        s = max(0, int((tick - rnd.freeze_end_tick) / tr))
        return f"{s // 60}:{s % 60:02d}"

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
                text = (f"{name} nimmt das Duell mit {match.name_of(best[1])} {round(best[0])} Units daneben "
                        f"und gewinnt es.")
        elif lid == "utility":
            nade = next((g for g in match.grenades if g.round == k.round and g.thrower_steamid == k.attacker_steamid
                         and g.kind in ("flash", "molotov") and g.points
                         and 0 <= k.tick - g.points[0][0] <= 4 * tr), None)
            if nade:
                kind = {"flash": "Flash", "molotov": "Molotov"}[nade.kind]
                secs = f"{(k.tick - nade.points[0][0]) / tr:.1f}".replace(".", ",")
                text = f"{name} wirft eine {kind} und holt {secs} s später den Kill."
        elif lid in ("no_shot_close", "moving"):
            if k.attacker_pos and k.victim_pos and dist(k.attacker_pos, k.victim_pos) < 600:
                text = (f"{name} gewinnt das Nahduell in {k.victim_place or 'diesem Spot'} "
                        f"({round(dist(k.attacker_pos, k.victim_pos))} Units).")
        elif lid == "moving_shot":
            last = max((s for s in match.shots if s.steamid == k.attacker_steamid and s.round == k.round
                        and s.tick <= k.tick), key=lambda s: s.tick, default=None)
            if last is not None and last.speed is not None and last.speed < 40:
                text = f"{name} steht beim Schuss ({round(last.speed)} Units/s) und trifft."
        elif lid == "no_shot_far":
            sm = next((u for u in match.utility if u.round == k.round and u.kind == "smoke"
                       and u.thrower_steamid in focus and u.start_tick <= k.tick <= (u.end_tick or k.tick)), None)
            if sm:
                text = f"Unter eurer Smoke holt {name} den Kill" + (f" in {k.victim_place}." if k.victim_place else ".")
        if text:
            out.append({"round": k.round, "tick": k.tick, "from": max(rnd.freeze_end_tick or 0, k.tick - 4 * tr),
                        "when": clock(k.round, k.tick), "text": text})
        if len(out) >= max_n:
            break
    return out
