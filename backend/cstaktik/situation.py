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
        plant = next((b.tick for b in match.bomb if b.round == r.num and b.event == "plant" and b.tick <= r.end_tick),
                     None)
        # nur bis Rundenende (Kills danach sind Waffen-Retten, keine Lage mehr)
        events = sorted([(k.tick, "k", k.victim_steamid) for k in match.kills
                         if k.round == r.num and k.tick <= r.end_tick]
                        + ([(plant, "p", "")] if plant is not None else []))
        planted = 0
        states = [[len(alive["ct"]), len(alive["t"]), 0]]
        for i, (tick, kind, victim) in enumerate(events):
            if kind == "p":
                planted = 1
            else:
                alive["ct"].discard(victim)
                alive["t"].discard(victim)
            if i + 1 < len(events) and events[i + 1][0] == tick:
                continue  # gleicher Tick: erst alles verbuchen, sonst entsteht kurz eine Lage, die es nie gab
            st = [len(alive["ct"]), len(alive["t"]), planted]
            if st != states[-1]:
                states.append(st)
        row = {"w": r.winner, "s": states}
        eq = eq_bucket(r)
        if eq is not None:
            row["eq"] = eq
        out.append(row)
    return out


EQ_DIFF = 4000  # Ausrüstungs-Unterschied (Summe Team) ab dem eine Seite als besser ausgerüstet gilt


def eq_bucket(rnd) -> int | None:
    """Ausrüstung aus CT-Sicht: 1 = CT deutlich besser, -1 = T deutlich besser, 0 = ähnlich (Economy-Sample)."""
    if not rnd.economy:
        return None
    ct = sum(e.equip_value or 0 for e in rnd.economy if e.side == "ct")
    t = sum(e.equip_value or 0 for e in rnd.economy if e.side == "t")
    return 1 if ct - t > EQ_DIFF else -1 if t - ct > EQ_DIFF else 0


class WinModel:
    """Gezählte Gewinnquoten je Lage. ``prob`` liefert None, wenn zu wenige Runden vorliegen."""

    def __init__(self, rounds: list[dict], min_n: int = 8):
        self.min_n = min_n
        self.exact: dict[tuple, list[int]] = {}
        self.coarse: dict[tuple, list[int]] = {}
        self.with_eq: dict[tuple, list[int]] = {}
        self.rounds = len(rounds)
        for rd in rounds:
            seen_e, seen_c, seen_q = set(), set(), set()
            for ct, t, p in rd["s"]:
                ke, kc = (ct, t, p), (max(-3, min(3, ct - t)), p, min(ct, t) > 0)
                keys = [(ke, self.exact, seen_e), (kc, self.coarse, seen_c)]
                if rd.get("eq") is not None:
                    keys.append(((ct, t, p, rd["eq"]), self.with_eq, seen_q))
                for key, table, seen in keys:
                    if key in seen:
                        continue
                    seen.add(key)
                    c = table.setdefault(key, [0, 0])
                    c[0] += rd["w"] == "ct"
                    c[1] += 1

    def prob(self, side: str, ct: int, t: int, planted: bool, eq: int | None = None) -> tuple[float, int, bool] | None:
        """(Gewinnchance der Seite 0..1, Anzahl Runden, grob?) oder None. Mit ``eq`` (Ausrüstungs-Stufe der Runde)
        zuerst die Lage mit gleicher Ausrüstung, sofern genug Runden; ``self.last_eq`` sagt, ob sie genutzt wurde."""
        self.last_eq = False
        if eq is not None and ct and t:
            c = self.with_eq.get((ct, t, int(planted), eq))
            if c and c[1] >= self.min_n:
                self.last_eq = True
                p_ct = c[0] / c[1]
                return (p_ct if side == "ct" else 1 - p_ct), c[1], False
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


    def _at_n(self, level: str, ct: int, t: int, planted: bool, eq: int | None) -> tuple[float, int] | None:
        """(CT-Siegchance, Runden) aus genau einer Tabelle; entschiedene Lagen sind fest (0 Runden)."""
        if ct == 0:
            return 0.0, 0
        if t == 0 and not planted:
            return 1.0, 0
        if level == "eq":
            c = self.with_eq.get((ct, t, int(planted), eq)) if eq is not None and t else None
        elif level == "exact":
            c = self.exact.get((ct, t, int(planted)))
        else:
            c = self.coarse.get((max(-3, min(3, ct - t)), int(planted), min(ct, t) > 0))
        return (c[0] / c[1], c[1]) if c and c[1] >= self.min_n else None

    def _at(self, level: str, ct: int, t: int, planted: bool, eq: int | None) -> float | None:
        r = self._at_n(level, ct, t, planted, eq)
        return None if r is None else r[0]

    def pair_detail(self, before: tuple, after: tuple, eq: int | None = None) -> dict | None:
        """Wie ``prob_pair``, mit Tabelle (``level``: eq/exact/coarse) und Rundenzahlen je Seite."""
        for level in ("eq", "exact", "coarse"):
            if level == "eq" and eq is None:
                continue
            b, a = self._at_n(level, *before, eq), self._at_n(level, *after, eq)
            if b is not None and a is not None:
                return {"before": b[0], "after": a[0], "n_before": b[1], "n_after": a[1], "level": level}
        return None

    def prob_pair(self, before: tuple, after: tuple, eq: int | None = None) -> tuple[float, float] | None:
        """CT-Siegchance vor und nach einem Ereignis aus DERSELBEN Tabelle (mit Ausrüstung, exakt, grob).
        Gemischte Tabellen können das Vorzeichen umdrehen (z. B. Eco-Runde: 5v5 mit, 4v5 ohne Ausrüstung)."""
        d = self.pair_detail(before, after, eq)
        return None if d is None else (d["before"], d["after"])


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
    """(Tick, Art) des Entscheidungsmoments; Art: 'bewegt' (losgegangen) oder 'gehalten'.

    Bewertet wird der Zustand ``min_before_s`` vor dem Tod (das Duell selbst zählt nicht). Bewegung geglättet
    (Mittel zweier Abschnitte) mit Hysterese: bewegt ab ``moving_units_s``, steht unter ``still_units_s``,
    dazwischen bleibt der vorige Zustand. Entscheidungsmoment = Beginn des aktuellen Zustands."""
    lo = max(rnd.freeze_end_tick or rnd.start_tick, death - int(cfg["lookback_s"] * tr))
    cut = death - int(cfg["min_before_s"] * tr)
    pts = [p for p in idx.path(rnd.num, sid) if lo <= p.tick <= cut]
    if len(pts) < 3:
        return None
    raw = []
    for a, b in zip(pts, pts[1:]):
        dt = (b.tick - a.tick) / tr
        raw.append((b.tick, dist(a.pos, b.pos) / dt if dt > 0 else 0.0))
    smooth = [(t, (raw[i][1] + raw[i - 1][1]) / 2 if i else v) for i, (t, v) in enumerate(raw)]
    hi, low = cfg["moving_units_s"], cfg.get("still_units_s", 40)
    states = []
    cur = smooth[0][1] > hi
    for t, v in smooth:
        cur = True if v > hi else False if v < low else cur
        states.append((t, cur))
    moving_now = states[-1][1]
    start = pts[0].tick
    for t, st in reversed(states):
        if st != moving_now:
            start = t
            break
    return max(lo, start), ("bewegt" if moving_now else "gehalten")


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


def frame(match: MatchData, idx: PositionIndex, rnd, sid: str, tick: int, death) -> dict | None:
    """Lagebild für das Training auf der Karte: wo alle im Entscheidungsmoment standen und von wo der Killer kam.

    Gegner nur, wenn die Demo 'spotted' liefert und sie in dem Moment für euer Team sichtbar waren (das, was man im
    Spiel auf dem Radar hätte wissen können). Spielkoordinaten; die Seite rechnet sie auf das Radarbild um."""
    tr = match.tickrate
    side = rnd.sides.get(sid)
    alive = alive_at(match, rnd, tick)
    me = idx.nearest(rnd.num, sid, tick, tr)
    if me is None or side is None:
        return None
    mates = []
    for s in sorted(alive[side] - {sid}):
        p = idx.nearest(rnd.num, s, tick, tr)
        if p is not None:
            mates.append([round(p.pos.x), round(p.pos.y), match.name_of(s)])
    foes, spotted_known = [], False
    for s in sorted(alive["t" if side == "ct" else "ct"]):
        p = idx.nearest(rnd.num, s, tick, tr)
        if p is not None and p.spotted is not None:
            spotted_known = True
            if p.spotted:
                foes.append([round(p.pos.x), round(p.pos.y)])
    out = {"me": [round(me.pos.x), round(me.pos.y)], "mates": mates, "foes": foes, "spotted": spotted_known}
    if death is not None and death.attacker_pos is not None and death.victim_pos is not None:
        out["killer"] = [round(death.attacker_pos.x), round(death.attacker_pos.y)]
        out["dead"] = [round(death.victim_pos.x), round(death.victim_pos.y)]
        out["kplace"] = death.attacker_place
    return out


def info_state(match: MatchData, idx: PositionIndex, rnd, side: str, killer: str | None, tick: int,
               death: int) -> dict | None:
    """Info-Lage aus dem Demo-Feld "spotted" (für das andere Team auf dem Radar sichtbar).

    Liefert None, wenn die Demo das Feld nicht enthält. ``killer_seen``: Tick, ab dem der spätere Killer
    zwischen Entscheidung (-3 s) und Tod für euer Team sichtbar war (None = nicht gesichtet)."""
    tr = match.tickrate
    enemies = [s for s, sd in rnd.sides.items() if sd != side]
    samples = [p for s in enemies for p in idx.path(rnd.num, s) if p.spotted is not None]
    if not samples:
        return None
    alive = alive_at(match, rnd, tick)["t" if side == "ct" else "ct"]
    seen_now = {p.steamid for p in samples if p.steamid in alive and abs(p.tick - tick) <= tr // 4 and p.spotted}
    killer_seen = None
    if killer:
        hits = [p.tick for p in idx.path(rnd.num, killer)
                if p.spotted and tick - 3 * tr <= p.tick <= death - tr // 4]
        killer_seen = min(hits) if hits else None
    return {"seen_now": len(seen_now), "killer_seen": killer_seen}


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


def info_text(info: dict | None, killer_name: str | None, rnd_freeze: int, tr: int) -> str | None:
    if info is None:
        return None
    parts = [f"{info['seen_now']} Gegner auf dem Radar sichtbar." if info["seen_now"] else "Kein Gegner auf dem Radar."]
    if killer_name:
        if info["killer_seen"] is not None:
            parts.append(f"{killer_name} war ab {_clock((info['killer_seen'] - rnd_freeze) / tr)} sichtbar.")
        else:
            parts.append(f"{killer_name} war vorher nicht gesichtet, also eine Überraschung.")
    return "Info: " + " ".join(parts)


def lage_text(snap: dict, kind: str, nades: list[str]) -> str:
    parts = [f"{snap['own']} gegen {snap['enemy']}"]
    if snap["hp"] is not None:
        parts.append(f"du hast {snap['hp']} HP")
    parts.append("Bombe liegt" if snap["planted"] else "Bombe nicht gelegt")
    parts.append(f"noch ca. {_clock(snap['time_left'])}")
    extra = []
    if snap["mate"] and snap["mate_d"] is not None:
        extra.append(f"{snap['mate']} ist {snap['mate_d']} Units weg.")
    elif snap["own"] == 1:
        extra.append("Kein Mitspieler lebt mehr.")
    if nades:
        extra.append("Du hattest " + ", ".join(f"{n}x {k}" if n > 1 else k for k, n in Counter(nades).items()) + ".")
    where = f" in {snap['place']}" if snap["place"] else ""
    act = f"gehst{where} los" if kind == "bewegt" else f"hältst{where} Position"
    return " ".join([f"{_clock(snap['secs'])}: Du {act}. Lage: " + ", ".join(parts) + "."] + extra)


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
            info = info_state(match, idx, rnd, side, death.attacker_steamid, tick, f.tick)
            f.evidence["snap"] = {**{k: snap[k] for k in ("own", "enemy", "planted", "hp", "mate_d", "secs",
                                                          "time_left", "place", "mate")}, "kind": kind}
            if info is not None:
                f.evidence["info_raw"] = {"seen_now": info["seen_now"],
                                          "killer_seen_s": None if info["killer_seen"] is None
                                          else round((f.tick - info["killer_seen"]) / tr, 1)}
            it = info_text(info, death.attacker_name, rnd.freeze_end_tick, tr)
            if it:
                f.evidence["info"] = it
                f.evidence["entscheidung"] += " " + it
            f.evidence["situation"] = category(side, snap["own"], snap["enemy"], snap["planted"], snap["mate_d"],
                                               kind, snap["first_contact"], cfg)
            f.evidence["aktion"] = act
            me = idx.nearest(rnd.num, f.steamid, tick, tr)
            if me is not None:
                f.overlay["decision"] = [me.pos.x, me.pos.y, tick]
            fr = frame(match, idx, rnd, f.steamid, tick, death)
            if fr:
                f.evidence["frame"] = fr
        if model is None:
            continue
        before = alive_at(match, rnd, f.tick)
        # Danach = nur dieser Tod und ein echter Trade (Killer stirbt durch das Team des Opfers); andere Tode
        # im Fenster gehören zu anderen Spielern und würden sonst doppelt gezählt.
        opp_side = "t" if side == "ct" else "ct"
        trade = death.attacker_steamid and any(
            x.round == rnd.num and x.victim_steamid == death.attacker_steamid and x.attacker_side == side
            and f.tick < x.tick <= f.tick + trade_window_s * tr for x in match.kills)
        after = {side: [s for s in before[side] if s != f.steamid],
                 opp_side: [s for s in before[opp_side] if not (trade and s == death.attacker_steamid)]}
        pl_b = planted_at(match, rnd.num, f.tick) is not None
        eq = eq_bucket(rnd)
        # vorher und danach aus DERSELBEN Tabelle (wie impact.py), sonst kann der Tod als Gewinn erscheinen;
        # ein Plant kurz nach dem Tod ist nicht Folge des Todes und zählt nicht in "danach"
        d = model.pair_detail((len(before["ct"]), len(before["t"]), pl_b), (len(after["ct"]), len(after["t"]), pl_b), eq)
        if d is None:
            continue
        conv = (lambda p: p) if side == "ct" else (lambda p: 1 - p)
        pb = (conv(d["before"]), d["n_before"], d["level"] == "coarse")
        pa = (conv(d["after"]), d["n_after"], d["level"] == "coarse")
        used_eq = d["level"] == "eq"
        cost = round(100 * (pb[0] - pa[0]))
        f.evidence["cost_pct"] = cost
        traded = bool(trade)
        rough = " Grobe Lage, wenig Daten." if pb[2] or pa[2] else ""
        f.evidence["chance"] = (f"Rundenchance vorher {_pct(pb[0])}, danach {_pct(pa[0])}"
                                + (", inklusive Trade" if traded else "")
                                + (", bei gleicher Ausrüstungslage" if used_eq else "") + "." + rough
                                + f" Gezählt aus {pb[1]} Runden vorher"
                                + (f" und {pa[1]} danach." if pa[1] else ". Danach war die Runde entschieden."))
        f.evidence["cost_n"] = min(n for n in (pb[1], pa[1]) if n) if (pb[1] or pa[1]) else 0


# ---------------------------------------------------------------- Pro-Vergleich nach Lage

ACTIONS = ("gehalten", "zurückgezogen", "Richtung Gegner")
ACTION_DE = {"gehalten": "Position gehalten", "zurückgezogen": "zurückgezogen", "Richtung Gegner": "Richtung Gegner"}


def lage_key(side: str, own: int, enemy: int, planted: bool) -> tuple:
    return (side, own, enemy, int(planted))


def pro_decisions(match: MatchData, window_s: float = 5.0) -> list[list]:
    """Lagen aus einer (Pro-)Demo: nach jedem Kill (+1 s) und bei 0:15 für jeden lebenden Spieler
    [seite, eigene, gegner, bombe, aktion, runde_gewonnen, runde, tick, steamid].
    Aktion wie beim eigenen Entscheidungsmoment: Abstand zum nächsten Gegner jetzt vs. ``window_s`` später."""
    tr = match.tickrate
    idx = PositionIndex(match.positions)
    out = []
    for rnd in match.rounds:
        if rnd.winner is None or rnd.freeze_end_tick is None or not rnd.sides:
            continue
        # je Tick nur einmal: zwei Kills im selben Tick würden sonst jede Lage doppelt zählen
        moments = [rnd.freeze_end_tick + 15 * tr] + sorted({k.tick + tr for k in match.kills if k.round == rnd.num})
        for m in moments:
            if m + int(window_s * tr) > rnd.end_tick:
                continue
            alive = alive_at(match, rnd, m)
            planted = planted_at(match, rnd.num, m) is not None
            for side in ("ct", "t"):
                own, enemy = len(alive[side]), len(alive["t" if side == "ct" else "ct"])
                if not own or not enemy:
                    continue
                for sid in sorted(alive[side]):
                    act = action(idx, rnd, sid, side, m, m + int(window_s * tr), match)
                    if act:
                        out.append([side, own, enemy, int(planted), act, rnd.winner == side, rnd.num, m, sid])
    return out


def compare(pro: list[dict], map_name: str | None, side: str, own: int, enemy: int, planted: bool,
            min_n: int = 8) -> dict | None:
    """Was haben Pros in derselben Lage gemacht und wie oft haben sie die Runde gewonnen?
    Erst exakte Lage (gleiche Map), sonst gleiche Differenz und Bombe. None bei zu wenigen Fällen."""
    rows = [(d.get("id"), r) for d in pro if d.get("map") == map_name for r in d.get("decisions", [])]
    exact = [(i, r) for i, r in rows if (r[0], r[1], r[2], r[3]) == (side, own, enemy, int(planted))]
    coarse = False
    use = exact
    if len(exact) < min_n:
        use = [(i, r) for i, r in rows if r[0] == side and r[3] == int(planted) and r[1] - r[2] == own - enemy
               and (r[1] == 1) == (own == 1)]
        coarse = True
    if len(use) < min_n:
        return None
    by = []
    for act in ACTIONS:
        xs = [(i, r) for i, r in use if r[4] == act]
        if xs:
            # mehrere Pros derselben Runde sind keine unabhängigen Fälle: Runden extra zählen
            by.append({"act": act, "n": len(xs), "won": sum(1 for _i, r in xs if r[5]),
                       "rounds": len({(i, r[6]) for i, r in xs})})
    # "Beste" Aktion nur, wenn mindestens zwei Aktionen aus je 3+ verschiedenen Runden verglichen werden können
    cands = [b for b in by if b["rounds"] >= 3]
    best = max(cands, key=lambda b: b["won"] / b["n"]) if len(cands) >= 2 else None
    return {"n": len(use), "by": by, "coarse": coarse, "best": best["act"] if best else None,
            "demos": len({i for i, _r in use}), "rounds": len({(i, r[6]) for i, r in use}), "rows": use}


def compare_text(cmp: dict, side: str, own: int, enemy: int, planted: bool, mine: str | None) -> str:
    lage = f"{side.upper()}, {own} gegen {enemy}, Bombe {'liegt' if planted else 'nicht gelegt'}"
    if cmp["coarse"]:
        lage += f". Ähnliche Lage mit gleicher Differenz {own - enemy:+d}"
    parts = [f"{ACTION_DE[b['act']]} {b['n']}x, davon {round(100 * b['won'] / b['n'])} % gewonnen." for b in cmp["by"]]
    text = f"Pros in dieser Lage: {lage}. Basis: {cmp['n']} Fälle aus {cmp.get('rounds', '?')} Runden in " \
           f"{cmp['demos']} Demo{'s' if cmp['demos'] != 1 else ''}. " \
           + " ".join(parts)
    if mine:
        text += f" Du: {ACTION_DE.get(mine, mine)}."
    return text


def enrich_pro(match: MatchData, findings: list[Finding], pro: list[dict], min_n: int = 8) -> None:
    """Ergänzt Tod-Analysen mit Lagebild um ``evidence["pro_lage"]`` (Vergleich nach Lage) und
    ``evidence["pro_best"]`` (Aktion mit der höchsten Siegquote, mind. 3 Fälle)."""
    for f in findings:
        snap = f.evidence.get("snap")
        if f.rule_id != "death_review" or not snap or f.round is None:
            continue
        rnd = match.round_by_num(f.round)
        side = rnd.sides.get(f.steamid) if rnd else None
        if not side:
            continue
        cmp = compare(pro, match.map_name, side, snap["own"], snap["enemy"], snap["planted"], min_n)
        if cmp is None:
            continue
        f.evidence["pro_rates"] = {b["act"]: [b["won"], b["n"]] for b in cmp["by"]}
        f.evidence["pro_coarse"] = cmp["coarse"]
        f.evidence["pro_rounds"] = cmp.get("rounds")
        f.evidence["pro_lage"] = compare_text(cmp, side, snap["own"], snap["enemy"], snap["planted"],
                                              f.evidence.get("aktion"))
        if cmp["best"]:
            f.evidence["pro_best"] = cmp["best"]
            mine = f.evidence.get("aktion")
            rate = {b["act"]: (b["won"] / b["n"], b["n"]) for b in cmp["by"]}
            best_r = rate[cmp["best"]][0]
            mine_r = rate.get(mine, (None, 0))
            if mine and mine != cmp["best"] and (mine_r[0] is None or best_r - mine_r[0] >= 0.15):
                vs = f" ({round(100 * mine_r[0])} %)" if mine_r[0] is not None and mine_r[1] >= 3 else ""
                f.evidence["pro_tip"] = (f"Pros gewinnen diese Lage am häufigsten mit "
                                         f"\"{ACTION_DE[cmp['best']]}\", zu {round(100 * best_r)} %. "
                                         f"Du: {ACTION_DE.get(mine, mine)}{vs}.")
