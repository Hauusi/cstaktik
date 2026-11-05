"""Was der Coach über deine Entscheidungen weiß: Muster aus allen Szenen, die du in Session und Warm-up entschieden hast.

Grundlage: drills "answers" (je Szene deine letzte Wahl, ob sie zur Wahl der Pros passte, deine Begründung) und die
Szene im Verlauf (Lage: eigene gegen Gegner lebend, Lektion). Aussagen erst ab MIN_N Szenen je Gruppe; "Pros" nur,
wo eine Pro-Wahl vorliegt. Keine Wertung der Person, nur der Entscheidungen.
"""

from __future__ import annotations

from collections import Counter

from cstaktik import drills

MIN_N = 5
CHOICE_DE = {"gehalten": "Halten", "zurückgezogen": "Zurückziehen", "Richtung Gegner": "Peeken"}


def _situation(sc: dict) -> str | None:
    snap = sc.get("snap") or {}
    own, enemy = snap.get("own"), snap.get("enemy")
    if own is None or enemy is None:
        return None
    return "unterzahl" if own < enemy else "ueberzahl" if own > enemy else "gleich"


SIT_DE = {"unterzahl": "In Unterzahl", "ueberzahl": "In Überzahl", "gleich": "Bei gleicher Zahl"}


def decisions(hist: list[dict], sid: str) -> dict:
    """Je Lage: Anzahl, häufigste Wahl, wie oft wie die Pros. Dazu Begründungen (worauf es ankam getroffen)."""
    scenes = {drills.scene_key(x): x for h in hist for x in h.get("scenes") or [] if x.get("sid") == sid}
    answers = drills.load(sid).get("answers") or {}
    groups: dict[str, list[dict]] = {}
    cue = []
    for key, rows in answers.items():
        if not rows or key not in scenes:
            continue
        last = rows[-1]
        sit = _situation(scenes[key])
        if sit:
            groups.setdefault(sit, []).append({**last, "best": scenes[key].get("pro_best")})
        if last.get("cue_ok") is not None:
            cue.append(last["cue_ok"])
    out = {"n": sum(len(v) for v in groups.values()), "groups": {}, "cue": None}
    for sit, rows in groups.items():
        c = Counter(r["choice"] for r in rows)
        top, k = c.most_common(1)[0]
        with_pro = [r for r in rows if r.get("ok") is not None]
        best = Counter(r["best"] for r in rows if r.get("best"))
        out["groups"][sit] = {"n": len(rows), "top": top, "top_n": k, "pro_n": len(with_pro),
                              "pro_ok": sum(1 for r in with_pro if r["ok"]),
                              "pro_top": best.most_common(1)[0][0] if best else None}
    if len(cue) >= MIN_N:
        out["cue"] = {"n": len(cue), "ok": sum(cue)}
    return out


def lines(hist: list[dict], sid: str) -> list[str]:
    """Sätze für Session und Warm-up: höchstens zwei, die auffälligsten zuerst."""
    d = decisions(hist, sid)
    out = []
    for sit in ("unterzahl", "ueberzahl", "gleich"):
        g = d["groups"].get(sit)
        if not g or g["n"] < MIN_N:
            continue
        s = f"{SIT_DE[sit]} entscheidest du dich in {g['top_n']} von {g['n']} Szenen für „{CHOICE_DE.get(g['top'], g['top'])}“."
        if g["pro_n"] >= MIN_N:
            s += f" Wie die Pros warst du in {g['pro_ok']} von {g['pro_n']}."
            if g["pro_top"] and g["pro_top"] != g["top"] and g["pro_ok"] * 2 < g["pro_n"]:
                s += f" Die Pros wählen dort meistens „{CHOICE_DE.get(g['pro_top'], g['pro_top'])}“."
        out.append((g["pro_ok"] / g["pro_n"] if g["pro_n"] else 1.0, s))
    out.sort(key=lambda x: x[0])  # wo du am weitesten von den Pros weg bist, zuerst
    res = [s for _, s in out[:2]]
    if d["cue"]:
        c = d["cue"]
        res.append(f"Bei der Frage, worauf es ankommt, lagst du in {c['ok']} von {c['n']} Szenen richtig."
                   + (" Du liest die Lagen gut." if c["ok"] * 3 >= c["n"] * 2 else " Da steckt noch Potenzial."))
    return res
