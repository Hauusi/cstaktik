"""Lehrplan je Coach-Lektion: Prinzip (warum), Merksatz, Übungsroutine, Ansage fürs Match.

Allgemeines CS-Wissen, als Ratschlag formuliert. Keine Zahlen über dich, die stehen in den Analysen.
Übungen nennen nur Dinge, die es sicher gibt (Deathmatch, Offline-Server mit Bots, Retake-Server,
Prefire-Maps aus dem Steam-Workshop), keine erfundenen Befehle oder Map-Namen.
"""

from __future__ import annotations

TEACH: dict[str, dict] = {
    "no_shot_close": {
        "principle": ("Wer einen Winkel hält, muss nur klicken. Wer reinläuft, muss erst finden, dann zielen, dann "
                      "klicken. Deshalb verliert der Laufende fast immer, wenn sein Fadenkreuz nicht schon dort ist, "
                      "wo der Kopf auftaucht."),
        "mantra": "Fadenkreuz zuerst, Füße danach.",
        "in_game": "Vor jeder Ecke: Fadenkreuz auf Kopfhöhe an die Kante, dann langsam aufschneiden (Pie).",
        "routine": {"title": "Prefire-Routine", "minutes": 10, "steps": [
            "Prefire-Map deiner nächsten Map aus dem Steam-Workshop laden.",
            "Jeden Spot einzeln clearen: Fadenkreuz an die Kante, dann erst bewegen.",
            "Ziel: einen ganzen Durchgang ohne Treffer bekommen.",
        ]},
    },
    "no_shot_far": {
        "principle": ("Lange Linien gehören dem, der sie hält (meist mit AWP oder Rifle). Wer sie offen kreuzt, gibt "
                      "dem Gegner einen freien Schuss. Eine Smoke oder ein anderer Weg nimmt ihm diesen Vorteil."),
        "mantra": "Lange Linie? Smoke oder anderer Weg.",
        "in_game": "Bevor du eine offene Linie kreuzt: Gibt es Smoke, Flash oder einen Umweg? Sonst nicht kreuzen.",
        "routine": {"title": "Smokes für deine Wege", "minutes": 10, "steps": [
            "Offline-Server: die zwei Linien, über die du am häufigsten stirbst, mit einer Smoke zumachen.",
            "Jede Smoke 5x werfen, bis sie sitzt.",
            "Im Match: diese Smoke zuerst werfen, dann kreuzen.",
        ]},
    },
    "blind": {
        "principle": ("Eine Flash wirkt nur, wenn du hinschaust. Wegdrehen kostet einen Augenblick, geblendet "
                      "stehenbleiben kostet die Runde. Wer weggedreht und einen Schritt zurück ist, wird zum Trader."),
        "mantra": "Flash hören, wegdrehen, zurück.",
        "in_game": "Bei jedem Flash-Geräusch sofort wegdrehen und einen Schritt hinter Deckung, auch wenn es zu spät wirkt.",
        "routine": {"title": "Flash-Reflex", "minutes": 5, "steps": [
            "Retake- oder Deathmatch-Server: bei jedem Flash-Geräusch wegdrehen, keine Ausnahme.",
            "Danach erst wieder peeken.",
        ]},
    },
    "alone": {
        "principle": ("In CS gewinnt das Team, das seine Tode tradet. Stirbst du allein, ist es ein Spieler weniger "
                      "ohne Gegenleistung. Stirbst du mit Mitspieler in Reichweite, kostet es den Gegner fast immer "
                      "auch einen Spieler."),
        "mantra": "Nie allein in ein Duell.",
        "in_game": "Vor dem Peek callen (\"ich peeke X\") und warten, bis dein Mitspieler nah genug zum Nachziehen ist.",
        "routine": {"title": "Zu zweit peeken", "minutes": 10, "steps": [
            "Retake-Server zu zweit: Regel, keiner peekt allein.",
            "Einer peekt, der andere zieht sofort nach (Trade).",
            "Nach jeder Runde kurz: War der Trade möglich?",
        ]},
    },
    "utility": {
        "principle": ("Granaten machen ein faires Duell unfair, zu deinen Gunsten. Wer mit Granaten im Inventar stirbt, "
                      "hat bezahlt, aber nichts bekommen."),
        "mantra": "Erst Utility, dann Duell.",
        "in_game": "Vor jedem geplanten Duell eine Flash oder Molotov. Spätestens wenn du merkst, dass es losgeht.",
        "routine": {"title": "Eine Pop-Flash pro Position", "minutes": 10, "steps": [
            "Offline-Server: für deine zwei Standard-Positionen je eine Flash, mit der du selbst peekst.",
            "Jede Flash 5x werfen: werfen, kurz warten, peeken.",
        ]},
    },
    "low_hp": {
        "principle": ("Mit wenig HP reicht dem Gegner ein Treffer. Dein Wert ist dann Info und Trade, nicht das "
                      "nächste Duell."),
        "mantra": "Unter 50 HP: Info, nicht Duell.",
        "in_game": "Mit wenig HP: zurückfallen, callen, wo der Gegner ist, auf den Trade deines Mitspielers spielen.",
        "routine": {"title": "Disziplin-Runde", "minutes": 5, "steps": [
            "Im nächsten Match: Bei unter 50 HP laut sagen \"ich spiele passiv\".",
            "Erst wieder peeken, wenn ein Mitspieler dabei ist.",
        ]},
    },
    "moving_shot": {
        "principle": ("In CS2 streuen Schüsse aus der Bewegung stark. Wer zum Schießen stoppt (Counter-Strafe), "
                      "trifft. Wer im Laufen schießt, verliert gegen jeden, der steht."),
        "mantra": "Stopp, dann Schuss.",
        "in_game": "Rauslaufen, Gegenrichtung tippen, schießen. Nie laufend sprayen.",
        "routine": {"title": "Counter-Strafe", "minutes": 10, "steps": [
            "Deathmatch: nur schießen, wenn du stehst.",
            "Strafen, Gegenrichtung tippen, ein bis drei Schüsse, weiter strafen.",
        ]},
    },
    "moving": {
        "principle": "Wer in einen gehaltenen Winkel läuft, ist ein bewegtes Ziel ohne eigenen Schuss.",
        "mantra": "Vor dem Winkel stoppen.",
        "in_game": "Vor jedem Winkel kurz stoppen, aufschneiden, erst dann rein.",
        "routine": {"title": "Langsam clearen", "minutes": 10, "steps": [
            "Prefire-Map: jeden Winkel mit Stopp vorher clearen.",
        ]},
    },
    "outnumbered": {
        "principle": ("In Unterzahl gewinnst du keine Einzelduelle. Du gewinnst, indem ihr zusammen spielt oder die "
                      "Zeit für euch arbeiten lasst."),
        "mantra": "Unterzahl heißt zusammen oder Zeit.",
        "in_game": "Bei Unterzahl: zum nächsten Mitspieler, gemeinsam spielen, keine Solo-Peeks.",
        "routine": {"title": "Retake zu zweit", "minutes": 10, "steps": [
            "Retake-Server: 2 gegen mehr bewusst gemeinsam lösen.",
        ]},
    },
    "crosshair": {
        "principle": ("Ein Duell wird oft entschieden, bevor jemand schießt: Wessen Fadenkreuz schon auf dem Kopf liegt, "
                      "muss nur klicken. Jedes Grad, das du nachziehen musst, kostet Zeit, die der Gegner nutzt."),
        "mantra": "Fadenkreuz wartet schon da.",
        "in_game": "Beim Laufen und Halten: Fadenkreuz immer auf Kopfhöhe an die nächste Kante, wo ein Gegner kommen kann.",
        "routine": {"title": "Crosshair-Placement", "minutes": 10, "steps": [
            "Prefire-Map deiner Map: an jeder Ecke Fadenkreuz vorher an die Kante auf Kopfhöhe.",
            "Deathmatch: beim Laufen bewusst nie auf den Boden schauen.",
        ]},
    },
    "duel": {
        "principle": "Die Lage war in Ordnung, das Duell selbst ging verloren. Das trainiert man mit Aim, nicht mit Taktik.",
        "mantra": "Aim warm, Kopf ruhig.",
        "in_game": "Vorzielen auf Kopfhöhe, ruhig bleiben.",
        "routine": {"title": "Aim-Warmup", "minutes": 10, "steps": ["10 Minuten Deathmatch vor dem Match."]},
    },
}
