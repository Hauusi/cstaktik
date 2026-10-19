"""Match-Verlauf: pro ausgewerteter Demo eine kleine Zusammenfassung (JSON) für die Fortschritts-Seite.

Gespeichert wird nur, was aus Demo und Analyse stammt. Das Datum ist der Auswertungszeitpunkt,
weil die Demo selbst kein Spieldatum enthält.
"""

from __future__ import annotations

from cstaktik.fsutil import write_atomic

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
        "ct_plays": _ct_plays(match),  # eure CT-Aufstellungen
        "clutch": _clutch(match),  # Clutch-Situationen der Fokus-Spieler (clutch.py)
        "impact": _impact(result, focus),  # Siegchance je Spieler (impact.py), Prozentpunkte
        "moments": _moments(match, result),  # größte Impact-Momente je Fokus-Spieler (Highlights)
        # Rundenfolge je Fokus-Spieler aus seiner Sicht (Tilt-Check); je Spieler, falls ihr gegeneinander spielt
        "seq": {sid: [[r.num, r.sides[sid], r.winner == r.sides[sid]] for r in match.rounds
                      if r.winner and sid in r.sides] for sid in focus},
        "won": won,
        "lost": lost,
        # Ergebnis je Fokus-Spieler aus seiner Sicht (Siege, Niederlagen): stimmt auch, wenn ihr gegeneinander spielt
        "score_by": {sid: [sum(1 for r in match.rounds if r.winner and r.sides.get(sid) == r.winner),
                           sum(1 for r in match.rounds if r.winner and sid in r.sides and r.sides[sid] != r.winner)]
                     for sid in focus},
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
        "by_round": by_round(match),  # je Fokus-Spieler und Runde: Seite, gewonnen, Kills, Tod, Schaden (Story, T/CT)
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


def by_round(match: MatchData) -> dict[str, list[list]]:
    """Je Fokus-Spieler und Runde: [Runde, Seite, gewonnen, Kills, gestorben (0/1), Schaden an Gegnern]. Gezählt wie
    stats.player_stats (Kills ohne Teamkills, Schaden nur an Gegnern), damit die Summen zu K/D und ADR passen."""
    from cstaktik.mechanics import is_teamkill

    out: dict[str, list[list]] = {}
    scoreboard = list(match.kills) + list(match.post_round_kills)  # wie stats: auch Kills nach Rundenende
    for sid in sorted(match.focus_ids()):
        rows = []
        for r in match.rounds:
            side = r.sides.get(sid)
            if side is None:
                continue
            k = sum(1 for x in scoreboard if x.round == r.num and x.attacker_steamid == sid
                    and not is_teamkill(match, x))
            d = sum(1 for x in scoreboard if x.round == r.num and x.victim_steamid == sid)
            dmg = sum(x.dmg for x in match.damages if x.round == r.num and x.attacker_steamid == sid
                      and x.victim_steamid != sid and r.sides.get(x.victim_steamid) != side)
            rows.append([r.num, side, None if r.winner is None else r.winner == side, k, d,
                         dmg if match.damages else None])
        out[sid] = rows
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


def _ct_plays(match: MatchData) -> list[dict]:
    from cstaktik.playbook import ct_plays

    return ct_plays(match, team=match.focus_ids())


MOMENTS_PER_PLAYER = 5  # je Richtung (beste und teuerste)


def _moments(match: MatchData, result: AnalysisResult) -> list[dict]:
    if not result.impact:
        return []
    names = {p.steamid: p.name for p in match.players}
    out = []
    for sid in match.focus_ids():
        ms = [m for m in result.impact["moments"] if m["sid"] == sid and m["val"]]
        best = sorted((m for m in ms if m["val"] > 0), key=lambda m: -m["val"])[:MOMENTS_PER_PLAYER]
        worst = sorted((m for m in ms if m["val"] < 0), key=lambda m: m["val"])[:MOMENTS_PER_PLAYER]
        out += [{"sid": sid, "round": m["round"], "tick": m["tick"], "kind": m["kind"], "val": m["val"],
                 "ctx": m.get("ctx"), "other": names.get(m.get("other")) if m.get("other") else None}
                for m in best + worst]
    return out


def _impact(result: AnalysisResult, focus: set[str]) -> dict:
    from cstaktik.impact import history_row

    return history_row(result.impact, focus) if result.impact else {}


def _clutch(match: MatchData) -> list[dict]:
    from cstaktik.clutch import clutches

    return clutches(match, team=match.focus_ids())


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
    """Tod-Szenen mit Lagebild fürs Training über mehrere Matches (Entscheidung nachspielen). ``lessons``: alle
    Lektionen des Todes (Haupt-Lektion zuerst), damit ein Thema auch seine Szenen findet, wenn es nur mitspielte."""
    from cstaktik.coach_voice import lesson_ids

    out = []
    for f in result.findings:
        v, ev = f.evidence.get("coach"), f.evidence
        if not v or not ev.get("snap") or not ev.get("aktion"):
            continue
        out.append({"lesson": v["id"], "lessons": lesson_ids(ev.get("f") or {}, v["id"]), "who": f.player_name, "sid": f.steamid, "round": f.round, "tick": f.tick,
                    "from": (f.overlay.get("decision") or [None, None, None])[2], "report": report_file,
                    "map": map_name, "snap": ev["snap"], "info": ev.get("info"), "aktion": ev["aktion"],
                    "pro_rates": ev.get("pro_rates"), "pro_best": ev.get("pro_best"), "cost": ev.get("cost_pct"),
                    "happened": v["happened"], "next": v["next"], "pos": (ev.get("f") or {}).get("vpos"),
                    "frame": ev.get("frame"),
                    "nades": (ev.get("f") or {}).get("nades"),  # Granaten im Inventar beim Tod (Beleg)
                    "own": (ev.get("f") or {}).get("own"), "enemy": (ev.get("f") or {}).get("enemy")})
    return out


def _running(fc: dict | None) -> dict[str | None, str]:
    """Laufende Aufträge (nicht gerade neu gesetzt) je Spieler aus ``focus_check``. Altes Format (ein gemeinsamer
    Auftrag) steht unter dem Schlüssel None und gilt für alle."""
    if not fc:
        return {}
    if "check" in fc or "focus" in fc and not any(isinstance(v, dict) and "check" in v for v in fc.values()):
        fc = {None: fc}
    return {sid: v["focus"]["lesson"] for sid, v in fc.items()
            if isinstance(v, dict) and v.get("focus") and not v.get("new")}


def set_leads(h: dict) -> dict:
    """Das eine Thema des Matches, einmal festgelegt (wie "Der eine Punkt" im Report): Kam ein laufender Auftrag
    heute vor, ist er das Thema, sonst die wichtigste Lektion. ``lead`` fürs Team, ``lead_by`` je Spieler (sein
    Auftrag, falls er ihn heute hatte, sonst seine wichtigste Lektion). ``main_lesson`` folgt ``lead``.
    Braucht ``focus_check``; ohne ihn bleibt es bei der Reihenfolge der Lektionen."""
    running = _running(h.get("focus_check"))
    rank = h.get("lesson_rank") or []
    counts = h.get("lessons") or {}  # {sid: {lid: Anzahl}}

    def often(lid, sids):  # einmal gestorben ist noch kein Thema (wie coach_voice.MIN_LEAD_COUNT)
        return lid is not None and sum((counts.get(x) or {}).get(lid, 0) for x in sids) >= 2

    first = rank[0] if rank and (not counts or often(rank[0], list(counts))) else None
    h["lead"] = next((lid for lid in rank if lid in running.values()), first)
    h["main_lesson"] = h["lead"]
    by = {}
    for sid, ls in (h.get("lesson_rank_by") or {}).items():
        r = running.get(sid) or running.get(None)
        top = ls[0] if ls and (sid not in counts or often(ls[0], [sid])) else None
        by[sid] = r if r and r in ls else top
    h["lead_by"] = by
    return h


def _seq_by(h: dict) -> dict:
    """Rundenfolge je Spieler; ältere Einträge speichern eine Liste (Sicht des Teams) und zählen hier nicht."""
    seq = h.get("seq")
    return seq if isinstance(seq, dict) else {}


def lead(h: dict, sid: str | None = None) -> str | None:
    """Thema des Matches für einen Spieler (None: fürs Team). Mit Spieler nur sein eigenes Thema: fehlen seine
    Daten (kein Fokus-Spieler, etwa ein Gegner, oder ein alter Eintrag ohne Daten je Spieler), dann None, denn das
    Team-Thema kann das eines anderen sein. Ältere Einträge ohne ``lead``: bisheriges Hauptthema."""
    if sid:
        if sid in (h.get("lead_by") or {}):
            return h["lead_by"][sid]
        if h.get("lead_by"):
            return None
        ls = (h.get("lesson_rank_by") or {}).get(sid) or []
        return ls[0] if ls else None  # ohne eigene Lektion kein fremdes Thema zeigen
    return h.get("lead", h.get("main_lesson"))


def score(h: dict, sid: str | None = None) -> tuple[int, int] | None:
    """(gewonnen, verloren) aus Sicht des Spielers; ohne Spieler: Team-Ergebnis. Mit Spieler, aber ohne seine
    Daten: None (er kann auf der anderen Seite gespielt haben). Alte Einträge ohne Daten je Spieler: Team-Ergebnis
    nur für Fokus-Spieler (die damals im Team standen)."""
    if sid:
        s = (h.get("score_by") or {}).get(sid)
        if s:
            return int(s[0]), int(s[1])
        seq = _seq_by(h).get(sid)
        if seq:
            return sum(1 for x in seq if x[2]), sum(1 for x in seq if not x[2])
        if h.get("score_by") or _seq_by(h):
            return None
        if sid not in (h.get("issues") or {}) and sid not in (h.get("impact") or {}):
            return None
    return int(h.get("won") or 0), int(h.get("lost") or 0)


def previous(histories: list[dict], current: dict) -> dict | None:
    """Das zuletzt ausgewertete andere Match vor ``current`` (nach Auswertungszeit)."""
    ids = [h.get("id") for h in histories]
    if current.get("id") in ids:  # im Verlauf: alles davor in der (nach Zeit sortierten) Liste, nie ein späteres
        before = histories[:ids.index(current.get("id"))]
    else:
        before = [h for h in histories if h.get("analyzed_at", "") <= (current.get("analyzed_at") or "9999")]
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
    write_atomic(out, json.dumps(summary, ensure_ascii=False))
    return out


def load_all(history_dir: Path) -> list[dict]:
    items = []
    for f in history_dir.glob("*.json"):
        try:
            items.append(json.loads(f.read_text()))
        except (OSError, ValueError):
            continue
    return sorted(items, key=lambda h: (h.get("analyzed_at", ""), str(h.get("id"))))  # feste Reihenfolge bei Gleichstand
