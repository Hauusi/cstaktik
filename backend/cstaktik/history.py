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
from cstaktik.coaching import now_local
from cstaktik.reference import timeline
from cstaktik.situation import round_states

FLOOR_UNITS = 64  # Rastergröße des Kartenumrisses in Spieleinheiten


def summarize(match: MatchData, result: AnalysisResult, report_file: str | None = None,
              past: list[dict] | None = None) -> dict:
    focus = match.focus_ids()
    won = lost = 0
    for r in match.rounds:
        side = match.focus_side(r.num)
        if side and r.winner:
            won += r.winner == side
            lost += r.winner != side

    issues: dict[str, Counter] = {sid: Counter() for sid in focus}
    for f in result.findings:
        if f.severity == "gut" or f.steamid not in issues or f.rule_id == "death_other":
            continue  # Tode ohne Duell (Bombe, Granate, Welt) sind keine Baustelle
        # Muster-Findings zählen ihre Runden, Einzel-Findings einmal
        issues[f.steamid][f.title] += len(f.rounds) if f.round is None and f.rounds else 1

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
        "analyzed_at": now_local(),  # deutsche Zeit (Wochenplan, Verlauf)
        "map": match.map_name,
        "rounds": len(match.rounds),
        "states": round_states(match),
        "lessons": lessons(result),
        "duel_stats": duel_stats(match),
        "util_stats": util_stats(match),
        "lesson_rank": (rank := lesson_rank(result, past)),
        "main_lesson": rank[0] if rank else None,  # wie "Der eine Punkt" im Report (mit Gedächtnis)
        "lesson_rank_by": lesson_rank_by(result, past),
        "scenes": scenes(result, report_file, match.map_name),
        "plays": _plays(match),  # eure T-Runden für das Playbook (Laufwege, Granaten, Plant)
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
        "deaths": death_rows(match),
        "floor": [[i, j, c] for (i, j), c in floor.items()],
        "timeline": timeline(match),  # Ortsname je 5 s Rundenzeit (Vorbild aus Siegrunden)
    }


def death_rows(match: MatchData, trade_window_s: float = 3.0) -> list[dict]:
    """Tode der Fokus-Spieler: Ort, Runde, Seite, erster Tod der Runde, getradet (Killer stirbt binnen
    ``trade_window_s`` durch das Team des Opfers)."""
    focus = match.focus_ids()
    tr = match.tickrate
    kills = sorted(match.kills, key=lambda k: k.tick)
    first: dict[int, int] = {}
    for k in kills:
        first.setdefault(k.round, k.tick)
    from cstaktik.duels import side_of

    fatal = {(d.tick, d.loser): d for d in match.duels}
    out = []
    for k in kills:
        if k.victim_steamid not in focus or k.victim_pos is None:
            continue
        duel = fatal.get((k.tick, k.victim_steamid))
        seen = side_of(duel, k.victim_steamid, tr)["seen"] if duel else None
        traded = bool(k.attacker_steamid) and k.attacker_side != k.victim_side and any(
            x.round == k.round and x.victim_steamid == k.attacker_steamid and x.attacker_side == k.victim_side
            and k.tick < x.tick <= k.tick + trade_window_s * tr for x in kills)
        out.append({"sid": k.victim_steamid, "x": round(k.victim_pos.x), "y": round(k.victim_pos.y),
                    "place": k.victim_place, "round": k.round, "side": k.victim_side,
                    "first": k.tick == first.get(k.round), "traded": traded,
                    **({"seen": seen} if seen else {}),  # wer im tödlichen Duell zuerst sah (duels.seen_first)
                    # von wo der Killer schoss (Map-Buch: Winkel zum Vorzielen)
                    **({"ax": round(k.attacker_pos.x), "ay": round(k.attacker_pos.y), "aplace": k.attacker_place}
                       if k.attacker_pos is not None and k.attacker_side != k.victim_side else {})})
    return out


def lessons(result: AnalysisResult) -> dict[str, dict[str, int]]:
    """Je Fokus-Spieler: Anzahl je Coach-Lektion (coach_voice) in diesem Match. Jeder Fehler eines Todes
    zählt (nicht nur der Titel), damit Raten nicht springen, wenn sich die Reihenfolge der Probleme ändert."""
    from cstaktik.coach_voice import lesson_ids

    out: dict[str, dict[str, int]] = {}
    for f in result.findings:
        v = f.evidence.get("coach")
        if v and f.steamid:
            d = out.setdefault(f.steamid, {})
            for lid in lesson_ids(f.evidence.get("f") or {}, v["id"]):
                d[lid] = d.get(lid, 0) + 1
    return out


def _plays(match: MatchData) -> list[dict]:
    from cstaktik.playbook import plays

    return plays(match, team=match.focus_ids())


def main_lesson(result: AnalysisResult) -> str | None:
    from cstaktik.coach_voice import focus

    top = focus(result.findings, 1)
    return top[0]["id"] if top else None


def duel_stats(match: MatchData) -> dict:
    from cstaktik import duels

    out = {}
    for sid in match.focus_ids():
        views = [duels.side_of(d, sid, match.tickrate) for d in match.duels if sid in (d.winner, d.loser)]
        if views:
            out[sid] = duels.stats(views)
    return out


def util_stats(match: MatchData) -> dict:
    from cstaktik import utility_cmp

    out = {}
    for sid in match.focus_ids():
        n, pr = utility_cmp.pre_contact(match, {sid})
        out[sid] = {"flash": utility_cmp.flash_stats(utility_cmp.flash_effect(match, {sid})) if match.blinds else None,
                    "pre": round(n / pr, 2) if pr else None}
    return out


def lesson_rank(result: AnalysisResult, past: list[dict] | None = None) -> list[str]:
    """Lektionen dieses Matches, wichtigste zuerst (wiederkehrend, verlorene Rundenchance, Häufigkeit)."""
    from cstaktik.coach_voice import focus, recurrence

    return [x["id"] for x in focus(result.findings, 10, recurrence(past or []))]


def lesson_rank_by(result: AnalysisResult, past: list[dict] | None = None) -> dict[str, list[str]]:
    """Je Fokus-Spieler: seine Lektionen, wichtigste zuerst (seine früheren Matches zählen mit)."""
    from cstaktik.coach_voice import focus, recurrence

    sids = {f.steamid for f in result.findings if f.evidence.get("coach") and f.steamid}
    return {sid: [x["id"] for x in focus([f for f in result.findings if f.steamid == sid], 10,
                                         recurrence(past or [], sid))] for sid in sids}


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
                    "happened": v["happened"], "next": v["next"], "pos": (ev.get("f") or {}).get("vpos"),
                    "frame": ev.get("frame")})
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
