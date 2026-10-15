"""Impact: wie viel Siegchance jede Aktion bringt oder kostet (Win Probability Added).

Grundlage ist das gezählte Gewinnmodell (situation.WinModel) aus euren anderen Matches und den Pro-Demos: Gewinnquote je
Lage (lebende CT, lebende T, Bombe gelegt, wenn genug Runden: Ausrüstung). Für jedes Ereignis einer Runde wird die
Chance davor und danach nachgeschlagen; die Differenz bekommt, wer es ausgelöst hat:

- Kill: der Schütze bekommt die Änderung aus Sicht seiner Seite, das Opfer die Änderung aus Sicht seiner Seite
  (also negativ). Teamkill: beide negativ.
- Plant: der Leger. Defuse: der Entschärfer bekommt den Rest bis zum sicheren Sieg.
- Was am Rundenende übrig bleibt (Zeit, Explosion, Retake ohne Kill), wird niemandem zugeschrieben.

Schaden ohne Kill, Granaten und Infos zählen hier nicht: Das misst das Modell nicht. Kennt das Modell eine Lage nicht
(zu wenige Runden), bekommt das Ereignis keinen Wert statt eines geschätzten.
Einheit: Prozentpunkte Siegchance; 100 Punkte = eine ganze Runde.
"""

from __future__ import annotations

from cstaktik.model import MatchData
from cstaktik.situation import WinModel, eq_bucket


def _other(side: str) -> str:
    return "t" if side == "ct" else "ct"


def rounds(match: MatchData, model: WinModel) -> dict[int, dict]:
    """Je Runde: Verlauf der CT-Siegchance [[tick, 0..100]] und alle bewerteten Ereignisse."""
    out = {}
    for r in match.rounds:
        if r.winner is None or not r.sides:
            continue
        alive = {sd: {s for s, x in r.sides.items() if x == sd} for sd in ("ct", "t")}
        eq = eq_bucket(r)
        planted = False
        t0 = r.freeze_end_tick if r.freeze_end_tick is not None else r.start_tick

        def p_ct() -> float | None:
            res = model.prob("ct", len(alive["ct"]), len(alive["t"]), planted, eq)
            return None if res is None else res[0] * 100

        cur = p_ct()
        line = [[t0, round(cur, 1)]] if cur is not None else []
        events = sorted([(k.tick, 0, "kill", k) for k in match.kills if k.round == r.num and k.tick <= r.end_tick]
                        + [(b.tick, 1, b.event, b) for b in match.bomb
                           if b.round == r.num and b.event in ("plant", "defuse") and b.tick <= r.end_tick],
                        key=lambda e: (e[0], e[1]))  # nach Rundenende zählt nichts mehr
        evs = []
        for tick, _o, kind, e in events:
            before = cur
            if kind == "kill":
                alive["ct"].discard(e.victim_steamid)
                alive["t"].discard(e.victim_steamid)
            elif kind == "plant":
                planted = True
            after = 100.0 if kind == "defuse" else p_ct()
            cur = after
            if after is not None:
                line.append([tick, round(after, 1)])
            if before is None or after is None:
                continue
            d_ct = after - before
            if kind == "kill":
                vs = e.victim_side or r.sides.get(e.victim_steamid)
                credit = []
                if vs:
                    credit.append((e.victim_steamid, "death", d_ct if vs == "ct" else -d_ct))
                    a = e.attacker_steamid
                    if a and a != e.victim_steamid and a in r.sides:
                        credit.append((a, "kill", d_ct if r.sides[a] == "ct" else -d_ct))
                evs.append({"tick": tick, "kind": "kill", "credit": credit, "d_ct": round(d_ct, 1),
                            "attacker": e.attacker_steamid, "victim": e.victim_steamid})
            elif e.steamid and e.steamid in r.sides:
                evs.append({"tick": tick, "kind": kind, "credit": [(e.steamid, kind, -d_ct if kind == "plant" else d_ct)],
                            "d_ct": round(d_ct, 1)})
            if kind == "defuse":
                break
        end = 100.0 if r.winner == "ct" else 0.0
        if line and line[-1][1] != end:
            line.append([r.end_tick, end])
        out[r.num] = {"line": line, "events": evs, "winner": r.winner, "sides": r.sides}
    return out


def build(match: MatchData, model: WinModel, focus: set[str] | None = None) -> dict:
    """Impact je Spieler (Summe, je Runde, nach Art) und die größten Momente der Fokus-Spieler."""
    focus = focus if focus is not None else match.focus_ids()
    per_round = rounds(match, model)
    players: dict[str, dict] = {}
    moments = []
    for num, rd in per_round.items():
        for ev in rd["events"]:
            for sid, kind, val in ev["credit"]:
                p = players.setdefault(sid, {"total": 0.0, "kill": 0.0, "death": 0.0, "plant": 0.0, "defuse": 0.0,
                                             "n": 0, "rounds": {}})
                p["total"] += val
                p[kind] += val
                p["n"] += 1
                p["rounds"][num] = round(p["rounds"].get(num, 0) + val, 1)
                if sid in focus:
                    moments.append({"sid": sid, "round": num, "tick": ev["tick"], "kind": kind, "val": round(val, 1),
                                    "other": ev.get("victim") if kind == "kill" else ev.get("attacker")
                                    if kind == "death" else None})
    n_rounds = len(per_round) or 1
    for p in players.values():
        p["per_round"] = round(p["total"] / n_rounds, 1)
        for k in ("total", "kill", "death", "plant", "defuse"):
            p[k] = round(p[k], 1)
    moments.sort(key=lambda m: -abs(m["val"]))
    return {"rounds": per_round, "players": players, "moments": moments, "n_rounds": len(per_round)}


def history_row(imp: dict, focus: set[str]) -> dict:
    """Was im Verlauf gespeichert wird: Summen und Wert je Runde der Fokus-Spieler, dazu Platz im Match."""
    order = sorted(imp["players"], key=lambda s: -imp["players"][s]["total"])
    return {sid: {**p, "rank": order.index(sid) + 1, "of": len(order)}
            for sid, p in imp["players"].items() if sid in focus}


WINDOW = 10


def profile(hist: list[dict], sid: str) -> dict | None:
    """Impact über die letzten Matches: je Runde, Verlauf, Herkunft (Kills/Tode/Bombe), Platz im Match."""
    rows = [(h, h["impact"][sid]) for h in hist if sid in (h.get("impact") or {}) and h.get("rounds")][-WINDOW:]
    if not rows:
        return None
    rounds = sum(h["rounds"] for h, _ in rows)
    per = [round(x["total"] / h["rounds"], 1) for h, x in rows]
    tot = {k: sum(x.get(k, 0) for _, x in rows) for k in ("total", "kill", "death", "plant", "defuse")}
    n = len(rows)
    top = max([abs(v) for v in per] + [1])
    pts = [(100 * i / max(1, n - 1), 15 - 13 * v / top) for i, v in enumerate(per)]
    ranks = [x["rank"] for _, x in rows if x.get("rank")]
    out = {"n": n, "per_round": round(tot["total"] / rounds, 1), "per_round_s": de(tot["total"] / rounds),
           "kill_s": de(tot["kill"] / 100 / n), "death_s": de(tot["death"] / 100 / n),
           "obj_s": de((tot["plant"] + tot["defuse"]) / 100 / n), "obj": tot["plant"] + tot["defuse"],
           "match_s": de(tot["total"] / 100 / n),
           "spark": " ".join(f"{x:.1f},{y:.1f}" for x, y in pts),
           "dots": [{"x": round(x, 1), "y": round(y, 1), "neg": v < 0} for (x, y), v in zip(pts, per)],
           "top1": sum(1 for r in ranks if r == 1), "ranked": len(ranks),
           "avg_rank": round(sum(ranks) / len(ranks), 1) if ranks else None}
    out["trend"] = None
    if n >= 6:
        old, new = rows[: n // 2], rows[n // 2:]
        a = sum(x["total"] for _, x in old) / sum(h["rounds"] for h, _ in old)
        b = sum(x["total"] for _, x in new) / sum(h["rounds"] for h, _ in new)
        out["trend"] = "besser" if b - a >= 1.5 else "schlechter" if a - b >= 1.5 else "gleich"
        out["trend_s"] = f"{de(a)} → {de(b)} Punkte je Runde"
    return out


def de(x: float) -> str:
    return (f"+{x:.1f}" if x > 0 else f"{x:.1f}").replace(".", ",")
