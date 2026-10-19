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
from cstaktik.coaching import bright_spots
from cstaktik.curriculum import TEACH
from cstaktik.icons import icon_for
from cstaktik.mechanics import is_gun
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


NADE_ICON = {"smoke": "smokegrenade", "flash": "flashbang", "he": "hegrenade", "molotov": "molotov",
             "decoy": "decoy"}


def _icon_data(names: set[str]) -> dict[str, str]:
    """SVG-Icons aus data/icons als data-URI (nur die im Match benutzten)."""
    import base64

    from cstaktik import icons

    out = {}
    for n in sorted(names):
        f = icons.ICONS_DIR / f"{n}.svg"
        if f.exists():
            out[n] = "data:image/svg+xml;base64," + base64.b64encode(f.read_bytes()).decode()
    return out


def _overlay_px(ov: dict, px) -> dict:
    out = {}
    if ov.get("ghost"):
        out["ghost"] = list(px(*ov["ghost"]))
        out["ghost_round"] = ov.get("ghost_round")
        out["ghost_offset_s"] = ov.get("ghost_offset_s")
    if ov.get("line"):
        out["line"] = [list(px(x, y)) for x, y in ov["line"]]
    if ov.get("label"):
        out["label"] = ov["label"]
    if ov.get("decision"):
        dx, dy, dt = ov["decision"]
        out["decision"] = [*px(dx, dy), dt]
    if ov.get("pro_clip") is not None:
        out["pro_clip"] = ov["pro_clip"]  # wird in build_payload auf den Rundenindex umgerechnet
        out["pro_tick"] = ov.get("pro_tick")
    if ov.get("pro_nade"):
        fx, fy, tx, ty = ov["pro_nade"]["xy"]
        out["pro_nade"] = {"kind": ov["pro_nade"]["kind"], "a": list(px(fx, fy)), "b": list(px(tx, ty))}
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


def build_payload(match: MatchData, result: AnalysisResult, maps_dirs: list[Path] | None = None,
                  pro_clips: list[dict] | None = None) -> dict:
    radar = build_radar(match, maps_dirs)
    px = radar.to_px
    focus = match.focus_ids()

    weapons: list[str] = []  # Waffennamen-Tabelle, im Track als Index
    widx: dict[str, int] = {}

    def wi(name: str | None) -> int | None:
        if not name:
            return None
        if name not in widx:
            widx[name] = len(weapons)
            weapons.append(name)
        return widx[name]

    tracks: dict[int, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for p in sorted(match.positions, key=lambda s: s.tick):
        if not p.alive:
            continue
        x, y = px(p.pos.x, p.pos.y)
        tracks[p.round][p.steamid].append([p.tick, x, y, None if p.yaw is None else round(p.yaw), wi(p.weapon)])

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

    draw_cfg0 = load_rules_config().get("report", {})
    default_s = {"smoke": draw_cfg0.get("smoke_default_s", 18), "molotov": draw_cfg0.get("molotov_default_s", 7)}

    def round_obj(m: MatchData, r, trk: dict, side, outcome, fids: list[int]) -> dict:
        """Eine Runde für das Replay (auch für Pro-Szenen aus anderen Demos derselben Map)."""
        kills = []
        for k in m.kills:
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
        for u in m.utility:
            if u.round == r.num:
                x, y = px(u.pos.x, u.pos.y)
                end = u.end_tick
                if not u.end_known:
                    # Demo liefert kein Ende: CS2-Standarddauer statt bis Rundenende (ohne Countdown)
                    dflt = default_s.get(u.kind)
                    if dflt:
                        cap = u.start_tick + int(dflt * m.tickrate)
                        end = cap if end is None else min(end, cap)
                util.append({"k": u.kind, "s": u.start_tick, "e": end, "ek": u.end_known, "x": x, "y": y,
                             "th": u.thrower_steamid})
        used_util: set[int] = set()
        nades = []
        for g in sorted((g for g in m.grenades if g.round == r.num and g.points), key=lambda g: g.points[0][0]):
            pts = [[t, *px(x, y)] for t, x, y, _z in g.points]
            nd = {"k": g.kind, "th": g.thrower_steamid, "pts": pts,
                  "ic": icon_for(g.grenade_type) or NADE_ICON.get(g.kind)}
            # Landung = Detonation derselben Granate (gleicher Werfer und Typ, erste danach)
            det = next((i for i, u in enumerate(util) if i not in used_util and u["k"] == g.kind
                        and u["th"] == g.thrower_steamid and u["s"] >= g.points[0][0]), None)
            if det is not None:
                used_util.add(det)
                nd["land"] = min(util[det]["s"], g.points[-1][0])
            nades.append(nd)
        shots = [[sh.tick, sh.steamid, wi(sh.weapon.removeprefix("weapon_"))] for sh in m.shots
                 if sh.round == r.num and is_gun(sh.weapon)]
        hurts = [[d.tick, d.attacker_steamid, d.victim_steamid, d.dmg] for d in m.damages
                 if d.round == r.num and d.attacker_steamid and is_gun(d.weapon)]
        bomb = []
        for b in m.bomb:
            if b.round == r.num and b.event in ("plant", "defuse", "detonate") and b.pos:
                x, y = px(b.pos.x, b.pos.y)
                bomb.append({"t": b.tick, "ev": b.event, "x": x, "y": y})
        return (
            {
                "n": r.num,
                "side": side,
                "out": outcome,
                "t0": r.freeze_end_tick if r.freeze_end_tick is not None else r.start_tick,
                "t1": r.end_tick,
                "teams": r.sides,
                "tracks": trk,
                "kills": kills,
                "util": util,
                "shots": shots,
                "hurts": hurts,
                "nades": nades,
                "bomb": bomb,
                "f": fids,
            }
        )

    rounds = []
    for r in match.rounds:
        side = match.focus_side(r.num)
        outcome = None
        if side and r.winner:
            outcome = "W" if r.winner == side else "L"
        rounds.append(round_obj(match, r, tracks.get(r.num, {}), side, outcome,
                                [f["id"] for f in findings if f["round"] == r.num]))

    # Pro-Szenen (reference.pro_clips): als zusätzliche Runden hinten angehängt, nicht in der Rundenleiste
    players = {p.steamid: {"name": p.name, "focus": p.steamid in focus} for p in match.players}
    base = len(rounds)
    for i, c in enumerate(pro_clips or []):
        pm, pr, t0, t1 = c["match"], c["round"], c["t0"], c["t1"]
        trk: dict[str, list] = defaultdict(list)
        for p in sorted(pm.positions, key=lambda s: s.tick):
            if p.round == pr.num and p.alive and t0 - pm.tickrate <= p.tick <= t1:
                x, y = px(p.pos.x, p.pos.y)
                trk[p.steamid].append([p.tick, x, y, None if p.yaw is None else round(p.yaw), wi(p.weapon)])
        side = pr.sides.get(c["sid"])
        ro = round_obj(pm, pr, dict(trk), side, "W", [])
        ro["kills"] = [k for k in ro["kills"] if k["t"] <= t1]
        ro["util"] = [u for u in ro["util"] if u["s"] <= t1 and (u["e"] is None or u["e"] >= t0 - 20 * pm.tickrate)]
        ro["nades"] = [n for n in ro["nades"] if n["pts"][0][0] <= t1 and n["pts"][-1][0] >= t0 - 2 * pm.tickrate]
        ro["shots"] = [x for x in ro["shots"] if t0 <= x[0] <= t1]
        ro["hurts"] = [x for x in ro["hurts"] if t0 <= x[0] <= t1]
        ro["bomb"] = [x for x in ro["bomb"] if x["t"] <= t1]
        name = next((p.name for p in pm.players if p.steamid == c["sid"]), "Pro")
        ro.update({"t0": t0, "t1": t1, "rt0": pr.freeze_end_tick, "pro": True, "hl": c["sid"], "n": f"P{i + 1}",
                   "desc": c.get("desc"),
                   "label": f"Pro-Szene · {name} · {(side or '').upper()}"})
        rounds.append(ro)
        for p in pm.players:
            players.setdefault(p.steamid, {"name": p.name, "focus": False})
    for f in findings:
        if f["ov"].get("pro_clip") is not None:
            f["ov"]["pro_clip"] += base

    floor, places = _floor_and_places(match, px)
    draw_cfg = load_rules_config().get("report", {})
    return {
        # Zeichengrößen in Radar-Pixeln (Konfiguration, reine Darstellung)
        "weapons": weapons,
        "weaponIcon": [icon_for(w) for w in weapons],
        "icons": _icon_data(({icon_for(w) for w in weapons} | set(NADE_ICON.values())) - {None}),
        "upx": round(1 / radar.scale, 4),  # Radar-Pixel pro Spieleinheit
        "rSmoke": round(draw_cfg.get("smoke_draw_radius_units", 140) / radar.scale, 1),
        "rMolly": round(draw_cfg.get("molotov_draw_radius_units", 110) / radar.scale, 1),
        "tickrate": match.tickrate,
        "size": radar.size,
        "img": radar.image_data_uri,
        "floor": {"cell": FLOOR_CELL, "cells": floor} if not radar.image_data_uri else None,
        "places": places,
        "players": players,
        "rounds": rounds,
        "findings": findings,
    }


def _with_sid(lines: list[str], match: MatchData) -> list[dict]:
    """Lob-Zeilen ("Name: ...") mit SteamID, damit die persönliche Ansicht nur die eigenen zeigt."""
    by_name = {p.name: p.steamid for p in match.players}
    return [{"sid": by_name.get(t.split(":", 1)[0]), "text": t} for t in lines]


def _setups(match: MatchData) -> dict | None:
    from cstaktik import pipeline, pro, setups

    pros = pro.load_all(pipeline.PRO_DIR)
    ct, top = setups.ct_positions(match, pros)
    t = setups.t_executes(match, pros)
    return {"ct": ct[:6], "ct_pro_top": top, "t": t} if ct or t else None


def _tactics(match: MatchData) -> dict | None:
    """Eure Taktiken und Aufstellungen dieses Matches in der Sprache des Playbooks, mit Pro-Vergleich.
    Je T-Runde der Taktikname, je CT-Runde die Aufstellung (A-Mitte-B nach 20 s); gruppiert mit Siegen."""
    from cstaktik import pipeline, playbook, pro

    focus = match.focus_ids()
    if not focus or not match.map_name:
        return None
    cfg = load_rules_config().get("playbook")
    pros = pro.load_all(pipeline.PRO_DIR)
    t_plays, ct_plays = playbook.plays(match, team=focus), playbook.ct_plays(match, team=focus)
    me = {"map": match.map_name, "plays": t_plays, "ct_plays": ct_plays}
    centers = playbook.site_centers(pros + [me], match.map_name)
    pro_t = {t["name"]: t for t in playbook.build(pros, match.map_name, cfg)["tactics"]}
    pro_ct = {s["key"]: s for s in playbook.ct_build(pros, match.map_name, centers, cfg)["setups"]}
    units = (cfg or {}).get("zone_units", playbook.CT_DEFAULTS["zone_units"])
    tags, t_rows, ct_rows = {}, {}, {}
    for p in t_plays:
        k = playbook.classify(p, cfg)
        tags[p["r"]] = k["name"]
        row = t_rows.setdefault(k["name"], {"name": k["name"], "style": k["style"], "n": 0, "won": 0, "rounds": []})
        row["n"] += 1
        row["won"] += p["won"]
        row["rounds"].append(p["r"])
    if len(centers) >= 2:
        for p in ct_plays:
            if len(p["pos"]) < 3:
                continue
            z = [playbook.zone(v[0], v[1], centers, units) for v in p["pos"].values()]
            key = f"{z.count('A')}-{z.count('M')}-{z.count('B')}"
            a, b = z.count("A"), z.count("B")
            name = f"Stack auf {'A' if a >= 4 else 'B'}" if max(a, b) >= 4 else key
            tags[p["r"]] = f"{tags[p['r']]} / CT {name}" if p["r"] in tags else f"CT {name}"  # Fokus-Spieler in beiden Teams
            row = ct_rows.setdefault(key, {"name": name, "key": key, "n": 0, "won": 0, "rounds": []})
            row["n"] += 1
            row["won"] += p["won"]
            row["rounds"].append(p["r"])
    for rows, ref, k in ((t_rows, pro_t, "name"), (ct_rows, pro_ct, "key")):
        for row in rows.values():
            row["won_pct"] = round(100 * row["won"] / row["n"])
            q = ref.get(row[k])
            row["pro"] = {"n": q["n"], "won_pct": q["won_pct"], "id": q["id"]} if q else None
    if not t_rows and not ct_rows:
        return None
    by = lambda d: sorted(d.values(), key=lambda r: (-r["n"], -r["won_pct"]))  # noqa: E731
    return {"t": by(t_rows), "ct": by(ct_rows), "tags": tags, "map": match.map_name, "zones": len(centers) >= 2}


def _util_cmp(match: MatchData) -> dict:
    from cstaktik import pipeline, pro, utility_cmp

    return utility_cmp.compare(match, pro.load_all(pipeline.PRO_DIR), load_rules_config().get("utility_cmp"))


def _glance(result: AnalysisResult, imp: dict | None) -> list[dict]:
    """Je Fokus-Spieler die Kernzahlen des Matches für die Kopfzeile im Coach-Reiter (nur vorhandene Werte)."""
    rows = {r["sid"]: r for r in (imp or {}).get("rows", [])}
    out = []
    for st in result.stats:
        r = rows.get(st.steamid)
        out.append({"sid": st.steamid, "name": st.name, "kd": f"{st.kills}/{st.deaths}",
                    "adr": None if st.adr is None else round(st.adr),
                    "imp": r["total_s"] if r else None, "pos": bool(r and r["total"] > 0),
                    "rank": f"{r['rank']}/{len(rows)}" if r else None})
    return out


KIND_DE = {"kill": "Kill", "death": "Tod", "plant": "Bombe gelegt", "defuse": "Entschärft", "teamkill": "Teamkill"}


def _impact(match: MatchData, result: AnalysisResult) -> dict | None:
    """Impact-Tabelle (alle Spieler) und je Fokus-Spieler die größten Momente nach Siegchance."""
    imp = result.impact
    if not imp or not imp["players"]:
        return None
    from cstaktik.impact import CTX_DE, de

    names = {p.steamid: p.name for p in match.players}
    focus = match.focus_ids()
    rows = sorted(({"sid": s, "name": names.get(s, s), "focus": s in focus, "total": p["total"] / 100,
                    "total_s": de(p["total"] / 100), "kill_s": de(p["kill"] / 100), "death_s": de(p["death"] / 100),
                    "obj_s": de((p["plant"] + p["defuse"]) / 100), "obj": p["plant"] + p["defuse"]}
                   for s, p in imp["players"].items() if s in names), key=lambda r: -r["total"])
    if not rows:
        return None
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    mine = []
    for sid in sorted(focus, key=lambda s: names.get(s, s)):
        p = imp["players"].get(sid)
        if not p:
            continue
        ms = [m for m in imp["moments"] if m["sid"] == sid]

        def line(m):
            who = names.get(m["other"]) if m.get("other") else None
            txt = KIND_DE[m["kind"]] + (f" gegen {who}" if m["kind"] in ("kill", "teamkill") and who else
                                        f" durch {who}" if m["kind"] == "death" and who else "")
            ctx = CTX_DE.get(m.get("ctx")) if m.get("ctx") not in (None, "bomb", "even") else None
            return {"round": m["round"], "tick": m["tick"], "text": txt + (f" · {ctx}" if ctx else ""),
                    "val": f"{de(m['val'])} %", "up": m["val"] > 0}

        best = [line(m) for m in sorted(ms, key=lambda m: -m["val"]) if m["val"] > 0][:3]
        worst = [line(m) for m in sorted(ms, key=lambda m: m["val"]) if m["val"] < 0][:3]
        rank = next(r["rank"] for r in rows if r["sid"] == sid)
        mine.append({"sid": sid, "name": names.get(sid, sid), "best": best, "worst": worst, "rank": rank,
                     "text": f"Platz {rank} von {len(rows)} mit {de(p['total'] / 100)} Runden Siegchance. "
                             f"Davon Kills {de(p['kill'] / 100)}, Tode {de(p['death'] / 100)}"
                             + (f", Bombe {de((p['plant'] + p['defuse']) / 100)}" if p["plant"] or p["defuse"] else "")
                             + "."})
    return {"rows": rows, "mine": mine}


def _duel_cmp(match: MatchData) -> dict | None:
    """Duell-Kennzahlen je Fokus-Spieler gegen den Schnitt aller Pro-Demos (Fadenkreuz, Reaktion, erste Kugel)."""
    from cstaktik import duels, pipeline, pro

    rows = {}
    for sid in sorted(match.focus_ids()):
        views = [duels.side_of(d, sid, match.tickrate) for d in match.duels if sid in (d.winner, d.loser)]
        if views:
            rows[sid] = {"sid": sid, "name": match.name_of(sid), **duels.stats(views)}
    if not rows:
        return None
    from cstaktik.coach_voice import duel_reading

    pr = pro.duel_stats(pro.load_all(pipeline.PRO_DIR))
    for row in rows.values():
        row["reading"] = duel_reading(row, pr)
    return {"players": list(rows.values()), "pro": pr}


AIM_LOW_GAP = 10  # Prozentpunkte mehr Duelle mit zu tiefem Fadenkreuz als Pros
AIM_ERR_GAP = 1.5  # Grad mehr Abstand zum Kopf als Pros
AIM_HIT_GAP = 8  # Prozentpunkte weniger "erste Kugel trifft" als Pros
AIM_MIN_DUELS = 15


def _aim(match: MatchData, duel_cmp: dict | None) -> list[dict]:
    """Je Fokus-Spieler ein konkreter Aim-Tipp, nur wenn seine Duell-Werte klar schlechter sind als die der Pros,
    mit den Runden, in denen genau das ihn das Duell gekostet hat (verlorene Duelle mit diesem Fehler)."""
    from cstaktik import duels

    if not duel_cmp or not duel_cmp.get("pro"):
        return []
    pro, out = duel_cmp["pro"], []
    for d in duel_cmp["players"]:
        if (d.get("n") or 0) < AIM_MIN_DUELS:
            continue
        sid = d["sid"]
        lost = [(x, duels.side_of(x, sid, match.tickrate)) for x in match.duels if x.loser == sid]
        tip = None
        if d.get("low_pct") is not None and pro.get("low_pct") is not None and d["low_pct"] - pro["low_pct"] >= AIM_LOW_GAP:
            rounds = [x.round for x, v in lost if v.get("height") is not None and v["height"] > 2
                      and v.get("err") is not None and v["err"] <= 20]
            tip = {"title": "Fadenkreuz zu tief",
                   "fact": f"In {d['low_pct']} % deiner Duelle lag das Fadenkreuz mehr als 2° unter dem Kopf. Pros: {pro['low_pct']} %.",
                   "drill": "Prefire-Map deiner Map, 10 Minuten: Laufe jede Ecke ab und halte das Fadenkreuz dabei auf "
                            "Kopfhöhe an der Kante. Nie auf den Boden schauen.",
                   "rounds": rounds}
        elif d.get("err") is not None and pro.get("err") is not None and d["err"] - pro["err"] >= AIM_ERR_GAP:
            rounds = [x.round for x, v in lost if v.get("err") is not None and v["err"] >= 10]
            tip = {"title": "Fadenkreuz neben dem Gegner",
                   "fact": f"Beim Duellstart lag dein Fadenkreuz im Mittel {_de1(d['err'])}° neben dem Kopf. Pros: {_de1(pro['err'])}°.",
                   "drill": "Prefire-Map, 10 Minuten: Vor jeder Ecke das Fadenkreuz auf die Kante legen, auf Kopfhöhe. "
                            "Erst dann um die Ecke gehen.",
                   "rounds": rounds}
        elif (d.get("first_hit") is not None and pro.get("first_hit") is not None
              and pro["first_hit"] - d["first_hit"] >= AIM_HIT_GAP):
            moving = (d.get("moving_pct") or 0) >= 30
            rounds = [x.round for x, v in lost if v.get("hit") is False]
            tip = {"title": "Erste Kugel trifft zu selten",
                   "fact": f"Deine erste Kugel trifft in {d['first_hit']} % der Duelle. Pros: {pro['first_hit']} %."
                           + (f" {d['moving_pct']} % deiner ersten Schüsse kamen aus der Bewegung." if moving else ""),
                   "drill": ("Deathmatch, 10 Minuten: nur schießen, wenn du stehst. Gegenrichtung tippen (Counter-Strafe), "
                             "dann ein Schuss auf den Kopf." if moving else
                             "Deathmatch, 10 Minuten: nur Kopfschüsse, nur die erste Kugel zählt. Danach kurz absetzen."),
                   "rounds": rounds}
        if tip:
            tip["rounds"] = sorted(set(tip["rounds"]))[:6]
            out.append({"sid": sid, "name": d["name"], **tip})
    return out


def _util_by(match: MatchData) -> dict:
    from cstaktik.history import util_stats

    return util_stats(match)


def _de1(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def _round_lines(match: MatchData) -> dict:
    """Je Runde: Kauf je Seite (Pistole/Eco/Force/Full, wie im Playbook) und je Fokus-Spieler [Kills, Tod, Schaden]."""
    from cstaktik import history, playbook

    cfg = load_rules_config().get("playbook")
    buys = {}
    for r in match.rounds:
        eq = {sd: [e.equip_value for e in r.economy if e.side == sd and e.equip_value is not None] for sd in ("t", "ct")}
        buys[r.num] = {sd: playbook.buy_of(sum(v) if len(v) >= 4 else None, r.num in (1, 13), cfg) for sd, v in eq.items()}
    me: dict[int, dict] = defaultdict(dict)
    for sid, rows in history.by_round(match).items():
        for n, _side, _won, k, d, dmg in rows:
            me[n][sid] = [k, d, dmg]
    return {"buy": buys, "me": me}


def _spots(result: AnalysisResult) -> list[dict]:
    """Gleicher Todesort, je Spieler zusammengefasst: "4x als T in Apartments (R5, 7, 9, 11)", häufigste zuerst."""
    from cstaktik.callouts import place

    per: dict[str, dict] = {}
    for f in result.findings:
        if f.rule_id != "repeated_death_spot" or not f.steamid:
            continue
        e = per.setdefault(f.steamid, {"sid": f.steamid, "name": f.player_name, "rows": []})
        ev = f.evidence
        e["rows"].append({"n": ev["tode"], "side": (ev.get("seite") or "").upper(), "place": place(ev["ort"]),
                          "rounds": ev["runden"]})
    for e in per.values():
        e["rows"].sort(key=lambda x: (-x["n"], x["rounds"]))
    return sorted(per.values(), key=lambda e: e["name"] or "")


def _debrief_lesson(match: MatchData, l0: dict, sid: str | None = None, bright: list[dict] | None = ...) -> dict:
    t = TEACH[l0["id"]]
    if bright is ...:
        bright = bright_spots(match, l0["id"], _trade_units(), sid=sid)
    return {"id": l0["id"], "title": l0["lesson"], "why": l0["why"], "count": l0["count"], "cost": l0["cost"],
            "scenes": l0["scenes"][:4], "principle": t["principle"], "mantra": t["mantra"],
            "routine": t["routine"], "in_game": t["in_game"], "bright": bright}


def _debrief_data(match: MatchData, lessons: list[dict], auftraege: list[dict], intro: list[str],
                  mine: list[dict] | None = None) -> dict:
    """Inhalt der geführten Debrief-Sitzung (Report-JS baut daraus die Schritte). ``lessons``: Thema zuerst, leer
    ohne Thema (wie history.set_leads). ``by``: je Spieler sein Thema (für die persönliche Ansicht mit
    window.__ME), nur wer eins hat; Auftrag-Checks und Abmachungen tragen die SteamID."""
    lesson = _debrief_lesson(match, lessons[0]) if lessons else None
    checks = [{"name": a["name"], "sid": a.get("sid"),
               **{k: a["check"].get(k) for k in ("title", "count", "rate", "target", "met", "streak",
                                                 "need", "rounds", "streak_rounds", "need_rounds", "drills")},
               "mastered": bool(a.get("mastered"))}
              for a in auftraege if a.get("check")]
    nexts = [{"name": a["name"], "sid": a.get("sid"), "lesson": a["focus"]["lesson"], "title": a["focus"]["title"],
              "target": a["focus"]["target"], "new": a.get("new"), "mantra": TEACH[a["focus"]["lesson"]]["mantra"],
              "routine": TEACH[a["focus"]["lesson"]]["routine"], "in_game": TEACH[a["focus"]["lesson"]]["in_game"]}
             for a in auftraege if a.get("focus")]
    by = {m["sid"]: _debrief_lesson(match, m["lessons"][0], m["sid"], m["bright"]) for m in mine or [] if m["lead"]}
    return {"intro": intro, "lesson": lesson, "checks": checks, "next": nexts, "by": by,
            "intro_by": {m["sid"]: m["intro"] for m in mine or []}}


RANK_N = 10  # so viele Lektionen kennt der Verlauf (history.lesson_rank); das Thema kommt nur aus ihnen


def _lead_first(ls: list[dict], running: set | list, fixed: str | None = ...) -> tuple[list[dict], bool]:
    """Thema zuerst, wie history.set_leads: ein laufender Auftrag, der heute vorkam (unter den ersten ``RANK_N``),
    sonst die wichtigste Lektion, aber nur ab ``MIN_LEAD_COUNT`` Toden. ``fixed``: Thema aus dem Verlauf (``lead``
    bzw. ``lead_by``), dann gilt genau dieses. Zweiter Wert: gibt es ein Thema?"""
    if fixed is ...:
        ids = [x["id"] for x in ls[:RANK_N]]
        fixed = next((lid for lid in ids if lid in running), ls[0]["id"] if ls and ls[0]["lead"] else None)
    lead = next((x for x in ls if x["id"] == fixed), None) if fixed else None
    return ([lead] + [x for x in ls if x is not lead] if lead else ls), lead is not None


def _side_score(match: MatchData, sid: str) -> tuple[int, int]:
    """Ergebnis aus Sicht des Spielers (falls ihr gegeneinander spielt)."""
    won = sum(1 for r in match.rounds if r.winner and r.sides.get(sid) == r.winner)
    lost = sum(1 for r in match.rounds if r.winner and sid in r.sides and r.sides[sid] != r.winner)
    return won, lost


def _lessons_by(match: MatchData, result: AnalysisResult, auftraege: list[dict], past: list[dict] | None,
                lead_by: dict | None = None) -> list[dict]:
    """Je Fokus-Spieler seine Lektionen, sein Thema zuerst (wie history.set_leads: sein laufender Auftrag, wenn er
    heute vorkam, sonst seine wichtigste Lektion ab zwei Toden; ``lead_by`` aus dem Verlauf, falls vorhanden).
    ``lead``: hat er ein Thema? Ohne Thema keine "Der eine Punkt"-Karte. Auch Spieler ohne Lektion stehen drin
    (eigene Ansprache mit seinem Ergebnis). Szenen verweisen auf die Findings des ganzen Matches."""
    from cstaktik import coach_voice

    running = {a.get("sid"): a["focus"]["lesson"] for a in auftraege if a.get("focus") and not a.get("new")}
    idx = {id(f): i for i, f in enumerate(result.findings)}
    label = (match.map_name or "?").removeprefix("de_").capitalize()
    out = []
    for sid in sorted(match.focus_ids(), key=match.name_of):
        own = [f for f in result.findings if f.steamid == sid]
        ls = coach_voice.focus(own, 20, coach_voice.recurrence(past or [], sid))
        for x in ls:
            for sc in x["scenes"]:
                sc["finding"] = idx[id(own[sc["finding"]])]
                sc["sid"] = sid
        r = running.get(sid) or running.get(None)
        ls, has = _lead_first(ls, {r} if r else set(), lead_by[sid] if lead_by and sid in lead_by else ...)
        won, lost = _side_score(match, sid)
        out.append({"sid": sid, "name": match.name_of(sid), "lessons": ls[:3], "lead": has,
                    "intro": coach_voice.intro(won, lost, label, ls[:3] if has else []),
                    "won": won, "lost": lost,
                    "bright": bright_spots(match, ls[0]["id"], _trade_units(), sid=sid) if has else None})
    return out


def normalize_focus(fc: dict | None) -> list[dict]:
    """Auftrags-Ergebnis je Spieler als Liste. Älteres Format (ein gemeinsamer Auftrag) wird zu einem Eintrag."""
    if not fc:
        return []
    if "check" in fc or "focus" in fc and not any(isinstance(v, dict) and "check" in v for v in fc.values()):
        return [{**fc, "name": "Ihr", "sid": None}]
    return [{**v, "sid": sid} for sid, v in sorted(fc.items(), key=lambda kv: kv[1].get("name", ""))]


def _duel_now(match: MatchData) -> dict:
    from cstaktik.history import duel_stats

    return duel_stats(match)


def _trade_units() -> float:
    return load_rules_config()["rules"]["death_review"]["trade_distance_units"]


def build_context(
    match: MatchData, result: AnalysisResult, maps_dirs: list[Path] | None = None, goal_check: dict | None = None,
    pro_clips: list[dict] | None = None, memory: dict | None = None, focus: dict | None = None,
    recur: tuple | None = None, past: list[dict] | None = None, leads: dict | None = None,
) -> dict:
    """``leads``: ``lead``/``lead_by`` aus dem Verlauf (history.set_leads), damit Report, Startseite und Push dasselbe
    Thema nennen; ohne sie gilt dieselbe Regel hier."""
    from cstaktik.coach import diagnose

    debrief = diagnose(match, result, load_rules_config()["coach"], load_rules_config()["mechanics"])
    payload = build_payload(match, result, maps_dirs, pro_clips)
    payload["moments"] = debrief["key_moments"]
    from cstaktik import coach_voice

    all_lessons = coach_voice.focus(result.findings, 20, recur=recur)
    auftraege = normalize_focus(focus)
    # Eine Sache zur Zeit: kam ein laufender Auftrag heute vor, ist er überall das Thema (Einleitung, Der eine Punkt,
    # Debrief), statt neben dem Auftrag ein zweites Thema aufzumachen
    # Ohne Thema (eine einzelne Szene ist noch kein Muster) keine "Der eine Punkt"-Karte, wie auf Startseite und Push
    running = [a["focus"]["lesson"] for a in auftraege if a.get("focus") and not a.get("new")]
    all_lessons, has_lead = _lead_first(all_lessons, running, leads.get("lead") if leads else ...)
    for x in all_lessons:  # wessen Szene (persönliche Ansicht im Report)
        for sc in x["scenes"]:
            sc["sid"] = result.findings[sc["finding"]].steamid
    lessons = all_lessons[:3]
    point = lessons if has_lead else []  # "Der eine Punkt" und Debrief nur mit Thema
    mine = _lessons_by(match, result, auftraege, past, (leads or {}).get("lead_by"))
    won = sum(1 for r in payload["rounds"] if r["out"] == "W" and not r.get("pro"))
    lost = sum(1 for r in payload["rounds"] if r["out"] == "L")
    radar_note = None if payload["img"] else build_radar(match, maps_dirs).note
    # "</" escapen, damit eingebettetes JSON das <script>-Tag nicht schließen kann
    map_label_s = (match.map_name or "?").removeprefix("de_").capitalize()
    payload["debrief"] = _debrief_data(match, point, auftraege, coach_voice.intro(won, lost, map_label_s, point),
                                       mine)
    tac_now = _tactics(match)
    for ro in payload["rounds"]:  # Taktik-Etikett je Runde (Runden-Reiter)
        if not ro.get("pro") and tac_now and ro.get("n") in tac_now["tags"]:
            ro["tac"] = tac_now["tags"][ro["n"]]
    imp = _impact(match, result)
    lines = _round_lines(match)
    for ro in payload["rounds"]:  # Runden-Reiter: Kauf und eigene Zeile
        if not ro.get("pro") and ro.get("n") in lines["buy"]:
            ro["buy"] = lines["buy"][ro["n"]]
            ro["me"] = lines["me"].get(ro["n"], {})
    if result.impact:  # Siegchance-Verlauf je Runde aus Sicht der Fokus-Seite (Linie im Replay)
        for ro in payload["rounds"]:
            rd = result.impact["rounds"].get(ro.get("n")) if not ro.get("pro") else None
            if rd and rd["line"] and ro.get("side"):
                ro["wp"] = [[t, p if p is None or ro["side"] == "ct" else round(100 - p, 1)] for t, p in rd["line"]]
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return {
        "match": match,
        "map_label": match.map_name.removeprefix("de_").capitalize() if match.map_name else "Unbekannte Map",
        "score": {"won": won, "lost": lost},
        "top": _top_issues(result),
        # Muster: "Gleicher Todesort" steht zusammengefasst je Spieler (spots), "Tod ohne Schaden" nicht: dieselbe Idee
        # zeigt die Mechanik als "Tode ohne Schuss" (eine Definition, einmal gezeigt)
        "patterns": [f for f in result.findings if f.round is None and f.severity != "gut"
                     and f.rule_id not in ("repeated_death_spot", "no_damage_death")],
        # abgeschaltete Regeln sind keine Datenlücke
        "unevaluated": [s for s in result.rule_status if not s.evaluated and s.reason != "deaktiviert"],
        "radar_note": radar_note,
        "debrief": debrief,
        "lessons": lessons,
        "point": point,
        "lessons_by": mine,
        "coach_line": coach_voice.headline(lessons) or debrief["sentence"],
        "font_css": __import__("cstaktik.fonts", fromlist=["font_css"]).font_css(),
        "intro": coach_voice.intro(won, lost, (match.map_name or "?").removeprefix("de_").capitalize(), point),
        "memory": memory,
        "focus": None,
        "duel_cmp": (dc := _duel_cmp(match)),
        "aim": _aim(match, dc),
        # Utility je Spieler (gleiche Werte wie im Verlauf und in der Match-Story): [(sid, flash, pre)]
        "util_by": [(sid, v.get("flash"), v.get("pre")) for sid, v in sorted(_util_by(match).items())],
        "spots": _spots(result),
        "death_phrase": coach_voice.DEATH_PHRASE,
        "deaths_by": {st.steamid: st.deaths for st in result.stats},
        "util_cmp": _util_cmp(match),
        "tactics": tac_now,
        "impact": imp,
        "glance": _glance(result, imp),
        "auftraege": auftraege,
        "checks": [a for a in auftraege if a.get("check")],
        "goal_cfg": load_rules_config()["goals"],
        "teach": TEACH,
        "bright": {lid: bright_spots(match, lid, _trade_units()) for lid in {l["id"] for l in point[:1]}},
        "praise": _with_sid(coach_voice.praise(result.findings) + coach_voice.strengths(
            _duel_now(match), {p.steamid: p.name for p in match.players}, past or []), match),
        "goal_check": goal_check,
        "mech_cfg": load_rules_config()["mechanics"],
        "n_findings": sum(1 for f in result.findings if f.severity != "gut"),
        "n_good": sum(1 for f in result.findings if f.severity == "gut"),
        "stats": result.stats,
        "homework": _homework(result),
        "data_json": data_json,
    }


def render_report(
    match: MatchData, result: AnalysisResult, maps_dirs: list[Path] | None = None, goal_check: dict | None = None,
    pro_clips: list[dict] | None = None, memory: dict | None = None, focus: dict | None = None,
    recur: tuple | None = None, past: list[dict] | None = None, leads: dict | None = None,
) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    from cstaktik import callouts

    callouts.register(env)
    env.globals["callouts_js"] = callouts.JS
    return env.get_template("report.html").render(**build_context(match, result, maps_dirs, goal_check, pro_clips,
                                                                  memory, focus, recur, past, leads))


def write_report(
    match: MatchData, result: AnalysisResult, out: Path, maps_dirs: list[Path] | None = None,
    goal_check: dict | None = None, pro_clips: list[dict] | None = None, memory: dict | None = None,
    focus: dict | None = None, recur: tuple | None = None, past: list[dict] | None = None,
    leads: dict | None = None,
) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report(match, result, maps_dirs, goal_check, pro_clips, memory, focus, recur, past, leads),
                   encoding="utf-8")
    return out
