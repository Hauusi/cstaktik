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


def plays(match: MatchData) -> list[dict]:
    """Je T-Runde: Laufwege der T, Ankunft am Bombsite, Zugänge, Plant, Ausrüstung. Für pro.summarize."""
    from cstaktik.rules.base import PositionIndex

    idx = PositionIndex(match.positions)
    tr = match.tickrate
    plants = {b.round: b for b in match.bomb if b.event == "plant"}
    halves = {1, 13}  # Pistolenrunden (MR12); Overtime startet mit Geld, keine Pistolenrunde
    out = []
    for r in match.rounds:
        if r.freeze_end_tick is None or r.winner is None:
            continue
        ts = sorted(s for s, sd in r.sides.items() if sd == "t")
        if not ts:
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
                    "pistol": r.num in halves})
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
    via = " + ".join(groups) if groups else None
    if style == "default":
        name = f"Default, spät auf {site}" if site else "Default ohne Bombsite"
    else:
        name = f"{site}-{STYLE_TEXT[style][0]}" + (f" über {via}" if via else "")
    return {"buy": buy, "tempo": tempo, "style": style, "via": groups, "name": name}


def build(pro: list[dict], map_name: str, cfg: dict | None = None, min_rounds: int = 2) -> dict:
    """Taktiken einer Map aus allen Pro-Demos: gruppiert, mit Granaten-Set und Beispielrunde."""
    c = {**DEFAULTS, **(cfg or {})}
    demos = [d for d in pro if d.get("map") == map_name and d.get("plays")]
    groups: dict[tuple, list] = {}
    total = 0
    for d in demos:
        nades = [n for n in d.get("nades", []) if n.get("side") == "t"]
        for p in d["plays"]:
            total += 1
            k = classify(p, c)
            key = (k["style"], p.get("site"), tuple(k["via"]) if k["style"] in ("split", "execute", "rush") else ())
            mine = []
            if p.get("arrive") is not None:
                lo, hi = p["arrive"] - c["nade_before_s"], p["arrive"] + c["nade_after_s"]
                mine = [n for n in nades if n["r"] == p["r"] and lo <= n["t"] <= hi and n["kind"] != "he"]
            groups.setdefault(key, []).append({**p, **k, "nades": mine, "demo": d.get("source_file")})
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
        ex = max(rows, key=lambda r: (r["won"], sum((y["kind"], y["to"]) in keys for y in r["nades"]),
                                      len(r["paths"])))
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
            "common": common, "example": ex, "share": None,
        })
    for t in tactics:
        t["share"] = round(100 * t["n"] / total) if total else None
    tactics.sort(key=lambda t: (-t["n"], -t["won_pct"]))
    return {"map": map_name, "demos": len(demos), "rounds": total, "tactics": tactics,
            "old_demos": sum(1 for d in pro if d.get("map") == map_name and not d.get("plays"))}
