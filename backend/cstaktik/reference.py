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


def enrich_pro(match: MatchData, findings: list[Finding], pro: list[dict]) -> None:
    """Ergänzt Tod-Analysen um ``evidence["pro"]``, wenn genug Pro-Daten zur Map vorliegen."""
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
        ps = pro_spots(pro, match.map_name, side, (f.tick - rnd.freeze_end_tick) / tr) if side else None
        if ps:
            f.evidence["pro"] = pro_text(ps, side)
