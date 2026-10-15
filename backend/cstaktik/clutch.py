"""Clutch-Bilanz: Runden, in denen ein Spieler als Letzter seines Teams gegen 1+ Gegner übrig ist.

Eigene Clutches kommen je Spieler aus der Kill-Reihenfolge (``clutches``, im Verlauf gespeichert). Der Pro-Vergleich
nutzt die gespeicherten Rundenzustände der Pro-Demos (``states``: [ct, t, gelegt] in Reihenfolge, ``w`` = Sieger): Der
erste Zustand mit 1 gegen k ist der Clutch-Start. Daraus die Pro-Siegquote je Seite, Gegnerzahl und Bombe.

Vergleich ehrlich über "erwartete Siege": Für jeden eigenen Clutch die Pro-Quote derselben Lage, summiert. Das ist
schwerer fair zu verzerren als eine Gesamtquote, weil 1v1 und 1v4 nicht vermischt werden.
"""

from __future__ import annotations

from collections import defaultdict

from cstaktik.model import MatchData

MIN_PRO = 10  # so viele Pro-Fälle braucht eine Lage für eine Pro-Quote
MIN_OWN = 5  # so viele eigene Clutches braucht eine Aussage


def clutches(match: MatchData, team: set[str] | None = None) -> list[dict]:
    """Je Clutch: Spieler, Seite, Gegnerzahl beim Start, Bombe beim Start, Ausgang, Kills, ob gelegt/entschärft.

    Kills im selben Tick werden gemeinsam verbucht, damit ein gleichzeitiger Doppeltod keine falsche Lage erzeugt.
    """
    out = []
    tr = match.tickrate or 64
    for r in match.rounds:
        if r.winner is None or not r.sides:
            continue
        alive = {sd: {s for s, x in r.sides.items() if x == sd} for sd in ("ct", "t")}
        # nur bis Rundenende: danach (Gegner retten Waffen) gibt es keinen Clutch mehr
        bomb = [b for b in match.bomb if b.round == r.num and b.event in ("plant", "defuse") and b.tick <= r.end_tick]
        kills = [k for k in match.kills if k.round == r.num and k.tick <= r.end_tick]
        ticks = sorted({k.tick for k in kills} | {b.tick for b in bomb})
        planted, started = False, {}
        for t in ticks:
            for b in bomb:
                if b.tick == t and b.event == "plant":
                    planted = True
            for k in kills:
                if k.tick == t:
                    alive["ct"].discard(k.victim_steamid)
                    alive["t"].discard(k.victim_steamid)
            for sd, other in (("ct", "t"), ("t", "ct")):
                if sd not in started and len(alive[sd]) == 1 and alive[other]:
                    started[sd] = {"sid": next(iter(alive[sd])), "side": sd, "vs": len(alive[other]),
                                   "planted": planted, "tick": t}
        for sd, c in started.items():
            if team is not None and c["sid"] not in team:
                continue
            # Tod auch nach Rundenende zählen: wer dann noch gejagt wird, hat die Waffe nicht gerettet
            death = next((k.tick for k in match.kills if k.round == r.num and k.victim_steamid == c["sid"]
                          and k.tick >= c["tick"]), None)
            row = {"sid": c["sid"], "round": r.num, "side": sd, "vs": c["vs"], "planted": c["planted"],
                   "won": r.winner == sd,
                   "kills": sum(1 for k in kills if k.attacker_steamid == c["sid"] and k.tick > c["tick"]
                                and k.victim_side and k.victim_side != sd),
                   "alive": death is None}
            if sd == "t" and not c["planted"]:
                row["plant"] = any(b.event == "plant" and b.tick > c["tick"] for b in bomb)
            if sd == "ct" and c["planted"]:
                row["defuse"] = any(b.event == "defuse" and b.steamid == c["sid"] for b in bomb)
            if death is not None:
                row["life_s"] = round((death - c["tick"]) / tr, 1)
            out.append(row)
    return out


def _vs(k: int) -> int:
    return min(k, 3)  # 1v3, 1v4, 1v5 zusammen: sonst zu wenig Fälle


def pro_rates(pros: list[dict]) -> dict:
    """Pro-Quoten aus Rundenzuständen: (Seite, vs, gelegt) -> [n, gewonnen]; T ohne Bombe: wie oft noch gelegt."""
    rates: dict = defaultdict(lambda: [0, 0])
    plant = [0, 0]  # T-Clutch ohne Bombe beim Start: [n, danach gelegt]
    for d in pros:
        for rnd in d.get("states") or []:
            s, w = rnd.get("s") or [], rnd.get("w")
            for sd, i, j in (("ct", 0, 1), ("t", 1, 0)):
                start = next((x for x in s if x[i] == 1 and x[j] >= 1), None)
                if start is None:
                    continue
                key = (sd, _vs(start[j]), bool(start[2]))
                rates[key][0] += 1
                rates[key][1] += w == sd
                if sd == "t" and not start[2]:
                    plant[0] += 1
                    plant[1] += any(x[2] for x in s[s.index(start):])
    return {"rates": dict(rates), "plant": plant}


def _pct(a: int, b: int) -> int | None:
    return round(100 * a / b) if b else None


def summary(hist: list[dict], sid: str, pros: list[dict]) -> dict | None:
    """Clutch-Bilanz eines Spielers über alle Matches im Verlauf, mit Pro-Quote je Lage und erwarteten Siegen."""
    own = [c for h in hist for c in h.get("clutch") or [] if c.get("sid") == sid]
    if not own:
        return None
    pro = pro_rates(pros)
    rows = []
    for vs in (1, 2, 3):
        mine = [c for c in own if _vs(c["vs"]) == vs]
        pn = sum(v[0] for (sd, k, _p), v in pro["rates"].items() if k == vs)
        pw = sum(v[1] for (sd, k, _p), v in pro["rates"].items() if k == vs)
        if mine or pn >= MIN_PRO:
            rows.append({"label": f"1 gegen {vs}" if vs < 3 else "1 gegen 3+", "n": len(mine),
                         "won": sum(c["won"] for c in mine), "won_pct": _pct(sum(c["won"] for c in mine), len(mine)),
                         "pro_pct": _pct(pw, pn) if pn >= MIN_PRO else None, "pro_n": pn})
    exp, exp_n = 0.0, 0  # erwartete Siege nach Pro-Quote derselben Lage (Seite, Gegner, Bombe)
    for c in own:
        n, w = pro["rates"].get((c["side"], _vs(c["vs"]), bool(c["planted"])), (0, 0))
        if n >= MIN_PRO:
            exp += w / n
            exp_n += 1
    won = sum(c["won"] for c in own)
    won_cmp = sum(c["won"] for c in own
                  if pro["rates"].get((c["side"], _vs(c["vs"]), bool(c["planted"])), (0, 0))[0] >= MIN_PRO)
    t_np = [c for c in own if c["side"] == "t" and not c["planted"] and "plant" in c]
    lost_alive = sum(1 for c in own if not c["won"] and c["alive"])
    out = {"n": len(own), "won": won, "won_pct": _pct(won, len(own)), "kills": sum(c["kills"] for c in own),
           "rows": rows, "exp": round(exp, 1) if exp_n else None, "exp_n": exp_n, "won_cmp": won_cmp,
           "saved": lost_alive, "lost": len(own) - won,
           "t_plant": {"n": len(t_np), "planted": sum(c["plant"] for c in t_np),
                       "pro_pct": _pct(pro["plant"][1], pro["plant"][0]) if pro["plant"][0] >= MIN_PRO else None}}
    out["reading"] = reading(out)
    return out


def reading(s: dict) -> str | None:
    """Ein Satz Bewertung, nur mit genug Fällen und Pro-Vergleich; sonst None."""
    parts = []
    if s["exp"] is not None and s["exp_n"] >= MIN_OWN:
        diff = s["won_cmp"] - s["exp"]
        base = (f"{s['won_cmp']} von {s['exp_n']} Clutches gewonnen; Pros hätten in denselben Lagen im Schnitt "
                f"{str(s['exp']).replace('.', ',')} gewonnen")
        if diff <= -1.5:
            parts.append(base + ". Hier lässt du Runden liegen: im Clutch Zeit nutzen, Gegner einzeln nehmen, "
                         "nicht in zwei gleichzeitig laufen.")
        elif diff >= 1.5:
            parts.append(base + ". Clutches sind eine Stärke von dir.")
        else:
            parts.append(base + ", also etwa Pro-Niveau.")
    tp = s["t_plant"]
    if tp["n"] >= MIN_OWN and tp["pro_pct"] is not None:
        mine = _pct(tp["planted"], tp["n"])
        if mine is not None and tp["pro_pct"] - mine >= 20:
            parts.append(f"Als letzter T ohne gelegte Bombe legst du nur in {mine} % der Fälle noch "
                         f"(Pros {tp['pro_pct']} %). Mit Bombe am Boden muss der Gegner zu dir kommen.")
    return " ".join(parts) or None
