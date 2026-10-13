"""Pro-Demos als Referenz, gespeichert in data/pro (eine kleine JSON je Demo).

Je Demo: Positionen aller Spieler je 5 s Rundenzeit (timeline), jede Granate (Seite, Rundenzeit,
Wurf- und Landeort) und jeder Tod (Ort, Rundenzeit, getradet ja/nein). Alles aus der Demo, nichts geschätzt.
Jede weitere Pro-Demo erweitert die Datenbasis; die Coach-Vergleiche nutzen alle Demos derselben Map.

Pro-Demos z. B. von HLTV am PC herunterladen, die .dem aus dem Archiv entpacken und mit
"Pro-Demo" hochladen (oder ``cstaktik pro <demo>``). Es wird kein eigener Report erzeugt.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from collections import Counter

from cstaktik.model import MatchData
from cstaktik.reference import timeline
from cstaktik.situation import pro_decisions, round_states
from cstaktik.utility_cmp import flash_effect, pre_contact

VERSION = 8  # 1: timeline; 2: + nades, deaths; 3: + states; 4: + decisions; 5: + duels; 6: + flashes, pre_util;
#             7: + Wurfposition/Blick je Granate (Lineups), sid bei Toden (Map-Buch); 8: Würfe je Entity getrennt
_CELL = 128  # Rastergröße für die Ortsbestimmung von Granaten-Punkten


def place_lookup(match: MatchData):
    """Ortsname (Callout) für beliebige Koordinaten: häufigster Ort der Spieler-Positionen in der Nähe."""
    grid: dict[tuple[int, int, int], Counter] = {}
    flat: dict[tuple[int, int], Counter] = {}
    for p in match.positions:
        if not p.place:
            continue
        gx, gy, gz = int(p.pos.x // _CELL), int(p.pos.y // _CELL), int(p.pos.z // _CELL)
        grid.setdefault((gx, gy, gz), Counter())[p.place] += 1
        flat.setdefault((gx, gy), Counter())[p.place] += 1

    def find(x: float, y: float, z: float) -> str | None:
        gx, gy, gz = int(x // _CELL), int(y // _CELL), int(z // _CELL)
        for r in (0, 1):
            c = Counter()
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    for dz in (-1, 0, 1):
                        c.update(grid.get((gx + dx, gy + dy, gz + dz), {}))
            if c:
                return c.most_common(1)[0][0]
        c = Counter()  # Granate in der Luft/auf Dach: nur x/y
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                c.update(flat.get((gx + dx, gy + dy), {}))
        return c.most_common(1)[0][0] if c else None

    return find


def nades(match: MatchData) -> list[dict]:
    """Granaten mit Seite, Rundenzeit (Wurf), Wurf- und Landeort aus der Flugbahn."""
    find = place_lookup(match)
    tr = match.tickrate
    out = []
    for g in match.grenades:
        rnd = match.round_by_num(g.round)
        if g.kind not in ("smoke", "flash", "molotov", "he") or len(g.points) < 2 or rnd is None \
                or rnd.freeze_end_tick is None or rnd.winner is None:
            continue
        side = rnd.sides.get(g.thrower_steamid or "")
        if side is None:
            continue
        (t0, fx, fy, fz), (_t1, tx, ty, tz) = g.points[0], g.points[-1]
        out.append({"r": g.round, "side": side, "won": rnd.winner == side, "kind": g.kind,
                    "t": round((t0 - rnd.freeze_end_tick) / tr, 1),
                    "from": find(*g.throw[1:4]) if g.throw else find(fx, fy, fz), "to": find(tx, ty, tz),
                    "fx": round(fx), "fy": round(fy), "tx": round(tx), "ty": round(ty), "tz": round(tz),
                    **({"p": g.throw[1:]} if g.throw else {})})
    return out


def deaths(match: MatchData, trade_window_s: float = 3.0) -> list[dict]:
    """Tode mit Ort, Rundenzeit, erstes Duell, getradet (Killer stirbt binnen trade_window_s durch Team des Opfers)."""
    tr = match.tickrate
    kills = sorted(match.kills, key=lambda k: k.tick)
    first: dict[int, int] = {}
    for k in kills:
        first.setdefault(k.round, k.tick)
    out = []
    for k in kills:
        rnd = match.round_by_num(k.round)
        if rnd is None or rnd.freeze_end_tick is None or rnd.winner is None or k.victim_side is None:
            continue
        if k.attacker_side == k.victim_side:
            continue
        traded = bool(k.attacker_steamid) and any(
            x.round == k.round and x.victim_steamid == k.attacker_steamid and x.attacker_side == k.victim_side
            and k.tick < x.tick <= k.tick + trade_window_s * tr for x in kills)
        out.append({"r": k.round, "sid": k.victim_steamid, "side": k.victim_side, "won": rnd.winner == k.victim_side,
                    "t": round((k.tick - rnd.freeze_end_tick) / tr, 1), "place": k.victim_place,
                    "first": first[k.round] == k.tick, "traded": traded})
    return out


def duel_rows(match: MatchData) -> list[list]:
    """Je Duell beide Sichten: [Abweichung Grad, Reaktion ms, erste Kugel getroffen, gewonnen]."""
    from cstaktik.duels import side_of

    out = []
    for d in match.duels:
        for sid in (d.winner, d.loser):
            v = side_of(d, sid)
            out.append([v["err"], v["react"], v["hit"], v["won"]])
    return out


def duel_stats(pro: list[dict]) -> dict | None:
    from cstaktik.duels import stats

    rows = [{"err": r[0], "react": r[1], "hit": r[2], "won": r[3]} for d in pro for r in d.get("duels", [])]
    return stats(rows) if rows else None


def summarize(match: MatchData, trade_window_s: float = 3.0) -> dict:
    return {
        "id": match.source_sha256 or match.source_file,
        "version": VERSION,
        "source_file": match.source_file,
        "map": match.map_name,
        "rounds": len(match.rounds),
        "analyzed_at": datetime.now().isoformat(timespec="minutes"),
        "timeline": timeline(match, all_players=True),
        "nades": nades(match),
        "deaths": deaths(match, trade_window_s),
        "states": round_states(match),
        "decisions": pro_decisions(match),
        "duels": duel_rows(match),
        "flashes": [[f["enemy_s"], f["team_s"]] for f in flash_effect(match)],
        "pre_util": list(pre_contact(match)),
    }


def save(summary: dict, pro_dir: Path) -> Path:
    pro_dir.mkdir(parents=True, exist_ok=True)
    key = "".join(ch for ch in str(summary["id"]) if ch.isalnum())[:40] or "pro"
    out = pro_dir / f"{key}.json"
    out.write_text(json.dumps(summary, ensure_ascii=False))
    return out


def load_all(pro_dir: Path) -> list[dict]:
    out = []
    for f in sorted(pro_dir.glob("*.json")) if pro_dir.exists() else []:
        try:
            out.append(json.loads(f.read_text()))
        except (OSError, ValueError):
            continue
    return out


def stats(pro_dir: Path) -> dict:
    """Für die Startseite: je Map Demos, Runden und ob die Detaildaten (Granaten/Tode) vorliegen."""
    out: dict[str, dict] = {}
    for d in load_all(pro_dir):
        m = out.setdefault(d.get("map") or "?", {"demos": 0, "rounds": 0, "nades": 0, "old": 0})
        m["demos"] += 1
        m["rounds"] += d.get("rounds") or 0
        m["nades"] += len(d.get("nades") or [])
        m["old"] += d.get("version", 1) < VERSION
    return dict(sorted(out.items()))


def overview(pro_dir: Path) -> dict[str, int]:
    """Map -> Anzahl Pro-Demos."""
    counts: dict[str, int] = {}
    for d in load_all(pro_dir):
        counts[d.get("map") or "?"] = counts.get(d.get("map") or "?", 0) + 1
    return counts
