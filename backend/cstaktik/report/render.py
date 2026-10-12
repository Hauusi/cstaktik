"""AnalysisResult + MatchData -> eine einzelne, mobile HTML-Datei mit 2D-Replay.

Alle Replay-Daten (Positionen, Kills, Utility, Bombe, Befunde) werden als JSON in die
Seite eingebettet. Koordinaten werden hier schon in Radar-Pixel umgerechnet.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from cstaktik.config import load_rules_config
from cstaktik.model import AnalysisResult, MatchData
from cstaktik.report.radar import build_radar

TEMPLATES = Path(__file__).parent / "templates"
_SEV_WEIGHT = {"hoch": 3, "mittel": 2, "niedrig": 1}


def _top_issues(result: AnalysisResult, n: int = 3) -> list[dict]:
    counter: Counter = Counter()
    weight: dict = {}
    for f in result.findings:
        if f.severity == "gut":
            continue
        key = (f.title, f.player_name or "Team")
        counter[key] += 1
        weight[key] = max(weight.get(key, 0), _SEV_WEIGHT[f.severity])
    ranked = sorted(counter, key=lambda k: (-(counter[k] * weight[k]), k))
    return [{"title": k[0], "who": k[1], "count": counter[k]} for k in ranked[:n]]


FLOOR_CELL = 8  # Radar-Pixel pro Zelle des Kartenumrisses
PLACE_MIN_SAMPLES = 20  # Mindestanzahl Positionen, damit ein Ortsname angezeigt wird


def _floor_and_places(match: MatchData, px) -> tuple[list, list]:
    """Kartenumriss (wo im Match Spieler standen) und Ortsnamen-Schwerpunkte, beides aus der Demo."""
    cells: Counter = Counter()
    sums: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0])
    for p in match.positions:
        x, y = px(p.pos.x, p.pos.y)
        cells[(int(x // FLOOR_CELL), int(y // FLOOR_CELL))] += 1
        if p.place:
            acc = sums[p.place]
            acc[0] += x
            acc[1] += y
            acc[2] += 1
    floor = [[i, j, c] for (i, j), c in cells.items()]
    places = [
        {"n": name, "x": round(sx / n, 1), "y": round(sy / n, 1)}
        for name, (sx, sy, n) in sums.items()
        if n >= PLACE_MIN_SAMPLES
    ]
    return floor, places


def _overlay_px(ov: dict, px) -> dict:
    out = {}
    if ov.get("line"):
        out["line"] = [list(px(x, y)) for x, y in ov["line"]]
    if ov.get("label"):
        out["label"] = ov["label"]
    return out


def _homework(result: AnalysisResult, n: int = 3) -> list[dict]:
    """Je Fokus-Spieler die n wichtigsten Fehler-Arten (Anzahl x Schwere) mit Tipp."""
    per: dict[str, dict] = defaultdict(dict)
    for f in result.findings:
        if f.severity == "gut" or not f.player_name:
            continue
        e = per[f.player_name].setdefault(f.title, {"title": f.title, "tip": f.tip, "count": 0, "w": 0, "rounds": set()})
        e["count"] += max(1, len(f.rounds)) if f.round is None else 1
        e["w"] = max(e["w"], _SEV_WEIGHT[f.severity])
        if f.round is not None:
            e["rounds"].add(f.round)
        e["rounds"].update(f.rounds)
    out = []
    for name, items in sorted(per.items()):
        ranked = sorted(items.values(), key=lambda e: (-(e["count"] * e["w"]), e["title"]))[:n]
        out.append({"name": name, "items": [{**e, "rounds": sorted(e["rounds"])} for e in ranked]})
    return out


def build_payload(match: MatchData, result: AnalysisResult, maps_dirs: list[Path] | None = None) -> dict:
    radar = build_radar(match, maps_dirs)
    px = radar.to_px
    focus = match.focus_ids()

    tracks: dict[int, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for p in sorted(match.positions, key=lambda s: s.tick):
        if not p.alive:
            continue
        x, y = px(p.pos.x, p.pos.y)
        tracks[p.round][p.steamid].append([p.tick, x, y, None if p.yaw is None else round(p.yaw)])

    findings = []
    for i, f in enumerate(result.findings):
        fx = fy = None
        if f.tick is not None and f.steamid:
            for k in match.kills:
                if k.tick == f.tick and k.victim_steamid == f.steamid and k.victim_pos:
                    fx, fy = px(k.victim_pos.x, k.victim_pos.y)
                    break
        findings.append(
            {
                "id": i,
                "rule": f.rule_id,
                "title": f.title,
                "round": f.round,
                "rounds": f.rounds,
                "tick": f.tick,
                "sev": f.severity,
                "who": f.player_name,
                "sid": f.steamid,
                "text": f.text,
                "tip": f.tip,
                "x": fx,
                "y": fy,
                "evidence": f.evidence,
                "ov": _overlay_px(f.overlay, px),
            }
        )

    rounds = []
    for r in match.rounds:
        side = match.focus_side(r.num)
        outcome = None
        if side and r.winner:
            outcome = "W" if r.winner == side else "L"
        kills = []
        for k in match.kills:
            if k.round != r.num:
                continue
            d = {"t": k.tick, "a": k.attacker_steamid, "v": k.victim_steamid, "w": k.weapon, "hs": k.headshot,
                 "pl": k.victim_place, "inv": k.victim_inventory}
            if k.victim_pos:
                d["vx"], d["vy"] = px(k.victim_pos.x, k.victim_pos.y)
            if k.attacker_pos:
                d["ax"], d["ay"] = px(k.attacker_pos.x, k.attacker_pos.y)
            kills.append(d)
        util = []
        for u in match.utility:
            if u.round == r.num:
                x, y = px(u.pos.x, u.pos.y)
                util.append({"k": u.kind, "s": u.start_tick, "e": u.end_tick, "ek": u.end_known, "x": x, "y": y,
                             "th": u.thrower_steamid})
        nades = []
        for g in match.grenades:
            if g.round == r.num and g.points:
                pts = [[t, *px(x, y)] for t, x, y, _z in g.points]
                nades.append({"k": g.kind, "th": g.thrower_steamid, "pts": pts})
        bomb = []
        for b in match.bomb:
            if b.round == r.num and b.event in ("plant", "defuse", "detonate") and b.pos:
                x, y = px(b.pos.x, b.pos.y)
                bomb.append({"t": b.tick, "ev": b.event, "x": x, "y": y})
        rounds.append(
            {
                "n": r.num,
                "side": side,
                "out": outcome,
                "t0": r.freeze_end_tick if r.freeze_end_tick is not None else r.start_tick,
                "t1": r.end_tick,
                "teams": r.sides,
                "tracks": tracks.get(r.num, {}),
                "kills": kills,
                "util": util,
                "nades": nades,
                "bomb": bomb,
                "f": [f["id"] for f in findings if f["round"] == r.num],
            }
        )

    floor, places = _floor_and_places(match, px)
    draw_cfg = load_rules_config().get("report", {})
    return {
        # Zeichengrößen in Radar-Pixeln (Konfiguration, reine Darstellung)
        "rSmoke": round(draw_cfg.get("smoke_draw_radius_units", 140) / radar.scale, 1),
        "rMolly": round(draw_cfg.get("molotov_draw_radius_units", 110) / radar.scale, 1),
        "tickrate": match.tickrate,
        "size": radar.size,
        "img": radar.image_data_uri,
        "floor": {"cell": FLOOR_CELL, "cells": floor} if not radar.image_data_uri else None,
        "places": places,
        "players": {p.steamid: {"name": p.name, "focus": p.steamid in focus} for p in match.players},
        "rounds": rounds,
        "findings": findings,
    }


def build_context(
    match: MatchData, result: AnalysisResult, maps_dirs: list[Path] | None = None, goal_check: dict | None = None
) -> dict:
    from cstaktik.coach import diagnose

    debrief = diagnose(match, result, load_rules_config()["coach"], load_rules_config()["mechanics"])
    payload = build_payload(match, result, maps_dirs)
    payload["moments"] = debrief["key_moments"]
    won = sum(1 for r in payload["rounds"] if r["out"] == "W")
    lost = sum(1 for r in payload["rounds"] if r["out"] == "L")
    radar_note = None if payload["img"] else build_radar(match, maps_dirs).note
    # "</" escapen, damit eingebettetes JSON das <script>-Tag nicht schließen kann
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return {
        "match": match,
        "map_label": (match.map_name or "unbekannte Map").removeprefix("de_").capitalize(),
        "score": {"won": won, "lost": lost},
        "top": _top_issues(result),
        "patterns": [f for f in result.findings if f.round is None and f.severity != "gut"],
        "unevaluated": [s for s in result.rule_status if not s.evaluated],
        "radar_note": radar_note,
        "debrief": debrief,
        "goal_check": goal_check,
        "mech_cfg": load_rules_config()["mechanics"],
        "n_findings": sum(1 for f in result.findings if f.severity != "gut"),
        "n_good": sum(1 for f in result.findings if f.severity == "gut"),
        "stats": result.stats,
        "homework": _homework(result),
        "data_json": data_json,
    }


def render_report(
    match: MatchData, result: AnalysisResult, maps_dirs: list[Path] | None = None, goal_check: dict | None = None
) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    return env.get_template("report.html").render(**build_context(match, result, maps_dirs, goal_check))


def write_report(
    match: MatchData, result: AnalysisResult, out: Path, maps_dirs: list[Path] | None = None,
    goal_check: dict | None = None,
) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report(match, result, maps_dirs, goal_check), encoding="utf-8")
    return out
