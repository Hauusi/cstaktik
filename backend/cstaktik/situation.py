"""Situations-Analyse: Lagebild im Entscheidungsmoment und Rundengewinn-Chance je Lage.

Entscheidungsmoment (je Tod eines Fokus-Spielers): Ein Coach bewertet nicht den Tod, sondern die
Entscheidung davor. Aus den Positions-Samples der letzten ``lookback_s`` Sekunden:
- War der Spieler beim Tod in Bewegung, ist der Entscheidungsmoment der Beginn dieser Bewegung
  ("losgegangen / gepeekt").
- Stand er, ist es der Moment, ab dem er dort stand ("Position gehalten").
Der Moment liegt mindestens ``min_before_s`` vor dem Tod und nie vor Freeze-Ende.

Lagebild (alles aus der Demo): Spieler am Leben je Seite, eigene HP (100 minus erlittener Schaden),
Bombe gelegt, Abstand zum nächsten lebenden Mitspieler, Utility im Inventar, Ausrüstungswert der Teams
(Economy-Sample der Runde). Die Restzeit nutzt die CS2-Standardzeiten aus rules.yaml (``round_time_s``,
``bomb_time_s``), weil die Demo sie nicht direkt liefert; so im Text gekennzeichnet.

Gewinnchance: Häufigkeit, mit der eine Seite eine Runde aus einer Lage (CT lebend, T lebend, Bombe
gelegt) gewonnen hat, gezählt über eure Matches, Pro-Demos und dieses Match. Zu wenige Runden für eine
Lage: grobere Lage (Differenz + Bombe), sonst keine Zahl. Kein Modell, keine Annahmen, nur Zählen.
"""

from __future__ import annotations

from collections import Counter

from cstaktik.model import Finding, MatchData
from cstaktik.rules.base import PositionIndex, dist

NADE_DE = {"smoke": "Smoke", "flash": "Flash", "molotov": "Molotov", "incend": "Molotov", "hegrenade": "HE",
           "explosive": "HE", "decoy": None}


# ---------------------------------------------------------------- Zustände je Runde (für die Gewinnchance)

def round_states(match: MatchData) -> list[dict]:
    """Je Runde: Gewinner und alle besuchten Lagen [ct_lebend, t_lebend, bombe_gelegt] in Reihenfolge."""
    out = []
    for r in match.rounds:
        if r.winner is None or not r.sides:
            continue
        alive = {"ct": {s for s, sd in r.sides.items() if sd == "ct"}, "t": {s for s, sd in r.sides.items() if sd == "t"}}
        plant = next((b.tick for b in match.bomb if b.round == r.num and b.event == "plant"), None)
        events = sorted([(k.tick, "k", k.victim_steamid) for k in match.kills if k.round == r.num]
                        + ([(plant, "p", None)] if plant is not None else []))
        planted = 0
        states = [[len(alive["ct"]), len(alive["t"]), 0]]
        for _tick, kind, victim in events:
            if kind == "p":
                planted = 1
            else:
                alive["ct"].discard(victim)
                alive["t"].discard(victim)
            st = [len(alive["ct"]), len(alive["t"]), planted]
            if st != states[-1]:
                states.append(st)
        out.append({"w": r.winner, "s": states})
    return out


class WinModel:
    """Gezählte Gewinnquoten je Lage. ``prob`` liefert None, wenn zu wenige Runden vorliegen."""

    def __init__(self, rounds: list[dict], min_n: int = 8):
        self.min_n = min_n
        self.exact: dict[tuple, list[int]] = {}
        self.coarse: dict[tuple, list[int]] = {}
        self.rounds = len(rounds)
        for rd in rounds:
            seen_e, seen_c = set(), set()
            for ct, t, p in rd["s"]:
                ke, kc = (ct, t, p), (max(-3, min(3, ct - t)), p, min(ct, t) > 0)
                for key, table, seen in ((ke, self.exact, seen_e), (kc, self.coarse, seen_c)):
                    if key in seen:
                        continue
                    seen.add(key)
                    c = table.setdefault(key, [0, 0])
                    c[0] += rd["w"] == "ct"
                    c[1] += 1

    def prob(self, side: str, ct: int, t: int, planted: bool) -> tuple[float, int, bool] | None:
        """(Gewinnchance der Seite 0..1, Anzahl Runden, grob?) oder None."""
        if ct == 0 or t == 0:  # entschieden (außer Bombe/Defuse): klare Grenzfälle
            if ct == 0:
                return (0.0 if side == "ct" else 1.0), 0, False
            if not planted:
                return (1.0 if side == "ct" else 0.0), 0, False
        c = self.exact.get((ct, t, int(planted)))
        coarse = False
        if not c or c[1] < self.min_n:
            c = self.coarse.get((max(-3, min(3, ct - t)), int(planted), min(ct, t) > 0))
            coarse = True
        if not c or c[1] < self.min_n:
            return None
        p_ct = c[0] / c[1]
        return (p_ct if side == "ct" else 1 - p_ct), c[1], coarse


# ---------------------------------------------------------------- Lage zu einem Zeitpunkt

def alive_at(match: MatchData, rnd, tick: int) -> dict[str, set[str]]:
    dead = {k.victim_steamid for k in match.kills if k.round == rnd.num and k.tick < tick}
    out = {"ct": set(), "t": set()}
    for s, sd in rnd.sides.items():
        if s not in dead:
            out[sd].add(s)
    return out


def hp_at(match: MatchData, rnd_num: int, sid: str, tick: int) -> int | None:
    if not match.damages:
        return None
    taken = sum(d.dmg for d in match.damages if d.round == rnd_num and d.victim_steamid == sid and d.tick < tick)
    return max(0, 100 - taken)


def planted_at(match: MatchData, rnd_num: int, tick: int) -> int | None:
    return next((b.tick for b in match.bomb if b.round == rnd_num and b.event == "plant" and b.tick <= tick), None)


def decision_tick(idx: PositionIndex, rnd, sid: str, death: int, tr: int, cfg: dict) -> tuple[int, str] | None:
    """(Tick, Art) des Entscheidungsmoments; Art: 'bewegt' (losgegangen) oder 'gehalten'."""
    lo = max(rnd.freeze_end_tick or rnd.start_tick, death - int(cfg["lookback_s"] * tr))
    pts = [p for p in idx.path(rnd.num, sid) if lo <= p.tick <= death]
    if len(pts) < 3:
        return None
    speeds = []
    for a, b in zip(pts, pts[1:]):
        dt = (b.tick - a.tick) / tr
        speeds.append((b.tick, dist(a.pos, b.pos) / dt if dt > 0 else 0.0))
    moving_now = speeds[-1][1] > cfg["moving_units_s"]
    start = pts[0].tick
    for tick, sp in reversed(speeds):  # rückwärts bis die Art (bewegt/steht) wechselt
        if (sp > cfg["moving_units_s"]) != moving_now:
            start = tick
            break
    latest = death - int(cfg["min_before_s"] * tr)
    return max(lo, min(start, latest)), ("bewegt" if moving_now else "gehalten")


def _enemy_dist(idx: PositionIndex, rnd, side: str, alive: dict, pos, tick: int, tr: int) -> float | None:
    ds = []
    for s in alive["t" if side == "ct" else "ct"]:
        p = idx.nearest(rnd.num, s, tick, tr)
        if p is not None:
            ds.append(dist(pos, p.pos))
    return min(ds) if ds else None


def action(idx: PositionIndex, rnd, sid: str, side: str, tick: int, until: int, match: MatchData) -> str | None:
    """Was tat der Spieler ab ``tick``: 'Richtung Gegner', 'zurückgezogen' oder 'gehalten'.
    Maß: Abstand zum nächsten lebenden Gegner jetzt vs. bei ``until`` (gleiche Definition für Pros)."""
    tr = match.tickrate
    a, b = idx.nearest(rnd.num, sid, tick, tr), idx.nearest(rnd.num, sid, until, tr)
    if a is None or b is None:
        return None
    alive = alive_at(match, rnd, tick)
    d0 = _enemy_dist(idx, rnd, side, alive, a.pos, tick, tr)
    d1 = _enemy_dist(idx, rnd, side, alive, b.pos, until, tr)
    if dist(a.pos, b.pos) < 150 or d0 is None or d1 is None:
        return "gehalten"
    if d1 < d0 - 250:
        return "Richtung Gegner"
    if d1 > d0 + 250:
        return "zurückgezogen"
    return "gehalten"


def category(side: str, own: int, enemy: int, planted: bool, mate_d: float | None, kind: str,
             first_contact: bool, cfg: dict) -> str:
    """Einordnung der Lage. Definitionen bewusst einfach und nachvollziehbar."""
    alone = mate_d is None or mate_d > cfg["alone_units"]
    if own == 1:
        return f"Clutch 1 gegen {enemy}"
    if side == "ct":
        if planted:
            return "Retake"
        if kind == "gehalten":
            return "Position allein halten" if alone else "Position mit Mitspieler halten"
        return "Allein vorrücken (CT)" if alone else "Vorrücken mit Mitspieler (CT)"
    if planted:
        return "Post-Plant"
    if first_contact and kind == "bewegt":
        return "Entry (erster Kontakt)"
    if alone:
        return "Lurk / allein unterwegs"
    return "Mit dem Team unterwegs (T)"


def snapshot(match: MatchData, idx: PositionIndex, rnd, sid: str, tick: int, cfg: dict) -> dict:
    tr = match.tickrate
    side = rnd.sides.get(sid)
    alive = alive_at(match, rnd, tick)
    own, enemy = alive[side], alive["t" if side == "ct" else "ct"]
    me = idx.nearest(rnd.num, sid, tick, tr)
    mate, mate_d = None, None
    if me is not None:
        for s in own - {sid}:
            p = idx.nearest(rnd.num, s, tick, tr)
            if p is not None and (mate_d is None or dist(me.pos, p.pos) < mate_d):
                mate, mate_d = s, dist(me.pos, p.pos)
    plant = planted_at(match, rnd.num, tick)
    secs = (tick - rnd.freeze_end_tick) / tr
    if plant is not None:
        left = cfg["bomb_time_s"] - (tick - plant) / tr
    else:
        left = cfg["round_time_s"] - secs
    eq = {e.steamid: e.equip_value for e in rnd.economy if e.equip_value is not None}
    return {
        "tick": tick, "secs": secs, "side": side, "own": len(own), "enemy": len(enemy),
        "planted": plant is not None, "time_left": max(0, round(left)),
        "hp": hp_at(match, rnd.num, sid, tick), "place": me.place if me else None,
        "mate": match.name_of(mate) if mate else None, "mate_d": round(mate_d) if mate_d is not None else None,
        "equip_own": sum(eq.get(s, 0) for s in own) if eq else None,
        "equip_enemy": sum(eq.get(s, 0) for s in enemy) if eq else None,
        "first_contact": not any(k.round == rnd.num and k.tick < tick for k in match.kills),
    }


def _nades(inv: list[str] | None) -> list[str]:
    out = []
    for item in inv or []:
        low = item.lower()
        name = next((de for key, de in NADE_DE.items() if key in low), None)
        if name:
            out.append(name)
    return out


def _clock(s: float) -> str:
    s = max(0, int(s))
    return f"{s // 60}:{s % 60:02d}"


def _pct(p: float) -> str:
    return f"{round(100 * p)} %"


def lage_text(snap: dict, kind: str, nades: list[str]) -> str:
    parts = [f"{snap['own']} gegen {snap['enemy']}"]
    if snap["hp"] is not None:
        parts.append(f"du {snap['hp']} HP")
    parts.append("Bombe liegt" if snap["planted"] else "Bombe nicht gelegt")
    parts.append(f"noch ca. {_clock(snap['time_left'])}")
    if snap["mate"] and snap["mate_d"] is not None:
        parts.append(f"{snap['mate']} {snap['mate_d']} Units weg")
    elif snap["own"] == 1:
        parts.append("kein Mitspieler mehr")
    if nades:
        parts.append("du hattest " + ", ".join(f"{n}x {k}" if n > 1 else k for k, n in Counter(nades).items()))
    verb = "gehst los" if kind == "bewegt" else "hältst Position"
    where = f" in {snap['place']}" if snap["place"] else ""
    return f"{_clock(snap['secs'])}: Du {verb}{where}. Lage: " + ", ".join(parts) + "."


def enrich(match: MatchData, findings: list[Finding], model: WinModel | None, cfg: dict,
           trade_window_s: float = 3.0) -> None:
    """Ergänzt jede Tod-Analyse um Entscheidungsmoment, Lagebild, Lage-Kategorie und Kosten.

    evidence: ``entscheidung`` (Text), ``situation`` (Kategorie), ``cost_pct`` (Prozentpunkte),
    ``chance`` (Text vorher -> nachher), ``snap`` (Rohwerte). overlay: ``decision`` = [x, y, tick].
    """
    tr = match.tickrate
    idx = PositionIndex(match.positions)
    for f in findings:
        if f.rule_id != "death_review" or f.tick is None or f.round is None or not f.steamid:
            continue
        rnd = match.round_by_num(f.round)
        if rnd is None or rnd.freeze_end_tick is None or f.steamid not in rnd.sides:
            continue
        side = rnd.sides[f.steamid]
        death = next((k for k in match.kills if k.tick == f.tick and k.victim_steamid == f.steamid), None)
        if death is None:
            continue
        dec = decision_tick(idx, rnd, f.steamid, f.tick, tr, cfg)
        if dec is not None:
            tick, kind = dec
            snap = snapshot(match, idx, rnd, f.steamid, tick, cfg)
            thrown = [g.kind for g in match.grenades if g.round == rnd.num and g.thrower_steamid == f.steamid
                      and g.points and tick <= g.points[0][0] <= f.tick]
            nades = _nades(death.victim_inventory) + [NADE_DE.get(k, k.capitalize()) for k in thrown
                                                      if k in ("smoke", "flash", "molotov")]
            act = action(idx, rnd, f.steamid, side, tick, min(f.tick, tick + int(5 * tr)), match)
            f.evidence["entscheidung"] = lage_text(snap, kind, nades)
            f.evidence["situation"] = category(side, snap["own"], snap["enemy"], snap["planted"], snap["mate_d"],
                                               kind, snap["first_contact"], cfg)
            f.evidence["aktion"] = act
            f.evidence["snap"] = {k: snap[k] for k in ("own", "enemy", "planted", "hp", "mate_d", "secs", "time_left")}
            me = idx.nearest(rnd.num, f.steamid, tick, tr)
            if me is not None:
                f.overlay["decision"] = [me.pos.x, me.pos.y, tick]
        if model is None:
            continue
        before = alive_at(match, rnd, f.tick)
        after = alive_at(match, rnd, f.tick + int(trade_window_s * tr) + 1)
        pl_b = planted_at(match, rnd.num, f.tick) is not None
        pl_a = planted_at(match, rnd.num, f.tick + int(trade_window_s * tr)) is not None
        pb = model.prob(side, len(before["ct"]), len(before["t"]), pl_b)
        pa = model.prob(side, len(after["ct"]), len(after["t"]), pl_a)
        if pb is None or pa is None:
            continue
        cost = round(100 * (pb[0] - pa[0]))
        f.evidence["cost_pct"] = cost
        traded = len(after["t" if side == "ct" else "ct"]) < len(before["t" if side == "ct" else "ct"])
        rough = " (grobe Lage, wenig Daten)" if pb[2] or pa[2] else ""
        f.evidence["chance"] = (f"Rundenchance vorher {_pct(pb[0])}, danach {_pct(pa[0])}"
                                + (" (inkl. Trade)" if traded else "") + rough
                                + f". Gezählt aus {model.rounds} Runden.")
