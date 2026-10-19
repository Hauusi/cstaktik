"""Playbook: T-Taktiken aus Pro-Demos erkennen und zum Nachspielen aufbereiten.

Je T-Runde einer Pro-Demo (pro.plays) liegen vor: Laufwege aller T-Spieler (x/y alle ``PATH_STEP_S`` s),
Ankunft am Bombsite, Plant (Ort, Zeit), Ausrüstung der Teams. Daraus wird je Runde bestimmt:

- Kauf: Pistolenrunde (erste Runde je Halbzeit), Eco, Force oder Full Buy (Team-Ausrüstung, Schwellen in rules.yaml).
- Ziel: Bombsite des Plants, sonst der Bombsite, den die T zuerst erreicht haben.
- Tempo: Rush (Ankunft bis ``rush_s``), Execute (bis ``late_s``), spät (danach).
- Spät: Default nur, wenn die T sich über die Map verteilen. "Zusammen", wenn mindestens ``group_min`` von ihnen
  zwischen ``group_from`` und ``group_to`` s überwiegend als Gruppe laufen (jeder höchstens ``group_gap`` Units vom
  nächsten, also auch hintereinander auf demselben Weg). Beispiele: alle 5 Mitte, 4 gemeinsam über Palace.

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
            "nade_after_s": 5, "common_share": 0.5, "group_from": 16, "group_to": 46, "group_step": 6, "group_min": 4,
            "group_gap": 700}

STYLE_TEXT = {
    "rush": ("Rush", "Alle gehen schnell auf einen Bombsite, bevor die CT rotieren. Das lebt von Tempo und "
                     "Überzahl, nicht von Utility. Gut gegen passive CT und in Eco-Runden."),
    "split": ("Split", "Das Team greift einen Bombsite aus zwei Richtungen an. Die CT müssen zwei Winkel halten. "
                       "So brechen ihre Crossfires auf. Entscheidend ist das Timing. Beide Gruppen müssen "
                       "gleichzeitig reinkommen."),
    "execute": ("Execute", "Ein geplanter Angriff mit festem Granaten-Set. Smokes nehmen den CT die Sicht. "
                           "Flashes blenden beim Reinlaufen, Molotovs räumen Ecken. Dann gehen alle zusammen rein."),
    "default": ("Default", "Erst kontrolliert ihr die Map und sammelt Infos, verteilt auf mehrere Orte. Der Bombsite "
                           "wird spät gewählt, oft nach einem Pick oder einer Info."),
    "group": ("Zusammen", "Das Team spielt die erste Phase gemeinsam an einem Ort, meist um ihn zu übernehmen. Der "
                          "Bombsite wird erst danach gewählt. Anders als beim Default fehlen Infos aus den übrigen "
                          "Bereichen. Dafür seid ihr beim ersten Kontakt eher in Überzahl."),
    "eco": ("Eco-Push", "Mit wenig Geld gewinnt man selten ein faires Duell. Deshalb drückt ihr zusammen und schnell "
                        "auf einen Ort. Sucht Überzahl im ersten Kontakt und hebt die Waffen der Gegner auf."),
    "pistol": ("Pistolenrunde", "Die erste Runde der Halbzeit. Alle haben nur Pistolen, Utility ist knapp und wertvoll. "
                                "Spielt meist zusammen. Trades sind wichtiger als Einzelaktionen."),
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
        # kein Rückgriff auf awpys bomb_site: das setzt fest Entity 220 = A, sonst B, und liegt auf vielen Maps falsch
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
        eq = {sd: (sum(vals) if (vals := [e.equip_value for e in r.economy if e.side == sd
                                           and e.equip_value is not None]) else None) for sd in ("t", "ct")}
        # Orte je Spieler (alle PATH_STEP_S s): verteilt (Default) oder gemeinsamer Weg (Name der Gruppe)
        out.append({"r": r.num, "won": r.winner == "t", "site": site, "arrive": arrive, "plant_t": plant_t,
                    "places": places,
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
    buy = buy_of(p.get("t_eq"), p.get("pistol", False), c)
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
    together = grouped(p, c) if tempo == "default" else None
    if together is not None:
        style = "group"
    if buy == "pistol" and tempo != "default":
        style = "pistol"
    main = main_via(p.get("approach") or {}, style)
    # Eco und Pistole werden nur nach Bombsite gruppiert: Name ohne Weg, sonst trüge die Gruppe den Weg der ersten Runde
    via = " + ".join(main) if main and style not in ("eco", "pistol") else None
    if style == "default":
        name = f"Default, spät auf {site}" if site else "Default ohne Bombsite"
    elif style == "group":
        main = [together] if together else []
        name = (f"Zusammen {together}" if together else "Zusammen") + (f", spät auf {site}" if site else "")
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


def _clusters(pts: dict, gap: float) -> list[list[str]]:
    """Gruppen von Spielern, die aneinanderhängen: jeder höchstens ``gap`` Units vom nächsten entfernt.
    So zählen auch Spieler, die hintereinander denselben Weg laufen, als eine Gruppe."""
    ids = list(pts)
    root = {s: s for s in ids}

    def find(x):
        while root[x] != x:
            x = root[x]
        return x
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if ((pts[a][0] - pts[b][0]) ** 2 + (pts[a][1] - pts[b][1]) ** 2) ** .5 <= gap:
                root[find(a)] = find(b)
    out: dict = {}
    for s in ids:
        out.setdefault(find(s), []).append(s)
    return sorted(out.values(), key=len, reverse=True)


def grouped(p: dict, c: dict) -> str | None:
    """Spielen die T früh gemeinsam statt verteilt? Geprüft alle ``group_step`` s zwischen ``group_from`` und
    ``group_to``: Hängen mindestens ``group_min`` lebende T aneinander (Abstand je höchstens ``group_gap`` Units),
    in mindestens der Hälfte der Zeitpunkte, ist es kein Default. Rückgabe: häufigster Ort dieser Gruppe ("" ohne
    Ortsangabe), sonst None. An echten Pro-Runden geprüft: verteilte Defaults bleiben darunter."""
    need, paths, places = c["group_min"], p.get("paths") or {}, p.get("places") or {}
    hits, checks, where = 0, 0, []
    for sec in range(c["group_from"], c["group_to"] + 1, c["group_step"]):
        i = sec // PATH_STEP_S
        pts = {sid: v[i] for sid, v in paths.items() if i < len(v)}
        if len(pts) < need:
            continue
        checks += 1
        big = _clusters(pts, c["group_gap"])[0]
        if len(big) >= need:
            hits += 1
            where += [places[s][i] for s in big if s in places and i < len(places[s]) and places[s][i]]
    if not checks or hits * 2 < checks:
        return None
    top = Counter(where).most_common(1)
    return top[0][0] if top else ""


def group_key(p: dict, k: dict) -> tuple:
    """Gruppe einer T-Runde: Taktikart, Bombsite, Hauptzugänge (bei Split, Execute, Rush; bei Zusammen der Ort)."""
    return k["style"], p.get("site"), tuple(k["via"]) if k["style"] in ("split", "execute", "rush", "group") else ()


def key_id(key: tuple) -> str:
    style, site, via = key
    return f"{style}-{site or 'x'}-{'-'.join(via)}".replace(" ", "")


def tactic_id(p: dict, cfg: dict | None = None) -> str:
    """Id der Taktik, zu der diese Runde gehört (gleich wie im Playbook)."""
    return key_id(group_key(p, classify(p, {**DEFAULTS, **(cfg or {})})))


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
            if "r" not in p or "won" not in p:
                continue
            total += 1
            k = classify(p, c)
            key = group_key(p, k)
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
    no_site = sum(len(rows) for (style, site, _v), rows in groups.items() if site is None)
    for (style, site, via), rows in groups.items():
        if len(rows) < min_rounds or site is None:  # ohne Bombsite: alle T tot, bevor einer ankam; keine Taktik
            continue
        n = len(rows)
        # typische Granaten: gleiche Art auf denselben Landeort in mindestens common_share der Runden
        cnt = Counter((x["kind"], x["to"]) for r in rows for x in {(y["kind"], y["to"]): y for y in r["nades"]}.values()
                      if x.get("to"))
        common = [{"kind": k, "to": to, "n": m} for (k, to), m in cnt.most_common() if m / n >= c["common_share"]]
        # Beispielrunde: gewonnen, mit den meisten typischen Granaten und Wegen
        keys = {(x["kind"], x["to"]) for x in common}
        score = lambda r: (r["won"], sum((y["kind"], y["to"]) in keys for y in r["nades"]), len(r.get("paths") or {}))  # noqa: E731
        ex = max(rows, key=score)
        ordered = [ex] + sorted((r for r in rows if r is not ex), key=score, reverse=True)
        plants = [r["plant_t"] for r in rows if r.get("plant_t") is not None]
        arr = [r["arrive"] for r in rows if r.get("arrive") is not None]
        tactics.append({
            "id": key_id((style, site, via)), "style": style, "site": site,
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
    return {"map": map_name, "demos": len(demos), "rounds": total, "tactics": tactics, "no_site": no_site,
            "old_demos": sum(1 for d in pro if d.get("map") == map_name and not d.get("plays"))}


def style_mix(sources: list[dict], map_name: str, cfg: dict | None = None) -> dict:
    """Alle T-Runden einer Map nach Taktikart: Runden, Anteil, Siege (auch Arten, die nur einmal vorkamen)."""
    c = {**DEFAULTS, **(cfg or {})}
    # Runden ohne Bombsite (alle T tot, bevor einer ankam) sind ein Ergebnis, keine Taktik: nicht mitzählen
    rows = [classify(p, c) | {"won": p["won"]} for d in sources if d.get("map") == map_name
            for p in d.get("plays") or [] if p.get("site") and "won" in p]
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
    tail = (f" Davon gewinnt ihr {o['won_pct']} %, aus {o['n']} Runden." if o["n"] >= min_style else "")
    return (f"Ihr spielt {o['label']} deutlich {more} als Pros. Das sind {o['share']} % eurer T-Runden, "
            f"bei Pros {p['share']} %.{tail}")


# ---------------------------------------------------------------- CT-Seite: Aufstellungen

CT_SNAP_S = 20  # Aufstellung: wo die CT nach so vielen Sekunden stehen
CT_UTIL_S = 35  # frühe CT-Granaten bis hier
CT_DEFAULTS = {"zone_units": 1300}
STACKED_SITES = {"de_nuke"}  # Bombsites übereinander: Zonen nur aus x/y wären falsch, deshalb keine CT-Aufstellungen


def ct_plays(match: MatchData, team: set[str] | None = None) -> list[dict]:
    """Je CT-Runde: Position jedes CT nach CT_SNAP_S s (x, y, Ort), frühe CT-Granaten, Gewinner, Plant-Bombsite.
    ``team``: nur Runden, in denen einer dieser Spieler CT ist (eigene Matches)."""
    from cstaktik.pro import nades as round_nades
    from cstaktik.rules.base import PositionIndex

    idx = PositionIndex(match.positions)
    tr = match.tickrate
    plants = {b.round: b for b in match.bomb if b.event == "plant"}
    from cstaktik.pro import deaths as round_deaths

    ct_nades = [n for n in round_nades(match) if n["side"] == "ct" and n["t"] <= CT_UTIL_S] if match.grenades else []
    all_kills = round_deaths(match)
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
        # Runde immer behalten (Kauf, erster Kill, Retake zählen sonst ohne die schnell verlorenen Runden);
        # unter 3 lebenden CT mit Daten gibt es nur keine Aufstellung ("setup": False)
        plant = plants.get(r.num)
        site = _site_of(_place_near(idx, r.num, plant)) if plant else None
        vals = [e.equip_value for e in r.economy if e.side == "ct" and e.equip_value is not None]
        out.append({"r": r.num, "won": r.winner == "ct", "pos": pos, "setup": len(pos) >= 3, "plant_site": site,
                    "plant": [round(plant.pos.x), round(plant.pos.y)] if plant and plant.pos else None,
                    "plant_t": round((plant.tick - r.freeze_end_tick) / tr, 1) if plant else None,
                    "ct_eq": sum(vals) if vals else None, "pistol": r.num in (1, 13),
                    "kills": [{"t": x["t"], "side": x["side"], "place": x.get("place"), "sid": x.get("sid"),
                               "first": x.get("first")} for x in all_kills if x["r"] == r.num],
                    "nades": [n for n in ct_nades if n["r"] == r.num]})
    return out


def site_centers(sources: list[dict], map_name: str) -> dict[str, list[float]]:
    """Mitte jedes Bombsites aus den Plant-Positionen (T- und CT-Runden der Demos): Median x/y je Bombsite."""
    if map_name in STACKED_SITES:
        return {}
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
            if len(p.get("pos") or {}) < 3:
                continue
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

    t_pro = [t for t in build(pro, map_name, cfg)["tactics"] if t["site"]]  # ohne Bombsite: Ergebnis, keine Taktik
    t_own = [t for t in build(own, map_name, cfg)["tactics"] if t["site"]]
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


BUY_LABEL = {"eco": "Eco", "force": "Force Buy", "full": "Full Buy"}


def buy_of(eq: int | None, pistol: bool, cfg: dict | None = None) -> str | None:
    """Kauf aus der Ausrüstung der 5 Spieler einer Seite: pistol / eco / force / full (None = unbekannt)."""
    c = {**DEFAULTS, **(cfg or {})}
    if pistol:
        return "pistol"
    return None if eq is None else "eco" if eq <= c["eco_max"] else "force" if eq <= c["force_max"] else "full"


SIDE_KEYS = {"t": ("plays", "t_eq"), "ct": ("ct_plays", "ct_eq")}


def buy_mix(sources: list[dict], cfg: dict | None = None, side: str = "t") -> dict:
    """Runden einer Seite aller Maps nach Kauf (ohne Pistolenrunden): Anteil und Siegquote je Eco / Force / Full."""
    key, eq = SIDE_KEYS[side]
    rows = [(buy_of(p.get(eq), p.get("pistol", False), cfg), p["won"]) for d in sources for p in d.get(key) or []
            if "won" in p]
    rows = [r for r in rows if r[0] in BUY_LABEL]
    out = {}
    for b, lbl in BUY_LABEL.items():
        sel = [w for k, w in rows if k == b]
        if sel:
            out[b] = {"label": lbl, "n": len(sel), "share": round(100 * len(sel) / len(rows)),
                      "won": sum(sel), "won_pct": round(100 * sum(sel) / len(sel))}
    return {"total": len(rows), "buys": out}


def buy_reading(own: dict, pro: dict, min_n: int = 8, side: str = "t") -> str | None:
    """Ein Satz zum Kaufverhalten, nur bei klarem Abstand zu den Pros und genug Runden."""
    o, p = own["buys"].get("force"), pro["buys"].get("force")
    if o and p and o["n"] >= min_n and p["n"] >= min_n and p["won_pct"] - o["won_pct"] >= 15:
        return (f"Force-Buys auf {side.upper()} lohnen sich bei euch selten. Ihr gewinnt {o['won_pct']} %, "
                f"{o['won']} von {o['n']}. Pros: {p['won_pct']} %. Tipp: Spielt lieber eine volle Eco und kauft "
                "danach voll. Oder spielt den Force gemeinsam auf einen Ort.")
    o, p = own["buys"].get("eco"), pro["buys"].get("eco")
    if o and p and o["n"] >= min_n and o["share"] - p["share"] >= 15:
        return (f"Ihr spielt deutlich öfter Eco als Pros. Das sind {o['share']} % eurer {side.upper()}-Runden, bei Pros "
                f"{p['share']} %. Tipp: Teilt euer Geld besser ein. Dann könnt ihr öfter voll kaufen.")
    return None


POSTPLANT = (("up", "Überzahl"), ("even", "Gleichstand"), ("down", "Unterzahl"))


def postplant_mix(sources: list[dict], side: str = "t") -> dict:
    """Runden mit Plant (alle Maps) aus Sicht einer Seite: Spieler beim Plant (aus den Kills bis zum Plant, 5 gegen 5
    zu Beginn) und ob die Runde gewonnen wurde, je Überzahl / Gleichstand / Unterzahl. T = Bombe halten,
    CT = Retake. Nur Runden mit Kill-Daten."""
    key = SIDE_KEYS[side][0]
    rows = []
    for d in sources:
        for p in d.get(key) or []:
            if p.get("plant_t") is None or "kills" not in p or "won" not in p:
                continue
            dead = [k for k in p["kills"] if k["t"] <= p["plant_t"]]
            t = 5 - sum(k["side"] == "t" for k in dead)
            ct = 5 - sum(k["side"] == "ct" for k in dead)
            mine, theirs = (t, ct) if side == "t" else (ct, t)
            rows.append(("up" if mine > theirs else "even" if mine == theirs else "down", p["won"]))
    out = {}
    for key, lbl in POSTPLANT:
        sel = [w for k, w in rows if k == key]
        if sel:
            out[key] = {"label": lbl, "n": len(sel), "won": sum(sel), "won_pct": round(100 * sum(sel) / len(sel))}
    return {"total": len(rows), "rows": out}


def postplant_reading(own: dict, pro: dict, min_n: int = 6, side: str = "t") -> str | None:
    """Ein Satz, wenn ihr eine gelegte Bombe in einer Lage klar seltener nach Hause bringt als Pros."""
    worst = None
    for key, _lbl in POSTPLANT:
        o, p = own["rows"].get(key), pro["rows"].get(key)
        if o and p and o["n"] >= min_n and p["n"] >= min_n and p["won_pct"] - o["won_pct"] >= 15:
            if worst is None or p["won_pct"] - o["won_pct"] > worst[2]["won_pct"] - worst[1]["won_pct"]:
                worst = (key, o, p)
    if not worst:
        return None
    key, o, p = worst
    tip = {"t": {"up": "Peekt in Überzahl nicht mehr. Haltet die Bombe aus sicheren Winkeln, die CT müssen kommen.",
                 "even": "Verteilt euch nach dem Plant nicht einzeln. Baut ein Crossfire auf die Bombe und hebt "
                         "Utility für den Retake auf.",
                 "down": "Spielt in Unterzahl auf Zeit und bleibt versteckt. Werft Molotov oder Smoke auf die Bombe, "
                         "wenn sie defusen."},
           "ct": {"up": "Retaket in Überzahl gemeinsam. Wartet auf die anderen und geht zusammen mit Flash rein.",
                  "even": "Hebt Utility für den Retake auf. Kommt von zwei Seiten gleichzeitig.",
                  "down": "Sterbt in Unterzahl nicht einzeln. Reicht die Zeit nicht, rettet die Waffe."}}
    what = "Nach dem Plant" if side == "t" else "Im Retake"
    return (f"{what} in {o['label']} gewinnt ihr klar seltener als Pros. Bei euch sind es {o['won_pct']} %, "
            f"{o['won']} von {o['n']}. Pros: {p['won_pct']} %. Tipp: {tip[side][key]}")


FIRSTBLOOD = (("for", "Erster Kill für euch (5 gegen 4)"), ("against", "Erster Tod bei euch (4 gegen 5)"))


def firstblood_mix(sources: list[dict], side: str = "t") -> dict:
    """Runden einer Seite nach dem ersten Kill der Runde: wie oft gewonnen, wenn er für bzw. gegen euch fiel."""
    key = SIDE_KEYS[side][0]
    rows = []
    for d in sources:
        for p in d.get(key) or []:
            kills = [k for k in p.get("kills") or [] if k.get("t") is not None]
            if not kills or "won" not in p:
                continue
            first = min(kills, key=lambda k: k["t"])
            rows.append(("against" if first["side"] == side else "for", p["won"]))
    out = {}
    for k, lbl in FIRSTBLOOD:
        sel = [w for kk, w in rows if kk == k]
        if sel:
            out[k] = {"label": lbl, "n": len(sel), "won": sum(sel), "won_pct": round(100 * sum(sel) / len(sel))}
    return {"total": len(rows), "rows": out}


def firstblood_reading(own: dict, pro: dict, side: str = "t", min_n: int = 8) -> str | None:
    """Ein Satz, wenn ihr nach dem ersten Kill klar schlechter umsetzt als Pros (Vorteil verschenkt / nicht aufgeholt)."""
    tips = {"for": {"t": "Pusht nach dem ersten Kill nicht einzeln nach. Nutzt die Überzahl und geht gemeinsam mit "
                         "Utility auf einen Bombsite.",
                    "ct": "Jagt nach dem ersten Kill nicht hinterher. Haltet eure Positionen, die T müssen jetzt in "
                          "Unterzahl kommen."},
            "against": {"t": "Werdet nach dem ersten Tod langsamer. Sammelt euch neu und setzt Utility zusammen ein.",
                        "ct": "Rotiert nach dem ersten Tod früh und zieht zusammen. Haltet nicht allein weiter."}}
    best = None
    for k, _lbl in FIRSTBLOOD:
        o, p = own["rows"].get(k), pro["rows"].get(k)
        if o and p and o["n"] >= min_n and p["n"] >= min_n and p["won_pct"] - o["won_pct"] >= 15:
            if best is None or p["won_pct"] - o["won_pct"] > best[2]["won_pct"] - best[1]["won_pct"]:
                best = (k, o, p)
    if not best:
        return None
    k, o, p = best
    what = ("verschenkt ihr den Vorteil nach eurem ersten Kill öfter" if k == "for"
            else "holt ihr nach eurem ersten Tod seltener auf")
    return (f"Auf {side.upper()} {what} als Pros. Ihr gewinnt {o['won_pct']} % dieser Runden, "
            f"{o['won']} von {o['n']}. Pros: {p['won_pct']} %. Tipp: {tips[k][side]}")
