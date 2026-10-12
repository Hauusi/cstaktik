"""Fokus-Ziele mit automatischem Ziel-Check (Lern-Kreislauf).

- Messgröße je Ziel: Anteil der Runden eines Matches, in denen die Ursache vorkam
  (aus history["cause_rounds"] / history["rounds"]). Unabhängig davon, ob die Runde gewonnen wurde.
- Neues Ziel: aus den Top-Ursachen des letzten Matches, Zielwert = Ausgangswert x target_factor.
- Check: bei jeder Auswertung. "geschafft", wenn der Zielwert in ``done_after`` Matches in Folge
  erreicht wurde; dann rückt ein neues Ziel nach. Max. ``max_active`` Ziele gleichzeitig.

Gespeichert in data/goals.json. Schwellen in rules.yaml unter ``goals`` (Heuristiken).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from cstaktik.coach import CAUSES

# Ziel-Formulierung und Training je Ursache. Übungen bewusst allgemein (keine Workshop-Map-Namen).
GOAL_TEXT = {
    "alone": ("Nicht mehr allein sterben", [
        "Im nächsten Match: vor jedem Peek kurz checken, ob der Bruder in Trade-Reichweite steht.",
        "Callout vor dem Peek: 'Ich peeke X, komm nach'. Erst peeken, wenn er da ist.",
    ]),
    "opening": ("Weniger als Erster sterben", [
        "Die ersten 20 Sekunden einer Runde nicht aktiv nach dem ersten Duell suchen, sondern Info sammeln.",
        "Ersten Kontakt nur mit Flash oder zu zweit nehmen.",
    ]),
    "blind": ("Gegner-Flashes ausweichen", [
        "Deathmatch/Retake: bei jedem Flash-Geräusch sofort wegdrehen, auch wenn es zu spät wirkt.",
        "Nach dem Wegdrehen einen Schritt zurück, dann neu peeken.",
    ]),
    "low_hp": ("Mit wenig HP passiv spielen", [
        "Unter 50 HP: Position halten, Info geben, auf Trade spielen. Kein neues Duell suchen.",
    ]),
    "outnumbered": ("In Unterzahl zusammen spielen", [
        "In Unterzahl: mit dem nächsten Mitspieler zusammenziehen oder Zeit spielen, keine Einzel-Peeks.",
    ]),
    "moving": ("Stehend schießen", [
        "10 Minuten Deathmatch vor dem Match: nur schießen, wenn du stehst (Counter-Strafe), Treffer zählen.",
        "Peeks kurz und kontrolliert: rauslaufen, stoppen, schießen.",
    ]),
    "no_shot": ("Nicht mehr ohne Gegenwehr sterben", [
        "Vor dem Match 5 Minuten Prefire üben: Ecken einzeln klären, Fadenkreuz vorher auf Kopfhöhe.",
        "Im Match: an bekannten Gegner-Spots langsam und vorgezielt clearen statt durchzulaufen.",
    ]),
    "utility": ("Utility vor dem Duell einsetzen", [
        "Pro Runde mindestens eine Granate werfen, bevor du stirbst.",
        "Für eure Standard-Positionen je eine Flash zum Selbst-Peeken einüben (Offline-Server).",
    ]),
    "advantage": ("Überzahl sauber zu Ende spielen", [
        "In Überzahl: zu zweit gehen, Trades sichern, keine Einzeljagd.",
    ]),
    "economy": ("Gemeinsam kaufen", [
        "Vor jeder Runde ansagen: kaufen, force oder sparen. Alle gleich.",
    ]),
}


# Mechanik-Ziele je Spieler: Kennzahl aus history["mech"][steamid]
MECH_GOALS = {
    "moving_pct": ("Stehend schießen", "Anteil eurer Schüsse in Bewegung", "goal_moving_pct", [
        "10 Minuten Deathmatch vor dem Match: nur schießen, wenn du stehst (Counter-Strafe).",
        "Peeks: rauslaufen, stoppen, schießen. Nicht im Laufen sprayen.",
    ], "Schüsse im Laufen streuen stark. Ein Teil deiner Duelle geht deshalb verloren.",
        "Vor dem Schuss stoppen (Counter-Strafe), dann schießen."),
    "deaths_no_shot_pct": ("Nicht ohne eigenen Schuss sterben", "Anteil deiner Tode ohne eigenen Schuss",
                           "goal_no_shot_pct", [
        "Prefire-Routine vor dem Match: Ecken einzeln klären, Fadenkreuz vorher auf Kopfhöhe.",
    ], "Du stirbst oft, ohne zu schießen: überrascht oder zu langsam.",
        "Vorzielen und Winkel einzeln klären, nicht unvorbereitet laufen."),
}


def _value(summary: dict, goal: dict) -> float | None:
    if goal.get("kind") == "mech":
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
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1))


def update(state: dict, summary: dict, cfg: dict, mech_cfg: dict | None = None) -> dict:
    """Prüft aktive Ziele gegen das neue Match und füllt freie Plätze auf.

    Gibt den Ziel-Check dieses Matches zurück: [{goal, pct, target, met, status}].
    Dieselbe Demo zweimal auszuwerten zählt nicht doppelt.
    """
    match_id = summary.get("id")
    checks = []
    still_active = []
    for g in state["active"]:
        if g.get("created_from") == match_id:
            still_active.append(g)
            continue
        pct = _value(summary, g)
        if pct is None:
            still_active.append(g)
            continue
        prior = [c for c in g["checks"] if c["match"] != match_id]
        entry = {"match": match_id, "pct": pct, "met": pct <= g["target_pct"], "date": summary.get("analyzed_at")}
        g["checks"] = prior + [entry]
        streak = 0
        for c in reversed(g["checks"]):
            if not c["met"]:
                break
            streak += 1
        if streak >= cfg["done_after"]:
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
    new_goals = []
    for cause in summary.get("cause_order", []):
        if len(state["active"]) >= cfg["max_active"]:
            break
        if cause in active_causes or cause not in GOAL_TEXT:
            continue
        base = _pct(summary, cause)
        if not base:
            continue
        title, drills = GOAL_TEXT[cause]
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
    for sid, mech in (summary.get("mech") or {}).items() if mech_cfg else []:
        name = (summary.get("players", {}).get(sid) or {}).get("name", sid)
        for metric, (title, label, thr_key, drills, why, tip) in MECH_GOALS.items():
            if len(state["active"]) >= cfg["max_active"]:
                break
            key = f"mech:{metric}:{sid}"
            base = mech.get(metric)
            if key in active_causes or base is None or base < mech_cfg[thr_key]:
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
