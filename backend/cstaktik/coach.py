"""Coach-Diagnose: aus Einzelbefunden ein Urteil machen.

- Ursachen: Befunde werden zu wenigen Ursachen gebündelt und nach Wirkung sortiert
  (in wie vielen VERLORENEN Runden kam die Ursache vor, zum Vergleich: in wie vielen gewonnenen).
  Das ist ein Zusammenhang, kein Beweis, dass genau das die Runde gekostet hat; so formuliert.
- Überzahl verspielt: aus der Kill-Reihenfolge exakt bestimmt.
- Schlüsselmomente: die teuersten Situationen fürs Replay.
- Duo: Abstand, Trades untereinander, Siegquote zusammen vs. getrennt.
- Utility-Wirkung: Gegner/Mitspieler geblendet (player_blind), Granatenschaden.

Alle Werte stammen aus MatchData/AnalysisResult. Schwellen in rules.yaml unter ``coach``.
"""

from __future__ import annotations

from collections import defaultdict
from statistics import mean

from cstaktik.model import AnalysisResult, MatchData
from cstaktik.rules.base import PositionIndex, dist

# Ursachen: Erkennungs-Label (aus death_review/anderen Regeln) -> Ursache
CAUSES = {
    "alone": {
        "title": "Getrennt gespielt, keine Trades",
        "explain": "Ihr sterbt ohne Mitspieler in der Nähe, niemand kann nachziehen. Jeder Tod ist ein reiner Verlust.",
        "tip": "Zu zweit spielen: einer peekt, der andere steht so, dass er sofort traden kann.",
    },
    "opening": {
        "title": "Erste Tode der Runde",
        "explain": "Wer als Erster stirbt, bringt das Team in 4 gegen 5. Das passiert euch zu oft.",
        "tip": "Nicht als Erster ohne Info oder Utility peeken. Den ersten Kontakt mit Flash oder zu zweit nehmen.",
    },
    "blind": {
        "title": "Geblendet gestorben",
        "explain": "Gegner-Flashes kommen an, ihr bleibt im Winkel stehen.",
        "tip": "Bei Flash-Sound wegdrehen oder einen Schritt hinter Deckung, danach neu peeken.",
    },
    "low_hp": {
        "title": "Mit wenig HP weiter gesucht",
        "explain": "Nach erlittenem Schaden nehmt ihr das nächste Duell trotzdem.",
        "tip": "Mit wenig HP Info geben und auf Trades spielen, nicht selbst das Duell suchen.",
    },
    "outnumbered": {
        "title": "In Unterzahl Duelle gesucht",
        "explain": "Ihr sucht in Unterzahl allein die Duelle statt Zeit zu spielen oder gemeinsam zu gehen.",
        "tip": "In Unterzahl zusammen ziehen oder Zeit spielen, keine Einzel-Peeks.",
    },
    "moving": {
        "title": "Im Laufen gestorben",
        "explain": "Beim Tod wart ihr in Bewegung. In CS2 trifft man im Laufen schlecht.",
        "tip": "Vor dem Schuss stoppen (Counter-Strafe), Winkel nicht offen anlaufen.",
    },
    "utility": {
        "title": "Utility nicht eingesetzt",
        "explain": "Granaten im Inventar beim Tod oder erster Kontakt ganz ohne Utility.",
        "tip": "Vor jedem geplanten Peek eine Granate einplanen: Flash für den Peek, Molotov gegen die Position.",
    },
    "advantage": {
        "title": "Überzahl verspielt",
        "explain": "Runden mit Überzahl gingen trotzdem verloren.",
        "tip": "In Überzahl nicht einzeln jagen: gemeinsam spielen, Trades sichern, Zeit für euch nutzen.",
    },
    "economy": {
        "title": "Economy-Fehler",
        "explain": "Uneinheitliche Käufe oder Force-Buys, die die Folgerunde kosten.",
        "tip": "Vor der Runde Kauf absprechen: alle kaufen oder alle sparen.",
    },
}
LABEL_TO_CAUSE = {
    "Allein, kein Trade": "alone",
    "Geblendet": "blind",
    "Wenig HP": "low_hp",
    "Unterzahl": "outnumbered",
    "Im Laufen": "moving",
    "Utility nicht genutzt": "utility",
    "Ohne Utility": "utility",
}


def _alive_timeline(match: MatchData, rnd) -> list[tuple[int, int, int, str]]:
    """(tick, eigene lebend, Gegner lebend, Opfer) nach jedem Kill der Runde, aus Fokus-Sicht."""
    side = match.focus_side(rnd.num)
    mine = {s for s, sd in rnd.sides.items() if sd == side}
    theirs = {s for s, sd in rnd.sides.items() if sd != side}
    out = []
    for k in sorted((k for k in match.kills if k.round == rnd.num), key=lambda k: k.tick):
        mine.discard(k.victim_steamid)
        theirs.discard(k.victim_steamid)
        out.append((k.tick, len(mine), len(theirs), k.victim_steamid))
    return out


def advantage_throws(match: MatchData, min_lead: int) -> list[dict]:
    """Runden, in denen das Fokus-Team mit >= min_lead Spielern vorne lag und trotzdem verlor."""
    out = []
    for r in match.rounds:
        side = match.focus_side(r.num)
        if side is None or r.winner is None or r.winner == side:
            continue
        best = None
        for tick, mine, theirs, _ in _alive_timeline(match, r):
            if mine - theirs >= min_lead and (best is None or mine - theirs > best[1] - best[2]):
                best = (tick, mine, theirs)
        if best:
            out.append({"round": r.num, "tick": best[0], "mine": best[1], "theirs": best[2]})
    return out


def _round_causes(match: MatchData, result: AnalysisResult, cfg: dict) -> dict[int, dict[str, list]]:
    """Runde -> Ursache -> Liste von Belegen (Finding-Indizes oder Dicts)."""
    focus = match.focus_ids()
    per: dict[int, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    first_kill = {}
    for k in sorted(match.kills, key=lambda k: k.tick):
        first_kill.setdefault(k.round, k)
    for i, f in enumerate(result.findings):
        if f.round is None or f.severity == "gut":
            continue
        if f.rule_id == "death_review":
            labels = [f.title.removeprefix("Tod: ")] + list(f.evidence.get("weitere_punkte", []))
            for lbl in labels:
                if lbl in LABEL_TO_CAUSE:
                    per[f.round][LABEL_TO_CAUSE[lbl]].append(i)
        elif f.rule_id == "economy":
            per[f.round]["economy"].append(i)
    for rnd, k in first_kill.items():
        if k.victim_steamid in focus:
            per[rnd]["opening"].append({"tick": k.tick, "steamid": k.victim_steamid})
    for t in advantage_throws(match, cfg["advantage_min_lead"]):
        per[t["round"]]["advantage"].append(t)
    return per


def diagnose(match: MatchData, result: AnalysisResult, cfg: dict) -> dict:
    lost_rounds, won_rounds = [], []
    for r in match.rounds:
        side = match.focus_side(r.num)
        if side and r.winner:
            (won_rounds if r.winner == side else lost_rounds).append(r.num)
    per = _round_causes(match, result, cfg)

    causes = []
    for cid, meta in CAUSES.items():
        in_lost = sorted(r for r in lost_rounds if per.get(r, {}).get(cid))
        in_won = sorted(r for r in won_rounds if per.get(r, {}).get(cid))
        if len(in_lost) < cfg["cause_min_lost_rounds"]:
            continue
        causes.append({"id": cid, **meta, "lost_rounds": in_lost, "won_rounds": in_won,
                       "share": round(len(in_lost) / len(lost_rounds), 2) if lost_rounds else 0})
    # Wirkung: mehr verlorene Runden zuerst; bei Gleichstand die Ursache, die in Siegrunden seltener ist
    causes.sort(key=lambda c: (-len(c["lost_rounds"]), len(c["won_rounds"])))
    top = causes[: cfg["max_causes"]]

    good = [f for f in result.findings if f.severity == "gut"]
    won, lost = len(won_rounds), len(lost_rounds)
    if top:
        parts = [f"{c['title']} ({len(c['lost_rounds'])} von {lost} verlorenen Runden)" for c in top[:2]]
        sentence = "Hauptgründe: " + "; ".join(parts) + "."
    elif lost:
        sentence = "Kein klares Muster in den verlorenen Runden gefunden."
    else:
        sentence = "Keine verlorene Runde."
    rounds_with = {cid: sum(1 for r in lost_rounds + won_rounds if per.get(r, {}).get(cid)) for cid in CAUSES}
    return {
        "won": won,
        "lost": lost,
        "rounds_total": won + lost,
        "rounds_with": rounds_with,  # Ursache -> Runden (egal ob gewonnen), Messgröße für Ziele
        "sentence": sentence,
        "causes": top,
        "all_causes": causes,
        "positives": [{"title": f.title, "who": f.player_name, "round": f.round, "text": f.text} for f in good][:4],
        "key_moments": key_moments(match, result, per, top, lost_rounds, cfg),
        "duo": duo(match, cfg),
        "utility": utility_impact(match, cfg),
    }


def key_moments(match: MatchData, result: AnalysisResult, per: dict, top: list, lost_rounds: list, cfg: dict) -> list[dict]:
    """Die teuersten Momente: je Top-Ursache der wichtigste Beleg in einer verlorenen Runde,
    dazu verspielte Überzahl. Jeder Moment hat Runde + Tick fürs Replay."""
    moments: list[dict] = []
    seen: set[tuple[int, int]] = set()

    def add(rnd: int, tick: int, title: str, text: str, finding: int | None) -> bool:
        if (rnd, tick) in seen or len(moments) >= cfg["max_key_moments"]:
            return False
        seen.add((rnd, tick))
        moments.append({"round": rnd, "tick": tick, "title": title, "text": text, "finding": finding})
        return True

    for c in top:
        for rnd in c["lost_rounds"]:
            ev = per[rnd][c["id"]][0]
            if isinstance(ev, int):
                f = result.findings[ev]
                ok = add(rnd, f.tick, c["title"], f"{f.player_name or 'Team'}: {f.text}", ev)
            elif c["id"] == "advantage":
                ok = add(rnd, ev["tick"], c["title"], f"{ev['mine']} gegen {ev['theirs']} und trotzdem verloren.", None)
            else:
                f_idx = next((i for i, f in enumerate(result.findings)
                              if f.rule_id == "death_review" and f.tick == ev["tick"]), None)
                ok = add(rnd, ev["tick"], c["title"], f"{match.name_of(ev['steamid'])} stirbt als Erster.", f_idx)
            if ok:
                break  # pro Ursache ein Moment, die nächste Ursache bekommt den nächsten Platz
    for t in advantage_throws(match, cfg["advantage_min_lead"]):
        add(t["round"], t["tick"], "Überzahl verspielt", f"{t['mine']} gegen {t['theirs']} und trotzdem verloren.", None)
    moments.sort(key=lambda m: (m["round"], m["tick"]))
    return moments


def duo(match: MatchData, cfg: dict) -> dict | None:
    focus = sorted(match.focus_ids())
    if len(focus) != 2:
        return None
    a, b = focus
    idx = PositionIndex(match.positions)
    window = int(cfg["trade_window_s"] * match.tickrate)
    together = {"rounds": 0, "won": 0}
    apart = {"rounds": 0, "won": 0}
    dists_all = []
    for r in match.rounds:
        side = match.focus_side(r.num)
        if side is None or r.winner is None or r.sides.get(a) != r.sides.get(b):
            continue
        pa, pb = idx.path(r.num, a), idx.path(r.num, b)
        pb_by_tick = {p.tick: p for p in pb}
        d = [dist(p.pos, pb_by_tick[p.tick].pos) for p in pa if p.tick in pb_by_tick]
        if not d:
            continue
        avg = mean(d)
        dists_all.append(avg)
        bucket = together if avg <= cfg["duo_close_units"] else apart
        bucket["rounds"] += 1
        bucket["won"] += r.winner == side
    kills = sorted(match.kills, key=lambda k: k.tick)
    trades = {a: 0, b: 0}
    for d_ in kills:
        if d_.victim_steamid not in (a, b) or not d_.attacker_steamid:
            continue
        other = b if d_.victim_steamid == a else a
        if any(x.round == d_.round and x.attacker_steamid == other and x.victim_steamid == d_.attacker_steamid
               and d_.tick < x.tick <= d_.tick + window for x in kills):
            trades[other] += 1
    first = {a: 0, b: 0}
    for r in match.rounds:
        rk = [k for k in kills if k.round == r.num and k.victim_steamid in (a, b)]
        if rk:
            first[rk[0].victim_steamid] += 1
    if not dists_all:
        return None
    names = {a: match.name_of(a), b: match.name_of(b)}
    t, p = together, apart
    if t["rounds"] and p["rounds"]:
        sentence = (f"Zusammen (unter {cfg['duo_close_units']} Units): {t['won']} von {t['rounds']} Runden gewonnen. "
                    f"Getrennt: {p['won']} von {p['rounds']}.")
    else:
        sentence = f"Ø Abstand zwischen euch: {round(mean(dists_all))} Units."
    return {
        "names": names,
        "avg_distance": round(mean(dists_all)),
        "together": t,
        "apart": p,
        "trades": {names[k]: v for k, v in trades.items()},
        "died_first": {names[k]: v for k, v in first.items()},
        "sentence": sentence,
    }


def utility_impact(match: MatchData, cfg: dict) -> list[dict]:
    out = []
    for sid in sorted(match.focus_ids()):
        thrown = {k: sum(1 for g in match.grenades if g.thrower_steamid == sid and g.kind == k)
                  for k in ("flash", "smoke", "molotov", "he")}
        enemy_b, team_b, self_b = [], [], []
        for b in match.blinds:
            if b.attacker_steamid != sid or b.duration < cfg["blind_min_s"]:
                continue
            rnd = match.round_by_num(b.round)
            if rnd is None:
                continue
            if b.victim_steamid == sid:
                self_b.append(b)
            elif rnd.sides.get(b.victim_steamid) == rnd.sides.get(sid):
                team_b.append(b)
            else:
                enemy_b.append(b)
        nade_dmg = {"he": 0, "fire": 0}
        for d in match.damages:
            if d.attacker_steamid != sid or d.victim_steamid == sid:
                continue
            rnd = match.round_by_num(d.round)
            if rnd is None or rnd.sides.get(d.victim_steamid) == rnd.sides.get(sid):
                continue
            w = (d.weapon or "").lower()
            if "hegrenade" in w:
                nade_dmg["he"] += d.dmg
            elif any(x in w for x in ("inferno", "molotov", "incgrenade")):
                nade_dmg["fire"] += d.dmg
        out.append({
            "steamid": sid,
            "name": match.name_of(sid),
            "thrown": thrown,
            "enemies_blinded": len(enemy_b),
            "enemy_blind_s": round(sum(b.duration for b in enemy_b), 1),
            "team_blinded": len(team_b),
            "self_blinded": len(self_b),
            "he_damage": nade_dmg["he"],
            "fire_damage": nade_dmg["fire"],
            "has_blind_data": bool(match.blinds),
            "has_damage_data": bool(match.damages),
        })
    return out
