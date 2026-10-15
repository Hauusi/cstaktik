"""Review über mehrere Matches: Was hat in den letzten N Matches am meisten gekostet, was wurde besser?

Vergleicht das Fenster der letzten ``n`` Matches mit den ``n`` Matches davor (je Fokus-Spieler):
- Lektionen: Anzahl, verlorene Rundenchance (Summe aus den Szenen), Rate pro 10 Runden vorher/jetzt.
- Duelle: Median Fadenkreuz-Abweichung, Reaktion, Erste-Kugel-Treffer (aus history["duel_stats"]).
- Auftrag: Checks im Fenster (geschafft/nicht).
- Empfehlung: die teuerste Lektion im Fenster.
Nur gespeicherte Werte aus dem Verlauf, nichts geschätzt.
"""

from __future__ import annotations

from cstaktik.coaching import compare_rates

import statistics


def _de(x: float | None, d: int = 1) -> str:
    return "–" if x is None else f"{x:.{d}f}".replace(".", ",")


def _lessons(window: list[dict], sid: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    rounds = sum((h["players"][sid].get("rounds") or h.get("rounds") or 0) for h in window if sid in h.get("players", {}))
    for h in window:
        for lid, n in (h.get("lessons") or {}).get(sid, {}).items():
            e = out.setdefault(lid, {"count": 0, "cost": 0})
            e["count"] += n
        for sc in h.get("scenes", []):
            if sc.get("sid") == sid and sc.get("cost"):
                out.setdefault(sc["lesson"], {"count": 0, "cost": 0})["cost"] += max(0, sc["cost"])
    for e in out.values():
        e["rate"] = round(10 * e["count"] / rounds, 1) if rounds else None
        e["rounds"] = rounds
    return out


def _rounds(window: list[dict], sid: str) -> int:
    return sum((h["players"][sid].get("rounds") or h.get("rounds") or 0) for h in window if sid in h.get("players", {}))


def _duels(window: list[dict], sid: str) -> dict:
    """Duell-Werte über das Fenster, nach Fallzahl gewichtet (wie im Fortschritt), inkl. Sichtung und Sehen->Schuss."""
    from cstaktik.report.progress import _pooled_duels

    return _pooled_duels(window, sid) or {"n": 0}


def build(histories: list[dict], n: int = 5) -> dict:
    from cstaktik.coach_voice import LESSONS
    from cstaktik.curriculum import TEACH

    hs = [h for h in histories if h.get("players")]
    window, before = hs[-n:], hs[-2 * n:-n]
    names = {sid: p["name"] for h in hs for sid, p in h.get("players", {}).items()}
    players = []
    for sid, name in sorted(names.items(), key=lambda kv: kv[1]):
        if not any(sid in h.get("players", {}) for h in window):
            continue
        now, old = _lessons(window, sid), _lessons(before, sid)
        ranked = sorted(((lid, e) for lid, e in now.items() if lid != "duel" and lid in LESSONS),
                        key=lambda kv: (-kv[1]["cost"], -kv[1]["count"]))
        lessons = []
        for lid, e in ranked[:4]:
            o = old.get(lid)
            trend = trend_text = None
            if before:
                # derselbe ehrliche Vergleich wie im Fortschritt: Richtung nur bei genug Runden und klarem Abstand
                c = compare_rates((o or {}).get("count", 0), _rounds(before, sid), e["count"], e.get("rounds") or 0)
                trend, trend_text = (None if c["state"] == "wenig" else c["state"]), c["text"]
            lessons.append({"id": lid, "title": LESSONS[lid][0], "count": e["count"], "rounds_lost": round(e["cost"] / 100, 1),
                            "rate": e["rate"], "rate_before": o.get("rate") if o else None, "trend": trend,
                            "trend_text": trend_text,
                            "mantra": TEACH[lid]["mantra"]})
        dn, do = _duels(window, sid), _duels(before, sid)
        checks = [((h.get("focus_check") or {}).get(sid) or {}).get("check") for h in window]
        checks = [c for c in checks if c]
        players.append({"sid": sid, "name": name, "lessons": lessons, "duels": dn, "duels_before": do,
                        "checks": [{"title": c["title"], "met": c["met"], "rate": c["rate"], "target": c["target"],
                                    "count": c.get("count"), "rounds": c.get("rounds")}
                                   for c in checks]})
    won = sum(1 for h in window if (h.get("won") or 0) > (h.get("lost") or 0))
    return {"n": len(window), "won": won, "lost": len(window) - won, "players": players,
            "has_before": bool(before), "say": _say(players, len(window))}


def _say(players: list[dict], n: int) -> list[str]:
    """Ansage in Ich-Form, nur aus den Zahlen oben."""
    out = []
    for p in players:
        if not p["lessons"]:
            continue
        top = p["lessons"][0]
        s = f"{p['name']}: In den letzten {n} Matches hat dich „{top['title']}“ am meisten gekostet, {top['count']}x"
        if top["rounds_lost"] >= 0.3:
            s += f", rechnerisch etwa {_de(top['rounds_lost'])} Runden"
        s += "."
        if top["trend"] == "besser":
            s += " Weniger als davor, das greift."
        elif top["trend"] == "schlechter":
            s += " Mehr als davor. Hier musst du ran."
        d, o = p["duels"], p["duels_before"]
        if d.get("err") is not None and o.get("err") is not None and abs(d["err"] - o["err"]) >= 3:
            s += (f" Dein Fadenkreuz liegt im Duell jetzt {_de(d['err'], 0)}° daneben, vorher {_de(o['err'], 0)}°"
                  + (" – besser." if d["err"] < o["err"] else " – schlechter."))
        if (d.get("seen_opp") is not None and o.get("seen_opp") is not None and (d.get("seen_n") or 0) >= 15
                and (o.get("seen_n") or 0) >= 15 and abs(d["seen_opp"] - o["seen_opp"]) >= 10):
            s += (f" Der Gegner sieht dich in {d['seen_opp']} % der Duelle zuerst, vorher {o['seen_opp']} %"
                  + (" – deine Positionen werden besser." if d["seen_opp"] < o["seen_opp"] else " – du stehst wieder offener."))
        out.append(s)
    return out
