"""Match-Verlauf: pro ausgewerteter Demo eine kleine Zusammenfassung (JSON) für die Fortschritts-Seite.

Gespeichert wird nur, was aus Demo und Analyse stammt. Das Datum ist der Auswertungszeitpunkt,
weil die Demo selbst kein Spieldatum enthält.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from cstaktik.model import AnalysisResult, MatchData
from cstaktik.reference import timeline
from cstaktik.situation import round_states

FLOOR_UNITS = 64  # Rastergröße des Kartenumrisses in Spieleinheiten


def summarize(match: MatchData, result: AnalysisResult, report_file: str | None = None) -> dict:
    focus = match.focus_ids()
    won = lost = 0
    for r in match.rounds:
        side = match.focus_side(r.num)
        if side and r.winner:
            won += r.winner == side
            lost += r.winner != side

    issues: dict[str, Counter] = {sid: Counter() for sid in focus}
    for f in result.findings:
        if f.severity == "gut" or f.steamid not in issues:
            continue
        # Muster-Findings zählen ihre Runden, Einzel-Findings einmal
        issues[f.steamid][f.title] += len(f.rounds) if f.round is None and f.rounds else 1

    _first_tick = {}
    for k in sorted(match.kills, key=lambda k: k.tick):
        _first_tick.setdefault(k.round, k.tick)
    from cstaktik.coach import diagnose
    from cstaktik.config import load_rules_config

    debrief = diagnose(match, result, load_rules_config()["coach"], load_rules_config()["mechanics"])
    floor = Counter()
    for p in match.positions:
        floor[(int(p.pos.x // FLOOR_UNITS), int(p.pos.y // FLOOR_UNITS))] += 1

    return {
        "id": match.source_sha256 or match.source_file,
        "source_file": match.source_file,
        "report_file": report_file,
        "analyzed_at": datetime.now().isoformat(timespec="minutes"),
        "map": match.map_name,
        "rounds": len(match.rounds),
        "states": round_states(match),
        "lessons": lessons(result),
        "main_lesson": main_lesson(result),
        "lesson_rank": lesson_rank(result),
        "lesson_rank_by": lesson_rank_by(result),
        "scenes": scenes(result, report_file, match.map_name),
        "won": won,
        "lost": lost,
        "players": {
            s.steamid: {
                "name": s.name, "rounds": s.rounds, "kills": s.kills, "deaths": s.deaths, "adr": s.adr,
                "opening_kills": s.opening_kills, "opening_deaths": s.opening_deaths,
                "traded_deaths": s.traded_deaths, "utility": s.utility_thrown,
            }
            for s in result.stats
        },
        "issues": {sid: dict(c) for sid, c in issues.items()},
        # Ursachen des Urteils: in wie vielen verlorenen Runden (Basis für Ziele/Ziel-Check)
        "causes": {c["id"]: len(c["lost_rounds"]) for c in debrief["all_causes"]},
        "cause_rounds": debrief["rounds_with"],
        "cause_order": [c["id"] for c in debrief["causes"]],
        "verdict": debrief["sentence"],
        "mech": {m["steamid"]: {k: m[k] for k in ("moving_pct", "hit_pct", "hs_pct", "deaths_no_shot_pct",
                                                   "spray_early_pct", "spray_late_pct", "shots")}
                 for m in debrief["mechanics"]},
        "deaths": [
            {"sid": k.victim_steamid, "x": round(k.victim_pos.x), "y": round(k.victim_pos.y), "place": k.victim_place,
             "round": k.round, "side": k.victim_side, "first": k.tick == _first_tick.get(k.round)}
            for k in match.kills
            if k.victim_steamid in focus and k.victim_pos is not None
        ],
        "floor": [[i, j, c] for (i, j), c in floor.items()],
        "timeline": timeline(match),  # Ortsname je 5 s Rundenzeit (Vorbild aus Siegrunden)
    }


def lessons(result: AnalysisResult) -> dict[str, dict[str, int]]:
    """Je Fokus-Spieler: Anzahl je Coach-Lektion (coach_voice) in diesem Match."""
    out: dict[str, dict[str, int]] = {}
    for f in result.findings:
        v = f.evidence.get("coach")
        if v and f.steamid:
            d = out.setdefault(f.steamid, {})
            d[v["id"]] = d.get(v["id"], 0) + 1
    return out


def main_lesson(result: AnalysisResult) -> str | None:
    from cstaktik.coach_voice import focus

    top = focus(result.findings, 1)
    return top[0]["id"] if top else None


def lesson_rank(result: AnalysisResult) -> list[str]:
    """Lektionen dieses Matches, wichtigste zuerst (verlorene Rundenchance, dann Häufigkeit)."""
    from cstaktik.coach_voice import focus

    return [x["id"] for x in focus(result.findings, 10)]


def lesson_rank_by(result: AnalysisResult) -> dict[str, list[str]]:
    """Je Fokus-Spieler: seine Lektionen, wichtigste zuerst."""
    from cstaktik.coach_voice import focus

    sids = {f.steamid for f in result.findings if f.evidence.get("coach") and f.steamid}
    return {sid: [x["id"] for x in focus([f for f in result.findings if f.steamid == sid], 10)] for sid in sids}


def scenes(result: AnalysisResult, report_file: str | None, map_name: str | None) -> list[dict]:
    """Tod-Szenen mit Lagebild fürs Training über mehrere Matches (Entscheidung nachspielen)."""
    out = []
    for f in result.findings:
        v, ev = f.evidence.get("coach"), f.evidence
        if not v or not ev.get("snap") or not ev.get("aktion"):
            continue
        out.append({"lesson": v["id"], "who": f.player_name, "sid": f.steamid, "round": f.round, "tick": f.tick,
                    "from": (f.overlay.get("decision") or [None, None, None])[2], "report": report_file,
                    "map": map_name, "snap": ev["snap"], "info": ev.get("info"), "aktion": ev["aktion"],
                    "pro_rates": ev.get("pro_rates"), "pro_best": ev.get("pro_best"), "cost": ev.get("cost_pct"),
                    "happened": v["happened"], "next": v["next"], "pos": (ev.get("f") or {}).get("vpos")})
    return out


def previous(histories: list[dict], current: dict) -> dict | None:
    """Das zuletzt ausgewertete andere Match vor ``current`` (nach Auswertungszeit)."""
    before = [h for h in histories if h.get("id") != current.get("id")
              and h.get("analyzed_at", "") <= (current.get("analyzed_at") or "9999")]
    return before[-1] if before else None


def save(summary: dict, history_dir: Path) -> Path:
    history_dir.mkdir(parents=True, exist_ok=True)
    key = "".join(ch for ch in str(summary["id"]) if ch.isalnum())[:40] or "match"
    out = history_dir / f"{key}.json"
    if out.exists():  # gleiche Demo erneut ausgewertet: ursprüngliches Datum behalten
        try:
            summary["analyzed_at"] = json.loads(out.read_text())["analyzed_at"]
        except (OSError, ValueError, KeyError):
            pass
    out.write_text(json.dumps(summary, ensure_ascii=False))
    return out


def load_all(history_dir: Path) -> list[dict]:
    items = []
    for f in history_dir.glob("*.json"):
        try:
            items.append(json.loads(f.read_text()))
        except (OSError, ValueError):
            continue
    return sorted(items, key=lambda h: h.get("analyzed_at", ""))
