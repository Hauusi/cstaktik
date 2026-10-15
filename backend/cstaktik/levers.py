"""Eure größten Hebel: alles, was sich in Runden messen lässt, auf eine Einheit gebracht (Runden pro Match).

- Fehler (Coach-Lektionen): Summe der verlorenen Rundenchance der Szenen (situation.cost_pct, Prozentpunkte) je Match.
  Bedeutung: "kostet euch etwa so viele Runden pro Match".
- Kauf, nach dem Plant, Retake, Taktikart (nur Full Buy, damit der Kauf nicht doppelt zählt): eure Runden dieser Art
  je Match mal Abstand der Siegquote zu den Pros.
  Bedeutung: "wenn ihr diese Runden so oft gewinnen würdet wie Pros, etwa so viele Runden mehr pro Match".
Beides sind Rechnungen aus euren Demos, keine Garantie; es werden nur Werte mit genug Runden verwendet.
Duell-Werte (Fadenkreuz, Sichtung) sind in Duellen gemessen, nicht in Runden, und stehen deshalb nicht in der Liste.
"""

from __future__ import annotations

from cstaktik import playbook
from cstaktik.coach_voice import LESSONS

WINDOW = 10  # letzte Matches des Spielers
MIN_GAIN = 0.2  # kleinere Hebel sind Rauschen


def _gap(own: dict | None, pro: dict | None, per_match: float, min_n: int) -> float | None:
    if not own or not pro or own["n"] < min_n or pro["n"] < min_n:
        return None
    return per_match * own["n"] * (pro["won_pct"] - own["won_pct"]) / 100


def build(hist: list[dict], pro: list[dict], sid: str, cfg: dict | None = None, top: int = 3) -> list[dict]:
    hs = [h for h in hist if sid in h.get("players", {})][-WINDOW:]
    if not hs:
        return []
    per = 1 / len(hs)
    out = []
    # Fehler: verlorene Rundenchance je Match
    cost: dict[str, float] = {}
    for h in hs:
        for sc in h.get("scenes", []):
            if sc.get("sid") == sid and sc.get("cost") and sc.get("lesson") in LESSONS and sc["lesson"] != "duel":
                cost[sc["lesson"]] = cost.get(sc["lesson"], 0) + max(0, sc["cost"]) / 100
    for lid, c in cost.items():
        out.append({"kind": "Fehler", "gain": c * per, "title": LESSONS[lid][0], "link": "/training",
                    "text": f"Kostet euch etwa {_de(c * per)} Runden pro Match (verlorene Rundenchance in diesen Szenen)."})
    for side in ("t", "ct"):
        S = side.upper()
        own_b, pro_b = playbook.buy_mix(hs, cfg, side), playbook.buy_mix(pro, cfg, side)
        for k, lbl in playbook.BUY_LABEL.items():
            g = _gap(own_b["buys"].get(k), pro_b["buys"].get(k), per, 8)
            if g:
                o, q = own_b["buys"][k], pro_b["buys"][k]
                out.append({"kind": "Kauf", "gain": g, "title": f"{lbl} auf {S}", "link": "/progress",
                            "text": f"Ihr gewinnt {o['won_pct']} % ({o['won']} von {o['n']}), Pros {q['won_pct']} %."})
        own_f, pro_f = playbook.firstblood_mix(hs, side), playbook.firstblood_mix(pro, side)
        for k, lbl in playbook.FIRSTBLOOD:
            g = _gap(own_f["rows"].get(k), pro_f["rows"].get(k), per, 8)
            if g:
                o, q = own_f["rows"][k], pro_f["rows"][k]
                out.append({"kind": "Erster Kill", "gain": g, "title": f"{lbl} auf {S}", "link": "/progress",
                            "text": f"Ihr gewinnt {o['won_pct']} % dieser Runden ({o['won']} von {o['n']}), Pros "
                                    f"{q['won_pct']} %."})
        own_p, pro_p = playbook.postplant_mix(hs, side), playbook.postplant_mix(pro, side)
        for k, lbl in playbook.POSTPLANT:
            g = _gap(own_p["rows"].get(k), pro_p["rows"].get(k), per, 6)
            if g:
                o, q = own_p["rows"][k], pro_p["rows"][k]
                what = "Bombe halten" if side == "t" else "Retake"
                out.append({"kind": "Nach dem Plant", "gain": g, "title": f"{what} in {lbl}", "link": "/progress",
                            "text": f"Ihr gewinnt {o['won_pct']} % ({o['won']} von {o['n']}), Pros {q['won_pct']} %."})
    # Taktikart auf T über alle Maps, nur Full-Buy-Runden: sonst zählt ein schlechter Kauf doppelt (Kauf und Taktik)
    def full_only(src):
        return [{**d, "plays": [p for p in d.get("plays") or []
                                if playbook.buy_of(p.get("t_eq"), p.get("pistol", False), cfg) == "full"]} for d in src]

    hs_full, pro = full_only(hs), full_only(pro)
    maps = {h.get("map") for h in hs if h.get("map")}
    styles: dict[str, dict] = {}
    for m in maps:
        for st, v in playbook.style_mix(hs_full, m, cfg)["styles"].items():
            e = styles.setdefault(st, {"label": v["label"], "n": 0, "won": 0})
            e["n"], e["won"] = e["n"] + v["n"], e["won"] + v["won"]
    pro_st = {}
    for m in {d.get("map") for d in pro if d.get("map")}:
        for st, v in playbook.style_mix(pro, m, cfg)["styles"].items():
            e = pro_st.setdefault(st, {"n": 0, "won": 0})
            e["n"], e["won"] = e["n"] + v["n"], e["won"] + v["won"]
    for st, o in styles.items():
        q = pro_st.get(st)
        if not q:
            continue
        o["won_pct"], q["won_pct"] = round(100 * o["won"] / o["n"]), round(100 * q["won"] / q["n"])
        g = _gap(o, q, per, 6)
        if g:
            out.append({"kind": "Taktik", "gain": g, "title": f"{o['label']} auf T", "link": "/playbook",
                        "text": f"Mit vollem Kauf gewinnt ihr {o['won_pct']} % eurer {o['label']}-Runden ({o['won']} von {o['n']}), "
                                f"Pros {q['won_pct']} %. Im Playbook ansehen, wie Pros das spielen."})
    out = [x for x in out if x["gain"] >= MIN_GAIN]
    out.sort(key=lambda x: -x["gain"])
    for x in out:
        x["gain_s"] = _de(x["gain"])
    return out[:top] if top else out


def _de(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")
