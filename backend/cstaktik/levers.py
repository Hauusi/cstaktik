"""Eure größten Hebel: alles, was sich in Runden messen lässt, auf eine Einheit gebracht (Runden pro Match).

- Clutch: erwartete Siege nach Pro-Quote derselben Lage minus eigene Siege, je Match.
- Fehler (Coach-Lektionen): Summe der verlorenen Rundenchance der Szenen (situation.cost_pct, Prozentpunkte) je Match.
  Bedeutung: "verlorene Rundenchance bei diesen Toden", kein Beweis, dass genau diese Runden sonst gewonnen wären.
  Nur ab ``MIN_SCENES`` Szenen aus ``MIN_MATCHES`` Matches.
- Kauf, nach dem Plant, Retake, Taktikart (nur Full Buy, damit der Kauf nicht doppelt zählt): eure Runden dieser Art
  je Match mal Abstand der Siegquote zu den Pros.
  Bedeutung: "wenn ihr diese Runden so oft gewinnen würdet wie Pros, etwa so viele Runden mehr pro Match".
Beides sind Rechnungen aus euren Demos, keine Garantie; es werden nur Werte mit genug Runden verwendet.
Duell-Werte (Fadenkreuz, Sichtung) sind in Duellen gemessen, nicht in Runden, und stehen deshalb nicht in der Liste.

Ehrlichkeit bei wenig Daten:
- Mindestzahlen: eigene Runden je Hebel (``MIN_OWN``), Pro-Runden (``MIN_PRO``).
- Überschneidung: Dieselbe Runde kann in mehreren Hebeln stecken (Full Buy auf T, erster Tod auf T, Default auf T).
  Die Hebel werden nach Größe abgearbeitet; ein späterer zählt nur mit dem Anteil seiner Runden, die noch in keinem
  größeren Hebel stecken. Ist weniger als die Hälfte neu, fällt er weg. So addieren sich die Zahlen nicht doppelt.
- Weniger als ``MIN_MATCHES`` Matches: höchstens ein Hebel, als Tendenz gekennzeichnet.
"""

from __future__ import annotations

from cstaktik import playbook
from cstaktik.coach_voice import LESSONS

WINDOW = 10  # letzte Matches des Spielers
MIN_GAIN = 0.2  # kleinere Hebel sind Rauschen
MIN_SCENES = 4  # Fehler-Hebel: so viele Szenen mit Rundenchance ...
MIN_MATCHES = 2  # ... aus mindestens so vielen Matches; darunter höchstens ein Hebel
MIN_OWN = 8  # eigene Runden je Hebel
MIN_PRO = 8  # Pro-Runden je Vergleich
MIN_NEW = 0.5  # so viel Anteil eigener Runden muss ein Hebel neu beitragen


def _gap(own: dict | None, pro: dict | None, per_match: float, min_n: int) -> float | None:
    if not own or not pro or own["n"] < min_n or pro["n"] < max(min_n, MIN_PRO):
        return None
    return per_match * own["n"] * (pro["won_pct"] - own["won_pct"]) / 100


def _rkey(i: int, side: str, j: int, p: dict) -> tuple:
    """Runde eindeutig: Match-Index und Rundennummer (ohne Nummer: Position in der Liste)."""
    return (i, p["r"]) if p.get("r") is not None else (i, side, j)


def _rounds(hs: list[dict], side: str, pick) -> set:
    key = playbook.SIDE_KEYS[side][0]
    return {_rkey(i, side, j, p) for i, h in enumerate(hs) for j, p in enumerate(h.get(key) or [])
            if "won" in p and pick(p)}


def _first_side(p: dict) -> str | None:
    kills = [k for k in p.get("kills") or [] if k.get("t") is not None]
    return min(kills, key=lambda k: k["t"])["side"] if kills else None


def _pp_key(p: dict, side: str) -> str | None:
    if p.get("plant_t") is None or "kills" not in p:
        return None
    dead = [k for k in p["kills"] if k["t"] <= p["plant_t"]]
    t = 5 - sum(k["side"] == "t" for k in dead)
    ct = 5 - sum(k["side"] == "ct" for k in dead)
    mine, theirs = (t, ct) if side == "t" else (ct, t)
    return "up" if mine > theirs else "even" if mine == theirs else "down"


def _pro_basis(pro: list[dict], side: str, n: int) -> str:
    key = playbook.SIDE_KEYS[side][0]
    demos = sum(1 for d in pro if d.get(key))
    return f"Pros: {{pct}} % ({n} Runden aus {demos} Demo{'s' if demos != 1 else ''})"


def build(hist: list[dict], pro: list[dict], sid: str, cfg: dict | None = None, top: int = 3) -> list[dict]:
    hs = [h for h in hist if sid in h.get("players", {})][-WINDOW:]
    if not hs:
        return []
    per = 1 / len(hs)
    out = []
    # Fehler: verlorene Rundenchance je Match
    cost: dict[str, float] = {}
    scenes: dict[str, int] = {}
    matches: dict[str, set] = {}
    rounds_of: dict[str, set] = {}
    for i, h in enumerate(hs):
        for sc in h.get("scenes", []):
            if sc.get("sid") == sid and sc.get("cost") and sc.get("lesson") in LESSONS and sc["lesson"] != "duel":
                cost[sc["lesson"]] = cost.get(sc["lesson"], 0) + max(0, sc["cost"]) / 100
                scenes[sc["lesson"]] = scenes.get(sc["lesson"], 0) + 1
                matches.setdefault(sc["lesson"], set()).add(i)
                if sc.get("round") is not None:
                    rounds_of.setdefault(sc["lesson"], set()).add((i, sc["round"]))
    for lid, c in cost.items():
        if scenes[lid] < MIN_SCENES or len(matches[lid]) < MIN_MATCHES:
            continue  # zu wenige Szenen: eine Zahl daraus wäre Zufall
        out.append({"kind": "Fehler", "gain": c * per, "title": LESSONS[lid][0], "link": "/training",
                    "rounds": rounds_of.get(lid, set()),
                    "text": f"Verlorene Rundenchance bei diesen Toden: im Schnitt etwa {_de(c * per)} Runden pro Match, "
                            f"aus {scenes[lid]} Szenen in {len(matches[lid])} Matches. Eine Rechnung, keine Garantie."})
    for side in ("t", "ct"):
        S = side.upper()
        eq_key = playbook.SIDE_KEYS[side][1]
        own_b, pro_b = playbook.buy_mix(hs, cfg, side), playbook.buy_mix(pro, cfg, side)
        for k, lbl in playbook.BUY_LABEL.items():
            g = _gap(own_b["buys"].get(k), pro_b["buys"].get(k), per, MIN_OWN)
            if g:
                o, q = own_b["buys"][k], pro_b["buys"][k]
                rs = _rounds(hs, side, lambda p, k=k: playbook.buy_of(p.get(eq_key), p.get("pistol", False), cfg) == k)
                out.append({"kind": "Kauf", "gain": g, "title": f"{lbl} auf {S}", "link": "/progress", "rounds": rs,
                            "text": f"Ihr gewinnt {o['won_pct']} % dieser Runden, {o['won']} von {o['n']}. "
                                    + _pro_basis(pro, side, q["n"]).format(pct=q["won_pct"]) + "."})
        own_f, pro_f = playbook.firstblood_mix(hs, side), playbook.firstblood_mix(pro, side)
        for k, lbl in playbook.FIRSTBLOOD:
            g = _gap(own_f["rows"].get(k), pro_f["rows"].get(k), per, MIN_OWN)
            if g:
                o, q = own_f["rows"][k], pro_f["rows"][k]
                want = side if k == "against" else ("ct" if side == "t" else "t")
                rs = _rounds(hs, side, lambda p, want=want: _first_side(p) == want)
                out.append({"kind": "Erster Kill", "gain": g, "title": f"{lbl} auf {S}", "link": "/progress",
                            "rounds": rs,
                            "text": f"Ihr gewinnt {o['won_pct']} % dieser Runden, {o['won']} von {o['n']}. "
                                    + _pro_basis(pro, side, q["n"]).format(pct=q["won_pct"]) + "."})
        own_p, pro_p = playbook.postplant_mix(hs, side), playbook.postplant_mix(pro, side)
        for k, lbl in playbook.POSTPLANT:
            g = _gap(own_p["rows"].get(k), pro_p["rows"].get(k), per, MIN_OWN)
            if g:
                o, q = own_p["rows"][k], pro_p["rows"][k]
                what = "Bombe halten" if side == "t" else "Retake"
                rs = _rounds(hs, side, lambda p, k=k, side=side: _pp_key(p, side) == k)
                out.append({"kind": "Nach dem Plant", "gain": g, "title": f"{what} in {lbl}", "link": "/progress",
                            "rounds": rs,
                            "text": f"Ihr gewinnt {o['won_pct']} % dieser Runden, {o['won']} von {o['n']}. "
                                    + _pro_basis(pro, side, q["n"]).format(pct=q["won_pct"]) + "."})
    # Clutch: eigene Siege gegen die Pro-Erwartung in denselben Lagen (Seite, Gegnerzahl, Bombe)
    from cstaktik import clutch

    cl = clutch.summary(hs, sid, pro)
    if cl and cl["exp"] is not None and cl["exp_n"] >= max(clutch.MIN_OWN, 5):
        rs = {(i, c["round"]) for i, h in enumerate(hs) for c in h.get("clutch") or []
              if c.get("sid") == sid and c.get("round") is not None}
        out.append({"kind": "Clutch", "gain": (cl["exp"] - cl["won_cmp"]) * per, "title": "Clutches als Letzter",
                    "link": "/progress", "rounds": rs,
                    "text": f"Du hast {cl['won_cmp']} von {cl['exp_n']} gewonnen. Pros hätten in "
                            f"denselben Lagen etwa {_de(cl['exp'])} gewonnen."})
    # Taktikart auf T über alle Maps, nur Full-Buy-Runden: sonst zählt ein schlechter Kauf doppelt (Kauf und Taktik)
    def full_only(src):
        return [{**d, "plays": [p for p in d.get("plays") or []
                                if playbook.buy_of(p.get("t_eq"), p.get("pistol", False), cfg) == "full"]} for d in src]

    hs_full, pro_full = full_only(hs), full_only(pro)
    maps = {h.get("map") for h in hs if h.get("map")}
    styles: dict[str, dict] = {}
    for m in maps:
        for st, v in playbook.style_mix(hs_full, m, cfg)["styles"].items():
            e = styles.setdefault(st, {"label": v["label"], "n": 0, "won": 0})
            e["n"], e["won"] = e["n"] + v["n"], e["won"] + v["won"]
    pro_st = {}
    for m in {d.get("map") for d in pro_full if d.get("map")}:
        for st, v in playbook.style_mix(pro_full, m, cfg)["styles"].items():
            e = pro_st.setdefault(st, {"n": 0, "won": 0})
            e["n"], e["won"] = e["n"] + v["n"], e["won"] + v["won"]
    c = {**playbook.DEFAULTS, **(cfg or {})}
    for st, o in styles.items():
        q = pro_st.get(st)
        if not q:
            continue
        o["won_pct"], q["won_pct"] = round(100 * o["won"] / o["n"]), round(100 * q["won"] / q["n"])
        g = _gap(o, q, per, MIN_OWN)
        if g:
            rs = {(i, p["r"]) if p.get("r") is not None else (i, "t", j) for i, h in enumerate(hs_full)
                  for j, p in enumerate(h.get("plays") or [])
                  if p.get("site") and "won" in p and playbook.classify(p, c)["style"] == st}
            out.append({"kind": "Taktik", "gain": g, "title": f"{o['label']} auf T", "link": "/playbook", "rounds": rs,
                        "text": f"Mit vollem Kauf gewinnt ihr {o['won_pct']} % eurer {o['label']}-Runden, {o['won']} von {o['n']}. "
                                + _pro_basis(pro_full, "t", q["n"]).format(pct=q["won_pct"])
                                + ". Tipp: Schaut im Playbook, wie Pros das spielen."})
    out = dedupe([x for x in out if x["gain"] >= MIN_GAIN])
    thin = len(hs) < MIN_MATCHES
    if thin:
        out = out[:1]
    for x in out:
        x["gain_s"] = _de(x["gain"])
        x["n_rounds"] = len(x.pop("rounds"))
        if thin:
            x["thin"] = True
            x["text"] += " Erst 1 Match: eine Tendenz, noch kein Urteil."
    return out[:top] if top else out


def dedupe(levers: list[dict]) -> list[dict]:
    """Größter Hebel zuerst; jeder weitere zählt nur mit dem Anteil seiner Runden, die noch frei sind."""
    used: set = set()
    out = []
    for x in sorted(levers, key=lambda x: -x["gain"]):
        rs = x.get("rounds") or set()
        if rs:
            new = rs - used
            share = len(new) / len(rs)
            if share < MIN_NEW:
                continue
            if share < 1:
                x = {**x, "gain": x["gain"] * share,
                     "text": x["text"] + f" {len(rs) - len(new)} dieser Runden stecken schon im Hebel darüber und "
                                         "zählen hier nicht noch einmal."}
            used |= rs
        if x["gain"] >= MIN_GAIN:
            out.append(x)
    out.sort(key=lambda x: -x["gain"])
    return out


def _de(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")
