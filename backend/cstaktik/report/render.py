"""AnalysisResult + MatchData -> eine einzelne, mobile HTML-Datei."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from cstaktik.model import AnalysisResult, MatchData
from cstaktik.report.radar import AWPY_MAPS_DIR, build_radar
from cstaktik.rules.base import PositionIndex

TEMPLATES = Path(__file__).parent / "templates"
FOCUS_COLORS = ["#4fc3f7", "#ffb74d", "#ba68c8", "#81c784", "#f06292"]
_SEV_WEIGHT = {"hoch": 3, "mittel": 2, "niedrig": 1}
SIDE_DE = {"ct": "CT", "t": "T"}


def _top_issues(result: AnalysisResult, n: int = 3) -> list[dict]:
    counter: Counter = Counter()
    weight: dict = {}
    for f in result.findings:
        key = (f.title, f.player_name or "Team")
        counter[key] += 1
        weight[key] = max(weight.get(key, 0), _SEV_WEIGHT[f.severity])
    ranked = sorted(counter, key=lambda k: (-(counter[k] * weight[k]), k))
    return [{"title": k[0], "who": k[1], "count": counter[k]} for k in ranked[:n]]


def build_context(match: MatchData, result: AnalysisResult, maps_dir: Path = AWPY_MAPS_DIR) -> dict:
    radar = build_radar(match, maps_dir)
    idx = PositionIndex(match.positions)
    focus = sorted(match.focus_ids())
    color = {sid: FOCUS_COLORS[i % len(FOCUS_COLORS)] for i, sid in enumerate(focus)}

    rounds = []
    won = lost = 0
    for r in match.rounds:
        side = match.focus_side(r.num)
        outcome = None
        if side and r.winner:
            outcome = "gewonnen" if r.winner == side else "verloren"
            won += outcome == "gewonnen"
            lost += outcome == "verloren"
        mates = [s for s, sd in r.sides.items() if side and sd == side]
        paths = []
        for sid in mates:
            pts = [radar.to_px(p.pos.x, p.pos.y) for p in idx.path(r.num, sid) if p.alive]
            if len(pts) >= 2:
                paths.append(
                    {
                        "points": " ".join(f"{x},{y}" for x, y in pts),
                        "color": color.get(sid, "#9e9e9e"),
                        "focus": sid in color,
                        "name": match.name_of(sid),
                    }
                )
        deaths = []
        for k in match.kills:
            if k.round != r.num or k.victim_steamid not in mates or k.victim_pos is None:
                continue
            vx, vy = radar.to_px(k.victim_pos.x, k.victim_pos.y)
            d = {"x": vx, "y": vy, "color": color.get(k.victim_steamid, "#9e9e9e"), "focus": k.victim_steamid in color}
            if k.attacker_pos is not None:
                d["ax"], d["ay"] = radar.to_px(k.attacker_pos.x, k.attacker_pos.y)
            deaths.append(d)
        rf = [f for f in result.findings if f.round == r.num]
        rounds.append(
            {
                "num": r.num,
                "side": SIDE_DE.get(side, "?"),
                "outcome": outcome,
                "findings": rf,
                "paths": paths,
                "deaths": deaths,
            }
        )

    return {
        "match": match,
        "map_label": (match.map_name or "unbekannte Map").removeprefix("de_").capitalize(),
        "score": {"won": won, "lost": lost},
        "top": _top_issues(result),
        "patterns": [f for f in result.findings if f.round is None],
        "rounds": rounds,
        "rule_status": result.rule_status,
        "radar": radar,
        "legend": [{"name": match.name_of(s), "color": color[s]} for s in focus],
        "n_findings": len(result.findings),
    }


def render_report(match: MatchData, result: AnalysisResult, maps_dir: Path = AWPY_MAPS_DIR) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    return env.get_template("report.html").render(**build_context(match, result, maps_dir))


def write_report(match: MatchData, result: AnalysisResult, out: Path, maps_dir: Path = AWPY_MAPS_DIR) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report(match, result, maps_dir), encoding="utf-8")
    return out
