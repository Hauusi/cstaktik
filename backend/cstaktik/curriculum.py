"""Lehrplan je Coach-Lektion: Prinzip (warum), Merksatz, was als Fehler zählt, Übungsroutine, Ansage fürs Match.

Allgemeines CS-Wissen, als Ratschlag formuliert. Keine Zahlen über dich, die stehen in den Analysen.
Übungen nennen nur Dinge, die es sicher gibt (Deathmatch, Offline-Server mit Bots, Retake-Server,
Prefire-Maps aus dem Steam-Workshop), keine erfundenen Befehle oder Map-Namen.
"""

from __future__ import annotations

TEACH: dict[str, dict] = {
    "no_shot_close": {
        "fault": "Ein Tod auf kurze Distanz, ohne dass du geschossen hast.",
        "principle": ("Wer einen Winkel hält, muss nur klicken. Wer reinläuft, muss erst finden, zielen und klicken. "
                      "Deshalb verliert der Laufende fast immer. Außer sein Fadenkreuz ist schon dort, wo der Kopf "
                      "auftaucht."),
        "mantra": "Fadenkreuz zuerst, Füße danach.",
        "in_game": "Vor jeder Ecke das Fadenkreuz auf Kopfhöhe an die Kante. Dann langsam aufschneiden (Pie).",
        "routine": {"title": "Prefire-Routine", "minutes": 10, "steps": [
            "Prefire-Map deiner nächsten Map aus dem Steam-Workshop laden.",
            "Jeden Spot einzeln clearen. Erst das Fadenkreuz an die Kante, dann bewegen.",
            "Ziel: Das Fadenkreuz liegt auf Kopfhöhe, bevor der Bot sichtbar wird.",
            "Klappt ein Spot nicht, sofort wiederholen.",
        ]},
    },
    "no_shot_far": {
        "fault": "Ein Tod auf einer langen, offenen Linie, ohne dass du geschossen hast.",
        "principle": ("Lange Linien gehören dem, der sie hält, meist mit AWP oder Rifle. Wer sie offen kreuzt, gibt "
                      "ihm einen freien Schuss. Eine Smoke oder ein anderer Weg nimmt ihm diesen Vorteil."),
        "mantra": "Lange Linie? Smoke oder anderer Weg.",
        "in_game": "Vor einer offenen Linie fragen: Gibt es Smoke, Flash oder einen Umweg? Wenn nicht, nicht kreuzen.",
        "routine": {"title": "Smokes für deine Wege", "minutes": 10, "steps": [
            "Offline-Server: Such die zwei Linien, auf denen du am häufigsten stirbst. Mach beide mit einer Smoke zu.",
            "Jede Smoke 5x werfen, bis sie sitzt.",
            "Im Match: diese Smoke zuerst werfen, dann kreuzen.",
        ]},
    },
    "blind": {
        "fault": "Ein Tod, während du geblendet warst.",
        "principle": ("Eine Flash wirkt nur, wenn du hinschaust. Wegdrehen kostet einen Augenblick. Geblendet "
                      "stehen bleiben kostet die Runde. Wer wegdreht und zurückgeht, kann danach traden."),
        "mantra": "Flash hören, wegdrehen, zurück.",
        "in_game": "Bei jedem Flash-Geräusch sofort wegdrehen und hinter Deckung. Auch wenn es zu spät wirkt.",
        "routine": {"title": "Flash-Reflex", "minutes": 5, "steps": [
            "Retake-Server, denn dort fliegen Flashes. Bei jedem Flash-Geräusch wegdrehen.",
            "Danach erst wieder peeken.",
            "Ziel: 10 Runden in Folge kein einziges Mal geblendet gestorben.",
        ]},
    },
    "alone": {
        "fault": "Ein Tod, den keiner traden konnte, weil kein Mitspieler in der Nähe war.",
        "principle": ("In CS gewinnt das Team, das seine Tode tradet. Stirbst du allein, seid ihr einer weniger. "
                      "Ohne Gegenleistung. Ist ein Mitspieler in Reichweite, verliert der Gegner fast immer auch "
                      "einen Spieler."),
        "mantra": "Nie allein in ein Duell.",
        "in_game": "Vor dem Peek callen, etwa „ich peeke X“. Dann warten, bis dein Mitspieler nachziehen kann.",
        "routine": {"title": "Zu zweit peeken", "minutes": 10, "steps": [
            "Retake-Server zu zweit. Regel: Keiner peekt allein.",
            "Einer peekt, der andere zieht sofort nach (Trade).",
            "Nach jeder Runde kurz: War der Trade möglich?",
            "Ziel: 10 Runden in Folge kein Solo-Peek.",
        ]},
    },
    "utility": {
        "fault": "Ein Tod, obwohl du noch Flash, Smoke oder Molotov dabei hattest.",
        "principle": ("Granaten machen ein faires Duell unfair, zu deinen Gunsten. Wer mit Granaten stirbt, "
                      "hat bezahlt und nichts bekommen."),
        "mantra": "Granate raus, bevor du rausgehst.",
        "in_game": "Vor jedem geplanten Duell eine Flash oder Molotov. Spätestens, wenn es losgeht.",
        "routine": {"title": "Eine Pop-Flash pro Position", "minutes": 10, "steps": [
            "Offline-Server: Lern für deine zwei Standard-Positionen je eine Flash, mit der du selbst peekst.",
            "Jede Flash 5x üben. Werfen, kurz warten, peeken.",
        ]},
    },
    "low_hp": {
        "fault": "Ein Tod in einem neuen Duell, das du mit wenig HP gesucht hast.",
        "principle": "Mit wenig HP reicht dem Gegner ein Treffer. Dann zählen Info und Trade, nicht das nächste Duell.",
        "mantra": "Unter 50 HP: Info, nicht Duell.",
        "in_game": "Mit wenig HP zurückfallen. Callen, wo der Gegner ist. Auf den Trade deines Mitspielers spielen.",
        "routine": {"title": "Wenig-HP-Runden", "minutes": 10, "steps": [
            "Retake-Server, 10 Runden. Unter 50 HP zurückfallen und nur noch callen.",
            "Erst wieder ins Duell, wenn ein Mitspieler direkt dabei ist.",
            "Ziel: kein Tod unter 50 HP ohne Mitspieler daneben.",
        ]},
    },
    "moving_shot": {
        "fault": "Ein verlorenes Duell, in dem du aus der Bewegung geschossen hast.",
        "principle": ("In CS2 streuen Schüsse aus der Bewegung stark. Wer zum Schießen stoppt, trifft. "
                      "Wer im Laufen schießt, verliert gegen jeden, der steht."),
        "mantra": "Stopp, dann Schuss.",
        "in_game": "Rauslaufen, Gegenrichtung tippen, schießen. Nie laufend sprayen.",
        "routine": {"title": "Counter-Strafe", "minutes": 10, "steps": [
            "Deathmatch: nur schießen, wenn du stehst.",
            "Strafen, Gegenrichtung tippen, ein bis drei Schüsse, weiter strafen.",
            "Ziel: 3 Deathmatch-Runden ohne Schuss aus dem Laufen. Selbst mitzählen.",
        ]},
    },
    "moving": {
        "fault": "Ein Tod, während du in einen Winkel gelaufen bist.",
        "principle": "Wer in einen gehaltenen Winkel läuft, ist ein bewegtes Ziel ohne eigenen Schuss.",
        "mantra": "Vor dem Winkel stoppen.",
        "in_game": "Vor jedem Winkel kurz stoppen, aufschneiden, erst dann rein.",
        "routine": {"title": "Langsam clearen", "minutes": 10, "steps": [
            "Prefire-Map: jeden Winkel mit Stopp vorher clearen.",
            "Ziel: ein ganzer Durchgang, an jedem Winkel vorher gestoppt.",
        ]},
    },
    "outnumbered": {
        "fault": "Ein Tod in einem Einzelduell, das du in Unterzahl gesucht hast.",
        "principle": ("In Unterzahl gewinnst du keine Einzelduelle. Ihr gewinnt nur zusammen. Oder ihr lasst "
                      "die Zeit für euch arbeiten."),
        "mantra": "Unterzahl heißt zusammen oder Zeit.",
        "in_game": "In Unterzahl zum nächsten Mitspieler gehen. Gemeinsam spielen, keine Solo-Peeks.",
        "routine": {"title": "Retake zu zweit", "minutes": 10, "steps": [
            "Retake-Server: In Unterzahl sofort zum nächsten Mitspieler laufen.",
            "Gemeinsam auf einen Spot gehen. Nicht getrennt Duelle suchen.",
            "Ziel: 10 Unterzahl-Situationen ohne Solo-Duell.",
        ]},
    },
    "crosshair": {
        "fault": "Ein Duell, bei dessen Start dein Fadenkreuz deutlich neben dem Gegner lag.",
        "principle": ("Ein Duell ist oft entschieden, bevor jemand schießt. Wessen Fadenkreuz schon auf dem Kopf "
                      "liegt, muss nur klicken. Jedes Grad Nachziehen kostet Zeit. Die nutzt der Gegner."),
        "mantra": "Fadenkreuz wartet schon da.",
        "in_game": "Beim Laufen und Halten: Fadenkreuz auf Kopfhöhe an die nächste Kante, an der ein Gegner kommen kann.",
        "routine": {"title": "Crosshair-Placement", "minutes": 10, "steps": [
            "Prefire-Map deiner Map: An jeder Ecke das Fadenkreuz vorher auf Kopfhöhe an die Kante.",
            "Deathmatch: Beim Laufen bewusst nie auf den Boden schauen.",
        ]},
    },
    "angle": {
        "fault": "Ein Tod aus einer Richtung, in die du nicht geschaut hast. Mehrere Winkel waren offen.",
        "principle": ("Du kannst nur in eine Richtung schauen. Zeigen zwei oder drei Winkel auf dich, verlierst du. "
                      "Der Gegner kommt aus dem Winkel, den du gerade nicht prüfst."),
        "mantra": "Ein Winkel pro Spieler.",
        "in_game": "Vor dem Halten fragen: Von wo kann er kommen? Mehr als ein Winkel? Dann Position wechseln oder absprechen.",
        "routine": {"title": "Positionen prüfen", "minutes": 10, "steps": [
            "Offline-Server: Stell dich auf deine drei Standard-Positionen.",
            "Zähl für jede, aus wie vielen Winkeln man dich sieht. Mehr als einer? Such eine bessere Stelle.",
            "Ziel: für jede Position eine Stelle mit nur einem offenen Winkel.",
        ]},
    },
    "seen_first": {
        "fault": "Ein Tod, bei dem der Gegner dich zuerst gesehen hat.",
        "principle": ("Ein Duell beginnt, wenn einer den anderen sieht. Wer zuerst sieht, hat Zeit zu zielen. "
                      "Der andere muss erst reagieren. Das holst du nicht mit Aim auf. Es hängt davon ab, wo du "
                      "stehst und wie du in den Winkel kommst."),
        "mantra": "Erst sehen, dann gesehen werden.",
        "in_game": ("Beim Halten nicht an der offenen Kante kleben. Tiefer stehen oder Off-Angle, dann siehst du "
                    "seinen Peek zuerst. Beim Peeken einen Winkel nach dem anderen nehmen."),
        "routine": {"title": "Sichtlinien prüfen", "minutes": 10, "steps": [
            "Map-Buch öffnen. Die orangen Punkte zeigen, wo er dich zuerst gesehen hat.",
            "Offline-Server: Stell dich genau dorthin. Lauf zur Killer-Position und schau zurück. Wie früh sieht man dich?",
            "Such für jeden Ort eine Stelle, an der du ihn zuerst siehst. Etwa tiefer, Off-Angle oder andere Kante.",
        ]},
    },
    "duel": {
        "fault": "Ein verlorenes Duell, obwohl die Lage in Ordnung war.",
        "principle": "Die Lage war in Ordnung. Das Duell selbst ging verloren. Das trainierst du mit Aim, nicht mit Taktik.",
        "mantra": "Aim warm, Kopf ruhig.",
        "in_game": "Vorzielen auf Kopfhöhe, ruhig bleiben.",
        "routine": {"title": "Aim-Warmup", "minutes": 10, "steps": ["10 Minuten Deathmatch vor dem Match."]},
    },
}
