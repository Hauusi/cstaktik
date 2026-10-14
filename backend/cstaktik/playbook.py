"""Playbook: T-Taktiken aus Pro-Demos erkennen und zum Nachspielen aufbereiten.

Je T-Runde einer Pro-Demo (pro.plays) liegen vor: Laufwege aller T-Spieler (x/y alle ``PATH_STEP_S`` s),
Ankunft am Bombsite, Plant (Ort, Zeit), Ausrüstung der Teams. Daraus wird je Runde bestimmt:

- Kauf: Pistolenrunde (erste Runde je Halbzeit), Eco, Force oder Full Buy (Team-Ausrüstung, Schwellen in rules.yaml).
- Ziel: Bombsite des Plants, sonst der Bombsite, den die T zuerst erreicht haben.
- Tempo: Rush (Ankunft bis ``rush_s``), Execute (bis ``late_s``), Default/spät (danach).
- Split: Die T, die den Bombsite betreten, kommen aus mindestens zwei verschiedenen Orten.

Runden mit gleichem Ziel, Tempo und gleichen Zugängen bilden eine Taktik ("A-Split über Palace + Ramp").
Je Taktik: Runden, Siege, typische Granaten (Wurf- und Landeort aus der Demo) und eine Beispielrunde zum Zeichnen.
Die Erklärtexte je Taktikart sind allgemeines CS-Wissen; alle Orte, Wege, Zeiten und Granaten stammen aus den Demos.
"""

from __future__ import annotations

import statistics
from collections import Counter

from cstaktik.model import MatchData

PATH_STEP_S = 2
PATH_MAX_S = 115

DEFAULTS = {"eco_max": 6000, "force_max": 18000, "rush_s": 25, "late_s": 55, "nade_before_s": 20,
            "nade_after_s": 5, "common_share": 0.5}

STYLE_TEXT = {
    "rush": ("Rush", "Alle schnell auf einen Bombsite, bevor die CT rotieren können. Funktioniert über Tempo und "
                     "Überzahl am Ort, nicht über Utility. Gut gegen passive CT und in Eco-Runden."),
    "split": ("Split", "Das Team greift einen Bombsite aus zwei Richtungen gleichzeitig an. Die CT am Ort müssen "
                       "zwei Winkel halten, Crossfires brechen auf. Entscheidend ist das Timing: Beide Gruppen "
                       "müssen zur selben Zeit reinkommen."),
    "execute": ("Execute", "Geplanter Angriff mit festem Granaten-Set: Smokes nehmen die Sichtlinien der CT weg, "
                           "Flashes blenden beim Reinlaufen, Molotovs räumen Ecken. Dann alle zusammen rein."),
    "default": ("Default", "Erst die Map kontrollieren und Infos sammeln, verteilt auf mehrere Orte. Die Entscheidung "
                           "für einen Bombsite fällt spät, oft nach einem Pick oder einer Info."),
    "eco": ("Eco-Push", "Mit wenig Geld gewinnt man selten ein faires Duell. Deshalb zusammen und schnell auf einen "
                        "Ort drücken, Überzahl im ersten Kontakt suchen und Waffen der Gegner aufheben."),
    "pistol": ("Pistolenrunde", "Erste Runde der Halbzeit: alle mit Pistole, Utility ist knapp und wertvoll. "
                                "Meist zusammen spielen, Trades sind wichtiger als Einzelaktionen."),
}


def _site_of(place: str | None) -> str | None:
    if place and place.startswith("Bombsite"):
        return place.removeprefix("Bombsite")[:1].upper() or None
    return None


def plays(match: MatchData, team: set[str] | None = None) -> list[dict]:
    """Je T-Runde: Laufwege der T, Ankunft am Bombsite, Zugänge, Plant, Ausrüstung, T-Granaten und Kills.
    ``team``: nur Runden, in denen einer dieser Spieler T ist (eigene Matches); None = alle (Pro-Demos)."""
    from cstaktik.pro import deaths as round_deaths
    from cstaktik.pro import nades as round_nades
    from cstaktik.rules.base import PositionIndex

    all_nades = [n for n in round_nades(match) if n["side"] == "t"] if match.grenades else []
    all_kills = round_deaths(match)

    idx = PositionIndex(match.positions)
    tr = match.tickrate
    plants = {b.round: b for b in match.bomb if b.event == "plant"}
    halves = {1, 13}  # Pistolenrunden (MR12); Overtime startet mit Geld, keine Pistolenrunde
    out = []
    for r in match.rounds:
        if r.freeze_end_tick is None or r.winner is None:
            continue
        ts = sorted(s for s, sd in r.sides.items() if sd == "t")
        if not ts or (team is not None and not team & set(ts)):
            continue
        plant = plants.get(r.num)
        plant_t = round((plant.tick - r.freeze_end_tick) / tr, 1) if plant else None
        stop = min(r.end_tick, r.freeze_end_tick + PATH_MAX_S * tr)
        if plant:
            stop = min(stop, plant.tick + 3 * tr)
        paths, places = {}, {}
        for sid in ts:
            pts, pls = [], []
            for s in range(0, PATH_MAX_S + 1, PATH_STEP_S):
                tick = r.freeze_end_tick + s * tr
                if tick > stop:
                    break
                p = idx.nearest(r.num, sid, tick, tr)
                if p is None or not p.alive:
                    break
                pts.append([round(p.pos.x), round(p.pos.y)])
                pls.append(p.place)
            if pts:
                paths[sid], places[sid] = pts, pls
        # Ziel: Plant-Ort, sonst erster erreichter Bombsite
        site = _site_of(_place_near(idx, r.num, plant)) if plant else None
        site = site or _site_of((r.bomb_site or "").replace("bombsite_", "Bombsite").replace("_", ""))
        first = None
        for i in range(max((len(v) for v in places.values()), default=0)):
            hits = [_site_of(v[i]) for v in places.values() if i < len(v) and _site_of(v[i])]
            if hits and (site is None or site in hits):
                first = (i, site or hits[0])
                break
        if first and site is None:
            site = first[1]
        arrive = first[0] * PATH_STEP_S if first else None
        # Zugang je Spieler: letzter Ort vor dem Betreten des Ziel-Bombsites
        approach = {}
        for sid, pls in places.items():
            for i, pl in enumerate(pls):
                if _site_of(pl) == site and site:
                    prev = next((q for q in reversed(pls[:i]) if q and not _site_of(q)), None)
                    if prev and (arrive is None or i * PATH_STEP_S <= arrive + 12):
                        approach[sid] = prev
                    break
        eq = {sd: sum(e.equip_value or 0 for e in r.economy if e.side == sd) for sd in ("t", "ct")} if r.economy else {}
        out.append({"r": r.num, "won": r.winner == "t", "site": site, "arrive": arrive, "plant_t": plant_t,
                    "plant": [round(plant.pos.x), round(plant.pos.y)] if plant and plant.pos else None,
                    "approach": approach, "paths": paths, "t_eq": eq.get("t"), "ct_eq": eq.get("ct"),
                    "pistol": r.num in halves,
                    "nades": [n for n in all_nades if n["r"] == r.num],
                    "kills": [{"t": x["t"], "side": x["side"], "place": x.get("place"), "sid": x.get("sid"),
                               "first": x.get("first")} for x in all_kills if x["r"] == r.num]})
    return out


def _place_near(idx, rnd: int, plant) -> str | None:
    p = idx.nearest(rnd, plant.steamid, plant.tick, 64) if plant.steamid else None
    return p.place if p is not None else None


def classify(p: dict, cfg: dict) -> dict:
    """Kauf, Tempo, Split und Name einer T-Runde."""
    c = {**DEFAULTS, **(cfg or {})}
    eq = p.get("t_eq")
    buy = ("pistol" if p.get("pistol") else None) or (None if eq is None else "eco" if eq <= c["eco_max"]
                                                         else "force" if eq <= c["force_max"] else "full")
    arrive, site = p.get("arrive"), p.get("site")
    groups = sorted(set((p.get("approach") or {}).values()))
    if site is None or arrive is None:
        tempo = "default"
    elif arrive <= c["rush_s"]:
        tempo = "rush"
    elif arrive <= c["late_s"]:
        tempo = "execute"
    else:
        tempo = "default"
    split = site is not None and len(groups) >= 2 and len(p.get("approach") or {}) >= 3
    style = ("eco" if buy == "eco" and tempo != "default" else "split" if split and tempo != "default"
             else tempo)
    if buy == "pistol" and tempo != "default":
        style = "pistol"
    main = main_via(p.get("approach") or {}, style)
    via = " + ".join(main) if main else None
    if style == "default":
        name = f"Default, spät auf {site}" if site else "Default ohne Bombsite"
    else:
        name = f"{site}-{STYLE_TEXT[style][0]}" + (f" über {via}" if via else "")
    return {"buy": buy, "tempo": tempo, "style": style, "via": main, "via_all": groups, "name": name}


def main_via(approach: dict, style: str) -> list[str]:
    """Hauptzugänge, nach denen Runden gruppiert werden: Ein einzelner Spieler auf einem Nebenweg macht keine
    neue Taktik. Split: alle Orte mit mindestens 2 Spielern, aufgefüllt auf 2 Orte (meiste Spieler zuerst).
    Sonst: der Ort mit den meisten Spielern."""
    cnt = Counter(approach.values())
    order = sorted(cnt, key=lambda pl: (-cnt[pl], pl))
    if style == "split":
        main = [pl for pl in order if cnt[pl] >= 2]
        main += [pl for pl in order if pl not in main][:max(0, 2 - len(main))]
        return sorted(main)
    return order[:1]


KIND_DE = {"smoke": "Smoke", "flash": "Flash", "molotov": "Molotov", "he": "HE"}


def events(ex: dict) -> list[dict]:
    """Schlüsselmomente einer Beispielrunde für die Wiedergabe: Granaten, Ankunft, Kills, Plant (Rundenzeit s).
    Momente bis 1,5 s Abstand werden zusammengefasst, damit die Wiedergabe nicht ständig stockt."""
    raw = []
    for i, n in enumerate(ex.get("nades", [])):
        src = f" von {n['from']}" if n.get("from") else ""
        raw.append({"t": n["t"], "text": f"{KIND_DE.get(n['kind'], n['kind'])}{src} auf {n.get('to') or '?'}",
                    "nade": i, "kind": "nade"})
    if ex.get("arrive") is not None and ex.get("site"):
        raw.append({"t": ex["arrive"], "text": f"Erste T am Bombsite {ex['site']}", "kind": "arrive"})
    for x in ex.get("deaths", []):
        who = "T" if x["side"] == "t" else "CT"
        raw.append({"t": x["t"], "text": f"{who} fällt{' in ' + x['place'] if x.get('place') else ''}"
                                         f"{' (Opening)' if x.get('first') else ''}",
                    "kind": "death", "side": x["side"], "sid": x.get("sid")})
    if ex.get("plant_t") is not None:
        raw.append({"t": ex["plant_t"], "text": "Bombe liegt", "kind": "plant"})
    raw.sort(key=lambda e: e["t"])
    out: list[dict] = []
    for e in raw:
        if out and e["t"] - out[-1]["t"] <= 1.5:
            out[-1]["items"].append(e)
        else:
            out.append({"t": e["t"], "items": [e]})
    return out


def build(pro: list[dict], map_name: str, cfg: dict | None = None, min_rounds: int = 2) -> dict:
    """Taktiken einer Map aus allen Pro-Demos: gruppiert, mit Granaten-Set und Beispielrunde."""
    c = {**DEFAULTS, **(cfg or {})}
    demos = [d for d in pro if d.get("map") == map_name and d.get("plays")]
    groups: dict[tuple, list] = {}
    total = 0
    for d in demos:
        demo_nades = [n for n in d.get("nades", []) if n.get("side") == "t"]
        deaths = d.get("deaths", [])
        for p in d["plays"]:
            total += 1
            k = classify(p, c)
            key = (k["style"], p.get("site"), tuple(k["via"]) if k["style"] in ("split", "execute", "rush") else ())
            mine = []
            nades = p["nades"] if "nades" in p else [n for n in demo_nades if n["r"] == p["r"]]
            if p.get("arrive") is not None:
                lo, hi = p["arrive"] - c["nade_before_s"], p["arrive"] + c["nade_after_s"]
                mine = [n for n in nades if lo <= n["t"] <= hi and n["kind"] != "he"]
            stop = (p.get("plant_t") or ((p.get("arrive") or 60) + 15)) + 3
            src = p["kills"] if "kills" in p else [x for x in deaths if x.get("r") == p["r"]]
            kills = [{"t": x["t"], "side": x["side"], "place": x.get("place"), "sid": x.get("sid"), "first": x.get("first")}
                     for x in src if x.get("t") is not None and x["t"] <= stop]
            groups.setdefault(key, []).append({**p, **k, "nades": mine, "deaths": kills, "demo": d.get("source_file")})
    tactics = []
    for (style, site, via), rows in groups.items():
        if len(rows) < min_rounds:
            continue
        n = len(rows)
        # typische Granaten: gleiche Art auf denselben Landeort in mindestens common_share der Runden
        cnt = Counter((x["kind"], x["to"]) for r in rows for x in {(y["kind"], y["to"]): y for y in r["nades"]}.values()
                      if x.get("to"))
        common = [{"kind": k, "to": to, "n": m} for (k, to), m in cnt.most_common() if m / n >= c["common_share"]]
        # Beispielrunde: gewonnen, mit den meisten typischen Granaten und Wegen
        keys = {(x["kind"], x["to"]) for x in common}
        score = lambda r: (r["won"], sum((y["kind"], y["to"]) in keys for y in r["nades"]), len(r["paths"]))  # noqa: E731
        ex = max(rows, key=score)
        ordered = [ex] + sorted((r for r in rows if r is not ex), key=score, reverse=True)
        plants = [r["plant_t"] for r in rows if r.get("plant_t") is not None]
        arr = [r["arrive"] for r in rows if r.get("arrive") is not None]
        tactics.append({
            "id": f"{style}-{site or 'x'}-{'-'.join(via)}".replace(" ", ""), "style": style, "site": site,
            "name": rows[0]["name"], "style_label": STYLE_TEXT[style][0], "explain": STYLE_TEXT[style][1],
            "via": list(via), "n": n, "won": sum(r["won"] for r in rows),
            "won_pct": round(100 * sum(r["won"] for r in rows) / n),
            "buys": dict(Counter(r["buy"] for r in rows if r["buy"])),
            "arrive": round(statistics.median(arr)) if arr else None,
            "plant_t": round(statistics.median(plants)) if plants else None, "plants": len(plants),
            "common": common, "example": ex, "rounds": ordered, "share": None,
        })
    for t in tactics:
        t["share"] = round(100 * t["n"] / total) if total else None
    tactics.sort(key=lambda t: (-t["n"], -t["won_pct"]))
    return {"map": map_name, "demos": len(demos), "rounds": total, "tactics": tactics,
            "old_demos": sum(1 for d in pro if d.get("map") == map_name and not d.get("plays"))}


def style_mix(sources: list[dict], map_name: str, cfg: dict | None = None) -> dict:
    """Alle T-Runden einer Map nach Taktikart: Runden, Anteil, Siege (auch Arten, die nur einmal vorkamen)."""
    c = {**DEFAULTS, **(cfg or {})}
    rows = [classify(p, c) | {"won": p["won"]} for d in sources if d.get("map") == map_name for p in d.get("plays") or []]
    out = {}
    for st in STYLE_TEXT:
        sel = [r for r in rows if r["style"] == st]
        if sel:
            out[st] = {"label": STYLE_TEXT[st][0], "n": len(sel), "share": round(100 * len(sel) / len(rows)),
                       "won": sum(r["won"] for r in sel), "won_pct": round(100 * sum(r["won"] for r in sel) / len(sel))}
    return {"total": len(rows), "styles": out}


def compare(own: dict, pro: dict, min_rounds: int = 10, min_style: int = 4) -> str | None:
    """Ein Satz: größter Unterschied zwischen eurer und der Pro-Taktikverteilung (Anteile in Prozentpunkten)."""
    if own["total"] < min_rounds or pro["total"] < min_rounds:
        return None
    best = None
    for st, o in own["styles"].items():
        p = pro["styles"].get(st, {"share": 0, "n": 0})
        diff = o["share"] - p["share"]
        if abs(diff) >= 15 and (best is None or abs(diff) > abs(best[1])):
            best = (st, diff, o, p)
    if not best:
        return None
    st, diff, o, p = best
    more = "öfter" if diff > 0 else "seltener"
    tail = (f" Eure {o['label']}-Runden: {o['won_pct']} % gewonnen ({o['n']} Runden)." if o["n"] >= min_style else "")
    return f"Ihr spielt {o['label']} deutlich {more} als Pros: {o['share']} % eurer T-Runden, Pros {p['share']} %.{tail}"


# ---------------------------------------------------------------- CT-Seite: Aufstellungen

CT_SNAP_S = 20  # Aufstellung: wo die CT nach so vielen Sekunden stehen
CT_UTIL_S = 35  # frühe CT-Granaten bis hier
CT_DEFAULTS = {"zone_units": 1300}


def ct_plays(match: MatchData, team: set[str] | None = None) -> list[dict]:
    """Je CT-Runde: Position jedes CT nach CT_SNAP_S s (x, y, Ort), frühe CT-Granaten, Gewinner, Plant-Bombsite.
    ``team``: nur Runden, in denen einer dieser Spieler CT ist (eigene Matches)."""
    from cstaktik.pro import nades as round_nades
    from cstaktik.rules.base import PositionIndex

    idx = PositionIndex(match.positions)
    tr = match.tickrate
    plants = {b.round: b for b in match.bomb if b.event == "plant"}
    ct_nades = [n for n in round_nades(match) if n["side"] == "ct" and n["t"] <= CT_UTIL_S] if match.grenades else []
    out = []
    for r in match.rounds:
        if r.freeze_end_tick is None or r.winner is None:
            continue
        cts = sorted(s for s, sd in r.sides.items() if sd == "ct")
        if not cts or (team is not None and not team & set(cts)):
            continue
        tick = r.freeze_end_tick + CT_SNAP_S * tr
        pos = {}
        for sid in cts:
            p = idx.nearest(r.num, sid, tick, tr)
            if p is not None and p.alive:
                pos[sid] = [round(p.pos.x), round(p.pos.y), p.place]
        if len(pos) < 3:  # zu viele schon tot oder ohne Daten: keine Aufstellung
            continue
        plant = plants.get(r.num)
        site = _site_of(_place_near(idx, r.num, plant)) if plant else None
        out.append({"r": r.num, "won": r.winner == "ct", "pos": pos, "plant_site": site,
                    "plant": [round(plant.pos.x), round(plant.pos.y)] if plant and plant.pos else None,
                    "nades": [n for n in ct_nades if n["r"] == r.num]})
    return out


def site_centers(sources: list[dict], map_name: str) -> dict[str, list[float]]:
    """Mitte jedes Bombsites aus den Plant-Positionen (T- und CT-Runden der Demos): Median x/y je Bombsite."""
    pts: dict[str, list] = {}
    for d in sources:
        if d.get("map") != map_name:
            continue
        for p in d.get("plays") or []:
            if p.get("site") and p.get("plant"):
                pts.setdefault(p["site"], []).append(p["plant"])
        for p in d.get("ct_plays") or []:
            if p.get("plant_site") and p.get("plant"):
                pts.setdefault(p["plant_site"], []).append(p["plant"])
    return {s: [statistics.median(q[0] for q in v), statistics.median(q[1] for q in v)]
            for s, v in pts.items() if len(v) >= 2}


def zone(x: float, y: float, centers: dict, units: float) -> str:
    """A/B, wenn die Position höchstens ``units`` von der Bombsite-Mitte entfernt ist, sonst M (Mitte/Rotation)."""
    best = min(((((x - c[0]) ** 2 + (y - c[1]) ** 2) ** .5, s) for s, c in centers.items()), default=None)
    return best[1] if best and best[0] <= units else "M"


def ct_build(sources: list[dict], map_name: str, centers: dict, cfg: dict | None = None, min_rounds: int = 2) -> dict:
    """CT-Aufstellungen einer Map: Anzahl Spieler je Zone (A, Mitte, B) nach CT_SNAP_S s, gruppiert."""
    c = {**CT_DEFAULTS, **(cfg or {})}
    groups: dict[str, list] = {}
    total = 0
    if len(centers) < 2:
        return {"map": map_name, "rounds": 0, "setups": [], "centers": centers}
    for d in sources:
        if d.get("map") != map_name:
            continue
        for p in d.get("ct_plays") or []:
            total += 1
            zones = {sid: zone(v[0], v[1], centers, c["zone_units"]) for sid, v in p["pos"].items()}
            cnt = Counter(zones.values())
            key = f"{cnt.get('A', 0)}-{cnt.get('M', 0)}-{cnt.get('B', 0)}"
            groups.setdefault(key, []).append({**p, "zones": zones, "demo": d.get("source_file")})
    setups = []
    for key, rows in groups.items():
        if len(rows) < min_rounds:
            continue
        a, m, b = (int(v) for v in key.split("-"))
        n = len(rows)
        stack = "A" if a >= 4 else "B" if b >= 4 else None
        name = f"Stack auf {stack}" if stack else f"{a}-{m}-{b}"
        rows.sort(key=lambda r: (not r["won"], -len(r["nades"])))
        util = Counter((x["kind"], x.get("to")) for r in rows for x in {(y["kind"], y.get("to")): y for y in r["nades"]}.values()
                       if x.get("to") and x["kind"] != "he")
        setups.append({
            "id": f"ct-{key}", "key": key, "name": name, "a": a, "m": m, "b": b, "stack": stack, "n": n,
            "won": sum(r["won"] for r in rows), "won_pct": round(100 * sum(r["won"] for r in rows) / n),
            "share": round(100 * n / total) if total else None,
            "t_went": dict(Counter(r["plant_site"] for r in rows if r.get("plant_site"))),
            "util": [{"kind": k, "to": to, "n": cnt_} for (k, to), cnt_ in util.most_common() if cnt_ / n >= .5],
            "rounds": rows,
        })
    setups.sort(key=lambda s: (-s["n"], -s["won_pct"]))
    return {"map": map_name, "rounds": total, "setups": setups, "centers": centers}


def gameplan(pro: list[dict], own: list[dict], map_name: str, cfg: dict | None = None, min_n: int = 3) -> dict | None:
    """Matchplan für die Kabine: beste Pro-Taktik (T) und -Aufstellung (CT) auf dieser Map, was bei euch klappt,
    was nicht. Nur Einträge mit mindestens ``min_n`` Runden; fehlt alles, None."""
    def best(rows, key="won_pct"):
        rows = [r for r in rows if r["n"] >= min_n]
        return max(rows, key=lambda r: (r[key], r["n"])) if rows else None

    t_pro, t_own = build(pro, map_name, cfg)["tactics"], build(own, map_name, cfg)["tactics"]
    centers = site_centers(pro + own, map_name)
    ct_pro, ct_own = ct_build(pro, map_name, centers, cfg)["setups"], ct_build(own, map_name, centers, cfg)["setups"]
    mix_own, mix_pro = style_mix(own, map_name, cfg), style_mix(pro, map_name, cfg)
    weak = [{"label": v["label"], **v} for v in mix_own["styles"].values() if v["n"] >= min_n + 1 and v["won_pct"] <= 35]
    ct_weak = [s for s in ct_own if s["n"] >= min_n + 1 and s["won_pct"] <= 35]
    own_good = best(t_own)

    def pick(rows):
        """Empfehlung nur ab 50 % Siegquote; sonst die häufigste Variante, als solche gekennzeichnet."""
        b = best(rows)
        if b and b["won_pct"] >= 50:
            return {**b, "why": "best"}
        often = [r for r in rows if r["n"] >= min_n]
        return {**max(often, key=lambda r: r["n"]), "why": "often"} if often else None

    plan = {
        "t_pro": pick(t_pro), "t_own": own_good if own_good and own_good["won_pct"] >= 50 else None,
        "t_weak": min(weak, key=lambda v: v["won_pct"]) if weak else None,
        "ct_pro": pick(ct_pro), "ct_weak": min(ct_weak, key=lambda s: s["won_pct"]) if ct_weak else None,
        "compare": compare(mix_own, mix_pro),
    }
    return plan if any(plan.values()) else None
