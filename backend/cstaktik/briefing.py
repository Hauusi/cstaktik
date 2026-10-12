"""Briefing vor dem Match: persönliche Hinweise pro Map aus dem Match-Verlauf (data/history).

Nur Dinge, die in euren ausgewerteten Matches passiert sind. Ohne Verlauf auf der Map: ehrlich leer.
"""

from __future__ import annotations

from collections import Counter

from cstaktik.coach import CAUSES

SIDE_DE = {"ct": "CT", "t": "T"}


def build(map_name: str, histories: list[dict], goals_state: dict, min_count: int = 2) -> dict:
    hs = [h for h in histories if h.get("map") == map_name]
    names: dict[str, str] = {}
    for h in hs:
        for sid, p in h.get("players", {}).items():
            names[sid] = p["name"]
    won_matches = sum(1 for h in hs if h.get("won", 0) > h.get("lost", 0))

    notes = []
    for side in ("ct", "t"):
        deaths = Counter((d["sid"], d["place"]) for h in hs for d in h.get("deaths", [])
                         if d.get("side") == side and d.get("place"))
        firsts = Counter((d["sid"], d["place"]) for h in hs for d in h.get("deaths", [])
                         if d.get("side") == side and d.get("place") and d.get("first"))
        for (sid, place), n in deaths.most_common(4):
            if n < min_count:
                break
            f = firsts.get((sid, place), 0)
            notes.append({
                "side": SIDE_DE[side],
                "text": f"{names.get(sid, sid)}: {n}x in {place} gestorben" + (f", davon {f}x als Erster" if f else ""),
                "tip": f"{place} anders spielen: Timing ändern, mit Utility nehmen oder Position wechseln.",
            })

    rounds = sum(h.get("rounds", 0) for h in hs)
    cause_rounds = Counter()
    for h in hs:
        cause_rounds.update(h.get("cause_rounds", {}))
    watch = []
    for cid, n in cause_rounds.most_common(2):
        if rounds and n and cid in CAUSES:
            watch.append({"title": CAUSES[cid]["title"], "pct": round(100 * n / rounds), "tip": CAUSES[cid]["tip"]})

    return {
        "map": map_name,
        "label": map_name.removeprefix("de_").capitalize(),
        "matches": len(hs),
        "won_matches": won_matches,
        "last_verdict": hs[-1].get("verdict") if hs else None,
        "notes": notes,
        "watch": watch,
        "goals": [{"title": g["title"], "tip": g["tip"], "target": g["target_pct"]} for g in goals_state.get("active", [])],
    }
