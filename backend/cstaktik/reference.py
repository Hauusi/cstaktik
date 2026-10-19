"""Eigene Siegrunden als Vorbild ("Was stattdessen").

Für jeden Tod eines Fokus-Spielers (Tod-Analyse): Wo stand derselbe Spieler auf derselben Seite
zur selben Rundenzeit in GEWONNENEN Runden? Quelle: dieses Match (Positionen) und der Verlauf
(``history["timeline"]``: Ortsname je 5 s Rundenzeit) auf derselben Map.

Alles sind eure eigenen Daten. Es ist ein Vergleich, keine Garantie, dass die andere Position
die Runde gewonnen hätte; so formuliert.
"""

from __future__ import annotations

from collections import Counter

from cstaktik.model import Finding, MatchData
from cstaktik.rules.base import PositionIndex

STEP_S = 5  # Raster der Rundenzeit
MAX_S = 115


def _bucket(seconds: float) -> int:
    return int(round(seconds / STEP_S)) * STEP_S


def timeline(match: MatchData, all_players: bool = False) -> list[dict]:
    """Je Runde und Spieler: Ortsname alle STEP_S Sekunden (None = tot/keine Daten).

    Standard: nur Fokus-Spieler; ``all_players`` für Pro-Demos (alle 10)."""
    idx = PositionIndex(match.positions)
    tr = match.tickrate
    out = []
    for r in match.rounds:
        if r.freeze_end_tick is None or r.winner is None:
            continue
        if not all_players and match.focus_side(r.num) is None:
            continue
        for sid in sorted(r.sides if all_players else match.focus_ids()):
            if sid not in r.sides:
                continue
            places = []
            for s in range(0, MAX_S + 1, STEP_S):
                tick = r.freeze_end_tick + s * tr
                if tick > r.end_tick:
                    break
                p = idx.nearest(r.num, sid, tick, tr // 2)
                places.append(p.place if p is not None and p.alive else None)
            out.append({"round": r.num, "sid": sid, "side": r.sides[sid], "won": r.winner == r.sides[sid],
                        "places": places})
    return out


def enrich(match: MatchData, findings: list[Finding], histories: list[dict] | None = None,
           min_samples: int = 2) -> None:
    """Ergänzt Tod-Analysen um ``evidence["vorbild"]`` und ein Geister-Overlay aus einer Siegrunde."""
    tr = match.tickrate
    idx = PositionIndex(match.positions)
    current = timeline(match)
    me = match.source_sha256 or match.source_file  # wie die Verlaufs-ID; sonst zählt dieses Match doppelt
    past = [t for h in (histories or []) if h.get("map") == match.map_name and h.get("id") != me
            for t in h.get("timeline", [])]

    for f in findings:
        if f.rule_id != "death_review" or f.tick is None or f.round is None or not f.steamid:
            continue
        rnd = match.round_by_num(f.round)
        if rnd is None or rnd.freeze_end_tick is None:
            continue
        side = rnd.sides.get(f.steamid)
        secs = (f.tick - rnd.freeze_end_tick) / tr
        b = _bucket(secs) // STEP_S
        # dieselbe Runde nur im aktuellen Match ausschließen (Runde N eines anderen Matches ist eine andere Runde)
        won = [t for t in [x for x in current if x.get("round") != f.round] + past
               if t["sid"] == f.steamid and t["side"] == side and t["won"]
               and b < len(t["places"]) and t["places"][b]]
        if len(won) < min_samples:
            continue
        counts = Counter(t["places"][b] for t in won)
        top, n = counts.most_common(1)[0]
        here = next((k.victim_place for k in match.kills if k.tick == f.tick and k.victim_steamid == f.steamid), None)
        mm, ss = divmod(_bucket(secs), 60)
        when = f"{mm}:{ss:02d}"
        if n < 2 or n * 2 < len(won):
            # kein klarer Schwerpunkt: Verteilung nennen statt "meist"
            spread = ", ".join(f"{pl} {c}x" for pl, c in counts.most_common(3))
            mm, ss = divmod(_bucket(secs), 60)
            f.evidence["vorbild"] = (f"In gewonnenen {side.upper()}-Runden hattest du nach {mm}:{ss:02d} keinen festen "
                                     f"Ort. Verteilung aus {len(won)} Runden: {spread}.")
            continue
        if here and top == here:
            text = (f"Auch in Siegrunden warst du nach {when} meist in {top}, in {n} von {len(won)}. "
                    "Die Position passt. Entscheidend war eher das Wie, siehe Lage.")
        else:
            text = (f"In gewonnenen {side.upper()}-Runden warst du nach {when} meist in {top}, in {n} von "
                    f"{len(won)}." + (f" Hier bist du in {here} gestorben." if here else ""))
        f.evidence["vorbild"] = text

        # Siegrunde aus diesem Match mit dem Spieler am Vorbild-Ort: als Geist + Sprungziel
        ref = next((t for t in current if t["sid"] == f.steamid and t["side"] == side and t["won"]
                    and t["round"] != f.round and b < len(t["places"]) and t["places"][b] == top), None)
        if ref:
            rr = match.round_by_num(ref["round"])
            tick = rr.freeze_end_tick + _bucket(secs) * tr
            p = idx.nearest(ref["round"], f.steamid, tick, tr // 2)
            if p is not None:
                f.overlay["ghost"] = [p.pos.x, p.pos.y]
                f.overlay["ghost_round"] = ref["round"]
                f.overlay["ghost_offset_s"] = _bucket(secs)


def winning_spots(histories: list[dict], map_name: str, at_s: int = 20, min_samples: int = 2) -> list[dict]:
    """Für das Briefing: wo standen die Fokus-Spieler in Siegrunden nach ``at_s`` Sekunden, je Seite."""
    b = _bucket(at_s) // STEP_S
    names: dict[str, str] = {}
    counts: dict[tuple[str, str], Counter] = {}
    for h in histories:
        if h.get("map") != map_name:
            continue
        for sid, p in h.get("players", {}).items():
            names[sid] = p["name"]
        for t in h.get("timeline", []):
            if t["won"] and b < len(t["places"]) and t["places"][b]:
                counts.setdefault((t["sid"], t["side"]), Counter())[t["places"][b]] += 1
    out = []
    for (sid, side), c in sorted(counts.items()):
        total = sum(c.values())
        place, n = c.most_common(1)[0]
        if total >= min_samples:
            out.append({"name": names.get(sid, sid), "side": side.upper(), "place": place, "n": n, "total": total,
                        "at": f"0:{at_s:02d}"})
    return out


PRO_MIN_SAMPLES = 10  # so viele Pro-Spieler-Samples braucht ein Vergleich mindestens


def pro_spots(pro: list[dict], map_name: str | None, side: str, seconds: float, top: int = 3) -> dict | None:
    """Verteilung der Pro-Positionen (Siegrunden ihrer Seite) zur Rundenzeit, aus data/pro."""
    b = _bucket(seconds) // STEP_S
    c = Counter()
    demos = set()
    for d in pro:
        if d.get("map") != map_name:
            continue
        for t in d.get("timeline", []):
            if t["side"] == side and t["won"] and b < len(t["places"]) and t["places"][b]:
                c[t["places"][b]] += 1
                demos.add(d.get("id"))
    total = sum(c.values())
    if total < PRO_MIN_SAMPLES:
        return None
    return {"spots": [{"place": p, "pct": round(100 * n / total)} for p, n in c.most_common(top)],
            "samples": total, "demos": len(demos), "at": _bucket(seconds)}


def pro_text(ps: dict, side: str) -> str:
    mm, ss = divmod(ps["at"], 60)
    spots = ", ".join(f"{s['place']} {s['pct']} %" for s in ps["spots"])
    return (f"Pros auf {side.upper()} in Siegrunden nach {mm}:{ss:02d}: {spots}. Das ist der Anteil der "
            f"Spieler-Positionen aus {ps['demos']} Demo{'s' if ps['demos'] != 1 else ''}.")


PRO_MIN_ROUNDS = 5  # so viele passende Pro-Runden braucht der Szenen-Vergleich
PRO_MIN_DEATHS = 8  # so viele Pro-Tode am Ort braucht die Trade-Quote
NADE_NAMES = {"smoke": "Smoke", "flash": "Flash", "molotov": "Molotov", "he": "HE"}


def pro_scene(pro: list[dict], map_name: str | None, side: str, place: str, seconds: float,
              lead_s: float = 20.0) -> dict | None:
    """Pro-Siegrunden derselben Seite, in denen ein Pro zur selben Rundenzeit am selben Ort war:
    In wie vielen kam vorher Utility zum Einsatz? T: Granaten, die dort landen. CT: Granaten, die von dort fliegen.
    """
    b = _bucket(seconds) // STEP_S
    rounds = 0
    with_util = 0
    kinds: Counter = Counter()
    throws: Counter = Counter()
    sample: dict = {}
    demos = set()
    key = "to" if side == "t" else "from"
    for d in pro:
        if d.get("map") != map_name or "nades" not in d:
            continue
        hit = {t["round"] for t in d.get("timeline", [])
               if t["side"] == side and t["won"] and b < len(t["places"]) and t["places"][b] == place}
        for r in hit:
            rounds += 1
            demos.add(d.get("id"))
            ns = [n for n in d["nades"] if n["r"] == r and n["side"] == side and n[key] == place
                  and seconds - lead_s <= n["t"] <= seconds + 2]
            if ns:
                with_util += 1
                kinds.update({n["kind"] for n in ns})
                for n in ns:
                    if n["kind"] in ("smoke", "flash", "molotov"):
                        k = (n["kind"], n["from"], n["to"])
                        throws[k] += 1
                        sample.setdefault(k, n)
    if rounds < PRO_MIN_ROUNDS:
        return None
    lineup = None
    if throws:
        (kind, frm, to), n = throws.most_common(1)[0]
        if n >= 2:
            s = sample[(kind, frm, to)]
            lineup = {"kind": kind, "from": frm, "to": to, "n": n, "xy": [s["fx"], s["fy"], s["tx"], s["ty"]]}
    return {"rounds": rounds, "with_util": with_util, "kinds": kinds.most_common(), "lineup": lineup,
            "demos": len(demos), "at": _bucket(seconds)}


def pro_trade(pro: list[dict], map_name: str | None, side: str, place: str) -> dict | None:
    """Wie oft werden Pros getradet, wenn sie auf dieser Seite an diesem Ort sterben?"""
    ds = [x for d in pro if d.get("map") == map_name for x in d.get("deaths", [])
          if x["side"] == side and x["place"] == place]
    if len(ds) < PRO_MIN_DEATHS:
        return None
    return {"n": len(ds), "pct": round(100 * sum(x["traded"] for x in ds) / len(ds))}


def scene_text(sc: dict, side: str, place: str) -> str:
    mm, ss = divmod(sc["at"], 60)
    if not sc["with_util"]:
        return (f"Pros ({side.upper()}) in {place} um {mm}:{ss:02d}: In {sc['rounds']} Siegrunden kam vorher "
                "keine Utility. Dort entscheiden Duell und Timing.")
    kinds = ", ".join(f"{NADE_NAMES[k]} {n}" for k, n in sc["kinds"])
    where = "dorthin" if side == "t" else "von dort"
    return (f"Pros ({side.upper()}) in {place} um {mm}:{ss:02d}: In {sc['with_util']} von {sc['rounds']} "
            f"Siegrunden kam vorher Utility {where}. Würfe: {kinds}.")


def enrich_pro(match: MatchData, findings: list[Finding], pro: list[dict]) -> None:
    """Ergänzt Tod-Analysen um Pro-Vergleiche, wenn genug Pro-Daten zur Map vorliegen:
    ``pro`` (Positionen), ``pro_util`` (Utility in derselben Szene), ``pro_trade`` (Trade-Quote am Ort),
    ``pro_lineup`` (häufigster Pro-Wurf, als Overlay ``pro_nade`` im Replay)."""
    if not pro:
        return
    tr = match.tickrate
    for f in findings:
        if f.rule_id != "death_review" or f.tick is None or f.round is None or not f.steamid:
            continue
        rnd = match.round_by_num(f.round)
        if rnd is None or rnd.freeze_end_tick is None:
            continue
        side = rnd.sides.get(f.steamid)
        if not side:
            continue
        secs = (f.tick - rnd.freeze_end_tick) / tr
        ps = pro_spots(pro, match.map_name, side, secs)
        if ps:
            f.evidence["pro"] = pro_text(ps, side)
        place = next((k.victim_place for k in match.kills if k.tick == f.tick and k.victim_steamid == f.steamid), None)
        if not place:
            continue
        sc = pro_scene(pro, match.map_name, side, place, secs)
        if sc:
            f.evidence["pro_util"] = scene_text(sc, side, place)
            lu = sc["lineup"]
            if lu:
                f.evidence["pro_lineup"] = (f"Häufigster Pro-Wurf dabei: {NADE_NAMES[lu['kind']]} aus "
                                            f"{lu['from'] or '?'} nach {lu['to'] or '?'} ({lu['n']}x). "
                                            "Im Replay ist er lila gestrichelt.")
                f.overlay["pro_nade"] = {"kind": lu["kind"], "xy": lu["xy"]}
        pt = pro_trade(pro, match.map_name, side, place)
        if pt:
            f.evidence["pro_trade"] = (f"Pros auf {side.upper()}, die in {place} sterben, werden zu {pt['pct']} % "
                                       f"getradet. Basis: {pt['n']} Tode.")


def pro_utility(pro: list[dict], map_name: str | None, side: str, top: int = 4, min_n: int = 3) -> list[dict]:
    """Für das Briefing: häufigste Pro-Würfe (Smoke/Flash/Molotov) in Siegrunden einer Seite, von Ort nach Ort."""
    c: Counter = Counter()
    rounds = 0
    for d in pro:
        if d.get("map") != map_name or "nades" not in d:
            continue
        rounds += len({t["round"] for t in d.get("timeline", []) if t["side"] == side and t["won"]})
        for n in d["nades"]:
            if n["side"] == side and n["won"] and n["kind"] in ("smoke", "flash", "molotov") and n["from"] and n["to"]:
                c[(n["kind"], n["from"], n["to"])] += 1
    return [{"kind": NADE_NAMES[k], "from": f, "to": t, "n": n, "rounds": rounds}
            for (k, f, t), n in c.most_common(top) if n >= min_n]


# ---- Pro-Szene zum eigenen Tod: dieselbe Situation in einer Pro-Demo zum Ansehen im Replay

CLIP_BEFORE_S = 8  # Szene beginnt so viele Sekunden vor dem Vergleichszeitpunkt
CLIP_AFTER_S = 12
MAX_CLIPS = 12  # Obergrenze je Report (Dateigröße)


def _clip_score(pm: MatchData, rnd, sid: str, moment: int, aplace: str) -> tuple[int, dict] | None:
    """Wie hat der Pro die Situation gelöst? None, wenn er binnen 5 s stirbt (kein Vorbild).

    Am meisten zählt ein Kill gegen einen Gegner aus derselben Richtung wie bei dir (``aplace``)."""
    tr = pm.tickrate
    if any(k.round == rnd.num and k.victim_steamid == sid and k.tick <= moment + 5 * tr for k in pm.kills):
        return None
    side = rnd.sides.get(sid)
    kills = [k for k in pm.kills if k.round == rnd.num and k.attacker_steamid == sid
             and k.victim_side != side and moment - 3 * tr <= k.tick <= moment + 10 * tr]
    dir_kills = [k for k in kills if k.victim_place == aplace]
    nades = [g for g in pm.grenades if g.round == rnd.num and g.thrower_steamid == sid and g.points
             and g.kind in ("smoke", "flash", "molotov", "he") and moment - 15 * tr <= g.points[0][0] <= moment + 2 * tr]
    mates = [k for k in pm.kills if k.round == rnd.num and k.attacker_side == side and k.attacker_steamid != sid
             and k.victim_place == aplace and moment - 3 * tr <= k.tick <= moment + 10 * tr]
    score = 1 + 4 * len(dir_kills) + (len(kills) - len(dir_kills)) + min(2, len(nades)) + min(1, len(mates))
    return score, {"kills": len(kills), "dir_kills": len(dir_kills), "nades": [g.kind for g in nades],
                   "team_kills": len(mates)}


def _situation_clip(match: MatchData, f: Finding, side: str, pro: list[dict], loaded: dict) -> tuple | None:
    """Ersatz, wenn kein Pro am selben Ort war: Pro-Runde in derselben LAGE (Seite, Spieler am Leben, Bombe),
    in der der Pro die erfolgreichste Aktion dieser Lage gewählt und die Runde gewonnen hat."""
    from cstaktik.situation import ACTION_DE, compare

    snap = f.evidence.get("snap")
    if not snap:
        return None
    cmp = compare(pro, match.map_name, side, snap["own"], snap["enemy"], snap["planted"])
    if cmp is None or not cmp["best"]:
        return None
    for demo_id, r in cmp["rows"]:
        pm = loaded.get(demo_id)
        if pm is None or r[4] != cmp["best"] or not r[5]:
            continue
        pr = pm.round_by_num(r[6])
        if pr is None:
            continue
        name = next((p.name for p in pm.players if p.steamid == r[8]), "Pro")
        text = (f"Gleiche Lage ({side.upper()}, {r[1]} gegen {r[2]}, Bombe {'liegt' if r[3] else 'nicht gelegt'}): "
                f"{name} hat {ACTION_DE[r[4]]} und die Runde gewonnen.")
        return pm, pr, r[8], r[7], text
    return None


def pro_clips(match: MatchData, findings: list[Finding], pro_matches: list[MatchData],
              pro: list[dict] | None = None) -> list[dict]:
    """Sucht zu jeder Tod-Analyse eine Pro-Runde in derselben Situation:
    gleiche Map und Seite, ein Pro steht zur selben Rundenzeit (5-s-Raster, ±5 s) am selben Ort UND ein Gegner
    steht wie bei dir am Ort deines Killers (gleiche Angriffsrichtung). Die Pro-Seite gewinnt die Runde,
    der Pro überlebt die nächsten 5 s. Bevorzugt: Pro tötet den Gegner aus dieser Richtung.
    Ohne Kandidat mit gleicher Angriffsrichtung gibt es keine Szene (lieber nichts als etwas Unpassendes).

    Setzt ``f.overlay["pro_clip"]`` (Index in der zurückgegebenen Liste) und ``f.evidence["pro_clip"]``.
    """
    tr = match.tickrate
    tls = [(pm, timeline(pm, all_players=True)) for pm in pro_matches if pm.map_name == match.map_name]
    clips: list[dict] = []
    keys: dict[tuple, int] = {}
    for f in findings:
        if len(clips) >= MAX_CLIPS:
            break
        if f.rule_id != "death_review" or f.tick is None or f.round is None or not f.steamid:
            continue
        rnd = match.round_by_num(f.round)
        if rnd is None or rnd.freeze_end_tick is None:
            continue
        side = rnd.sides.get(f.steamid)
        death = next((k for k in match.kills if k.tick == f.tick and k.victim_steamid == f.steamid), None)
        place = death.victim_place if death else None
        aplace = death.attacker_place if death else None
        if not side or not place or not aplace:
            continue
        secs = (f.tick - rnd.freeze_end_tick) / tr
        b = _bucket(secs) // STEP_S
        best = None
        for pm, tl in tls:
            enemy_at: dict[int, set[int]] = {}  # Runde -> Raster-Indizes, in denen ein Gegner am Killer-Ort steht
            for t in tl:
                if t["side"] != side:
                    for i, pl in enumerate(t["places"]):
                        if pl == aplace:
                            enemy_at.setdefault(t["round"], set()).add(i)
            for t in tl:
                if t["side"] != side or not t["won"]:
                    continue
                hits = [bb for bb in (b, b - 1, b + 1) if 0 <= bb < len(t["places"]) and t["places"][bb] == place
                        and bb in enemy_at.get(t["round"], ())]
                if not hits:
                    continue
                pr = pm.round_by_num(t["round"])
                moment = pr.freeze_end_tick + hits[0] * STEP_S * pm.tickrate
                res = _clip_score(pm, pr, t["sid"], moment, aplace)
                if res and (best is None or res[0] > best[0]):
                    best = (res[0], res[1], pm, pr, t["sid"], moment)
        if best is None:
            sit = _situation_clip(match, f, side, pro or [], {m.source_sha256: m for m in pro_matches})
            if sit is None:
                continue
            pm, pr, sid, moment, text = sit
            key = (pm.source_sha256, pr.num, sid)
            if key not in keys:
                keys[key] = len(clips)
                ptr = pm.tickrate
                clips.append({"match": pm, "round": pr, "sid": sid, "moment": moment, "desc": text,
                              "t0": max(pr.freeze_end_tick, moment - CLIP_BEFORE_S * ptr),
                              "t1": min(pr.end_tick, moment + CLIP_AFTER_S * ptr)})
            f.evidence["pro_clip"] = text
            f.overlay["pro_clip"] = keys[key]
            f.overlay["pro_tick"] = moment
            continue
        _score, info, pm, pr, sid, moment = best
        key = (pm.source_sha256, pr.num, sid)
        if key not in keys:
            keys[key] = len(clips)
            ptr = pm.tickrate
            clips.append({"match": pm, "round": pr, "sid": sid, "moment": moment,
                          "t0": max(pr.freeze_end_tick, moment - CLIP_BEFORE_S * ptr),
                          "t1": min(pr.end_tick, moment + CLIP_AFTER_S * ptr)})
        pname = next((p.name for p in pm.players if p.steamid == sid), "Pro")
        from cstaktik.callouts import clock as _gclock, place as _pl

        when = _gclock((moment - pr.freeze_end_tick) / pm.tickrate)  # Uhr im Spiel (Pro-Szenen liegen vor dem Plant)
        did = ["überlebt"]
        if info["nades"]:
            did.append("vorher " + ", ".join(NADE_NAMES[k] for k in info["nades"]) + " geworfen")
        if info["dir_kills"]:
            did.append(f"tötet {info['dir_kills']} Gegner aus {_pl(aplace)}")
        if info["kills"] > info["dir_kills"]:
            n = info["kills"] - info["dir_kills"]
            did.append(f"{n} weitere{'r' if n == 1 else ''} Kill{'s' if n != 1 else ''}")
        if info["team_kills"]:
            did.append(f"Team tötet {info['team_kills']} aus {_pl(aplace)}")
        f.evidence["pro_clip"] = (f"{pname} ({side.upper()}) in {_pl(place)} bei {when}. Der Gegner kam wie bei dir "
                                  f"aus {_pl(aplace)}. Runde gewonnen: " + ", ".join(did) + ".")
        clips[keys[key]].setdefault("desc", f.evidence["pro_clip"])
        f.overlay["pro_clip"] = keys[key]
        f.overlay["pro_tick"] = moment
    return clips
