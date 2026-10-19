"""Coach-Stimme: macht aus den Fakten einer Tod-Analyse eine Ansage wie von einem Coach.

Aufbau je Szene (``f.evidence["coach"]``):
- ``lesson``: Lektion als kurze Ansage ("Ecke vorzielen statt reinlaufen"), immer dieselbe je Fehlerart,
  damit Wiederholungen über Matches zählbar sind (``id``).
- ``happened``: 1–3 kurze Sätze in Du-Form, was passiert ist, mit echten Namen, Orten, Zeiten.
- ``next``: eine konkrete Ansage fürs nächste Mal, mit den Orten/Utility dieser Szene.
- ``pro``: kurze Zeile, was Pros in derselben Lage tun (nur wenn Daten da sind).

Nur Fakten aus ``evidence["f"]`` (death_review) und ``situation.enrich``. Fehlt ein Fakt, fällt der
Halbsatz weg. Die Lektions-Texte und Übungen sind allgemeines CS-Wissen, als Ratschlag formuliert.
"""

from __future__ import annotations

from collections import defaultdict

from cstaktik.callouts import clock as _gclock, meters as _m, place as _pl
from cstaktik.model import Finding

# id -> (Lektion, warum das kostet, Übung fürs nächste Match)
LESSONS = {
    "no_shot_close": ("Ecke vorzielen statt reinlaufen",
                      "Du stirbst, bevor du schießt. Der Gegner hatte den Winkel schon, dein Fadenkreuz nicht.",
                      "Bekannte Gegner-Spots einzeln clearen. Fadenkreuz vorher auf Kopfhöhe."),
    "no_shot_far": ("Lange Linien nicht offen kreuzen",
                    "Du kreuzt eine lange, offene Linie ohne Deckung. Genau darauf wartet der Gegner.",
                    "Lange Linien mit Smoke zumachen oder einen anderen Weg nehmen."),
    "blind": ("Bei Flash sofort wegdrehen",
              "Geblendet im Winkel stehen ist ein geschenkter Kill.",
              "Beim Flash-Geräusch wegdrehen und einen Schritt hinter Deckung. Erst dann wieder peeken."),
    "alone": ("Nicht ohne Trade-Partner peeken",
              "Stirbst du allein, kann dich niemand traden. Ihr seid einer weniger, ohne Gegenleistung.",
              "Vor dem Peek callen. Warten, bis ein Mitspieler in Trade-Reichweite ist."),
    "utility": ("Erst Utility, dann Duell",
                "Du stirbst mit Granaten in der Tasche. Das Duell war fairer als nötig.",
                "Vor jedem geplanten Duell eine Flash oder Molotov werfen."),
    "low_hp": ("Mit wenig HP kein neues Duell",
               "Mit wenig HP verlierst du fast jedes Duell. Auch gegen schwächere Waffen.",
               "Unter 50 HP: zurückfallen, Info callen, auf den Trade spielen."),
    "moving_shot": ("Erst stoppen, dann schießen",
                    "Schüsse aus der Bewegung streuen. Der Gegner steht und trifft.",
                    "Deathmatch: nur schießen, wenn du stehst (Counter-Strafe)."),
    "moving": ("Nicht laufend in den Winkel",
               "Wer in den Winkel läuft, ist für den Haltenden ein leichtes Ziel.",
               "Vor dem Winkel stoppen, kurz peeken, erst dann rein."),
    "outnumbered": ("In Unterzahl zusammenbleiben",
                    "In Unterzahl gewinnst du selten ein Einzelduell. Nur gemeinsam habt ihr eine Chance.",
                    "In Unterzahl zum nächsten Mitspieler gehen oder auf Zeit spielen."),
    "crosshair": ("Fadenkreuz vorher auf den Spot",
                  "Beim Duellstart zeigte dein Fadenkreuz deutlich neben den Gegner. Bis du nachziehst, hat er geschossen.",
                  "Prefire-Map: Fadenkreuz an jede Kante auf Kopfhöhe, bevor du dich bewegst."),
    "angle": ("Nicht offen in mehrere Winkel stehen",
              "Der Gegner kam aus einer Richtung, in die du nicht geschaut hast. Das ist kein Aim-Problem. "
              "Deine Position ließ zu viele Winkel gleichzeitig offen.",
              "Stell dich so, dass nur ein Winkel auf dich zeigt. Den Rest deckt ein Mitspieler oder Utility."),
    "seen_first": ("Sehen, bevor du gesehen wirst",
                   "Er hatte dich im Blick, bevor du ihn sehen konntest. Wer zuerst sieht, gewinnt fast jedes Duell. "
                   "Egal, wie gut der andere zielt.",
                   "Nicht an der offenen Kante warten. Einen Schritt tiefer in Deckung oder auf einen Off-Angle. "
                   "Dann siehst du ihn zuerst."),
    "duel": ("Duell verloren, Lage war okay",
             "Die Lage war nicht das Problem. Das Duell selbst ging verloren.",
             "Aim und Peek-Timing im Deathmatch trainieren."),
}
# Wie ein Tod dieser Lektion in Worten zählt ("11 von 19 Toden mit Flash oder Molotov in der Tasche")
DEATH_PHRASE = {
    "no_shot_close": "ohne einen Schuss, Gegner auf kurze Distanz",
    "no_shot_far": "ohne einen Schuss, über eine lange Linie",
    "blind": "geblendet",
    "alone": "ohne Mitspieler in Trade-Reichweite",
    "utility": "mit Flash oder Molotov in der Tasche",
    "low_hp": "mit wenig HP in einem neuen Duell",
    "moving_shot": "mit dem letzten Schuss aus der Bewegung",
    "moving": "im Laufen",
    "outnumbered": "in Unterzahl im Einzelduell",
    "crosshair": "mit dem Fadenkreuz deutlich neben dem Gegner",
    "angle": "aus einem Winkel, in den du nicht geschaut hast",
    "seen_first": "weil der Gegner dich zuerst gesehen hat",
}
LABEL_TO_LESSON = {"Geblendet": "blind", "Allein, kein Trade": "alone", "Utility nicht genutzt": "utility",
                   "Wenig HP": "low_hp", "Im Laufen geschossen": "moving_shot", "Im Laufen": "moving",
                   "Unterzahl": "outnumbered", "Duell verloren": "duel"}
ACTION_SHORT = {"gehalten": "halten", "zurückgezogen": "zurückziehen", "Richtung Gegner": "Richtung Gegner gehen"}
ACTION_NOUN = {"gehalten": "Halten", "zurückgezogen": "Rückzug", "Richtung Gegner": "Peek Richtung Gegner"}


def _clock(s: float | None, plant_s: float | None = None) -> str | None:
    """Uhr im Spiel (1:55 abwärts, nach dem Plant Bombentimer) aus Sekunden seit Rundenstart."""
    return _gclock(s, plant_s) or None


def _at(when: str | None) -> str:
    """"Bei 1:05 " bzw. "Bei 0:23 auf dem Bombentimer " (leer ohne Zeit)."""
    if not when:
        return ""
    if when.startswith("Bombe "):
        return f"Bei {when.removeprefix('Bombe ')} auf dem Bombentimer "
    return f"Bei {when} "


def _ms(speed: float) -> str:
    return f"{speed * 0.0254:.1f} m/s".replace(".", ",")


CROSSHAIR_BAD_DEG = 20.0  # ab dieser Abweichung im Kontakt-Moment gilt das Fadenkreuz als "nicht vorgehalten"
WRONG_ANGLE_DEG = 60.0  # ab hier schaute man in eine andere Richtung (Gegner kam von der Seite/hinten)
SEEN_FIRST_MS = 300  # so viel früher muss der Gegner dich gesehen haben, damit es als "zuerst gesehen" zählt


def lesson_id(fx: dict, close_units: int = 600) -> str:
    label = fx.get("label")
    duel = fx.get("duel") or {}
    if label in ("Duell verloren", "Ohne Gegenwehr") and duel.get("err") is not None and duel["err"] >= WRONG_ANGLE_DEG:
        return "angle"
    if label == "Duell verloren" and duel.get("seen") == "gegner" and (
            duel.get("seen_ms") is None or duel["seen_ms"] <= -SEEN_FIRST_MS):
        return "seen_first"
    if label == "Duell verloren" and duel.get("err") is not None and duel["err"] >= CROSSHAIR_BAD_DEG:
        return "crosshair"
    if label == "Ohne Gegenwehr":
        d = fx.get("a_dist")
        return "no_shot_close" if d is None or d < close_units else "no_shot_far"
    return LABEL_TO_LESSON.get(label, "duel")


def _trade_units() -> float:
    """Trade-Reichweite aus rules.yaml (death_review), überall dieselbe Grenze."""
    from cstaktik.config import load_rules_config

    return load_rules_config()["rules"]["death_review"]["trade_distance_units"]


def lesson_ids(fx: dict, main: str, close_units: int = 600) -> list[str]:
    """Alle Lektionen eines Todes: die Haupt-Lektion und die der weiteren Probleme (ohne Doppelte).
    Für Raten und Trends; sonst wandert ein Tod beim Besserwerden einer Lektion in die nächste."""
    out = [main]
    for lbl in (fx.get("issues") or [])[1:]:
        lid = lesson_id({**fx, "label": lbl}, close_units)
        if lid not in out and lid != "duel":
            out.append(lid)
    return out


def _lage_sentence(snap: dict | None, fx: dict | None = None) -> str | None:
    if not snap:
        return None
    plant = (fx or {}).get("plant_s")
    when = _clock(snap.get("secs"), plant if snap.get("planted") else None)
    where = f" {_pl(snap['place'])}" if snap.get("place") else ""
    verb = f"gehst du{(' in' + where) if where else ''} los" if snap.get("kind") == "bewegt" \
        else f"hältst du{where or ' deine Position'}"
    bits = [f"{snap['own']} gegen {snap['enemy']}"]
    hp = snap.get("hp")
    if hp is not None:
        bits.append("volle HP" if hp >= 100 else f"nur {hp} HP" if hp < 50 else f"{hp} HP")
    if snap.get("mate") and snap.get("mate_d") is not None:
        bits.append(f"{snap['mate']} {_m(snap['mate_d'])} neben dir" if snap["mate_d"] <= _trade_units()
                    else f"{snap['mate']} {_m(snap['mate_d'])} weg")
    elif snap.get("own") == 1:
        bits.append("du bist der Letzte")
    return f"{_at(when) or 'Da '}{verb}: " + ", ".join(bits) + "."


def _death_sentence(fx: dict) -> str:
    when = fx.get("when")
    att = fx.get("attacker") or "der Gegner"
    src = f" aus {_pl(fx['aplace'])}" if fx.get("aplace") else ""
    dist = f", {_m(fx['a_dist'])} entfernt" if fx.get("a_dist") is not None else ""
    pre = _at(when)
    if fx.get("blind_by"):
        return (f"{fx['blind_by']} flasht dich. {str(fx.get('blind_ago')).replace('.', ',')} s später erwischt dich {att}{src}.")
    if fx.get("no_shot"):
        return f"{pre}taucht {att}{src} auf{dist}. Du kommst nicht zum Schuss."
    dealt = fx.get("dealt")
    tail = ("" if dealt is None else f" Du machst {dealt} Schaden. Das reicht nicht." if dealt
            else " Du triffst nicht.")
    return f"{pre}gewinnt {att}{src} das Duell{dist}." + tail


def _duel_sentence(fx: dict) -> str | None:
    d = fx.get("duel")
    if not d:
        return None
    att = fx.get("attacker") or "der Gegner"
    parts = []
    seen, ms = d.get("seen"), d.get("seen_ms")
    if seen == "gegner":
        # "du ihn gar nicht" nur, wenn du auch nicht geschossen hast (sonst widerspricht der Satz danach)
        never = ms is None and d.get("react") is None and not d.get("tts")
        parts.append(f"{att[:1].upper() + att[1:]} hat dich zuerst gesehen"
                     + (f", {_de2(-ms / 1000)} s vor dir." if ms is not None else ", du ihn gar nicht." if never else "."))
    elif seen == "ich":
        parts.append("Du hast ihn zuerst gesehen" + (f", {_de2(ms / 1000)} s vor ihm." if ms is not None else ".")
                     + (" Trotzdem hast du verloren." if d.get("won") is False else ""))
    elif seen == "gleich":
        parts.append("Ihr habt euch gleichzeitig gesehen.")
    early = bool(d.get("early_shot"))  # eigener Schuss vor dem Kontakt: Reaktion/erste Kugel sagen dann nichts
    if d.get("tts") is not None and seen in ("ich", "gleich") and not early:
        parts.append(f"Bis zu deinem ersten Schuss vergingen {d['tts']} ms.")
    if d.get("err") is not None:
        s = f"Beim Duellstart lag dein Fadenkreuz {_de1(d['err'])}° neben {att}"
        h = d.get("height")
        if h is not None and d["err"] <= 20 and abs(h) > 2:
            s += f", {_de1(abs(h))}° {'unter' if h > 0 else 'über'} dem Kopf"
        s += "."
        if d.get("opp_err") is not None:
            s += f" Seins lag {_de1(d['opp_err'])}° neben dir."
        parts.append(s)
    if early:
        pass
    elif d.get("react") == 0:
        parts.append("Du hast zuerst geschossen." + (" Die erste Kugel traf." if d.get("hit")
                                                     else " Die erste Kugel ging daneben." if d.get("hit") is False else ""))
    elif d.get("react") is not None:
        parts.append(f"Dein erster Schuss kam {d['react']} ms nach seinem."
                     + (f" Du warst dabei mit {_ms(d['speed'])} unterwegs." if d.get("speed") and d["speed"] > 80 else ""))
    return " ".join(parts) or None


def _de2(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def _de1(x: float) -> str:
    return f"{x:.0f}"


def _info_sentence(info: dict | None, fx: dict) -> str | None:
    if not info:
        return None
    att = fx.get("attacker") or "Der Gegner"
    if info.get("killer_seen_s") is None:
        return f"Keiner von euch hatte {att} auf dem Radar."
    return f"{att} war {str(info['killer_seen_s']).replace('.', ',')} s vorher auf dem Radar zu sehen."


def _next(lid: str, fx: dict, snap: dict | None, aktion: str | None = None) -> str:
    nades = fx.get("nades") or []
    aplace = _pl(fx.get("aplace")) or None
    held = _held(snap, aktion)
    if lid == "no_shot_close" and held:
        return ("Beim Halten das Fadenkreuz auf die Kante legen" + (f" Richtung {aplace}" if aplace else "")
                + ". Nach einem Kontakt die Position wechseln.")
    if lid == "no_shot_close":
        util = [n for n in ("Flash", "Molotov") if n in nades]
        return (f"{aplace or 'Den Spot'} vorher anvisieren, Fadenkreuz auf Kopfhöhe."
                + (f" Oder mit deiner {util[0]} prüfen." if util else ""))
    if lid == "no_shot_far":
        return (f"Die Linie aus {aplace or 'dieser Richtung'} mit Smoke zumachen oder einen anderen Weg nehmen."
                + (" Du hattest eine Smoke dabei." if "Smoke" in nades else ""))
    if lid == "blind":
        return "Flash hören, sofort wegdrehen, einen Schritt zurück. Erst danach wieder peeken."
    if lid == "alone" and held:
        mate = fx.get("mate")
        return (f"Stell dich so, dass {mate} nachziehen kann. Oder fall nach dem ersten Kontakt zurück und calle."
                if mate else "Nach dem ersten Kontakt zurückfallen und callen. Nicht allein weiter halten.")
    if lid == "alone":
        mate = fx.get("mate")
        return (f"Erst callen und warten, bis {mate} bei dir ist. Dann zusammen peeken." if mate
                else "Erst callen und auf einen Mitspieler warten. Dann zusammen peeken.")
    if lid == "utility":
        pick = next((n for n in ("Flash", "Molotov", "Smoke", "HE") if n in nades), None)
        return (f"Vor dem Duell deine {pick} werfen" + (f" auf {aplace}" if aplace and pick != "Smoke" else "")
                + "." if pick else "Vor dem Duell Utility werfen.")
    if lid == "low_hp":
        return f"Mit {fx.get('hp')} HP nicht nachpeeken. Zurückfallen, Info callen, auf den Trade spielen."
    if lid == "moving_shot":
        return "Vor dem Schuss stoppen (Counter-Strafe). Dann schießen."
    if lid == "angle":
        return (f"Stell dich so, dass nur ein Winkel auf dich zeigt. {aplace or 'Diese Richtung'} "
                "muss ein Mitspieler oder eine Smoke abdecken, nicht du nebenbei.")
    if lid == "seen_first":
        place = _pl((snap or {}).get("place")) or None
        return (f"{'In ' + place if place else 'Hier'} nicht an der offenen Kante warten. Geh einen Schritt tiefer "
                f"oder auf einen Off-Angle. Dann sieht {'der Gegner aus ' + aplace if aplace else 'er'} dich erst, "
                "wenn du ihn schon im Fadenkreuz hast.")
    if lid == "crosshair":
        return (f"Fadenkreuz schon vorher auf {aplace or 'den Spot'} legen, auf Kopfhöhe. "
                "Dann musst du nur noch klicken, nicht erst suchen.")
    if lid == "moving":
        return "Vor dem Winkel stoppen, kurz peeken, erst dann rein."
    if lid == "outnumbered":
        own, enemy = fx.get("own"), fx.get("enemy")
        return f"Bei {own} gegen {enemy} mit dem nächsten Mitspieler zusammen gehen. Oder auf Zeit spielen."
    return LESSONS["duel"][2]


def _pro_line(ev: dict) -> str | None:
    """``pro_rates``: Aktion -> [gewonnene Runden, verschiedene Runden] (situation.compare). Eine "beste" Aktion
    nur mit genug Runden je Aktion; sonst lieber nichts sagen."""
    from cstaktik.situation import BEST_MIN_ROUNDS

    best, mine, rates = ev.get("pro_best"), ev.get("aktion"), ev.get("pro_rates") or {}
    if not best or best not in rates:
        return None
    won, n = rates[best]
    if n < BEST_MIN_ROUNDS:
        return None
    lage = "in ähnlicher Lage" if ev.get("pro_coarse") else "in dieser Lage"
    line = f"Pros {lage} gewinnen am häufigsten mit {ACTION_NOUN[best]}: {won} von {n} Runden."
    if mine and mine != best and mine in rates and rates[mine][1] >= BEST_MIN_ROUNDS:
        w2, n2 = rates[mine]
        line += f" Mit {ACTION_NOUN[mine]} wie du: {w2} von {n2}."
    if ev.get("pro_rounds"):
        line += f" Basis: {ev['pro_rounds']} Pro-Runden in dieser Lage."
    return line


def _held(snap: dict | None, aktion: str | None) -> bool:
    """Hat der Spieler im Entscheidungsmoment gehalten (nicht gepeekt)? Nur aus den Positionsdaten."""
    return bool(snap) and snap.get("kind") != "bewegt" and aktion in (None, "gehalten")


def _why(lid: str, fx: dict, snap: dict | None, aktion: str | None) -> str | None:
    """Warum es in DIESER Szene gekostet hat, passend zu dem, was die Daten zeigen (statt eines festen Satzes,
    der z. B. 'reinlaufen' unterstellt, obwohl gehalten wurde). None = allgemeiner Satz der Lektion passt."""
    att = fx.get("attacker") or "der Gegner"
    src = f" aus {_pl(fx['aplace'])}" if fx.get("aplace") else ""
    d = fx.get("duel") or {}
    err = d.get("err")
    held = _held(snap, aktion)
    if lid in ("no_shot_close", "no_shot_far"):
        if err is not None and err < CROSSHAIR_BAD_DEG:
            return (f"Dein Fadenkreuz lag richtig, nur {_de(err)}° neben ihm. Trotzdem hat {att}{src} zuerst getroffen. "
                    "Hier entscheidet nicht das Zielen, sondern wer die Position zuerst hat.")
        if held:
            return (f"Du hast gehalten. {att[:1].upper() + att[1:]} kam{src}, und du kamst nicht zum Schuss. "
                    "Er wusste, wo du stehst. Du wusstest nicht, wann er kommt.")
        return None
    if lid == "alone":
        mate, md = fx.get("mate"), fx.get("mate_dist")
        # Abstand nur nennen, wenn der Lage-Satz davor ihn nicht schon nennt
        said = bool(snap) and snap.get("mate_d") is not None
        far = "" if said else (f" {mate} war {_m(md)} weg." if mate and md is not None
                               else " Kein Mitspieler war in Reichweite.")
        if held:
            return f"Du hast allein gehalten.{far} Nach dem ersten Kontakt konnte dich niemand traden."
        return f"Du bist ins Duell gegangen.{far} Dein Tod blieb ohne Antwort."
    if lid == "seen_first":
        ms = d.get("seen_ms")
        never = ms is None and d.get("react") is None and not d.get("tts")
        lead = (f"{_de2(-ms / 1000)} s früher gesehen als du ihn" if ms is not None
                else "gesehen, du ihn gar nicht" if never else "zuerst gesehen")
        if held:
            return f"Du hast gehalten. Trotzdem hat {att}{src} dich {lead}. Deine Stelle war für ihn zuerst einsehbar."
        return f"Du bist in seine Sicht gelaufen. {att[:1].upper() + att[1:]}{src} hat dich {lead}."
    if lid == "moving" and aktion == "zurückgezogen":
        return "Du warst auf dem Rückzug, als er dich erwischt hat. Auch wer rückwärts läuft, ist ein bewegtes Ziel."
    return None


def voice(f: Finding, close_units: int = 600) -> dict | None:
    fx = f.evidence.get("f")
    if f.rule_id != "death_review" or not fx:
        return None
    lid = lesson_id(fx, close_units)
    happened = [s for s in (_lage_sentence(f.evidence.get("snap"), fx), _death_sentence(fx), _duel_sentence(fx),
                            _info_sentence(f.evidence.get("info_raw"), fx)) if s]
    if fx.get("traded"):
        happened.append("Immerhin wurdest du getradet.")
    snap, aktion = f.evidence.get("snap"), f.evidence.get("aktion")
    return {"id": lid, "lesson": LESSONS[lid][0], "happened": " ".join(happened),
            "why": _why(lid, fx, snap, aktion),
            "next": _next(lid, fx, snap, aktion), "pro": _pro_line(f.evidence)}


def apply(findings: list[Finding], close_units: int = 600) -> None:
    for f in findings:
        v = voice(f, close_units)
        if v:
            f.evidence["coach"] = v


def recurrence(past: list[dict], sid: str | None = None, window: int = 4) -> tuple[dict[str, int], int]:
    """In wie vielen der letzten ``window`` Matches kam jede Lektion vor (für einen Spieler oder das Team)?
    Rückgabe: (Lektion -> Anzahl Matches, Anzahl betrachteter Matches). Gedächtnis über Matches hinweg."""
    rows = [h for h in past if "lessons" in h and (sid is None or sid in h.get("players", {}))][-window:]
    seen: dict[str, int] = defaultdict(int)
    for h in rows:
        les = (h["lessons"].get(sid) or {}) if sid else {}
        if sid is None:
            for d in h["lessons"].values():
                for lid, n in d.items():
                    les[lid] = les.get(lid, 0) + n
        for lid, n in les.items():
            if n:
                seen[lid] += 1
    return dict(seen), len(rows)


def focus(findings: list[Finding], n: int = 3, recur: tuple[dict[str, int], int] | None = None) -> list[dict]:
    """Die Lektionen des Matches, gleiche Lektion zusammengefasst.

    Gezählt wird jede Beteiligung an einem Tod (wie im Verlauf und im Auftrag-Check), die verlorene Rundenchance
    nur beim Hauptfehler. Reihenfolge: zuerst Lektionen, die heute mindestens ``MIN_LEAD_COUNT``-mal vorkamen
    (eine einzelne Szene ist noch kein Muster), darunter zuerst Muster aus früheren Matches (``recur``, Gedächtnis),
    dann verlorene Rundenchance, dann Häufigkeit. Ein einzelner teurer Ausreißer schlägt so kein Dauerproblem.
    ``lead``: darf die Lektion Thema des Matches sein (Überschrift, Einleitung)?"""
    groups: dict[str, dict] = defaultdict(lambda: {"count": 0, "main": 0, "cost": 0, "has_cost": False, "scenes": [],
                                                   "players": set()})
    for i, f in enumerate(findings):
        v = f.evidence.get("coach")
        if not v:
            continue
        c = f.evidence.get("cost_pct")
        for j, lid in enumerate(lesson_ids(f.evidence.get("f") or {}, v["id"])):
            if lid == "duel" or lid not in LESSONS:
                continue
            g = groups[lid]
            g["count"] += 1
            if j == 0:
                g["main"] += 1
                if c is not None:
                    g["cost"] += max(0, c)
                    g["has_cost"] = True
                    cn = f.evidence.get("cost_n")
                    if cn is not None:
                        g["cost_n"] = min(g.get("cost_n", cn), cn)
            g["players"].add(f.player_name)
            g["scenes"].append({"round": f.round, "tick": f.tick, "finding": i, "who": f.player_name,
                                "cost": c if j == 0 else None,
                                "from": (f.overlay.get("decision") or [None, None, None])[2]})
    seen, n_past = recur or ({}, 0)
    out = []
    for lid, g in groups.items():
        title, why, drill = LESSONS[lid]
        out.append({"id": lid, "lesson": title, "why": why, "drill": drill, "count": g["count"], "main": g["main"],
                    "cost": g["cost"] if g["has_cost"] else None, "players": sorted(p for p in g["players"] if p),
                    "seen_in": seen.get(lid, 0) + 1, "of_matches": n_past + 1,
                    "rough": g.get("cost_n", 99) < 20,  # Rundenchance aus wenigen Vergleichsrunden
                    "lead": g["count"] >= MIN_LEAD_COUNT,
                    "scenes": sorted(g["scenes"], key=lambda s: -(s["cost"] or 0))})
    # Gedächtnis-Bonus nur, wenn die Lektion auch heute ein Muster ist (nicht nur eine Szene)
    out.sort(key=lambda x: (-x["lead"], -(x["lead"] and x["seen_in"] >= 2), -(x["cost"] or 0), -x["count"]))
    return out[:n]


MIN_LEAD_COUNT = 2  # so oft muss eine Lektion heute vorkommen, bevor sie Thema des Matches sein darf


def headline(lessons: list[dict]) -> str | None:
    """Ein Satz wie vom Coach nach dem Match."""
    items = [f"{l['lesson']} ({l['count']}x)" for l in lessons[:2] if l["count"] >= MIN_LEAD_COUNT]
    if not items:
        return None
    # neutral: nicht jeder dieser Tode hat die Runde gekostet (auch in gewonnenen Runden gezählt)
    return "Woran ihr heute am häufigsten gestorben seid: " + " und ".join(items) + "."


# ---------------------------------------------------------------- Coach-Ansprache für den ganzen Match


def _de(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def memory(prev: dict | None, now_lessons: dict, now_rounds: int) -> dict | None:
    """Erinnerung an das Hauptthema des letzten Matches: dort wie oft, heute wie oft (Rate pro Runde)."""
    if not prev or not prev.get("main_lesson") or not prev.get("rounds") or not now_rounds:
        return None
    lid = prev["main_lesson"]
    if lid not in LESSONS:
        return None
    before = sum(d.get(lid, 0) for d in (prev.get("lessons") or {}).values())
    after = sum(d.get(lid, 0) for d in now_lessons.values())
    # Ein Match gegen ein Match ist fast immer Zufall: Zahlen nennen, ein Urteil nur bei klarem Unterschied
    from cstaktik.coaching import compare_rates

    c = compare_rates(before, prev["rounds"], after, now_rounds, min_rounds=0)
    if after == 0:
        # Text ja, Urteil nur aus dem Vergleich: 1x gegen 0x ist noch kein "besser"
        verdict, state = "Heute kein einziges Mal. Jetzt im nächsten Match bestätigen.", c["state"]
    elif c["state"] == "besser":
        verdict, state = "Deutlich weniger, das greift.", "besser"
    elif c["state"] == "schlechter":
        verdict, state = "Deutlich mehr als letztes Mal. Bleib dran.", "schlechter"
    else:
        verdict, state = "Ein Match allein ist noch kein Trend. Bleib dran.", "gleich"
    return {"lesson": LESSONS[lid][0], "before": before, "after": after, "state": state,
            "text": f"Euer Hauptpunkt im letzten Match: „{LESSONS[lid][0]}“, {before}x in {prev['rounds']} Runden. "
                    f"Heute {after}x in {now_rounds} Runden. {verdict}"}


def intro(won: int, lost: int, map_label: str, lessons: list[dict]) -> list[str]:
    """Ansprache in Ich-Form, nur aus Zahlen dieses Matches."""
    on = f" auf {map_label}" if map_label and map_label != "?" else ""  # ohne Mapnamen kein "auf ?"
    out = [f"Ich hab mir euer {won}:{lost}{on} angesehen." if lost > won
           else f"{won}:{lost}{on}. Gewonnen, trotzdem gibt es was zu holen." if won > lost
           else f"{won}:{lost}{on}. Ich hab es mir angesehen."]
    # nur das Thema, und nur bei einem Muster (mind. MIN_LEAD_COUNT Szenen); Zahlen stehen direkt darunter
    if lessons and lessons[0]["count"] >= MIN_LEAD_COUNT:
        out.append(f"Heute geht es um: {lessons[0]['lesson']}.")
    return out


def strengths(now: dict[str, dict], names: dict[str, str], past: list[dict], min_duels: int = 15,
              min_matches: int = 2) -> list[str]:
    """Persönliche Stärke je Spieler: ein Duell-Wert, der klar besser ist als sein eigener Schnitt (Median) der
    letzten Matches. ``now``: sid -> duels.stats() dieses Matches. Nur mit genug Duellen und Vergleichs-Matches."""
    import statistics

    out = []
    for sid, d in now.items():
        if not d or (d.get("n") or 0) < min_duels:
            continue
        rows = [(h.get("duel_stats") or {}).get(sid) for h in past[-5:]]
        rows = [r for r in rows if r and (r.get("n") or 0) >= 5]
        if len(rows) < min_matches:
            continue
        cand = []
        for key, label, unit, better, gap in (("first_hit", "Erste Kugel trifft", " %", 1, 8),
                                               ("won", "Duelle gewonnen", " %", 1, 8),
                                               ("err", "Fadenkreuz im Duell", "°", -1, 2.0)):
            vals = [r[key] for r in rows if r.get(key) is not None]
            if d.get(key) is None or len(vals) < min_matches:
                continue
            med = statistics.median(vals)
            diff = (d[key] - med) * better
            if diff >= gap:
                fmt = (lambda x: f"{x:.0f}") if unit == " %" else _de  # Prozent ganz, Grad mit Komma
                cand.append((diff / gap, f"{names.get(sid, sid)}: {label} {fmt(d[key])}{unit} in {d['n']} Duellen. "
                                         f"Dein Schnitt der letzten {len(vals)} Matches: {fmt(med)}{unit}."))
        if cand:
            out.append(max(cand)[1])
    return out


def duel_reading(d: dict, pro: dict | None, min_duels: int = 15) -> str | None:
    """Ein Satz, was die Duell-Werte zusammen bedeuten (wie ein Coach, der die Zahlen verbindet). Nur bei klaren
    Abständen zu den Pros (gleiche Grenzen wie die Balken) und genug Duellen; sonst None."""
    if not d or (d.get("n") or 0) < min_duels or not pro:
        return None

    def gap(key: str, lower_better: bool = False) -> float | None:
        if d.get(key) is None or pro.get(key) is None:
            return None
        return (pro[key] - d[key]) if lower_better else (d[key] - pro[key])  # > 0 = besser als Pros

    err, first, hit = gap("err", True), gap("shot_first"), gap("first_hit")
    if err is not None and err <= -1.5:
        head = f"Dein Fadenkreuz liegt im Duell weiter neben dem Kopf als bei Pros: {_de(d['err'])}° statt {_de(pro['err'])}°."
        part = _aim_part(d, pro)
        return f"{head} {part}" if part else f"{head} Vorzielen auf Kopfhöhe ist hier der größte Hebel."
    aim_ok = err is not None and err > -1.5
    seen = _seen_reading(d, pro)
    if seen:
        return seen
    tts, ptts = d.get("tts"), pro.get("tts")
    if (tts is not None and ptts is not None and (d.get("tts_n") or 0) >= 10 and (pro.get("tts_n") or 0) >= 10
            and tts - ptts >= 80):
        return (f"Vom Sehen bis zum ersten Schuss brauchst du {tts} ms, Pros {ptts} ms. In der Zeit schießt er. "
                "Liegt dein Fadenkreuz schon auf Kopfhöhe an der Kante, musst du nur klicken.")
    if aim_ok and first is not None and first <= -8:
        return (f"Dein Zielen ist auf Pro-Niveau. Aber du schießt seltener zuerst: {d['shot_first']} %, "
                f"Pros {pro['shot_first']} %. Du siehst den Gegner später. Der Hebel ist Position und Timing, nicht Aim.")
    if aim_ok and hit is not None and hit <= -8:
        if (d.get("moving_n") or 0) >= 10 and (d.get("moving_pct") or 0) >= 30:
            return (f"Dein Fadenkreuz passt. Aber die erste Kugel trifft seltener: {d['first_hit']} %, "
                    f"Pros {pro['first_hit']} %. {d['moving_pct']} % deiner ersten Schüsse kamen aus der Bewegung. "
                    "Erst stoppen, dann schießen.")
        return (f"Dein Fadenkreuz passt. Aber die erste Kugel trifft seltener: {d['first_hit']} %, "
                f"Pros {pro['first_hit']} %.")
    if aim_ok and all(g is not None and g > -8 for g in (first, hit)):
        return ("Im Duell selbst bist du auf Pro-Niveau. Was dich Runden kostet, passiert eher vor dem Duell. "
                "Mehr dazu im Coach-Reiter.")
    return None


def _aim_part(d: dict, pro: dict, min_n: int = 10) -> str | None:
    """Welcher Teil des Fadenkreuz-Fehlers größer ist als bei Pros: Höhe (zu tief) oder seitlich."""
    if (d.get("aim_n") or 0) < min_n or (pro.get("aim_n") or 0) < min_n:
        return None
    low, plow = d.get("low_pct"), pro.get("low_pct")
    if low is not None and plow is not None and low - plow >= 10:
        return (f"Vor allem zu tief. In {low} % der Duelle lag es mehr als 2° unter dem Kopf, Pros {plow} %. "
                "Halte das Fadenkreuz beim Laufen auf Kopfhöhe, nicht am Boden.")
    side, pside = d.get("err_side"), pro.get("err_side")
    if side is not None and pside is not None and side - pside >= 1.5:
        return (f"Die Höhe passt. Aber seitlich liegst du {_de(side)}° daneben, Pros {_de(pside)}°. Du hältst neben "
                "die Stelle, an der er rauskommt. Leg das Fadenkreuz direkt an die Kante.")
    return None


def _seen_reading(d: dict, pro: dict, min_seen: int = 15) -> str | None:
    """Wer sah zuerst, gegen die Pros: zuerst gesehen worden (Position) oder Vorteil verschenkt (Umsetzung)."""
    if (d.get("seen_n") or 0) < min_seen or (pro.get("seen_n") or 0) < min_seen:
        return None
    opp, won_me = d.get("seen_opp"), d.get("won_seen_me")
    if opp is not None and pro.get("seen_opp") is not None and opp - pro["seen_opp"] >= 8:
        tail = (f" Dann gewinnst du nur {d['won_seen_opp']} %." if d.get("won_seen_opp") is not None
                and (d.get("seen_opp_n") or 0) >= 5 else "")
        return (f"Der Gegner sieht dich in {opp} % der Duelle zuerst, Pros {pro['seen_opp']} %.{tail} Das ist "
                "Position, nicht Aim. Steh weniger offen und wechsle nach einem Kill den Platz. Nimm Winkel einzeln, "
                "statt in mehrere gleichzeitig zu laufen.")
    if (won_me is not None and pro.get("won_seen_me") is not None and (d.get("seen_me_n") or 0) >= 8
            and pro["won_seen_me"] - won_me >= 10):
        return (f"Du siehst den Gegner oft zuerst, in {d['seen_me']} % der Duelle. Diese Duelle gewinnst du aber nur "
                f"zu {won_me} %, Pros {pro['won_seen_me']} %. Der Vorteil verpufft. Fadenkreuz vorher auf Kopfhöhe, "
                "stehen bleiben, sofort schießen.")
    return None


def praise(findings: list[Finding]) -> list[str]:
    """Lob je Spieler aus den positiven Befunden ("gut"), z. B. "Bruder: 3x Trade gegeben, Clutch (R12)"."""
    per: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for f in findings:
        if f.severity == "gut" and f.player_name:
            per[f.player_name][f.title].append(f.round)
    out = []
    for name, items in per.items():
        parts = []
        for title, rounds in sorted(items.items(), key=lambda kv: -len(kv[1])):
            rs = [r for r in rounds if r is not None]
            parts.append(f"{len(rounds)}x {title}" if len(rounds) > 1 else f"{title}" + (f" (R{rs[0]})" if rs else ""))
        out.append(f"{name}: " + ", ".join(parts[:3]))
    return out
