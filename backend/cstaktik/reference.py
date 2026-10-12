"""Eigene Siegrunden als Vorbild ("Was stattdessen").

Für jeden Tod eines Fokus-Spielers (Tod-Analyse): Wo stand derselbe Spieler auf derselben Seite
zur selben Rundenzeit in GEWONNENEN Runden? Quelle: dieses Match (Positionen) und der Verlauf
(``history["timeline"]``: Ortsname je 5 s Rundenzeit) auf derselben Map.

Alles sind eure eigenen Daten. Es ist ein Vergleich, keine Garantie, dass die andere Position
die Runde gewonnen hätte; so formuliert.
"""

from __future__ import annotations

from collections import Counter

from cstaktik.model import Finding, MatchData
from cstaktik.rules.base import PositionIndex

STEP_S = 5  # Raster der Rundenzeit
MAX_S = 115


def _bucket(seconds: float) -> int:
    return int(round(seconds / STEP_S)) * STEP_S


def timeline(match: MatchData, all_players: bool = False) -> list[dict]:
    """Je Runde und Spieler: Ortsname alle STEP_S Sekunden (None = tot/keine Daten).

    Standard: nur Fokus-Spieler; ``all_players`` für Pro-Demos (alle 10)."""
    idx = PositionIndex(match.positions)
    tr = match.tickrate
    out = []
    for r in match.rounds:
        if r.freeze_end_tick is None or r.winner is None:
            continue
        if not all_players and match.focus_side(r.num) is None:
            continue
        for sid in sorted(r.sides if all_players else match.focus_ids()):
            if sid not in r.sides:
                continue
            places = []
            for s in range(0, MAX_S + 1, STEP_S):
                tick = r.freeze_end_tick + s * tr
                if tick > r.end_tick:
                    break
                p = idx.nearest(r.num, sid, tick, tr // 2)
                places.append(p.place if p is not None and p.alive else None)
            out.append({"round": r.num, "sid": sid, "side": r.sides[sid], "won": r.winner == r.sides[sid],
                        "places": places})
    return out


def enrich(match: MatchData, findings: list[Finding], histories: list[dict] | None = None,
           min_samples: int = 2) -> None:
    """Ergänzt Tod-Analysen um ``evidence["vorbild"]`` und ein Geister-Overlay aus einer Siegrunde."""
    tr = match.tickrate
    idx = PositionIndex(match.positions)
    current = timeline(match)
    past = [t for h in (histories or []) if h.get("map") == match.map_name and h.get("id") != match.source_sha256
            for t in h.get("timeline", [])]

    for f in findings:
        if f.rule_id != "death_review" or f.tick is None or f.round is None or not f.steamid:
            continue
        rnd = match.round_by_num(f.round)
        if rnd is None or rnd.freeze_end_tick is None:
            continue
        side = rnd.sides.get(f.steamid)
        secs = (f.tick - rnd.freeze_end_tick) / tr
        b = _bucket(secs) // STEP_S
        won = [t for t in current + past
               if t["sid"] == f.steamid and t["side"] == side and t["won"] and t.get("round") != f.round
               and b < len(t["places"]) and t["places"][b]]
        if len(won) < min_samples:
            continue
        counts = Counter(t["places"][b] for t in won)
        top, n = counts.most_common(1)[0]
        here = next((k.victim_place for k in match.kills if k.tick == f.tick and k.victim_steamid == f.steamid), None)
        mm, ss = divmod(_bucket(secs), 60)
        when = f"{mm}:{ss:02d}"
        if n < 2 or n * 2 < len(won):
            # kein klarer Schwerpunkt: Verteilung nennen statt "meist"
            spread = ", ".join(f"{pl} {c}x" for pl, c in counts.most_common(3))
            mm, ss = divmod(_bucket(secs), 60)
            f.evidence["vorbild"] = (f"In gewonnenen {side.upper()}-Runden nach {mm}:{ss:02d} kein fester Ort "
                                     f"({len(won)} Runden: {spread}).")
            continue
        if here and top == here:
            text = (f"Auch in Siegrunden warst du nach {when} meist in {top} ({n} von {len(won)}). "
                    "Die Position passt, entscheidend war eher das Wie (siehe Lage).")
        else:
            text = (f"In gewonnenen {side.upper()}-Runden warst du nach {when} meist in {top} "
                    f"({n} von {len(won)})" + (f", hier in {here}." if here else "."))
        f.evidence["vorbild"] = text

        # Siegrunde aus diesem Match mit dem Spieler am Vorbild-Ort: als Geist + Sprungziel
        ref = next((t for t in current if t["sid"] == f.steamid and t["side"] == side and t["won"]
                    and t["round"] != f.round and b < len(t["places"]) and t["places"][b] == top), None)
        if ref:
            rr = match.round_by_num(ref["round"])
            tick = rr.freeze_end_tick + _bucket(secs) * tr
            p = idx.nearest(ref["round"], f.steamid, tick, tr // 2)
            if p is not None:
                f.overlay["ghost"] = [p.pos.x, p.pos.y]
                f.overlay["ghost_round"] = ref["round"]
                f.overlay["ghost_offset_s"] = _bucket(secs)


def winning_spots(histories: list[dict], map_name: str, at_s: int = 20, min_samples: int = 2) -> list[dict]:
    """Für das Briefing: wo standen die Fokus-Spieler in Siegrunden nach ``at_s`` Sekunden, je Seite."""
    b = _bucket(at_s) // STEP_S
    names: dict[str, str] = {}
    counts: dict[tuple[str, str], Counter] = {}
    for h in histories:
        if h.get("map") != map_name:
            continue
        for sid, p in h.get("players", {}).items():
            names[sid] = p["name"]
        for t in h.get("timeline", []):
            if t["won"] and b < len(t["places"]) and t["places"][b]:
                counts.setdefault((t["sid"], t["side"]), Counter())[t["places"][b]] += 1
    out = []
    for (sid, side), c in sorted(counts.items()):
        total = sum(c.values())
        place, n = c.most_common(1)[0]
        if total >= min_samples:
            out.append({"name": names.get(sid, sid), "side": side.upper(), "place": place, "n": n, "total": total,
                        "at": f"0:{at_s:02d}"})
    return out


PRO_MIN_SAMPLES = 10  # so viele Pro-Spieler-Samples braucht ein Vergleich mindestens


def pro_spots(pro: list[dict], map_name: str | None, side: str, seconds: float, top: int = 3) -> dict | None:
    """Verteilung der Pro-Positionen (Siegrunden ihrer Seite) zur Rundenzeit, aus data/pro."""
    b = _bucket(seconds) // STEP_S
    c = Counter()
    demos = set()
    for d in pro:
        if d.get("map") != map_name:
            continue
        for t in d.get("timeline", []):
            if t["side"] == side and t["won"] and b < len(t["places"]) and t["places"][b]:
                c[t["places"][b]] += 1
                demos.add(d.get("id"))
    total = sum(c.values())
    if total < PRO_MIN_SAMPLES:
        return None
    return {"spots": [{"place": p, "pct": round(100 * n / total)} for p, n in c.most_common(top)],
            "samples": total, "demos": len(demos), "at": _bucket(seconds)}


def pro_text(ps: dict, side: str) -> str:
    mm, ss = divmod(ps["at"], 60)
    spots = ", ".join(f"{s['place']} {s['pct']} %" for s in ps["spots"])
    return (f"Pros auf {side.upper()} in Siegrunden nach {mm}:{ss:02d}: {spots} "
            f"(Anteil der Spieler-Positionen, {ps['demos']} Demo{'s' if ps['demos'] != 1 else ''})")


PRO_MIN_ROUNDS = 5  # so viele passende Pro-Runden braucht der Szenen-Vergleich
PRO_MIN_DEATHS = 8  # so viele Pro-Tode am Ort braucht die Trade-Quote
NADE_NAMES = {"smoke": "Smoke", "flash": "Flash", "molotov": "Molotov", "he": "HE"}


def pro_scene(pro: list[dict], map_name: str | None, side: str, place: str, seconds: float,
              lead_s: float = 20.0) -> dict | None:
    """Pro-Siegrunden derselben Seite, in denen ein Pro zur selben Rundenzeit am selben Ort war:
    In wie vielen kam vorher Utility zum Einsatz? T: Granaten, die dort landen. CT: Granaten, die von dort fliegen.
    """
    b = _bucket(seconds) // STEP_S
    rounds = 0
    with_util = 0
    kinds: Counter = Counter()
    throws: Counter = Counter()
    sample: dict = {}
    demos = set()
    key = "to" if side == "t" else "from"
    for d in pro:
        if d.get("map") != map_name or "nades" not in d:
            continue
        hit = {t["round"] for t in d.get("timeline", [])
               if t["side"] == side and t["won"] and b < len(t["places"]) and t["places"][b] == place}
        for r in hit:
            rounds += 1
            demos.add(d.get("id"))
            ns = [n for n in d["nades"] if n["r"] == r and n["side"] == side and n[key] == place
                  and seconds - lead_s <= n["t"] <= seconds + 2]
            if ns:
                with_util += 1
                kinds.update({n["kind"] for n in ns})
                for n in ns:
                    if n["kind"] in ("smoke", "flash", "molotov"):
                        k = (n["kind"], n["from"], n["to"])
                        throws[k] += 1
                        sample.setdefault(k, n)
    if rounds < PRO_MIN_ROUNDS:
        return None
    lineup = None
    if throws:
        (kind, frm, to), n = throws.most_common(1)[0]
        if n >= 2:
            s = sample[(kind, frm, to)]
            lineup = {"kind": kind, "from": frm, "to": to, "n": n, "xy": [s["fx"], s["fy"], s["tx"], s["ty"]]}
    return {"rounds": rounds, "with_util": with_util, "kinds": kinds.most_common(), "lineup": lineup,
            "demos": len(demos), "at": _bucket(seconds)}


def pro_trade(pro: list[dict], map_name: str | None, side: str, place: str) -> dict | None:
    """Wie oft werden Pros getradet, wenn sie auf dieser Seite an diesem Ort sterben?"""
    ds = [x for d in pro if d.get("map") == map_name for x in d.get("deaths", [])
          if x["side"] == side and x["place"] == place]
    if len(ds) < PRO_MIN_DEATHS:
        return None
    return {"n": len(ds), "pct": round(100 * sum(x["traded"] for x in ds) / len(ds))}


def scene_text(sc: dict, side: str, place: str) -> str:
    mm, ss = divmod(sc["at"], 60)
    if not sc["with_util"]:
        return (f"In {sc['rounds']} Pro-Siegrunden ({side.upper()}, {place}, um {mm}:{ss:02d}) "
                "kam vorher keine Utility: dort entscheidet das Duell/Timing.")
    kinds = ", ".join(f"{NADE_NAMES[k]} {n}" for k, n in sc["kinds"])
    where = "dorthin" if side == "t" else "von dort"
    return (f"Pros ({side.upper()}) in {place} um {mm}:{ss:02d}: in {sc['with_util']} von {sc['rounds']} "
            f"Siegrunden kam vorher Utility {where} ({kinds}).")


def enrich_pro(match: MatchData, findings: list[Finding], pro: list[dict]) -> None:
    """Ergänzt Tod-Analysen um Pro-Vergleiche, wenn genug Pro-Daten zur Map vorliegen:
    ``pro`` (Positionen), ``pro_util`` (Utility in derselben Szene), ``pro_trade`` (Trade-Quote am Ort),
    ``pro_lineup`` (häufigster Pro-Wurf, als Overlay ``pro_nade`` im Replay)."""
    if not pro:
        return
    tr = match.tickrate
    for f in findings:
        if f.rule_id != "death_review" or f.tick is None or f.round is None or not f.steamid:
            continue
        rnd = match.round_by_num(f.round)
        if rnd is None or rnd.freeze_end_tick is None:
            continue
        side = rnd.sides.get(f.steamid)
        if not side:
            continue
        secs = (f.tick - rnd.freeze_end_tick) / tr
        ps = pro_spots(pro, match.map_name, side, secs)
        if ps:
            f.evidence["pro"] = pro_text(ps, side)
        place = next((k.victim_place for k in match.kills if k.tick == f.tick and k.victim_steamid == f.steamid), None)
        if not place:
            continue
        sc = pro_scene(pro, match.map_name, side, place, secs)
        if sc:
            f.evidence["pro_util"] = scene_text(sc, side, place)
            lu = sc["lineup"]
            if lu:
                f.evidence["pro_lineup"] = (f"Häufigster Pro-Wurf dabei: {NADE_NAMES[lu['kind']]} aus "
                                            f"{lu['from'] or '?'} nach {lu['to'] or '?'} ({lu['n']}x). "
                                            "Im Replay lila gestrichelt.")
                f.overlay["pro_nade"] = {"kind": lu["kind"], "xy": lu["xy"]}
        pt = pro_trade(pro, match.map_name, side, place)
        if pt:
            f.evidence["pro_trade"] = (f"Pros, die in {place} sterben ({side.upper()}), werden zu {pt['pct']} % "
                                       f"getradet ({pt['n']} Tode).")


def pro_utility(pro: list[dict], map_name: str | None, side: str, top: int = 4, min_n: int = 3) -> list[dict]:
    """Für das Briefing: häufigste Pro-Würfe (Smoke/Flash/Molotov) in Siegrunden einer Seite, von Ort nach Ort."""
    c: Counter = Counter()
    rounds = 0
    for d in pro:
        if d.get("map") != map_name or "nades" not in d:
            continue
        rounds += len({t["round"] for t in d.get("timeline", []) if t["side"] == side and t["won"]})
        for n in d["nades"]:
            if n["side"] == side and n["won"] and n["kind"] in ("smoke", "flash", "molotov") and n["from"] and n["to"]:
                c[(n["kind"], n["from"], n["to"])] += 1
    return [{"kind": NADE_NAMES[k], "from": f, "to": t, "n": n, "rounds": rounds}
            for (k, f, t), n in c.most_common(top) if n >= min_n]
