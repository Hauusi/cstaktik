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

Wie die Chancen entstehen (situation.WinModel): gezählt je Lage, dann hierarchisch geglättet. Eine genaue Lage
(z. B. 5 gegen 3) wird zur Lage mit gleichem Spielerunterschied (+2) gezogen, diese zu 50 %. Gewicht: 8 Runden. So
ergibt eine Zelle aus 3 Pro-Runden nicht "100 %", und ein einzelner Kill springt nicht um 35 Punkte, nur weil zwei
benachbarte Zellen zufällig weit auseinanderliegen. Hat nur die grobe Lage genug Runden, ist der Wert "grob".
Kills nach Rundenende (Waffe retten) bewegen keine Siegchance und zählen hier nicht, wohl aber in K/D (stats.py).
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


CTX_TIP = {"opening": "Nimm das erste Duell nur mit Flash, Info oder zu zweit.",
           "clutch": "Nutze die Zeit und isoliere die Gegner einzeln. Lauf nie in zwei gleichzeitig.",
           "trade": "Steh näher am Mitspieler. Dann kommt der Trade sofort.",
           "postplant": "Als T lasst ihr die Zeit für euch spielen. Als CT retaket ihr gemeinsam, nicht einzeln.",
           "up": "Peek in Überzahl nicht allein. Geht zusammen, die Zeit arbeitet für euch.",
           "even": "Bereite Duelle bei Gleichstand vor: Utility, Pre-Aim, Trade-Partner.",
           "down": "Such in Unterzahl nicht allein das Duell. Zieht zusammen oder rette die Waffe."}


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
        line = [[t0, None if cur is None else round(cur, 1)]]
        events = sorted([(k.tick, 0, "kill", k) for k in match.kills if k.round == r.num and k.tick <= r.end_tick]
                        + [(b.tick, 1, b.event, b) for b in match.bomb
                           if b.round == r.num and b.event in ("plant", "defuse") and b.tick <= r.end_tick],
                        key=lambda e: (e[0], e[1]))  # nach Rundenende zählt nichts mehr
        evs = []
        done: list = []  # bisherige Kills (tick, Schütze, Opfer) für Opening und Trade
        for tick, _o, kind, e in events:
            n_before = {sd: len(alive[sd]) for sd in ("ct", "t")}
            was_planted = planted
            if kind == "kill":
                alive["ct"].discard(e.victim_steamid)
                alive["t"].discard(e.victim_steamid)
            elif kind == "plant":
                planted = True
            cur = 100.0 if kind == "defuse" else p_ct()
            line.append([tick, None if cur is None else round(cur, 1)])  # None: Lage unbekannt, Linie setzt aus
            if kind == "defuse":
                pair = model.prob_pair((n_before["ct"], n_before["t"], was_planted), (n_before["ct"], 0, False), eq)
            else:
                pair = model.prob_pair((n_before["ct"], n_before["t"], was_planted),
                                       (len(alive["ct"]), len(alive["t"]), planted), eq)
            if kind == "defuse":
                pair = None if pair is None else (pair[0], 1.0)
            # Bombe, Fallschaden, Welt: kein Schütze, Wert wird niemandem zugeschrieben (Docstring)
            no_shooter = kind == "kill" and (not e.attacker_steamid or (e.weapon or "").lower() in ("planted_c4", "c4"))
            if pair is None or no_shooter:
                if kind == "kill":
                    done.append((tick, e.attacker_steamid, e.victim_steamid))
                if kind == "defuse":
                    break
                continue
            before, after = pair[0] * 100, pair[1] * 100
            d_ct = after - before
            # Ein Tod kann die Chance des eigenen Teams nicht erhöhen, ein Plant die der T nicht senken: passiert das
            # laut Tabelle doch, ist es Rauschen aus wenigen Runden. Dann kein Wert statt eines falschen Vorzeichens.
            vside = (e.victim_side or r.sides.get(e.victim_steamid)) if kind == "kill" else None
            if (vside == "ct" and d_ct > 0) or (vside == "t" and d_ct < 0) or (kind == "plant" and d_ct > 0):
                if kind == "kill":
                    done.append((tick, e.attacker_steamid, e.victim_steamid))
                continue
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
                        credit.append((a, "kill" if sa != vs else "teamkill", d_ct if sa == "ct" else -d_ct,
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
                                             "teamkill": 0.0, "n": 0, "rounds": {}, "ctx": {}})
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
                                    "other": ev.get("victim") if kind in ("kill", "teamkill") else ev.get("attacker")
                                    if kind == "death" else None})
    # Vergleichswert je Lage: Durchschnitt aller Spieler dieses Matches. Kill und Tod haben verschiedene Lagen
    # (Opfer meist in Unterzahl, Schütze in Überzahl), deshalb ist 0 NICHT der Durchschnitt.
    ctx_avg: dict[str, list] = {}
    for p in players.values():
        for c, (v, k) in p["ctx"].items():
            a = ctx_avg.setdefault(c, [0.0, 0])
            a[0] += v
            a[1] += k
    n_pl = len(players) or 1
    ctx_avg = {c: [round(v / n_pl, 1), round(k / n_pl, 2)] for c, (v, k) in ctx_avg.items()}
    n_rounds = len(per_round) or 1
    for p in players.values():
        p["ctx_avg"] = ctx_avg
        p["per_round"] = round(p["total"] / n_rounds, 1)
        for k in ("total", "kill", "death", "plant", "defuse", "teamkill"):
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
           # je Match ein Balken (Höhe relativ zum größten Betrag, -1..1), für den Trend auf "Fortschritt"
           "bars": [{"h": round(v / top, 3), "s": de(v), "map": (h.get("map") or "?").removeprefix("de_").capitalize()}
                    for (h, _), v in zip(rows, per)],
           "top1": sum(1 for r in ranks if r == 1), "ranked": len(ranks),
           "avg_rank": round(sum(ranks) / len(ranks), 1) if ranks else None,
           "rank_s": rank_text([(x["rank"], x.get("of")) for _, x in rows if x.get("rank")])}
    out["trend"] = None
    if n >= 6:
        old, new = rows[: n // 2], rows[n // 2:]
        a = sum(x["total"] for _, x in old) / sum(h["rounds"] for h, _ in old)
        b = sum(x["total"] for _, x in new) / sum(h["rounds"] for h, _ in new)
        out["trend"] = "besser" if b - a >= 1.5 else "schlechter" if a - b >= 1.5 else "gleich"
        out["trend_s"] = f"{de(a)} → {de(b)} Punkte je Runde"
    out["ctx"], out["ctx_reading"] = contexts(rows)
    out["ctx_min"] = MIN_CTX
    return out


def rank_text(ranks: list[tuple[int, int | None]]) -> str | None:
    """"Platz 6 von 10" (ein Match) oder "im Schnitt Platz 5,5 von 10" (mehrere). Ohne Platz: None."""
    if not ranks:
        return None
    ofs = {o for _r, o in ranks if o}
    of = f" von {ofs.pop()}" if len(ofs) == 1 else ""
    if len(ranks) == 1:
        return f"Platz {ranks[0][0]}{of}"
    avg = sum(r for r, _o in ranks) / len(ranks)
    avg_s = str(int(avg)) if avg == int(avg) else f"{avg:.1f}".replace(".", ",")
    return f"im Schnitt Platz {avg_s}{of}"


MIN_CTX = 10  # so viele Ereignisse braucht eine Lage für eine Aussage


def contexts(rows: list[tuple[dict, dict]]) -> tuple[list[dict], str | None]:
    """Impact nach Lage über die Matches, je Match gegen den Durchschnitt aller Spieler derselben Matches
    (``ctx_avg``). Positiv = in dieser Lage besser als ein durchschnittlicher Spieler eurer Matches."""
    rows = [(h, x) for h, x in rows if x.get("ctx") and x.get("ctx_avg")]  # ältere Einträge ohne Lage/Vergleich
    n = len(rows)
    if not n:
        return [], None
    agg: dict[str, list] = {}
    for _h, x in rows:
        for ctx in set(x["ctx"]) | set(x["ctx_avg"]):
            v, k = x["ctx"].get(ctx, (0.0, 0))
            bv = x["ctx_avg"].get(ctx, (0.0, 0))[0]
            a = agg.setdefault(ctx, [0.0, 0, 0.0])
            a[0] += v
            a[1] += k
            a[2] += bv
    out = []
    for ctx, (v, k, bv) in agg.items():
        if ctx not in CTX_DE or not k:
            continue
        diff = (v - bv) / 100 / n
        out.append({"ctx": ctx, "label": CTX_DE[ctx], "n": k, "per_match": diff, "per_match_s": de(diff),
                    "per_event_s": de(v / k), "enough": k >= MIN_CTX})
    out.sort(key=lambda c: c["per_match"])
    sure = [c for c in out if c["enough"] and c["ctx"] != "bomb"]
    parts = []
    if sure and sure[0]["per_match"] <= -0.15:
        w = sure[0]
        parts.append(f"Am meisten Runden verlierst du {CTX_IN[w['ctx']]}: {de(-w['per_match']).lstrip('+')} Runden pro "
                     f"Match unter dem Schnitt, aus {w['n']} Kills und Toden. Tipp: {CTX_TIP[w['ctx']]}")
    if sure and sure[-1]["per_match"] >= 0.15:
        b = sure[-1]
        parts.append(f"Am meisten holst du {CTX_IN[b['ctx']]}: {de(b['per_match']).lstrip('+')} Runden pro Match über dem "
                     f"Schnitt, aus {b['n']} Kills und Toden.")
    return out, " ".join(parts) or None


KIND_DE = {"kill": "Kill", "death": "Tod", "plant": "Bombe gelegt", "defuse": "Entschärft", "teamkill": "Teamkill"}


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
                txt += f" gegen {m['other']}" if m["kind"] in ("kill", "teamkill") else f" durch {m['other']}" if m["kind"] == "death" else ""
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
    note = (f"{common[1]} deiner {len(worst)} teuersten Momente fallen in diese Lage: {common[0]}." if common and common[1] >= 3 else None)
    return {"best": best, "worst": worst, "note": note, "n": len(rows)}


def de(x: float) -> str:
    return (f"+{x:.1f}" if x > 0 else f"{x:.1f}").replace(".", ",")
