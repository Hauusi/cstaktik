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


CTX_DE = {"opening": "Opening-Duell", "trade": "Trade gegeben", "clutch": "Clutch", "postplant": "Nach dem Plant",
          "up": "In Überzahl", "even": "Gleichstand", "down": "In Unterzahl", "bomb": "Bombe legen/entschärfen"}


CTX_IN = {"opening": "in Opening-Duellen", "trade": "bei Trades", "clutch": "im Clutch", "postplant": "nach dem Plant",
          "up": "in Überzahl", "even": "bei Gleichstand", "down": "in Unterzahl"}


CTX_TIP = {"opening": "Erstes Duell nur mit Flash, Info oder zu zweit nehmen, nicht trocken peeken.",
           "clutch": "Zeit nutzen, Gegner einzeln isolieren, nicht in zwei gleichzeitig laufen.",
           "trade": "Näher am Mitspieler stehen, damit der Trade sofort kommt.",
           "postplant": "Nach dem Plant Zeit für euch spielen lassen (T) bzw. gemeinsam retaken (CT), nicht einzeln.",
           "up": "In Überzahl nicht einzeln peeken: zusammen gehen, die Zeit arbeitet für euch.",
           "even": "Bei Gleichstand Duelle vorbereiten: Utility, Pre-Aim, Trade-Partner.",
           "down": "In Unterzahl nicht allein das Duell suchen: zusammenziehen oder Waffe retten."}


def _ctx(own: int, enemy: int, first: bool, planted: bool, trade: bool = False) -> str:
    """Lage aus Sicht eines Spielers VOR dem Ereignis; Reihenfolge = Vorrang."""
    if first:
        return "opening"
    if own == 1 and enemy >= 1:
        return "clutch"
    if trade:
        return "trade"
    if planted:
        return "postplant"
    return "up" if own > enemy else "down" if own < enemy else "even"


def rounds(match: MatchData, model: WinModel, trade_s: float = 3.0) -> dict[int, dict]:
    """Je Runde: Verlauf der CT-Siegchance [[tick, 0..100]] und alle bewerteten Ereignisse mit Lage (``ctx``)."""
    out = {}
    tw = trade_s * (match.tickrate or 64)
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
        done: list = []  # bisherige Kills (tick, Schütze, Opfer) für Opening und Trade
        for tick, _o, kind, e in events:
            before = cur
            n_before = {sd: len(alive[sd]) for sd in ("ct", "t")}
            was_planted = planted
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
                first = not done
                if vs:
                    credit.append((e.victim_steamid, "death", d_ct if vs == "ct" else -d_ct,
                                   _ctx(n_before[vs], n_before[_other(vs)], first, was_planted)))
                    a = e.attacker_steamid
                    if a and a != e.victim_steamid and a in r.sides:
                        sa = r.sides[a]
                        # Trade: das Opfer hat kurz vorher einen Mitspieler des Schützen getötet
                        trade = any(k_att == e.victim_steamid and r.sides.get(k_vic) == sa and tick - k_t <= tw
                                    for k_t, k_att, k_vic in done)
                        credit.append((a, "kill", d_ct if sa == "ct" else -d_ct,
                                       _ctx(n_before[sa], n_before[_other(sa)], first, was_planted, trade)))
                done.append((tick, e.attacker_steamid, e.victim_steamid))
                evs.append({"tick": tick, "kind": "kill", "credit": credit, "d_ct": round(d_ct, 1),
                            "attacker": e.attacker_steamid, "victim": e.victim_steamid})
            elif e.steamid and e.steamid in r.sides:
                evs.append({"tick": tick, "kind": kind,
                            "credit": [(e.steamid, kind, -d_ct if kind == "plant" else d_ct, "bomb")],
                            "d_ct": round(d_ct, 1)})
            if kind == "defuse":
                break
        end = 100.0 if r.winner == "ct" else 0.0
        if line and line[-1][1] != end:
            line.append([r.end_tick, end])
        out[r.num] = {"line": line, "events": evs, "winner": r.winner, "sides": r.sides}
    return out


def build(match: MatchData, model: WinModel, focus: set[str] | None = None, trade_s: float = 3.0) -> dict:
    """Impact je Spieler (Summe, je Runde, nach Art) und die größten Momente der Fokus-Spieler."""
    focus = focus if focus is not None else match.focus_ids()
    per_round = rounds(match, model, trade_s)
    players: dict[str, dict] = {}
    moments = []
    for num, rd in per_round.items():
        for ev in rd["events"]:
            for sid, kind, val, ctx in ev["credit"]:
                p = players.setdefault(sid, {"total": 0.0, "kill": 0.0, "death": 0.0, "plant": 0.0, "defuse": 0.0,
                                             "n": 0, "rounds": {}, "ctx": {}})
                c = p["ctx"].setdefault(ctx, [0.0, 0])  # Lage -> [Summe, Anzahl]
                c[0] = round(c[0] + val, 1)
                c[1] += 1
                p["total"] += val
                p[kind] += val
                p["n"] += 1
                p["rounds"][num] = round(p["rounds"].get(num, 0) + val, 1)
                if sid in focus:
                    moments.append({"sid": sid, "round": num, "tick": ev["tick"], "kind": kind, "val": round(val, 1),
                                    "ctx": ctx,
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
    out["ctx"], out["ctx_reading"] = contexts(rows)
    return out


MIN_CTX = 10  # so viele Ereignisse braucht eine Lage für eine Aussage


def contexts(rows: list[tuple[dict, dict]]) -> tuple[list[dict], str | None]:
    """Impact nach Lage über die Matches: Netto je Match (Kills minus Tode). 0 = Durchschnitt aller Spieler,
    weil jeder Kill-Gewinn genau einem Tod-Verlust gegenübersteht."""
    agg: dict[str, list] = {}
    n = len(rows)
    for _h, x in rows:
        for ctx, (v, k) in (x.get("ctx") or {}).items():
            a = agg.setdefault(ctx, [0.0, 0])
            a[0] += v
            a[1] += k
    out = []
    for ctx, (v, k) in agg.items():
        if ctx not in CTX_DE:
            continue
        out.append({"ctx": ctx, "label": CTX_DE[ctx], "n": k, "per_match": v / 100 / n, "per_match_s": de(v / 100 / n),
                    "per_event_s": de(v / k) if k else "0,0", "enough": k >= MIN_CTX})
    out.sort(key=lambda c: c["per_match"])
    sure = [c for c in out if c["enough"] and c["ctx"] != "bomb"]
    parts = []
    if sure and sure[0]["per_match"] <= -0.15:
        w = sure[0]
        parts.append(f"Am meisten Runden verlierst du {CTX_IN[w['ctx']]}: {w['per_match_s']} Runden pro Match "
                     f"({w['n']} Kills und Tode, im Schnitt {w['per_event_s']} Punkte). {CTX_TIP[w['ctx']]}")
    if sure and sure[-1]["per_match"] >= 0.15:
        b = sure[-1]
        parts.append(f"Am meisten holst du {CTX_IN[b['ctx']]}: {b['per_match_s']} Runden pro Match.")
    return out, " ".join(parts) or None


KIND_DE = {"kill": "Kill", "death": "Tod", "plant": "Bombe gelegt", "defuse": "Entschärft"}


def highlights(hist: list[dict], sid: str, top: int = 8) -> dict:
    """Beste Plays und teuerste Momente eines Spielers über alle Matches, mit Sprung ins Replay."""
    from cstaktik.report.progress import _label

    rows = []
    for h in hist:
        for m in h.get("moments") or []:
            if m.get("sid") != sid:
                continue
            txt = KIND_DE.get(m["kind"], m["kind"])
            if m.get("other"):
                txt += f" gegen {m['other']}" if m["kind"] == "kill" else f" durch {m['other']}" if m["kind"] == "death" else ""
            ctx = CTX_DE.get(m.get("ctx")) if m.get("ctx") not in (None, "bomb", "even") else None
            rows.append({"val": m["val"], "val_s": de(m["val"]) + " %", "text": txt, "ctx": ctx,
                         "match": _label(h), "round": m["round"],
                         "link": f"/reports/{h['report_file']}#s{m['round']}-{m['tick']}" if h.get("report_file") else None})
    best = sorted((r for r in rows if r["val"] > 0), key=lambda r: -r["val"])[:top]
    worst = sorted((r for r in rows if r["val"] < 0), key=lambda r: r["val"])[:top]
    ctx_worst = {}
    for r in worst:
        if r["ctx"]:
            ctx_worst[r["ctx"]] = ctx_worst.get(r["ctx"], 0) + 1
    common = max(ctx_worst.items(), key=lambda kv: kv[1]) if ctx_worst else None
    note = (f"{common[1]} deiner {len(worst)} teuersten Momente: {common[0]}." if common and common[1] >= 3 else None)
    return {"best": best, "worst": worst, "note": note, "n": len(rows)}


def de(x: float) -> str:
    return (f"+{x:.1f}" if x > 0 else f"{x:.1f}").replace(".", ",")
