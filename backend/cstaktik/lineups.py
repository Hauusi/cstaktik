"""Lineup-Trainer: wiederholte Granaten-Würfe aus Pro-Demos.

Ein Lineup ist ein Wurf, den Pros mehrfach gleich gemacht haben: gleiche Wurfstelle (Werfer-Position im Tick vor
dem Abwurf), gleicher Blick (yaw/pitch) und gleiche Landestelle. Alles aus den Demos (pro.nades, Feld "p").

Was die Demo nicht verrät: linke oder rechte Maustaste (Wurfstärke). Sprung und Bewegung werden aus dem Tempo
gemessen, Ducken nur, wenn die Demo es liefert. Unbekanntes wird als unbekannt angezeigt.

Zum Üben: ``setpos``/``setang`` auf einem eigenen Server mit sv_cheats 1 setzen dich genau an die Stelle des Pros.
"""

from __future__ import annotations

import math
import statistics

from cstaktik import callouts

KIND_DE = {"smoke": "Smoke", "flash": "Flash", "molotov": "Molotov", "he": "HE"}
POS_UNITS = 48  # Wurfstelle gleich
ANGLE_DEG = 3.0  # Blick gleich
LAND_UNITS = 160  # Landestelle gleich
AIR_UNITS_S = 120  # senkrechtes Tempo darüber: in der Luft (Sprungwurf)
MOVE_UNITS_S = 40  # waagrechtes Tempo darüber: in Bewegung


def _ang(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def _same(a: dict, b: dict) -> bool:
    pa, pb = a["p"], b["p"]
    return (math.hypot(pa[0] - pb[0], pa[1] - pb[1]) <= POS_UNITS and abs(pa[2] - pb[2]) <= 40
            and _ang(pa[3], pb[3]) <= ANGLE_DEG and abs(pa[4] - pb[4]) <= ANGLE_DEG
            and math.hypot(a["tx"] - b["tx"], a["ty"] - b["ty"]) <= LAND_UNITS)


def technique(rows: list[dict]) -> dict:
    """Mehrheit der Würfe: in der Luft, in Bewegung, geduckt (None = nicht messbar)."""
    def vote(vals):
        vals = [v for v in vals if v is not None]
        return None if not vals else sum(vals) * 2 > len(vals)

    air = vote([None if r["p"][6] is None else abs(r["p"][6]) > AIR_UNITS_S for r in rows])
    move = vote([None if r["p"][5] is None else r["p"][5] > MOVE_UNITS_S for r in rows])
    duck = vote([None if len(r["p"]) < 8 or r["p"][7] is None else r["p"][7] > .5 for r in rows])
    if air:
        label = "Sprungwurf"
    elif move:
        label = "im Laufen"
    elif move is False:
        label = "im Stehen"
    else:
        label = "Wurfart unbekannt"
    if duck:
        label += ", geduckt"
    speeds = [r["p"][5] for r in rows if r["p"][5] is not None]
    return {"air": air, "move": move, "duck": duck, "label": label,
            "speed": round(statistics.median(speeds)) if speeds else None}


def build(pro: list[dict], map_name: str, min_n: int = 2) -> list[dict]:
    """Lineups einer Map, häufigste zuerst."""
    rows = []
    for d in pro:
        if d.get("map") != map_name:
            continue
        for g in d.get("nades", []):
            if g.get("p") and g.get("tx") is not None and g["kind"] in KIND_DE:
                rows.append({**g, "demo": d.get("id")})
    clusters: list[list[dict]] = []
    for g in rows:
        for c in clusters:
            if c[0]["kind"] == g["kind"] and c[0]["side"] == g["side"] and _same(c[0], g):
                c.append(g)
                break
        else:
            clusters.append([g])
    out = []
    for c in clusters:
        if len(c) < min_n:
            continue
        # Stellvertreter: der Wurf mit der kleinsten Summe der Abstände zu den anderen (Medoid)
        rep = min(c, key=lambda a: sum(math.hypot(a["p"][0] - b["p"][0], a["p"][1] - b["p"][1])
                                       + math.hypot(a["tx"] - b["tx"], a["ty"] - b["ty"]) for b in c))
        x, y, z, yaw, pitch = rep["p"][:5]
        spread = max(math.hypot(g["tx"] - rep["tx"], g["ty"] - rep["ty"]) for g in c)
        lid = f"{rep['kind']}-{rep['side']}-{round(x)}-{round(y)}-{round(rep['tx'])}-{round(rep['ty'])}"
        out.append({
            "id": lid, "kind": rep["kind"], "kind_de": KIND_DE[rep["kind"]], "side": rep["side"],
            "from": rep.get("from"), "to": rep.get("to"), "n": len(c), "demos": len({g["demo"] for g in c}),
            "won": round(100 * sum(bool(g.get("won")) for g in c) / len(c)),
            "t": round(statistics.median(g["t"] for g in c)),
            "clock": callouts.clock(round(statistics.median(g["t"] for g in c))),
            "from_c": callouts.place(rep.get("from")) or "?", "to_c": callouts.place(rep.get("to")) or "?",
            "x": x, "y": y, "z": z, "yaw": yaw, "pitch": pitch, "tx": rep["tx"], "ty": rep["ty"],
            "spread": round(spread), "tech": technique(c),
            "cmd": f"setpos {x:.2f} {y:.2f} {z:.2f};setang {pitch:.2f} {yaw:.2f} 0",
        })
    out.sort(key=lambda l: (-l["n"], -l["demos"]))
    return out


def dedupe(items: list[dict]) -> list[dict]:
    """Gleicher Wurf (Seite, Art, Wurfort, Landeort) aus leicht anderer Stelle: nur der häufigste bleibt.
    Er bekommt die Ids der übrigen (``alt_ids``, für Links von anderen Seiten) und ihre Würfe (``alt_n``)."""
    out: dict[tuple, dict] = {}
    for x in sorted(items, key=lambda l: (-l["n"], -l["demos"])):
        k = (x["side"], x["kind"], x.get("from"), x.get("to"))
        if k in out:
            out[k]["alt_ids"].append(x["id"])
            out[k]["alt_n"] += x["n"]
        else:
            out[k] = {**x, "alt_ids": [], "alt_n": 0}
    return list(out.values())


def organize(items: list[dict], core_n: int = 5) -> list[dict]:
    """Lineup-Seite je Seite (T zuerst): die ``core_n`` meistgeworfenen als Kern, der Rest nach Landeort gruppiert."""
    out = []
    for side in ("t", "ct"):
        sel = [x for x in dedupe(items) if x["side"] == side]
        if not sel:
            continue
        core, rest = sel[:core_n], sel[core_n:]
        groups: dict[str, list] = {}
        for x in rest:
            groups.setdefault(x["to_c"], []).append(x)
        out.append({"side": side, "label": side.upper(), "core": core, "n": len(sel),
                    "groups": [{"to": to, "rows": g, "n": sum(x["n"] for x in g)}
                               for to, g in sorted(groups.items(), key=lambda kv: -sum(x["n"] for x in kv[1]))]})
    return out


def clock(s: float) -> str:
    s = max(0, int(s))
    return f"{s // 60}:{s % 60:02d}"
