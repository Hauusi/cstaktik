"""Fokus-Ziele mit automatischem Ziel-Check (Lern-Kreislauf).

- Messgröße je Ziel: Anteil der Runden eines Matches, in denen die Ursache vorkam
  (aus history["cause_rounds"] / history["rounds"]). Unabhängig davon, ob die Runde gewonnen wurde.
- Neues Ziel: aus den Top-Ursachen des letzten Matches, Zielwert = Ausgangswert x target_factor.
- Check: bei jeder Auswertung. "geschafft", wenn der Zielwert in ``done_after`` Matches in Folge
  erreicht wurde; dann rückt ein neues Ziel nach. Max. ``max_active`` Ziele gleichzeitig.

Mindestgrößen (rules.yaml ``goals``): Matches unter ``min_check_rounds`` Runden prüfen und erzeugen kein Ziel,
"geschafft" erst ab zusammen ``min_master_rounds`` Runden in der Serie, ein Team-Ziel erst ab ``min_count``
Runden mit der Ursache. Mechanik-Ziele brauchen mindestens ``MIN_MECH_SAMPLE`` Schüsse bzw. Tode.

Gespeichert in data/goals.json. Schwellen in rules.yaml unter ``goals`` (Heuristiken).
"""

from __future__ import annotations

from cstaktik.fsutil import write_atomic

import json
from datetime import datetime
from pathlib import Path

from cstaktik.coach import CAUSES

# Ziel-Formulierung und Training je Ursache. Übungen bewusst allgemein (keine Workshop-Map-Namen).
GOAL_TEXT = {
    "alone": ("Nicht mehr allein sterben", [
        "Prüf im nächsten Match vor jedem Peek, ob dein Bruder in Trade-Reichweite steht.",
        "Sag vor dem Peek an: 'Ich peeke X, komm nach'. Peek erst, wenn er da ist.",
    ]),
    "opening": ("Weniger als Erster sterben", [
        "Such in den ersten 20 Sekunden nicht aktiv das erste Duell. Sammle lieber Info.",
        "Nimm den ersten Kontakt nur mit Flash oder zu zweit.",
    ]),
    "blind": ("Gegner-Flashes ausweichen", [
        "Dreh dich in Deathmatch oder Retake bei jedem Flash-Geräusch sofort weg. Auch wenn es zu spät wirkt.",
        "Geh nach dem Wegdrehen einen Schritt zurück. Peek dann neu.",
    ]),
    "low_hp": ("Mit wenig HP passiv spielen", [
        "Unter 50 HP hältst du Position, gibst Info und spielst auf Trade. Such kein neues Duell.",
    ]),
    "outnumbered": ("In Unterzahl zusammen spielen", [
        "Zieh in Unterzahl mit dem nächsten Mitspieler zusammen oder spiel auf Zeit. Keine Einzel-Peeks.",
    ]),
    "moving": ("Stehend schießen", [
        "Spiel vor dem Match 10 Minuten Deathmatch. Schieß nur im Stehen (Counter-Strafe) und zähl deine Treffer.",
        "Peek kurz und kontrolliert: rauslaufen, stoppen, schießen.",
    ]),
    "no_shot": ("Nicht mehr ohne Gegenwehr sterben", [
        "Üb vor dem Match 5 Minuten Prefire. Kläre Ecken einzeln, das Fadenkreuz vorher auf Kopfhöhe.",
        "Cleare bekannte Gegner-Spots im Match langsam und vorgezielt. Lauf nicht einfach durch.",
    ]),
    "utility": ("Utility vor dem Duell einsetzen", [
        "Wirf pro Runde mindestens eine Granate, bevor du stirbst.",
        "Üb für eure Standard-Positionen je eine Flash zum Selbst-Peeken ein. Am besten auf einem Offline-Server.",
    ]),
    "advantage": ("Überzahl sauber zu Ende spielen", [
        "Geht in Überzahl zu zweit und sichert Trades. Keine Einzeljagd.",
    ]),
    "economy": ("Gemeinsam kaufen", [
        "Sagt vor jeder Runde an: kaufen, force oder sparen. Alle machen dasselbe.",
    ]),
}


# Mechanik-Ziele je Spieler: Kennzahl aus history["mech"][steamid]
MECH_GOALS = {
    "moving_pct": ("Stehend schießen", "Anteil eurer Schüsse in Bewegung", "goal_moving_pct", [
        "Spiel vor dem Match 10 Minuten Deathmatch. Schieß nur im Stehen (Counter-Strafe).",
        "Peek so: rauslaufen, stoppen, schießen. Spray nicht im Laufen.",
    ], "Schüsse im Laufen streuen stark. Ein Teil deiner Duelle geht deshalb verloren.",
        "Stopp vor dem Schuss mit Counter-Strafe. Dann schieß."),
    "deaths_no_shot_pct": ("Nicht ohne eigenen Schuss sterben", "Anteil deiner Tode ohne eigenen Schuss",
                           "goal_no_shot_pct", [
        "Mach vor dem Match eine Prefire-Routine. Kläre Ecken einzeln, das Fadenkreuz vorher auf Kopfhöhe.",
    ], "Du stirbst oft, ohne zu schießen. Du wirst überrascht oder bist zu langsam.",
        "Ziel vor und kläre Winkel einzeln. Lauf nicht unvorbereitet."),
}


MIN_MECH_SAMPLE = 8  # weniger Schüsse/Tode: ein Prozentwert ist Zufall


def _mech_sample(summary: dict, sid: str, metric: str) -> int | None:
    """Stichprobe hinter einer Mechanik-Kennzahl: Schüsse (moving_pct) bzw. Tode (deaths_no_shot_pct)."""
    if metric == "moving_pct":
        return (summary.get("mech", {}).get(sid) or {}).get("shots")
    if metric == "deaths_no_shot_pct":
        return (summary.get("players", {}).get(sid) or {}).get("deaths")
    return None


def _value(summary: dict, goal: dict) -> float | None:
    if goal.get("kind") == "mech":
        n = _mech_sample(summary, goal["player"], goal["metric"])
        if n is None or n < MIN_MECH_SAMPLE:
            return None  # zu wenig Daten: zählt weder für noch gegen das Ziel
        return (summary.get("mech", {}).get(goal["player"]) or {}).get(goal["metric"])
    return _pct(summary, goal["cause"])


def _pct(summary: dict, cause: str) -> float | None:
    rounds = summary.get("rounds") or 0
    if not rounds or "cause_rounds" not in summary:
        return None
    return round(100 * summary["cause_rounds"].get(cause, 0) / rounds, 1)


def load(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            pass
    return {"active": [], "done": []}


def save(state: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, json.dumps(state, ensure_ascii=False, indent=1))


def update(state: dict, summary: dict, cfg: dict, mech_cfg: dict | None = None) -> dict:
    """Prüft aktive Ziele gegen das neue Match und füllt freie Plätze auf.

    Gibt den Ziel-Check dieses Matches zurück: [{goal, pct, target, met, status}].
    Dieselbe Demo zweimal auszuwerten zählt nicht doppelt.
    """
    match_id = summary.get("id")
    checks = []
    still_active = []
    rounds = summary.get("rounds") or 0
    min_check = cfg.get("min_check_rounds", 12)
    enough = rounds >= min_check  # kurzes Match: kein Check, kein neues Ziel
    for g in state["active"]:
        if g.get("created_from") == match_id:
            still_active.append(g)
            continue
        pct = _value(summary, g) if enough else None
        when = summary.get("analyzed_at") or ""
        if pct is None or (when and when < (g.get("created_at") or "")):  # älteres Match als das Ziel: zählt nicht
            still_active.append(g)
            continue
        prior = [c for c in g["checks"] if c["match"] != match_id]
        entry = {"match": match_id, "pct": pct, "met": pct <= g["target_pct"], "date": summary.get("analyzed_at"),
                 "rounds": rounds}
        # chronologisch, damit ein später neu ausgewertetes altes Match die Serie nicht verfälscht
        g["checks"] = sorted(prior + [entry], key=lambda c: c.get("date") or "")
        streak = streak_rounds = 0
        for c in reversed(g["checks"]):
            if not c["met"]:
                break
            streak += 1
            streak_rounds += c.get("rounds") or 0  # alte Checks ohne Rundenzahl zählen nicht mit
        if streak >= cfg["done_after"] and streak_rounds >= cfg.get("min_master_rounds", 40):
            g["status"] = "geschafft"
            g["done_at"] = summary.get("analyzed_at")
            state["done"].append(g)
        else:
            g["status"] = "aktiv"
            still_active.append(g)
        checks.append({"title": g["title"], "pct": pct, "target": g["target_pct"], "met": entry["met"],
                       "status": g["status"], "streak": streak})
    state["active"] = still_active

    active_causes = {g["cause"] for g in state["active"]}
    # gerade geschafft: nicht aus demselben oder einem älteren Match sofort wieder anlegen
    when = summary.get("analyzed_at") or ""
    active_causes |= {g["cause"] for g in state["done"] if (g.get("done_at") or "") >= when}
    new_goals = []
    for cause in summary.get("cause_order", []) if enough else []:
        if len(state["active"]) >= cfg["max_active"]:
            break
        if cause in active_causes or cause not in GOAL_TEXT:
            continue
        base = _pct(summary, cause)
        if not base or (summary.get("cause_rounds") or {}).get(cause, 0) < cfg.get("min_count", 3):
            continue
        title, drills = GOAL_TEXT[cause]
        from cstaktik.coach_voice import LESSONS

        title = LESSONS[cause][0] if cause in LESSONS else title  # überall dieselbe Sprache wie Auftrag und Report
        state["active"].append({
            "cause": cause,
            "title": title,
            "why": CAUSES[cause]["explain"],
            "tip": CAUSES[cause]["tip"],
            "drills": drills,
            "baseline_pct": base,
            "target_pct": round(base * cfg["target_factor"], 1),
            "created_at": summary.get("analyzed_at") or datetime.now().isoformat(timespec="minutes"),
            "created_from": match_id,
            "checks": [],
            "status": "aktiv",
        })
        active_causes.add(cause)
        new_goals.append(state["active"][-1]["title"])

    # Mechanik-Ziele je Spieler, wenn eine Kennzahl über der Schwelle liegt
    for sid, mech in (summary.get("mech") or {}).items() if mech_cfg and enough else []:
        name = (summary.get("players", {}).get(sid) or {}).get("name", sid)
        for metric, (title, label, thr_key, drills, why, tip) in MECH_GOALS.items():
            if len(state["active"]) >= cfg["max_active"]:
                break
            key = f"mech:{metric}:{sid}"
            if metric == "moving_pct" and "moving" in active_causes:
                continue  # dasselbe Thema läuft schon als Team-Ziel ("Stehend schießen")
            base = mech.get(metric)
            n = _mech_sample(summary, sid, metric)
            if key in active_causes or base is None or base < mech_cfg[thr_key] or n is None or n < MIN_MECH_SAMPLE:
                continue
            state["active"].append({
                "cause": key, "kind": "mech", "metric": metric, "player": sid,
                "title": f"{title} ({name})", "why": why, "tip": tip, "drills": drills, "label": label,
                "baseline_pct": base, "target_pct": round(base * cfg["target_factor"], 1),
                "created_at": summary.get("analyzed_at") or datetime.now().isoformat(timespec="minutes"),
                "created_from": match_id, "checks": [], "status": "aktiv",
            })
            active_causes.add(key)
            new_goals.append(state["active"][-1]["title"])
    return {"checks": checks, "new": new_goals,
            "active": [{"title": g["title"], "target": g["target_pct"], "baseline": g["baseline_pct"]} for g in state["active"]]}
