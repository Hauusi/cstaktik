"""Tilt-Check: spielst du nach verlorenen Runden anders?

Je Runde der Zustand davor aus eurer Sicht: nach mindestens zwei Niederlagen in Folge ("nach Serie"), nach einer
gewonnenen Runde oder sonst. Verglichen werden, was in den Demos steht: Impact je Runde (impact.py), wie oft du als
Erster der Runde stirbst und wie oft ohne Trade. Pistolenrunden (1. Runde jeder Hälfte) zählen nicht, weil davor
nichts lief bzw. die Seite wechselt. Ein Unterschied ist ein Zusammenhang, kein Beweis; deshalb erst ab
genug Runden je Gruppe und mit klaren Schwellen.

Impact je Runde: Der Verlauf speichert nur Runden, in denen der Spieler einen bewerteten Wert bekam. Fehlt eine
Runde, in der er gestorben ist, war sein Tod nicht bewertbar (zu wenig Vergleichsrunden, Bombe, falsches
Vorzeichen): Impact unbekannt, die Runde fällt aus dem Impact-Schnitt. Fehlt eine Runde ohne Tod, lässt sich aus
den gespeicherten Daten nicht unterscheiden, ob er dort nichts bewirkt hat oder ein Kill nicht bewertbar war; sie
zählt weiter als 0.
"""

from __future__ import annotations

MIN_ROUNDS = 25  # so viele Runden braucht jede Gruppe
STREAK = 2  # Niederlagen in Folge, ab der eine Runde als "nach Serie" gilt
IMPACT_GAP = 2.0  # Punkte Siegchance je Runde Unterschied, ab dem es auffällt
FIRST_GAP = 8  # Prozentpunkte "als Erster gestorben"


def _de(x: float) -> str:
    return (f"+{x:.1f}" if x > 0 else f"{x:.1f}").replace(".", ",")


def rows(hist: list[dict], sid: str) -> list[dict]:
    """Je eigene Runde: Gruppe, Impact, erster Tod, Tod ohne Trade."""
    out = []
    for h in hist:
        seq = h.get("seq") or []
        if isinstance(seq, dict):  # je Spieler (neu); vorher eine Folge aus Sicht des Teams
            seq = seq.get(sid) or []
        imp = ((h.get("impact") or {}).get(sid) or {}).get("rounds")
        # ohne Impact-Daten (z. B. Gegner, ältere Matches) keine Aussage: sonst wirkt "0 %" wie kein Tilt
        if sid not in (h.get("players") or {}) or not seq or imp is None:
            continue
        deaths = {d["round"]: d for d in h.get("deaths") or [] if d.get("sid") == sid}
        streak, prev_won, prev_side = 0, None, None
        for num, side, won in seq:
            pistol = prev_side is not None and side != prev_side or num == 1
            group = None if pistol or prev_won is None else "serie" if streak >= STREAK else \
                "sieg" if prev_won else "sonst"
            if group:
                d = deaths.get(num)
                val = imp.get(str(num), imp.get(num))
                # gestorben, aber kein Wert gespeichert: Tod war nicht bewertbar -> unbekannt statt 0
                impact = None if val is None and d else float(val or 0)
                out.append({"group": group, "impact": impact,
                            "first": bool(d and d.get("first")), "untraded": bool(d and not d.get("traded"))})
            streak = 0 if won else streak + 1
            prev_won, prev_side = won, side
    return out


def summary(hist: list[dict], sid: str) -> dict | None:
    rs = rows(hist, sid)
    if not rs:
        return None
    groups = {}
    for g, label in (("serie", f"Nach {STREAK}+ verlorenen Runden"), ("sieg", "Nach einer gewonnenen Runde"),
                     ("sonst", "Nach einer einzelnen Niederlage")):
        x = [r for r in rs if r["group"] == g]
        imp = [r["impact"] for r in x if r["impact"] is not None]
        groups[g] = {"label": label, "n": len(x),
                     "impact": round(sum(imp) / len(imp), 1) if imp else None, "impact_n": len(imp),
                     "first": round(100 * sum(r["first"] for r in x) / len(x)) if x else None,
                     "untraded": round(100 * sum(r["untraded"] for r in x) / len(x)) if x else None}
    for g in groups.values():
        g["impact_s"] = _de(g["impact"]) if g["impact"] is not None else None
    out = {"groups": groups, "reading": None, "enough": False}
    a, b = groups["serie"], groups["sieg"]
    if a["n"] >= MIN_ROUNDS and b["n"] >= MIN_ROUNDS:
        out["enough"] = True
        parts = []
        if a["impact"] is not None and b["impact"] is not None and a["impact_n"] >= MIN_ROUNDS \
                and b["impact_n"] >= MIN_ROUNDS and b["impact"] - a["impact"] >= IMPACT_GAP:
            parts.append(f"Dein Impact sinkt auf {a['impact_s']} statt {b['impact_s']} Punkte je Runde.")
        if a["first"] - b["first"] >= FIRST_GAP:
            parts.append(f"Du stirbst in {a['first']} % statt {b['first']} % der Runden als Erster.")
        if a["untraded"] - b["untraded"] >= FIRST_GAP:
            parts.append(f"Ohne Trade stirbst du in {a['untraded']} % statt {b['untraded']} % der Runden.")
        if parts:
            out["reading"] = (f"Nach {STREAK}+ verlorenen Runden in Folge spielst du messbar schlechter. "
                              + " ".join(parts) + " Tipp: Spiel genau dann eine ruhige Standard-Runde zu zweit, "
                              "keinen Einzel-Peek.")
        else:
            out["reading"] = (f"Kein Tilt erkennbar. Nach Niederlagen-Serien spielst du nicht schlechter als "
                              f"nach Siegen. Verglichen wurden {a['n']} und {b['n']} Runden.")
    return out
