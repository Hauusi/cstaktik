"""Texte des Kurses: Ein Coach bringt CS2 Schritt für Schritt bei.

Aufbau: ``STAGES`` ist der Lernpfad (Reihenfolge = Reihenfolge im Kurs), ``LESSONS`` die Lektionen. Die Schlüssel der
Lektionen sind dieselben wie in coach_voice.LESSONS (dort wird gezählt, wie oft der Fehler im Match passiert).

Regeln für die Texte:
- Ganze, verständliche Sätze. Der Coach spricht den Spieler mit "du" an, ruhig und klar, wie ein Trainer.
- Allgemeines CS-Wissen ist erlaubt (warum etwas Runden gewinnt, wie man es übt). Keine erfundenen Zahlen über den
  Spieler oder die Pros; Zahlen kommen nur aus den Demos und werden von der App eingesetzt.

Felder je Lektion:
- ``title``: kurzer Titel, z. B. "Erst stoppen, dann schießen"
- ``stage``: Schlüssel der Stufe in STAGES
- ``goal``: ein Satz, was du nach der Lektion kannst
- ``what``: 2 bis 3 Sätze, worum es geht
- ``why``: 2 bis 3 Sätze, warum das Runden gewinnt
- ``spot``: 1 bis 2 Sätze, woran du im Match merkst, dass es gerade zählt
- ``how``: 3 bis 4 Schritte, wie du es richtig machst (Liste von Sätzen)
- ``drill``: konkrete Übung mit "name", "where" (Workshop-Map oder Modus), "minutes", "steps" (Liste), "done"
  (woran du merkst, dass die Übung sitzt)
- ``measure``: ein Satz, was der Coach in deinen Matches zählt (passend zum Fehler in coach_voice)
"""

STAGES = [
    {"key": "shoot", "title": "Schießen", "intro": ""},
    {"key": "duel", "title": "Duelle", "intro": ""},
    {"key": "utility", "title": "Granaten", "intro": ""},
    {"key": "team", "title": "Zusammenspiel", "intro": ""},
    {"key": "round", "title": "Runden lesen", "intro": ""},
]

# Reihenfolge innerhalb einer Stufe = Reihenfolge im Kurs
LESSONS: dict[str, dict] = {
    "moving_shot": {"stage": "shoot", "title": "Erst stoppen, dann schießen"},
    "crosshair": {"stage": "shoot", "title": "Fadenkreuz vorher auf den Spot"},
    "no_shot_close": {"stage": "duel", "title": "Ecke vorzielen statt reinlaufen"},
    "seen_first": {"stage": "duel", "title": "Sehen, bevor du gesehen wirst"},
    "angle": {"stage": "duel", "title": "Nicht offen in mehrere Winkel stehen"},
    "no_shot_far": {"stage": "duel", "title": "Lange Linien nicht offen kreuzen"},
    "moving": {"stage": "duel", "title": "Nicht laufend in den Winkel"},
    "utility": {"stage": "utility", "title": "Erst Utility, dann Duell"},
    "blind": {"stage": "utility", "title": "Bei Flash sofort wegdrehen"},
    "alone": {"stage": "team", "title": "Nicht ohne Trade-Partner peeken"},
    "low_hp": {"stage": "round", "title": "Mit wenig HP kein neues Duell"},
    "outnumbered": {"stage": "round", "title": "In Unterzahl zusammenbleiben"},
}


def path() -> list[str]:
    """Lektionen in Kursreihenfolge (Stufe für Stufe)."""
    order = [s["key"] for s in STAGES]
    return sorted(LESSONS, key=lambda k: (order.index(LESSONS[k]["stage"]), list(LESSONS).index(k)))
