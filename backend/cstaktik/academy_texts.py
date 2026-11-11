"""CS-Wissen: die Wissensbasis des Coaches. Jeder Bereich des Spiels als Thema mit Erklärung, Beispiel, typischen
Fehlern, Übung und Wissens-Check.

Regeln für die Texte (wie course_texts):
- Ganze Sätze, "du", ruhig und klar wie ein Trainer. Allgemeines CS-Wissen, keine Zahlen über den Spieler.
- Feste Spielwerte nur, wenn sie geprüft sind (Stand CS2, 2026): Loss-Bonus 1400/1900/2400/2900/3400 $, verlorene
  Pistolenrunde 1900 $, Rundensieg 3250 $ (Bombe gezündet oder entschärft 3500 $), Kill-Prämie Messer 1500 $,
  Schrotflinten 900 $ (XM1014 600 $), MPs 600 $ (P90 300 $), Gewehre und Pistolen 300 $, AWP 100 $, Bombe 40 s,
  Entschärfen 10 s, mit Kit 5 s, Kit 400 $. Werte, die nicht sicher sind (Dauer von Smoke und Molotov,
  Freeze-Time), stehen nicht drin.
- Anweisungen mit äußerem Fokus formulieren ("Fadenkreuz an die Kante", nicht "Hand ruhig halten"): Das hilft
  beim Lernen von Bewegungen (Chua u. a. 2021; Effekt umstritten, McKay u. a. 2024).
- Übungen nennen nur Modi und Werkzeuge, die es sicher gibt (Deathmatch, Offline-Server mit Bots, Retake-Server,
  Workshop-Maps wie Aim Botz und Prefire-Maps, Demo ansehen).

Felder je Thema (TOPICS):
- ``area``: Schlüssel in AREAS, ``title``, ``key``: der Kernsatz in einem Satz
- ``teach``: 2 bis 4 Absätze Erklärung
- ``example``: Schritte eines Beispiels, wie es richtig abläuft (ausgearbeitetes Beispiel)
- ``mistakes``: typische Fehler
- ``drill``: {"where", "steps", "done"}
- ``cue``: kurzes Schlüsselwort, ``ask``: Frage für die eigene Demo-Review
- ``quiz``: Fragen {"id", "q", "options", "a" (Index der richtigen Antwort), "why"}
- ``lessons``: verwandte Kurs-Lektionen (course_texts.LESSONS), ``links``: Seiten der App ("granaten", "duelle",
  "stats", "lineups", "playbook", "briefing", "mapbook")
"""

from __future__ import annotations

AREAS = [
    {"key": "aim", "title": "Schießen und Bewegen",
     "intro": "Die Mechanik, ohne die nichts anderes funktioniert: wo dein Fadenkreuz wartet, wie du stoppst und wie du "
              "nach dem ersten Schuss weiter triffst."},
    {"key": "duel", "title": "Duelle und Peeks",
     "intro": "Wie du in ein Duell gehst, entscheidet oft mehr als dein Aim. Hier lernst du die Arten zu peeken und "
              "wann welche passt."},
    {"key": "info", "title": "Information und Kommunikation",
     "intro": "CS gewinnt, wer mehr weiß und es schneller teilt. Sound, Radar und klare Calls machen aus fünf Spielern "
              "ein Team."},
    {"key": "eco", "title": "Economy",
     "intro": "Geld ist eine zweite Lebensleiste. Wer richtig kauft und spart, hat in den wichtigen Runden die "
              "besseren Waffen."},
    {"key": "nades", "title": "Granaten",
     "intro": "Smokes, Flashes, Molotovs und HEs machen Duelle unfair. Hier lernst du, wofür jede Granate da ist und "
              "in welcher Reihenfolge sie wirkt."},
    {"key": "t", "title": "T-Seite",
     "intro": "Als T hast du die Wahl: wo, wann und wie. Map-Kontrolle, Execute, Split, Lurk und die Entscheidung "
              "mitten in der Runde."},
    {"key": "ct", "title": "CT-Seite",
     "intro": "Als CT verteidigst du mit weniger Infos. Positionen, Crossfires, Rotationen und wann du einen Bombspot "
              "aufgibst."},
    {"key": "bomb", "title": "Bombe, Post-Plant und Retake",
     "intro": "Nach dem Plant dreht sich die Runde: Jetzt muss der CT kommen. Wer das versteht, gewinnt Runden in "
              "Unterzahl."},
    {"key": "round", "title": "Runden lesen",
     "intro": "Zahlen, Zeit und HP: Wer sie im Kopf hat, trifft in jeder Lage die passende Entscheidung, bis zum "
              "Clutch."},
    {"key": "team", "title": "Rollen und Team",
     "intro": "Jeder im Team hat eine Aufgabe. Wer seine Rolle kennt, weiß in jeder Runde, wo er gebraucht wird."},
    {"key": "mind", "title": "Training und Kopf",
     "intro": "So arbeiten Coaches mit ihren Spielern: gezielt üben, Demos richtig ansehen, ruhig bleiben. Das macht "
              "aus Spielzeit echten Fortschritt."},
]

TOPICS: dict[str, dict] = {
    # --- Schießen und Bewegen ----------------------------------------------------------------------------------
    "crosshair_placement": {
        "area": "aim", "title": "Crosshair-Placement",
        "key": "Dein Fadenkreuz wartet auf Kopfhöhe an der Kante, an der als Nächstes ein Gegner auftauchen kann.",
        "teach": [
            "Crosshair-Placement ist der wichtigste Baustein des Aims. Je weniger du nachziehen musst, wenn ein Gegner "
            "auftaucht, desto früher kommt dein Schuss. Gute Spieler wirken schnell, weil sie fast nie weit ziehen.",
            "Kopfhöhe heißt: dort, wo ein stehender Gegner seinen Kopf hat. Auf Treppen, Rampen und Kisten ändert sich "
            "diese Höhe. Dein Fadenkreuz geht mit, bevor du die Stelle erreichst.",
            "Die richtige Kante ist die nächste, hinter der jemand stehen kann, nicht die Mitte des Raums. Beim Laufen "
            "schiebst du das Fadenkreuz an dieser Kante entlang.",
        ],
        "example": [
            "Du läufst als T Richtung Bombspot. Vor dir liegt eine Ecke rechts.",
            "Noch bevor du an der Ecke bist, liegt dein Fadenkreuz auf Kopfhöhe direkt an der Kante.",
            "Du schneidest die Ecke Stück für Stück auf. Das Fadenkreuz bleibt an der Kante, dein Körper bewegt sich.",
            "Taucht ein Gegner auf, ist sein Kopf schon fast unter deinem Fadenkreuz. Ein kleiner Zug, ein Klick.",
        ],
        "mistakes": [
            "Beim Laufen auf den Boden schauen, etwa um den Weg zu sehen.",
            "Das Fadenkreuz in die Mitte des Raums statt an die Kante legen.",
            "Auf Treppen und Rampen die Höhe nicht anpassen.",
        ],
        "drill": {"where": "Prefire-Map deiner Map aus dem Steam-Workshop, danach Deathmatch",
                  "steps": ["Lauf jeden Weg langsam und lass das Fadenkreuz an jeder Ecke auf Kopfhöhe an der Kante.",
                            "Prüfe bei jedem Bot: Wie weit musstest du ziehen? Mehr als ein kleines Stück heißt: Placement korrigieren.",
                            "Im Deathmatch fünf Minuten nur auf eine Sache achten: Das Fadenkreuz sinkt nie zum Boden."],
                  "done": "Du musst bei den meisten Kills nur noch ein kleines Stück ziehen."},
        "cue": "Kopfhöhe, Kante", "ask": "Wo lag dein Fadenkreuz, eine Sekunde bevor der Gegner auftauchte?",
        "quiz": [
            {"id": "cp1", "q": "Wohin gehört dein Fadenkreuz, wenn du auf eine Ecke zuläufst?",
             "options": ["In die Mitte des Raums dahinter", "Auf Kopfhöhe an die Kante der Ecke", "Leicht auf den Boden, damit du den Weg siehst"],
             "a": 1, "why": "An der Kante taucht der Gegner zuerst auf. Liegt das Fadenkreuz dort auf Kopfhöhe, musst du kaum ziehen."},
            {"id": "cp2", "q": "Du läufst eine Rampe hoch. Was passiert mit der Kopfhöhe?",
             "options": ["Sie bleibt gleich", "Du passt das Fadenkreuz an die neue Höhe an, bevor du oben bist", "Kopfhöhe spielt auf Rampen keine Rolle"],
             "a": 1, "why": "Die Höhe des Gegnerkopfes hängt vom Boden ab, auf dem er steht. Gute Spieler passen sie vorher an."},
        ],
        "lessons": ["crosshair", "no_shot_close"], "links": ["duelle"],
    },
    "counter_strafe": {
        "area": "aim", "title": "Counter-Strafe",
        "key": "Bevor du schießt, stehst du: Taste loslassen, Gegenrichtung kurz antippen, dann der Schuss.",
        "teach": [
            "In CS2 streuen Schüsse aus der Bewegung stark. Genau bist du erst, wenn du fast stillstehst. Der schnellste "
            "Weg zum Stillstand ist der Counter-Strafe: Du lässt A los und tippst kurz D, oder umgekehrt.",
            "Seitlich bewegst du dich, weil du dabei schwer zu treffen bist und am schnellsten stoppst. Laufen nach "
            "vorne mit W macht dich langsamer im Stopp und leichter zu treffen.",
            "Nach dem Schuss bewegst du dich wieder. So wechselst du zwischen schwer treffbar und genau.",
        ],
        "example": [
            "Du peekst mit D aus einer Deckung.",
            "Du siehst den Gegner. Im selben Moment lässt du D los und tippst kurz A.",
            "Du stehst und schießt ein bis drei Kugeln auf den Kopf.",
            "Trifft es nicht sofort, gehst du mit A wieder in Deckung, statt laufend weiterzuschießen.",
        ],
        "mistakes": ["Schießen, während eine Bewegungstaste noch gedrückt ist.",
                     "Mit W in den Gegner laufen und dabei sprayen.",
                     "Zu lange gegentippen, sodass du in die andere Richtung losläufst."],
        "drill": {"where": "Workshop-Map Aim Botz, danach Deathmatch",
                  "steps": ["Vor einer Reihe Bots mit A und D hin und her, bei jedem Wechsel ein Schuss auf den Kopf.",
                            "Danach fünf Minuten Deathmatch mit einer Regel: Schuss nur, wenn du stehst."],
                  "done": "Zwanzig Stopps hintereinander, davon mindestens fünfzehn Kopftreffer."},
        "cue": "Stopp, dann Schuss", "ask": "Hast du gestanden, als du geschossen hast?",
        "quiz": [
            {"id": "cs1", "q": "Wie stoppst du am schnellsten, wenn du mit A nach links läufst?",
             "options": ["A loslassen und kurz D antippen", "Ducken und gleichzeitig schießen", "Einfach A loslassen und warten"],
             "a": 0, "why": "Der kurze Tipp in die Gegenrichtung bremst sofort. Nur loslassen dauert länger, Ducken macht dich langsam und vorhersehbar."},
            {"id": "cs2", "q": "Warum bewegt man sich beim Peeken seitlich statt nach vorne?",
             "options": ["Weil man seitlich mehr von der Map sieht", "Weil man seitlich schwerer zu treffen ist und schneller stoppt", "Weil der Rückstoß seitlich kleiner ist"],
             "a": 1, "why": "Seitlich bist du ein schwer treffbares Ziel und kannst mit einem kurzen Gegentipp sofort genau schießen."},
        ],
        "lessons": ["moving_shot", "moving"], "links": ["duelle"],
    },
    "first_bullet": {
        "area": "aim", "title": "Tappen, Bursten, Sprayen",
        "key": "Die Distanz entscheidet: weit tappen, mittel kurze Bursts, nah sprayen.",
        "teach": [
            "Die erste Kugel einer Gewehrsalve ist die genaueste. Jede weitere springt nach oben und zur Seite. Auf "
            "große Distanz zählt deshalb fast nur der erste Schuss, auf kurze Distanz kannst du einen Spray kontrollieren.",
            "Tappen heißt: einzelne Schüsse mit kleinen Pausen, damit die Waffe sich wieder beruhigt. Bursts sind zwei "
            "bis vier Kugeln. Sprayen heißt: Maustaste halten und den Rückstoß mit der Maus gegensteuern.",
            "Mit Gewehren gilt: Je weiter der Gegner, desto weniger Kugeln pro Salve.",
        ],
        "example": [
            "Ein Gegner steht weit weg am Ende einer langen Linie.",
            "Du stoppst, legst das Fadenkreuz auf den Kopf und tappst einen Schuss.",
            "Kein Treffer: kurze Pause, nächster Einzelschuss, statt die Maus festzuhalten.",
            "Kommt derselbe Gegner nah heran, sprayst du und ziehst die Maus nach unten.",
        ],
        "mistakes": ["Auf große Distanz die Maustaste halten.", "Nach einem Burst nicht kurz warten, bevor der nächste kommt.",
                     "Auf kurze Distanz einzeln tappen, obwohl ein Spray schneller tötet."],
        "drill": {"where": "Offline-Server oder Aim Botz",
                  "steps": ["Stell dich weit weg von einer Wand und schieß Einzelschüsse auf einen Punkt.",
                            "Geh näher und schieß Bursts von drei Kugeln, dann noch näher und spray zehn Kugeln.",
                            "Schau dir jedes Mal die Einschüsse an der Wand an."],
                  "done": "Auf großer Distanz liegen deine Einzelschüsse eng beieinander."},
        "cue": "Weit: ein Schuss", "ask": "Wie viele Kugeln hast du auf diese Distanz geschossen, und war das passend?",
        "quiz": [
            {"id": "fb1", "q": "Ein Gegner steht sehr weit weg. Was machst du mit der AK?",
             "options": ["Durchgehend sprayen", "Einzelne Schüsse mit kurzen Pausen", "Im Laufen schießen, damit er dich nicht trifft"],
             "a": 1, "why": "Auf große Distanz ist nur die erste Kugel genau. Mit Pausen beruhigt sich die Waffe wieder."},
            {"id": "fb2", "q": "Welche Kugel einer Gewehrsalve trifft am genauesten?",
             "options": ["Die erste", "Die dritte, wenn die Waffe warm ist", "Alle gleich, wenn man steht"],
             "a": 0, "why": "Ab der zweiten Kugel springt der Rückstoß. Deshalb ist die erste Kugel die wichtigste."},
        ],
        "lessons": ["no_shot_far"], "links": ["duelle"],
    },
    "spray_control": {
        "area": "aim", "title": "Spray-Kontrolle",
        "key": "Beim Spray ziehst du die Maus gegen das Muster: zuerst nach unten, dann seitlich.",
        "teach": [
            "Jedes Gewehr hat ein festes Rückstoßmuster. Die ersten Kugeln steigen nach oben, danach zieht der Spray "
            "zur Seite. Wer das Muster kennt, zieht die Maus genau entgegen und hält die Kugeln auf dem Ziel.",
            "Die AK-47 und die beiden M4 haben unterschiedliche Muster. Lern zuerst die Waffe, die du am meisten spielst.",
            "Ein Spray lohnt sich vor allem auf kurze und mittlere Distanz, und wenn mehrere Gegner nah beieinander sind.",
        ],
        "example": [
            "Zwei Gegner kommen nah um die Ecke.",
            "Du stoppst und beginnst den Spray auf Kopfhöhe des ersten.",
            "Du ziehst die Maus nach unten, damit die Kugeln nicht über ihn steigen.",
            "Nach dem Kill ziehst du den Spray seitlich zum zweiten Gegner weiter.",
        ],
        "mistakes": ["Beim Spray nicht nach unten ziehen, die Kugeln gehen über den Kopf.", "Beim Spray laufen.",
                     "Das Muster der AK auf die M4 übertragen."],
        "drill": {"where": "Offline-Server, an einer Wand",
                  "steps": ["Spray ein ganzes Magazin auf einen Punkt an der Wand, ohne zu ziehen, und schau dir das Muster an.",
                            "Spray dann noch einmal und zieh dagegen. Ziel: die Einschüsse bleiben auf einem kleinen Fleck.",
                            "Danach im Deathmatch die ersten zehn Kugeln bewusst gegensteuern."],
                  "done": "Die ersten zehn Kugeln landen auf mittlere Distanz auf einem kleinen Fleck."},
        "cue": "Runter ziehen", "ask": "Hast du beim Spray gegengesteuert oder sind die Kugeln gestiegen?",
        "quiz": [
            {"id": "sp1", "q": "In welche Richtung ziehst du die Maus am Anfang eines Gewehrsprays?",
             "options": ["Nach oben", "Nach unten", "Zur Seite, gegen den Gegner"], "a": 1,
             "why": "Die ersten Kugeln steigen nach oben. Du ziehst nach unten, damit sie auf dem Ziel bleiben."},
        ],
        "lessons": ["moving_shot"], "links": ["duelle"],
    },
    "movement_sound": {
        "area": "aim", "title": "Bewegung und Geräusche",
        "key": "Rennen ist laut, Shift ist leise. Du entscheidest, wann der Gegner dich hören darf.",
        "teach": [
            "Wer rennt, macht Schritte, die der Gegner hört. Mit gehaltener Shift-Taste gehst du langsamer, aber leise. "
            "Auch Landen nach einem Sprung, Waffenwechsel, Nachladen und manche Böden machen Geräusche.",
            "Am Rundenanfang, weit weg vom Gegner, rennst du. Nah an der Stelle, an der du überraschen willst, gehst du "
            "leise. Wer die ganze Runde shiftet, ist zu langsam. Wer die ganze Runde rennt, verrät jeden Schritt.",
            "Geräusche kannst du auch absichtlich machen: Ein paar laute Schritte an einer Stelle können einen Gegner "
            "dorthin ziehen, während dein Team woanders hingeht.",
        ],
        "example": [
            "Du willst als CT einen Gegner überraschen, der bei dir in der Nähe lauert.",
            "Bis zur letzten Ecke rennst du, denn dort hört er dich noch nicht.",
            "Ab dort hältst du Shift und gehst leise in deine Position.",
            "Er weiß nicht, dass du da bist, und läuft in dein Fadenkreuz.",
        ],
        "mistakes": ["Nah am Gegner rennen oder springen.", "Nachladen, wenn der Gegner es hören kann und du kein Team in der Nähe hast.",
                     "Die ganze Runde shiften und dadurch zu spät kommen."],
        "drill": {"where": "Offline-Server mit einem Mitspieler",
                  "steps": ["Dein Mitspieler steht still, du läufst einmal rennend und einmal mit Shift auf ihn zu.",
                            "Er sagt, ab wann er dich hört. Dann tauscht ihr.",
                            "Merkt euch für eure Standard-Positionen, ab wo man shiften sollte."],
                  "done": "Ihr wisst für eure Positionen, ab welcher Stelle ihr leise sein müsst."},
        "cue": "Nah heißt leise", "ask": "Wusste der Gegner, wo du bist, weil er dich gehört hat?",
        "quiz": [
            {"id": "mv1", "q": "Wann gehst du mit Shift?",
             "options": ["Die ganze Runde", "Nah an der Stelle, an der du überraschen willst", "Nur als CT, als T zählt Tempo"],
             "a": 1, "why": "Weit weg vom Gegner zählt Tempo. Nah dran zählt, dass er dich nicht hört."},
            {"id": "mv2", "q": "Was verrät dich außer Schritten noch?",
             "options": ["Nur Schüsse und Granaten", "Landen nach Sprüngen und Nachladen", "Waffenwechsel, aber nur beim Messer"],
             "a": 1, "why": "Auch Landen und Nachladen sind hörbar. Wer nah am Gegner springt oder nachlädt, verrät sich."},
        ],
        "lessons": ["seen_first"], "links": [],
    },
    "weapons": {
        "area": "aim", "title": "Waffen und Distanz",
        "key": "Jede Waffe hat ihre Distanz. Du suchst Duelle dort, wo deine Waffe stark ist.",
        "teach": [
            "Gewehre wie AK-47, M4A4 und M4A1-S sind auf allen Distanzen stark. Die AWP tötet mit einem Treffer in den "
            "Körper, ist aber langsam und im Laufen ungenau. MPs und Schrotflinten sind nah stark und weit schwach.",
            "Mit einer schwächeren Waffe suchst du die Distanz, auf der sie gegen ein Gewehr eine Chance hat. Mit einer "
            "MP heißt das: nah, aus einer Ecke, am besten mit Flash. Mit einer Pistole: Kopfschüsse nah oder mittel.",
            "Kill-Prämien unterscheiden sich: Gewehre und Pistolen bringen 300 $, die meisten MPs 600 $ (P90: 300 $), "
            "Schrotflinten 900 $ (XM1014: 600 $), die AWP nur 100 $ und das Messer 1500 $.",
        ],
        "example": [
            "Du hast in einer Force-Runde nur eine MP gekauft.",
            "Statt auf einer langen Linie gegen ein Gewehr zu halten, stellst du dich hinter eine enge Ecke.",
            "Der Gegner muss nah an dir vorbei. Dort ist deine MP so stark wie sein Gewehr.",
        ],
        "mistakes": ["Mit MP oder Pistole lange Linien halten.", "Mit der AWP ohne Deckung im Offenen stehen.",
                     "Eine Schrotflinte auf mittlere Distanz einsetzen."],
        "drill": {"where": "Deathmatch",
                  "steps": ["Spiel eine Runde Deathmatch nur mit einer MP und such bewusst kurze Distanzen.",
                            "Spiel eine Runde nur mit der Desert Eagle oder einer anderen Pistole und zieh auf Kopfhöhe vor."],
                  "done": "Du merkst, welche Distanz zu welcher Waffe gehört, ohne nachzudenken."},
        "cue": "Meine Distanz", "ask": "Hast du das Duell auf der Distanz gesucht, auf der deine Waffe stark ist?",
        "quiz": [
            {"id": "wp1", "q": "Du hast eine MP, der Gegner ein Gewehr. Wo suchst du das Duell?",
             "options": ["Auf einer langen offenen Linie", "Nah an einer engen Ecke", "Auf mittlere Distanz mit Einzelschüssen"],
             "a": 1, "why": "MPs sind nah stark und weit schwach. Nah gleicht sich der Nachteil gegen ein Gewehr aus."},
            {"id": "wp2", "q": "Wie viel bringt ein Kill mit der AWP?",
             "options": ["100 $", "300 $", "600 $"], "a": 0,
             "why": "Die AWP bringt nur 100 $ pro Kill. Mit MPs sind es meist 600 $, mit Gewehren 300 $."},
        ],
        "lessons": ["no_shot_far"], "links": ["stats"],
    },
    # --- Duelle und Peeks -------------------------------------------------------------------------------------
    "peek_types": {
        "area": "duel", "title": "Arten zu peeken",
        "key": "Weiter Peek für das Duell, Jiggle für Info, Schulter-Peek gegen die AWP.",
        "teach": [
            "Ein weiter Peek heißt: schnell und weit aus der Deckung, sodass du mehr siehst als der Gegner, der auf die "
            "Kante zielt. Er ist gut, wenn du das Duell willst und weißt, ungefähr wo der Gegner steht.",
            "Ein Jiggle-Peek ist kurz raus und sofort zurück. Du willst nur sehen, wer da ist, ohne ein Duell zu "
            "riskieren. Ein Schulter-Peek zeigt nur einen kleinen Teil deines Körpers, damit eine AWP schießt und "
            "danach nachladen muss.",
            "Wichtig ist, dass du vor dem Peek weißt, was du willst: ein Duell, eine Info oder einen Schuss der AWP "
            "ziehen. Ein halber Peek, der nichts davon ist, kostet nur HP.",
        ],
        "example": [
            "Du vermutest eine AWP auf einer langen Linie.",
            "Du zeigst kurz die Schulter und gehst sofort zurück.",
            "Die AWP schießt daneben. Jetzt hast du kurz Zeit, weil sie nachladen muss.",
            "Du oder dein Mitspieler peekt jetzt weit und nimmt das Duell.",
        ],
        "mistakes": ["Langsam in einen Winkel schieben, in dem eine AWP wartet.", "Jigglen und dabei stehen bleiben, weil man doch schießen will.",
                     "Weit peeken, ohne zu wissen, wo man hinschauen muss."],
        "drill": {"where": "Offline-Server mit Bots, die Winkel halten, oder mit einem Mitspieler",
                  "steps": ["Peek denselben Winkel zehnmal weit, zehnmal als Jiggle und zehnmal als Schulter-Peek.",
                            "Achte beim Jiggle darauf, dass du sofort wieder hinter der Deckung bist."],
                  "done": "Du kannst vor jedem Peek sagen, welche Art du nimmst und warum."},
        "cue": "Was will ich?", "ask": "Wolltest du bei diesem Peek ein Duell, eine Info oder einen AWP-Schuss?",
        "quiz": [
            {"id": "pk1", "q": "Du willst nur wissen, ob jemand auf einer Position steht. Welcher Peek?",
             "options": ["Weiter Peek", "Jiggle-Peek", "Langsam reinschieben"], "a": 1,
             "why": "Beim Jiggle bist du nur kurz sichtbar. Du bekommst die Info, ohne dich auf ein Duell einzulassen."},
            {"id": "pk2", "q": "Wofür ist ein Schulter-Peek gegen eine AWP gut?",
             "options": ["Um die AWP zu einem Schuss zu bringen, nach dem sie nachladen muss", "Um ihre genaue Position für eine Wallbang zu sehen", "Um Zeit zu gewinnen, bis sie die Position wechselt"],
             "a": 0, "why": "Schießt die AWP auf deine Schulter, muss sie nachladen. In diesem Moment kann dein Team peeken."},
        ],
        "lessons": ["no_shot_close", "moving", "seen_first"], "links": ["duelle"],
    },
    "peekers_advantage": {
        "area": "duel", "title": "Peeker's Advantage und Halten",
        "key": "Wer schnell peekt, sieht kurz früher. Wer hält, gleicht das mit Abstand und Off-Angle aus.",
        "teach": [
            "Durch die Verzögerung im Netz sieht der Peekende den Haltenden einen kleinen Augenblick früher, als der "
            "Haltende ihn sieht. Das nennt man Peeker's Advantage. Er wird größer, je schneller der Peek ist.",
            "Als Haltender gleichst du das aus, wenn du nicht direkt an der Kante stehst. Mit Abstand zur Kante bewegt "
            "sich der Gegner langsamer über deinen Bildschirm, und du siehst ihn früher. Ein Off-Angle ist eine "
            "Stelle, an der der Gegner dich nicht erwartet.",
            "Wer hält, muss nicht ewig halten: Nach einer Info darfst du zurückgehen und neu einen Winkel nehmen. "
            "Ein Gegner, der weiß, wo du bist, hat den Vorteil.",
        ],
        "example": [
            "Du hältst als CT einen Durchgang.",
            "Statt direkt an der Kante stehst du einige Schritte zurück und leicht seitlich.",
            "Der T peekt weit, erwartet dich aber an der Kante. Er muss erst suchen.",
            "Du siehst ihn früher und hast den ersten Schuss.",
        ],
        "mistakes": ["Direkt an der Kante kleben, an der jeder dich erwartet.", "Nach einem Kill auf derselben Stelle bleiben.",
                     "Langsam peeken gegen einen Gegner, der hält."],
        "drill": {"where": "Offline-Server, deine Standard-Positionen",
                  "steps": ["Stell dich für jede Position einmal an die Kante und einmal mit Abstand.",
                            "Lauf zur Seite des Gegners und schau zurück: Von wo sieht man dich zuerst?"],
                  "done": "Für jede Standard-Position kennst du eine Stelle mit Abstand oder Off-Angle."},
        "cue": "Abstand zur Kante", "ask": "Stand der Gegner an einer Stelle, an der du ihn erwartet hast? Und du?",
        "quiz": [
            {"id": "pa1", "q": "Wie gleichst du als Haltender den Peeker's Advantage aus?",
             "options": ["Direkt an die Kante stellen", "Mit Abstand zur Kante oder einem Off-Angle", "Durch Ducken im Moment des Peeks"],
             "a": 1, "why": "Mit Abstand bewegt sich der Gegner langsamer über deinen Bildschirm. Ein Off-Angle zwingt ihn zu suchen."},
        ],
        "lessons": ["seen_first", "angle"], "links": ["duelle", "mapbook"],
    },
    "isolation": {
        "area": "duel", "title": "Duelle isolieren",
        "key": "Du willst immer nur ein Duell auf einmal. Zwei Gegner gleichzeitig verliert fast jeder.",
        "teach": [
            "Steht man an einer Stelle, von der aus mehrere Gegner gleichzeitig schießen können, entscheidet nicht mehr "
            "das Aim. Gute Spieler nehmen Winkel einzeln: erst den einen, dann den nächsten.",
            "Das gilt beim Clearen genauso wie beim Halten. Als Haltender suchst du eine Stelle, an der nur einer "
            "gleichzeitig auftauchen kann. Als Peekender schneidest du die Ecke so auf, dass du nur einen Winkel siehst.",
            "Granaten helfen dabei: Eine Smoke auf den zweiten Winkel macht aus zwei Duellen eines.",
        ],
        "example": [
            "Du kommst als T auf einen Bombspot, auf dem zwei typische CT-Positionen sind.",
            "Eine Smoke deines Teams nimmt eine davon aus dem Spiel.",
            "Du clearst die zweite allein mit voller Konzentration und gewinnst das Duell.",
        ],
        "mistakes": ["Mitten auf den Spot laufen, wo alle Winkel gleichzeitig auf dich zeigen.", "Zwei Winkel gleichzeitig prüfen wollen."],
        "drill": {"where": "Prefire-Map deiner Map",
                  "steps": ["Clear jeden Spot so, dass du immer nur einen Bot gleichzeitig siehst.",
                            "Wenn zwei gleichzeitig auf dich schießen können: Weg ändern."],
                  "done": "Du clearst einen ganzen Bombspot, ohne je zwei Bots gleichzeitig zu sehen."},
        "cue": "Einer nach dem anderen", "ask": "Konnten dich in diesem Moment mehrere Gegner gleichzeitig sehen?",
        "quiz": [
            {"id": "is1", "q": "Zwei Winkel zeigen auf dich, du hast eine Smoke. Was machst du?",
             "options": ["Die Smoke auf einen der Winkel, dann den anderen clearen", "Die Smoke behalten und beide gleichzeitig prüfen", "Die Smoke zwischen beide Winkel und durch die Mitte laufen"],
             "a": 0, "why": "So wird aus zwei Duellen eines. Ein Duell kannst du gewinnen, zwei gleichzeitig fast nie."},
        ],
        "lessons": ["angle"], "links": ["mapbook"],
    },
    "trading": {
        "area": "duel", "title": "Trades und Abstand",
        "key": "Steht dein Mitspieler so nah, dass er dich sofort rächen kann, kostet dein Tod den Gegner auch einen Spieler.",
        "teach": [
            "Ein Trade ist ein Kill, der kurz nach dem Tod eines Mitspielers den Gegner tötet, der ihn erwischt hat. Ein "
            "Tod mit Trade ist fast ein Tausch, ein Tod ohne Trade ist ein reiner Verlust.",
            "Damit ein Trade möglich ist, braucht es den richtigen Abstand: nah genug, um sofort nachzuziehen, aber nicht "
            "so nah, dass eine Granate oder ein Spray beide trifft. Der Zweite sieht den Gegner, sobald dieser schießt.",
            "Zum Trade gehört auch der Call: Wer stirbt, sagt sofort, wo der Gegner steht. Wer tradet, peekt genau "
            "dorthin.",
        ],
        "example": [
            "Du und dein Bruder geht als T durch einen Durchgang.",
            "Er peekt zuerst. Du stehst zwei Schritte hinter ihm, Fadenkreuz auf der Stelle, an der er schießt.",
            "Er stirbt. Der Gegner hat gerade geschossen und muss nachziehen.",
            "Du peekst sofort und tradest. Die Runde bleibt ausgeglichen.",
        ],
        "mistakes": ["Zu weit hinten stehen, sodass der Trade zu spät kommt.", "Direkt hinter dem Mitspieler stehen, sodass beide im Spray sterben.",
                     "Nach dem Tod des Mitspielers warten, statt sofort zu traden."],
        "drill": {"where": "Retake-Server oder Deathmatch zu zweit",
                  "steps": ["Einer peekt, der andere zieht sofort nach.",
                            "Nach jeder Runde: War der Abstand richtig? Kam der Trade in einer Sekunde?"],
                  "done": "Ihr tradet in den meisten Fällen innerhalb von etwa einer Sekunde."},
        "cue": "Nah genug zum Traden", "ask": "Hätte dich jemand traden können? Wenn nicht, warum nicht?",
        "quiz": [
            {"id": "tr1", "q": "Was ist der richtige Abstand zum Mitspieler, der vor dir peekt?",
             "options": ["So weit wie möglich, um sicher zu sein", "Nah genug, um sofort nachzuziehen, aber nicht direkt hinter ihm", "Direkt hinter ihm"],
             "a": 1, "why": "Du musst sofort nachziehen können. Zu nah trifft euch beide derselbe Spray oder dieselbe Molotov."},
            {"id": "tr2", "q": "Dein Mitspieler stirbt. Was sagt er sofort?",
             "options": ["Wo der Gegner steht und wie viel HP er hat", "Welche Waffe er selbst verloren hat", "Nichts, bis die Runde vorbei ist, um nicht zu stören"],
             "a": 0, "why": "Mit der Position kann der Nächste den Trade genau dorthin peeken."},
        ],
        "lessons": ["alone"], "links": ["duelle", "stats"],
    },
    # --- Information und Kommunikation ------------------------------------------------------------------------
    "sound_info": {
        "area": "info", "title": "Sound lesen",
        "key": "Jedes Geräusch ist eine Info: wie viele, wo, wohin und mit welcher Ausrüstung.",
        "teach": [
            "Schritte verraten, wie viele Gegner wo sind und in welche Richtung sie laufen. Granaten-Geräusche zeigen, "
            "wo ein Angriff vorbereitet wird. Eine fallende Waffe, Nachladen oder ein Kit-Geräusch beim Entschärfen "
            "sind ebenfalls Infos.",
            "Gutes Hören braucht Ruhe: Im Voice-Chat spricht niemand, während ein wichtiges Geräusch zu hören ist. Ein "
            "Kopfhörer mit klarer Stereo-Ortung hilft.",
            "Auch Stille ist eine Info. Hörst du an einem Spot lange nichts, ist dort wahrscheinlich wenig los, oder es "
            "wartet jemand leise.",
        ],
        "example": [
            "Du hältst als CT einen Bombspot. Du hörst mehrere Schritte, die schnell lauter werden, und eine Flash.",
            "Du callst sofort: Mehrere kommen, Flash.",
            "Du drehst weg, wenn die Flash kommt, und fällst etwas zurück, bis Hilfe da ist.",
        ],
        "mistakes": ["Sprechen, während der Gegner zu hören ist.", "Geräusche hören, aber nicht callen.",
                     "Nur auf Schritte achten und Granaten-Geräusche übergehen."],
        "drill": {"where": "Eigene Demo",
                  "steps": ["Spiel eine Runde deiner Demo ab und hör nur zu, ohne auf das Bild zu achten.",
                            "Sag nach jedem Geräusch, was es bedeutet. Prüf dann im Bild, ob du recht hattest."],
                  "done": "Du kannst bei den meisten Geräuschen sagen, wie viele Gegner wohin laufen."},
        "cue": "Hören, callen", "ask": "Welches Geräusch hättest du in dieser Runde hören können?",
        "quiz": [
            {"id": "so1", "q": "Was ist im Voice-Chat wichtig, wenn ein Gegner zu hören ist?",
             "options": ["Ruhig sein, damit alle hören können", "Laut rufen, wo er ist, auch wenn er noch spricht", "Sofort die nächste Taktik besprechen"],
             "a": 0, "why": "Ein wichtiges Geräusch überhört man, wenn jemand spricht. Erst hören, dann kurz callen."},
            {"id": "so2", "q": "Du hörst an einem Bombspot lange nichts. Was ist das?",
             "options": ["Keine Info", "Eine Info: dort ist wahrscheinlich wenig los oder jemand wartet leise", "Ein sicheres Zeichen, dass alle fünf auf dem anderen Spot sind"],
             "a": 1, "why": "Auch Stille sagt etwas. Gute Spieler nutzen sie für Rotationen und Entscheidungen."},
        ],
        "lessons": ["seen_first", "blind"], "links": [],
    },
    "callouts": {
        "area": "info", "title": "Calls, die helfen",
        "key": "Ein guter Call ist kurz: wie viele, wo, wie viel HP, welche Waffe. Danach Ruhe.",
        "teach": [
            "Ein Call soll in einer Sekunde verstanden werden. Die Reihenfolge, die viele Teams nutzen: Anzahl, Ort, "
            "Zustand. Zum Beispiel: Zwei auf B Apps, einer angeschlagen, AWP dabei.",
            "Tote Spieler sprechen nur noch, wenn sie eine wirklich neue Info haben, und halten sich sonst raus. Wer "
            "lebt und im Duell steckt, braucht Ruhe.",
            "Nutze die Namen der Orte, die dein Team kennt. Die Callouts der Map lernst du im Map-Buch und in der "
            "2D-Wiederholung der App.",
        ],
        "example": [
            "Du stirbst auf A gegen einen Gegner.",
            "Du sagst: Einer auf Site, Ecke links, 30 HP.",
            "Dann bist du still. Dein Mitspieler peekt genau dorthin und gewinnt das Duell.",
        ],
        "mistakes": ["Lange erzählen, wie man gestorben ist.", "Ungenaue Calls wie da drüben.",
                     "Als toter Spieler in ein Clutch reinreden."],
        "drill": {"where": "Nächstes Match zu zweit",
                  "steps": ["Macht vorher ab: Jeder Call hat Anzahl, Ort und Zustand.",
                            "Nach dem Match: An welchen Call erinnert ihr euch, der zu lang oder zu ungenau war?"],
                  "done": "Eure Calls sind kurz und haben immer Anzahl und Ort."},
        "cue": "Anzahl, Ort, HP", "ask": "Wusste dein Team nach deinem Tod genau, wo der Gegner stand?",
        "quiz": [
            {"id": "ca1", "q": "Welcher Call ist am besten?",
             "options": ["Einer irgendwo auf A, glaube ich", "Einer auf Site, Ecke links, 30 HP", "Zwei oder drei kommen vielleicht gleich über Mitte oder A"],
             "a": 1, "why": "Anzahl, Ort und Zustand in einem Satz. Damit kann dein Mitspieler sofort handeln."},
            {"id": "ca2", "q": "Dein Mitspieler ist im 1-gegen-1. Was machst du als toter Spieler?",
             "options": ["Viele Tipps geben", "Still sein, außer du hast eine wirklich neue Info", "Jede Sekunde die Restzeit ansagen"],
             "a": 1, "why": "Im Clutch braucht der Spieler Ruhe, um zu hören und zu denken."},
        ],
        "lessons": ["alone"], "links": ["mapbook"],
    },
    "radar": {
        "area": "info", "title": "Radar und Übersicht",
        "key": "Ein Blick aufs Radar zeigt dir, wo dein Team steht und welche Seite der Map offen ist.",
        "teach": [
            "Auf dem Radar siehst du die Positionen deiner Mitspieler und gemeldete Gegner. Wer regelmäßig hinschaut, "
            "weiß, ob er allein ist, wo ein Trade möglich ist und welche Wege niemand abdeckt.",
            "Gute Momente für einen Blick: in der Kaufzeit, nach jedem Kill und bevor du einen Winkel peekst.",
            "Ein Radar, das die ganze Map zeigt und nicht mitdreht, ist für viele leichter zu lesen. Probier aus, was "
            "dir hilft.",
        ],
        "example": [
            "Du willst einen Durchgang peeken.",
            "Ein kurzer Blick aufs Radar: Dein Mitspieler ist weit weg auf der anderen Seite.",
            "Ohne Trade-Partner wartest du oder spielst auf Zeit, statt allein zu peeken.",
        ],
        "mistakes": ["Die ganze Runde nicht aufs Radar schauen.", "Allein peeken, obwohl das Radar zeigt, dass niemand in der Nähe ist."],
        "drill": {"where": "Deathmatch oder Retake",
                  "steps": ["Schau nach jedem Kill einmal kurz aufs Radar.", "Sag dir dabei, wo dein nächster Mitspieler steht."],
                  "done": "Der Blick aufs Radar nach dem Kill passiert von selbst."},
        "cue": "Blick aufs Radar", "ask": "Wusstest du in dem Moment, wo dein nächster Mitspieler war?",
        "quiz": [
            {"id": "ra1", "q": "Wann ist ein guter Moment für einen Blick aufs Radar?",
             "options": ["Während du einen Winkel hältst", "Nach einem Kill und bevor du peekst", "Nur in der Kaufzeit"],
             "a": 1, "why": "Nach einem Kill hast du kurz Ruhe. Vor dem Peek klärst du, ob ein Mitspieler traden kann."},
        ],
        "lessons": ["alone", "outnumbered"], "links": [],
    },
    # --- Economy ---------------------------------------------------------------------------------------------
    "buy_types": {
        "area": "eco", "title": "Rundentypen: Full Buy, Eco, Force",
        "key": "Das Team kauft zusammen: alle voll, alle sparen oder alle forcen. Halbe Käufe verlieren meist doppelt.",
        "teach": [
            "Full Buy heißt Gewehr, Rüstung mit Helm und Granaten. Eco heißt sparen: höchstens eine Pistole, damit die "
            "nächste Runde ein Full Buy wird. Force Buy heißt: alles ausgeben, obwohl es nicht für einen vollen Kauf "
            "reicht, weil diese Runde besonders wichtig ist.",
            "Entscheidend ist, dass alle dasselbe machen. Wenn zwei voll kaufen und drei sparen, verlieren die zwei "
            "Gewehre meist gegen fünf Gegner und das Geld ist weg.",
            "Ein Force lohnt sich vor allem, wenn der Gegner selbst schwach ausgerüstet ist, wenn es um die letzte "
            "Runde einer Hälfte oder des Matches geht, oder wenn Sparen nichts mehr bringt.",
        ],
        "example": [
            "Ihr habt die Pistolenrunde und die Runde danach verloren. Das Team hat wenig Geld.",
            "Ihr sprecht ab: Diese Runde sparen alle.",
            "In der nächsten Runde reicht das Geld bei allen für Gewehre, Rüstung und Granaten.",
        ],
        "mistakes": ["Allein voll kaufen, während das Team spart.", "Auf einer Eco trotzdem MPs kaufen, sodass es nächste Runde nicht reicht.",
                     "Ohne Absprache forcen."],
        "drill": {"where": "Kaufzeit in deinen nächsten Matches",
                  "steps": ["Schau in jeder Kaufzeit zuerst auf das Geld deines Teams, dann erst ins Kaufmenü.",
                            "Frag oder sag im Team: Full, Eco oder Force?"],
                  "done": "Ihr kauft in fast jeder Runde alle denselben Rundentyp."},
        "cue": "Alle gleich", "ask": "Habt ihr in dieser Runde alle denselben Rundentyp gekauft?",
        "quiz": [
            {"id": "bt1", "q": "Zwei im Team haben Geld für Gewehre, drei nicht. Was ist meist richtig?",
             "options": ["Die zwei kaufen voll, die drei sparen", "Alle sparen und kaufen nächste Runde zusammen", "Die drei kaufen Pistolen und Rüstung dazu"],
             "a": 1, "why": "Zwei Gewehre gegen fünf Gegner verlieren meist. Zusammen sparen heißt zusammen voll kaufen."},
            {"id": "bt2", "q": "Wann lohnt sich ein Force Buy besonders?",
             "options": ["In der letzten Runde einer Hälfte", "Direkt nach jeder verlorenen Runde", "Wenn der Gegner gerade voll gekauft hat"],
             "a": 0, "why": "Danach wird das Geld ohnehin zurückgesetzt, Sparen bringt dann nichts mehr."},
        ],
        "lessons": [], "links": ["stats"],
    },
    "loss_bonus": {
        "area": "eco", "title": "Loss-Bonus und Teamgeld",
        "key": "Jede verlorene Runde in Folge bringt mehr Geld: 1400, 1900, 2400, 2900, dann 3400 $.",
        "teach": [
            "Wer verliert, bekommt einen Loss-Bonus. Er steigt mit jeder weiteren Niederlage in Folge: 1400 $, 1900 $, "
            "2400 $, 2900 $ und höchstens 3400 $. Die verlorene Pistolenrunde bringt schon 1900 $.",
            "Ein Rundensieg bringt 3250 $. Wird die Bombe gezündet oder entschärft, bekommt das siegreiche Team 3500 $. "
            "Wie hoch dein Loss-Bonus gerade ist, zeigt das Spiel im Scoreboard.",
            "Daraus folgt: Nach mehreren Niederlagen ist Sparen weniger schmerzhaft, weil das Geld schneller wieder da ist. "
            "Und wer gegen einen Gegner mit hohem Loss-Bonus spielt, muss damit rechnen, dass er bald wieder voll kauft.",
        ],
        "example": [
            "Ihr habt drei Runden in Folge verloren. Der nächste Verlust brächte 2900 $.",
            "Ihr könnt jetzt einmal sparen und in der Runde danach mit dem Bonus voll kaufen.",
            "Gewinnt ihr die Spar-Runde doch, umso besser: Ihr bekommt das Geld für den Sieg und habt kaum etwas ausgegeben.",
        ],
        "mistakes": ["Den Loss-Bonus nicht einrechnen und unnötig forcen.", "Glauben, dass der Gegner nach einem Sieg pleite ist, obwohl er Bonus hat."],
        "drill": {"where": "Kaufzeit",
                  "steps": ["Schau in jeder Kaufzeit, welcher Loss-Bonus bei dir und beim Gegner gerade gilt.",
                            "Rechne kurz: Reicht es nächste Runde für einen Full Buy, wenn wir diese verlieren?"],
                  "done": "Du kannst vor jeder Runde sagen, wie viel Geld du nach einer Niederlage hättest."},
        "cue": "Was nach dem Verlust?", "ask": "Hättet ihr mit Sparen in dieser Runde nächste Runde voll kaufen können?",
        "quiz": [
            {"id": "lb1", "q": "Wie viel bringt die erste Niederlage nach einem Sieg normalerweise?",
             "options": ["1400 $", "3250 $", "1900 $"], "a": 0,
             "why": "Die Reihe beginnt bei 1400 $ und steigt bis 3400 $. Die verlorene Pistolenrunde ist eine Ausnahme mit 1900 $."},
            {"id": "lb2", "q": "Wie viel bekommt das Team für einen Rundensieg durch Ausschalten aller Gegner?",
             "options": ["1400 $", "3250 $", "5000 $"], "a": 1,
             "why": "Ein Rundensieg bringt 3250 $. Mit gezündeter oder entschärfter Bombe sind es 3500 $."},
            {"id": "lb3", "q": "Was ist der höchste Loss-Bonus?",
             "options": ["2400 $", "3400 $", "4000 $"], "a": 1,
             "why": "Nach fünf Niederlagen in Folge ist mit 3400 $ das Maximum erreicht."},
        ],
        "lessons": [], "links": ["stats"],
    },
    "saving": {
        "area": "eco", "title": "Saven und droppen",
        "key": "Eine verlorene Runde mit gerettetem Gewehr kostet weniger als ein sinnloser Tod. Wer Geld hat, droppt.",
        "teach": [
            "Saven heißt: Die Runde ist kaum noch zu gewinnen, also versteckst du dich und behältst deine Waffe für die "
            "nächste Runde. Das spart viel Geld und kann die nächste Runde retten.",
            "Ob du savest, hängt von Zahlen, Zeit und Geld ab. Allein gegen drei mit wenig Zeit ist Saven meist richtig. "
            "Als T ohne Plant gibt es außerdem keinen Bonus für den Plant.",
            "Droppen heißt: Wer viel Geld hat, kauft einem Mitspieler eine Waffe. So kauft das ganze Team voll, statt "
            "dass einer zwei Gewehre bezahlen könnte und ein anderer gar keins.",
        ],
        "example": [
            "Du bist als CT allein gegen drei, die Bombe liegt, und du hast kein Kit.",
            "Ein Retake ist fast unmöglich. Du versteckst dich und behältst dein Gewehr.",
            "Nächste Runde hast du dein Gewehr und kannst Geld für Granaten ausgeben.",
        ],
        "mistakes": ["Hoffnungslos allein in drei Gegner laufen und die Waffe verlieren.", "Das Geld behalten, während ein Mitspieler nur eine Pistole hat."],
        "drill": {"where": "Nächstes Match",
                  "steps": ["Bei jeder Unterzahl-Lage kurz fragen: Ist die Runde noch zu gewinnen? Wenn nicht: saven.",
                            "In jeder Kaufzeit schauen, ob ein Mitspieler zu wenig Geld hat, und droppen."],
                  "done": "Du savest in klar verlorenen Lagen und droppst, wenn du kannst."},
        "cue": "Waffe retten?", "ask": "War die Runde noch zu gewinnen, oder hättest du saven sollen?",
        "quiz": [
            {"id": "sv1", "q": "Du bist allein gegen drei, die Bombe liegt, du hast kein Kit. Was ist meist richtig?",
             "options": ["Saven und die Waffe behalten", "Alleine zur Bombe laufen", "Durch eine Smoke zur Bombe und sofort entschärfen"],
             "a": 0, "why": "Ohne Kit dauert das Entschärfen 10 s. Gegen drei Gegner ist das fast nie zu schaffen."},
        ],
        "lessons": ["outnumbered"], "links": ["stats"],
    },
    "equipment": {
        "area": "eco", "title": "Rüstung, Helm und Kit",
        "key": "Rüstung zuerst, Helm gegen Gewehre, Kit für jeden CT, der zur Bombe muss.",
        "teach": [
            "Rüstung senkt den Schaden an Körper und Kopf. Ohne Helm sterben Spieler gegen viele Waffen an einem "
            "Kopfschuss, gegen den sie mit Helm noch leben würden. Gegen Gewehre lohnt sich der Helm fast immer.",
            "Das Entschärfen dauert ohne Kit 10 Sekunden und mit Kit 5. Das Kit kostet 400 $. Mindestens zwei CTs sollten "
            "eins haben, damit ein Retake nicht an der Zeit scheitert.",
            "Auf einer Pistolenrunde musst du abwägen: Rüstung oder Granaten und eine bessere Pistole. Beides hat Vor- "
            "und Nachteile, wichtig ist, dass das Team einen Plan hat.",
        ],
        "example": [
            "Du hast als CT nach dem Gewehr und der Rüstung noch etwas Geld.",
            "Du kaufst ein Kit, weil auf deinem Spot oft retaket werden muss.",
            "Beim Retake reichen dir dadurch 5 Sekunden statt 10 zum Entschärfen.",
        ],
        "mistakes": ["Ohne Rüstung in eine Gewehrrunde gehen.", "Als ganzes CT-Team ohne Kit spielen."],
        "drill": {"where": "Kaufzeit",
                  "steps": ["Prüfe als CT in jeder Gewehrrunde: Wer im Team hat ein Kit?", "Kauf eins, wenn weniger als zwei eins haben."],
                  "done": "In jeder CT-Gewehrrunde haben mindestens zwei ein Kit."},
        "cue": "Kit dabei?", "ask": "Hättest du die Bombe mit Kit noch rechtzeitig entschärft?",
        "quiz": [
            {"id": "eq1", "q": "Wie lange dauert das Entschärfen mit Kit?",
             "options": ["3 Sekunden", "5 Sekunden", "10 Sekunden"], "a": 1,
             "why": "Ohne Kit 10 Sekunden, mit Kit 5. Das Kit kostet 400 $."},
            {"id": "eq2", "q": "Wie lange läuft die Bombe nach dem Plant?",
             "options": ["30 Sekunden", "40 Sekunden", "60 Sekunden"], "a": 1,
             "why": "Die Bombe zündet nach 40 Sekunden. Ohne Kit braucht ein CT 10 davon zum Entschärfen."},
        ],
        "lessons": [], "links": [],
    },
    # --- Granaten -------------------------------------------------------------------------------------------
    "smokes": {
        "area": "nades", "title": "Smokes: Linien schneiden",
        "key": "Eine Smoke nimmt dem Gegner eine Sichtlinie weg. Du wirfst sie dort, wo er dich sonst sehen würde.",
        "teach": [
            "Smokes haben drei Aufgaben. Als T schneiden sie Positionen vom Bombspot ab, damit ihr weniger Winkel "
            "gleichzeitig habt. Als CT verzögern sie einen Angriff. Beim Retake oder Post-Plant trennen sie Gegner voneinander.",
            "Eine gute Smoke sitzt immer gleich. Deshalb lernen Teams feste Lineups: eine Stelle, ein Zielpunkt, eine Art zu "
            "werfen. Im Reiter Lineups der App siehst du, welche Smokes die Pros auf deiner Map werfen.",
            "Achtung bei Smokes, durch die man nur von einer Seite sieht. Wer am Rand einer Smoke steht, ist für den "
            "Gegner oft sichtbar, ohne es zu merken.",
        ],
        "example": [
            "Ihr wollt als T auf einen Bombspot, den ein CT aus einer Position mit langer Sicht hält.",
            "Einer wirft die Smoke auf genau diese Position.",
            "Ihr geht auf den Spot und habt einen Winkel weniger gegen euch.",
        ],
        "mistakes": ["Die Smoke so werfen, dass sie halb sitzt und Lücken lässt.", "Smoken, aber nicht gehen, sodass sie ohne Wirkung ausläuft.",
                     "Durch den Rand einer Smoke laufen."],
        "drill": {"where": "Offline-Server, Lineups-Reiter der App",
                  "steps": ["Such dir für deine Map zwei Smokes aus dem Reiter Lineups aus, je eine pro Bombspot.",
                            "Wirf jede so lange, bis sie fünfmal in Folge sitzt."],
                  "done": "Du kannst zwei Smokes pro Map im Schlaf."},
        "cue": "Linie zu, dann gehen", "ask": "Welche Sichtlinie hat dich getötet, und hätte eine Smoke sie schließen können?",
        "quiz": [
            {"id": "sm1", "q": "Wofür werfen Ts beim Angriff auf einen Bombspot Smokes?",
             "options": ["Um Positionen abzuschneiden, damit weniger Winkel offen sind", "Damit die CTs ihre eigenen Granaten nicht mehr werfen können", "Um sich selbst zu verstecken und zu warten"],
             "a": 0, "why": "Jede abgeschnittene Position ist ein Winkel weniger, aus dem euch ein CT treffen kann."},
            {"id": "sm2", "q": "Ihr werft eure Smokes, geht aber nicht los. Was passiert?",
             "options": ["Die CTs bleiben geblendet, bis ihr kommt", "Die Smokes laufen ohne Wirkung aus und die Granaten sind verloren", "Die CTs müssen rotieren"],
             "a": 1, "why": "Eine Smoke wirkt nur, solange sie steht. Utility und Laufen gehören zusammen."},
        ],
        "lessons": ["no_shot_far", "utility"], "links": ["lineups", "granaten"],
    },
    "flashes": {
        "area": "nades", "title": "Flashes: Pop-Flash und Team-Flash",
        "key": "Eine gute Flash platzt, bevor der Gegner sie sieht, und du peekst genau in diesem Moment.",
        "teach": [
            "Eine Flash wirkt, wenn der Gegner zu ihr schaut. Eine Pop-Flash platzt direkt, nachdem sie über eine Kante "
            "fliegt, sodass er nicht mehr wegdrehen kann.",
            "Du kannst für dich selbst flashen, dann peekst du direkt danach. Oder ein Mitspieler flasht für dich. Dann "
            "braucht es eine Absprache: Wer wirft, sagt flash raus, wer peekt, geht im Moment der Explosion.",
            "Eine Flash hinter dem Rücken deines Teams blendet die eigenen Leute. Wirf so, dass deine Mitspieler von der "
            "Flash wegschauen. Was deine Flashes bewirken, siehst du im Reiter Granaten.",
        ],
        "example": [
            "Ein CT hält eine Ecke, an der du vorbei musst.",
            "Du wirfst die Flash über die Kante, sodass sie direkt vor ihm platzt.",
            "Im Moment der Explosion peekst du und hast einen geblendeten Gegner vor dir.",
        ],
        "mistakes": ["Flash werfen und zu spät peeken, wenn sie schon nachlässt.", "Mitspieler blenden.",
                     "Flashes so hoch werfen, dass der Gegner sie kommen sieht und wegdreht."],
        "drill": {"where": "Offline-Server",
                  "steps": ["Lern für jede deiner Standard-Positionen eine Flash, mit der du selbst peeken kannst.",
                            "Werfen, im Moment der Explosion peeken. Fünfmal pro Flash."],
                  "done": "Du kannst für deine Positionen eine Pop-Flash werfen und direkt peeken."},
        "cue": "Flash, dann peek", "ask": "Hast du direkt nach deiner Flash gepeekt?",
        "quiz": [
            {"id": "fl1", "q": "Wann peekst du nach deiner eigenen Pop-Flash?",
             "options": ["Ein paar Sekunden später", "Im Moment der Explosion", "Kurz davor, damit du zuerst da bist"],
             "a": 1, "why": "Direkt nach der Explosion ist der Gegner am stärksten geblendet."},
            {"id": "fl2", "q": "Warum werfen gute Spieler Flashes über eine Kante, statt hoch in die Luft?",
             "options": ["Damit sie platzt, bevor der Gegner wegdrehen kann", "Weil sie weiter fliegt", "Weil sie dann länger blendet"],
             "a": 0, "why": "Sieht der Gegner die Flash kommen, dreht er weg. Eine Pop-Flash lässt ihm keine Zeit."},
        ],
        "lessons": ["utility", "blind"], "links": ["granaten", "lineups"],
    },
    "molotov": {
        "area": "nades", "title": "Molotov und Brandgranate",
        "key": "Feuer zwingt den Gegner, eine Stelle zu verlassen oder nicht zu betreten.",
        "teach": [
            "Mit einer Molotov (T) oder Brandgranate (CT) räumst du Ecken, in denen ein Gegner sitzt. Er muss raus und "
            "läuft dabei oft in dein Fadenkreuz, oder er nimmt Schaden.",
            "Als CT verzögern Brandgranaten einen Angriff. Ein Durchgang mit Feuer ist für einige Sekunden gesperrt, "
            "genug Zeit, dass Hilfe kommt.",
            "Nach dem Plant ist die Molotov eine der stärksten Granaten der Ts: Wer die Bombe brennen lässt, verhindert "
            "das Entschärfen.",
        ],
        "example": [
            "Ihr kommt als T auf einen Bombspot, auf dem oft ein CT in einer engen Ecke sitzt.",
            "Du wirfst die Molotov in diese Ecke, bevor ihr reingeht.",
            "Der CT muss raus. Dein Mitspieler hält genau die Stelle, an der er rauskommt.",
        ],
        "mistakes": ["Mit einer Molotov in der Tasche sterben.", "Die Molotov irgendwohin werfen, wo kein Gegner sitzt.",
                     "Nach dem Plant keine Molotov für die Bombe aufheben."],
        "drill": {"where": "Offline-Server",
                  "steps": ["Lern für deinen Lieblingsspot eine Molotov, die die häufigste CT-Ecke räumt.",
                            "Lern dazu eine Molotov, mit der du die Bombe von einer sicheren Stelle aus treffen kannst."],
                  "done": "Du hast pro Spot eine Molotov zum Räumen und eine für die Bombe."},
        "cue": "Feuer in die Ecke", "ask": "Hättest du mit deiner Molotov eine Ecke räumen oder die Bombe schützen können?",
        "quiz": [
            {"id": "mo1", "q": "Wofür hebst du als T nach dem Plant am besten eine Molotov auf?",
             "options": ["Um die Bombe brennen zu lassen, wenn der CT entschärfen will", "Um einen Zugang zu sperren, durch den der CT schon durch ist", "Gar nicht, Molotovs sind nur vor dem Plant gut"],
             "a": 0, "why": "Wer im Feuer entschärft, stirbt oder muss abbrechen. So rettest du die Runde ohne Duell."},
        ],
        "lessons": ["utility"], "links": ["granaten", "lineups"],
    },
    "he_grenade": {
        "area": "nades", "title": "HE-Granate",
        "key": "Eine HE macht Schaden, der den nächsten Schuss tödlich macht, und mehrere zusammen töten.",
        "teach": [
            "Eine HE allein tötet selten. Aber Gegner mit wenig HP sind danach für jede Waffe leichte Beute. Zwei HEs auf "
            "dieselbe Stelle können Gegner töten, besonders ohne Rüstung.",
            "Gute Ziele sind Stellen, an denen Gegner eng zusammenstehen, zum Beispiel am Anfang eines Rushs oder auf einer "
            "Eco-Runde des Gegners ohne Rüstung.",
            "Wie viel Schaden deine HEs machen, siehst du im Reiter Granaten.",
        ],
        "example": [
            "Ihr hört als CT, dass sich mehrere Ts eng vor einem Durchgang sammeln.",
            "Du und dein Mitspieler werft gleichzeitig eine HE dorthin.",
            "Mehrere Ts kommen mit wenig HP raus, und ihr gewinnt die Duelle leicht.",
        ],
        "mistakes": ["HEs auf leere Stellen werfen.", "Auf Anti-Eco-Runden die HE vergessen."],
        "drill": {"where": "Offline-Server",
                  "steps": ["Such dir die Stelle, an der sich Gegner auf deiner Map am Rundenanfang sammeln.", "Lern eine HE dorthin."],
                  "done": "Du kennst eine HE für den Rundenanfang deiner Map."},
        "cue": "Schaden vor dem Duell", "ask": "Hätte eine HE den Gegner vor deinem Duell schwächen können?",
        "quiz": [
            {"id": "he1", "q": "Wann ist eine HE besonders stark?",
             "options": ["Gegen eng stehende Gegner ohne Rüstung", "Gegen einen einzelnen Gegner hinter einer Wand weit weg", "Gegen einen Gegner mit voller Rüstung auf großer Distanz"],
             "a": 0, "why": "Ohne Rüstung und eng zusammen nehmen mehrere Gegner viel Schaden."},
        ],
        "lessons": ["utility"], "links": ["granaten"],
    },
    "utility_order": {
        "area": "nades", "title": "Granaten im richtigen Moment",
        "key": "Zuerst Smokes, dann Molotovs, dann Flashes, und direkt danach geht ihr. Utility ohne Laufen verpufft.",
        "teach": [
            "Bei einem Angriff gibt es eine Reihenfolge, die viele Teams nutzen: Smokes schneiden Positionen ab, Molotovs "
            "räumen Ecken, Flashes blenden die verbleibenden Gegner im Moment des Peeks.",
            "Das Timing ist wichtiger als die Menge. Kommt die Flash zu früh, ist der Gegner wieder klar, wenn ihr peekt. "
            "Kommen die Smokes zu spät, steht ihr ohne Schutz im Offenen.",
            "Als CT gilt Ähnliches: Brandgranaten und HEs gegen einen Rush wirken nur, wenn sie kommen, solange die Ts "
            "noch eng stehen.",
        ],
        "example": [
            "Ihr greift zu zweit einen Bombspot an.",
            "Du wirfst zuerst die Smoke auf die Position mit langer Sicht.",
            "Dein Bruder wirft eine Molotov in die enge Ecke.",
            "Dann flasht du über die Kante und ihr geht gleichzeitig rein.",
        ],
        "mistakes": ["Flashes zu früh werfen.", "Alle Granaten werfen und dann warten.", "Utility für das Ende der Runde aufheben und dann sterben."],
        "drill": {"where": "Offline-Server zu zweit",
                  "steps": ["Spielt einen Execute auf einen Spot mit fester Reihenfolge: Smoke, Molotov, Flash, Laufen.",
                            "Zählt bei jedem Durchgang, ob alle Granaten gesessen haben und ob ihr direkt gegangen seid."],
                  "done": "Ihr könnt einen Execute zu zweit fünfmal hintereinander sauber durchziehen."},
        "cue": "Smoke, Molly, Flash, geh", "ask": "Kam deine Flash im Moment des Peeks oder zu früh?",
        "quiz": [
            {"id": "uo1", "q": "In welcher Reihenfolge werfen viele Teams beim Execute?",
             "options": ["Flash, Smoke, Molotov", "Smoke, Molotov, Flash", "Molotov, Flash, Smoke"],
             "a": 1, "why": "Smokes stehen länger und müssen zuerst sitzen. Die Flash kommt im Moment des Peeks."},
        ],
        "lessons": ["utility"], "links": ["granaten", "lineups", "playbook"],
    },
    "counter_utility": {
        "area": "nades", "title": "Gegner-Utility kontern",
        "key": "Bei einer Flash drehst du weg, bei Feuer gehst du zurück, an der Smoke wartest du auf den, der durchkommt.",
        "teach": [
            "Eine Flash, die du hörst, kannst du oft noch abwehren: wegdrehen, hinter Deckung, danach wieder peeken. "
            "Geblendet stehen bleiben kostet fast immer das Leben.",
            "Gegen Molotovs und Brandgranaten gehst du raus und nimmst eine Position, die den Ausgang hält. Gegen Smokes "
            "hilft Geduld: Wer durch die Smoke kommt, ist kurz sichtbar und ohne Sicht.",
            "Eine eigene Smoke kann eine Molotov löschen. Das ist wichtig, wenn du als CT eine Bombe entschärfen willst, die "
            "brennt.",
        ],
        "example": [
            "Du hältst als CT eine Ecke und hörst eine Flash kommen.",
            "Du drehst weg und gehst einen Schritt hinter die Deckung.",
            "Die Ts erwarten dich geblendet. Du peekst wieder, wenn die Flash vorbei ist, und hast den ersten Schuss.",
        ],
        "mistakes": ["Bei einer Flash weiter hinschauen.", "Durch Feuer laufen, um eine Position zu halten.", "Direkt durch eine Smoke peeken."],
        "drill": {"where": "Retake-Server",
                  "steps": ["Bei jedem Flash-Geräusch sofort wegdrehen.", "Zähl zehn Runden lang, wie oft du geblendet gestorben bist."],
                  "done": "Zehn Runden ohne geblendet zu sterben."},
        "cue": "Flash hören, wegdrehen", "ask": "Hast du die Flash kommen hören, bevor sie dich geblendet hat?",
        "quiz": [
            {"id": "cu1", "q": "Was löscht eine brennende Molotov?",
             "options": ["Eine Smoke", "Eine Flash", "Eine HE-Granate"], "a": 0,
             "why": "Eine Smoke löscht das Feuer. Damit kann ein CT eine brennende Bombe doch noch entschärfen."},
            {"id": "cu2", "q": "Du hörst eine Flash kommen. Was ist richtig?",
             "options": ["Weiter auf die Kante schauen", "Wegdrehen und hinter Deckung gehen", "Die eigene Flash dagegen werfen"],
             "a": 1, "why": "Weggedreht wirkt die Flash kaum. Danach kannst du wieder peeken oder traden."},
        ],
        "lessons": ["blind"], "links": ["granaten"],
    },
    # --- T-Seite --------------------------------------------------------------------------------------------
    "t_default": {
        "area": "t", "title": "Default und Map-Kontrolle",
        "key": "Ein Default verteilt das Team über die Map, sammelt Infos und entscheidet erst dann, wo ihr angreift.",
        "teach": [
            "Bei einem Default gehen die Ts nicht sofort auf einen Spot, sondern nehmen Teile der Map: Mitte, Zugänge, "
            "Positionen vor den Bombspots. Dabei sammeln sie Infos, wo die CTs stehen.",
            "Map-Kontrolle heißt: Ihr besitzt Teile der Map, über die ihr später schnell und sicher auf einen Spot "
            "kommt. Wer die Mitte hat, kann beide Spots angreifen und zwingt die CTs, sich zu verteilen.",
            "Im Playbook der App siehst du, welche Taktiken die Pros auf deiner Map spielen und wie sie die Map aufteilen.",
        ],
        "example": [
            "Ihr startet als T mit einem Default: einer Mitte, zwei Richtung A, zwei Richtung B.",
            "Der Mitte-Spieler sieht, dass B dünn besetzt ist.",
            "Ihr sammelt euch nach etwa einer Minute und geht gemeinsam auf B.",
        ],
        "mistakes": ["Im Default Duelle suchen, statt nur die Map zu nehmen.", "Zu lange im Default bleiben und am Ende keine Zeit für den Angriff haben.",
                     "Allein auf einer Position sterben, ohne Info zu geben."],
        "drill": {"where": "Playbook deiner Map, dann ein Match",
                  "steps": ["Schau dir im Playbook den häufigsten Default der Pros auf deiner Map an.",
                            "Sprecht vor dem Match ab, welche Positionen ihr zwei darin nehmt."],
                  "done": "Ihr habt für jede Map eine feste Position im Default."},
        "cue": "Map nehmen, nicht Duelle", "ask": "Welche Info hast du im Default gesammelt und weitergegeben?",
        "quiz": [
            {"id": "td1", "q": "Was ist das Ziel eines Defaults?",
             "options": ["Sofort einen Spot angreifen", "Map-Kontrolle und Infos sammeln, dann entscheiden", "Möglichst früh die ersten Duelle suchen"],
             "a": 1, "why": "Erst Infos und Kontrolle, dann der Angriff dort, wo die CTs schwach sind."},
        ],
        "lessons": ["alone"], "links": ["playbook", "briefing"],
    },
    "t_execute": {
        "area": "t", "title": "Execute",
        "key": "Ein Execute ist ein gemeinsamer Angriff mit Granaten: alle gleichzeitig, alle mit Utility.",
        "teach": [
            "Beim Execute geht das ganze Team mit Granaten auf einen Bombspot. Die Kraft liegt im gleichzeitigen "
            "Kommen: Die CTs müssen mehrere Ts zugleich halten und verlieren den Vorteil der festen Position.",
            "Ein guter Execute braucht feste Granaten, die jeder kennt, und ein Signal, wann es losgeht.",
            "Ein Execute einzeln hintereinander ist keiner. Wer zu spät kommt, kämpft allein gegen einen bereiten CT.",
        ],
        "example": [
            "Der Call kommt: Execute A in drei, zwei, eins.",
            "Alle werfen ihre festen Granaten: Smokes auf die CT-Wege, Molotov in die Ecke, Flashes über den Spot.",
            "Alle gehen gleichzeitig rein, nehmen ihre Winkel und planten die Bombe.",
        ],
        "mistakes": ["Einer nach dem anderen reinlaufen.", "Granaten werfen, bevor alle bereit sind.", "Keine feste Aufgabe für jeden."],
        "drill": {"where": "Offline-Server zu zweit, Lineups und Playbook",
                  "steps": ["Wählt einen Execute aus dem Playbook. Jeder lernt seine Granaten.",
                            "Übt das Signal und das gleichzeitige Reingehen."],
                  "done": "Ihr könnt einen Execute pro Map gemeinsam ausführen."},
        "cue": "Alle zusammen", "ask": "Kamt ihr gleichzeitig oder einer nach dem anderen auf den Spot?",
        "quiz": [
            {"id": "te1", "q": "Was macht einen Execute stark?",
             "options": ["Dass einer nach dem anderen reingeht", "Dass alle gleichzeitig mit Granaten kommen", "Dass man die Granaten spart und nur mit Aim kommt"],
             "a": 1, "why": "Gleichzeitig kommen heißt: Die CTs müssen mehrere Ts zugleich halten."},
        ],
        "lessons": ["utility", "alone"], "links": ["playbook", "lineups"],
    },
    "t_split_fake": {
        "area": "t", "title": "Split und Fake",
        "key": "Ein Split greift einen Spot von zwei Seiten an. Ein Fake zieht die CTs auf den falschen Spot.",
        "teach": [
            "Beim Split kommt das Team aus zwei Richtungen auf denselben Spot, zum Beispiel aus der Mitte und von außen. "
            "Die CTs müssen in zwei Richtungen schauen und können nicht beide gleichzeitig halten.",
            "Beim Fake täuscht ihr einen Angriff vor, etwa mit Granaten und Geräuschen auf einem Spot. Rotieren die CTs, "
            "greift der Rest des Teams den anderen Spot an.",
            "Ein Fake kostet Granaten und Zeit. Er lohnt sich, wenn die CTs schnell rotieren.",
        ],
        "example": [
            "Ihr habt gemerkt, dass die CTs bei jedem Geräusch auf A sofort rotieren.",
            "Einer wirft Granaten auf A und macht Lärm. Vier warten nah an B.",
            "Der CT von B rotiert. Ihr geht auf B gegen weniger Verteidiger.",
        ],
        "mistakes": ["Beim Split nicht gleichzeitig ankommen.", "Fake ohne genug Zeit für den echten Angriff."],
        "drill": {"where": "Eigene Demos",
                  "steps": ["Schau in einer Demo, wie schnell die CTs nach dem ersten Kontakt rotieren.",
                            "Macht daraus eine Regel: Rotieren sie schnell, lohnt sich ein Fake."],
                  "done": "Ihr erkennt, ob ein Gegner schnell rotiert."},
        "cue": "Zwei Seiten", "ask": "Wie haben die CTs auf euren ersten Kontakt reagiert?",
        "quiz": [
            {"id": "sf1", "q": "Wann lohnt sich ein Fake besonders?",
             "options": ["Wenn die CTs schnell rotieren", "Wenn die CTs nie rotieren", "Wenn nur noch wenig Zeit auf der Uhr ist"],
             "a": 0, "why": "Ein Fake zieht CTs weg. Das klappt nur, wenn sie auf Lärm reagieren."},
        ],
        "lessons": [], "links": ["playbook"],
    },
    "lurk": {
        "area": "t", "title": "Lurken",
        "key": "Der Lurker ist allein, leise und auf der anderen Seite. Er sucht keine Duelle, sondern das richtige Timing.",
        "teach": [
            "Ein Lurker spielt abseits des Teams. Er sammelt Infos, schneidet Rotationen ab und greift Gegner von hinten "
            "an, wenn das Team auf einen Spot geht.",
            "Das Wichtigste ist Timing: Er wartet, bis die CTs zum Team rotieren, und tötet sie dann von hinten. Wer zu "
            "früh peekt, stirbt allein ohne Wirkung.",
            "Lurken ist schwer, weil man allein ist. Ein Lurker braucht gute Calls vom Team, um zu wissen, wann sein "
            "Moment kommt.",
        ],
        "example": [
            "Dein Team geht auf B. Du bist leise nah an A.",
            "Du hörst, dass ein CT von A rotiert.",
            "Du wartest, bis er weg ist, dann nimmst du A oder greifst den nächsten Rotierer von hinten an.",
        ],
        "mistakes": ["Zu früh peeken.", "Laut sein.", "Lurken, ohne dass das Team weiß, wo du bist."],
        "drill": {"where": "Eigene Demos",
                  "steps": ["Schau dir in deiner Demo an, wann die CTs rotiert sind.",
                            "Überleg: Wo hätte ein Lurker gestanden, um sie abzufangen?"],
                  "done": "Du kennst für deine Map einen Lurk-Weg und weißt, wann du dort zuschlägst."},
        "cue": "Warten auf die Rotation", "ask": "Hast du zugeschlagen, als die CTs rotiert sind, oder vorher?",
        "quiz": [
            {"id": "lu1", "q": "Wann greift ein Lurker an?",
             "options": ["Sofort zu Rundenbeginn", "Wenn die CTs zum Angriff des Teams rotieren", "Erst nach dem Plant"],
             "a": 1, "why": "Dann kommen sie mit dem Rücken zu ihm, und der Lurker hat den Vorteil."},
        ],
        "lessons": ["alone"], "links": ["playbook"],
    },
    "midround": {
        "area": "t", "title": "Entscheidung mitten in der Runde",
        "key": "Nach dem ersten Kontakt fragst du: Wie viele sind wir, wie viele sie, wie viel Zeit, wo ist Platz?",
        "teach": [
            "Ein Plan zu Rundenbeginn ist nur der Anfang. Nach dem ersten Kill oder der ersten Info ändert sich die Lage. "
            "Gute Teams entscheiden dann neu, statt den Plan stur durchzuziehen.",
            "Vier Fragen helfen: Zahlen (wie viele auf jeder Seite), Zeit (wie viel bleibt), Ort (wo sind die CTs, wo ist "
            "Platz) und Ausrüstung (welche Granaten und Waffen habt ihr noch).",
            "Ein Beispiel: Ihr habt früh einen Kill auf A geholt. Die CTs rotieren nach A. Jetzt kann B die bessere "
            "Entscheidung sein, weil dort einer fehlt.",
        ],
        "example": [
            "Ihr holt im Default einen Kill in der Mitte.",
            "Zahlen: fünf gegen vier. Zeit: noch viel. Ort: Ein CT fehlt jetzt auf der B-Seite.",
            "Ihr entscheidet neu: Alle auf B, weil dort jetzt einer weniger hält.",
        ],
        "mistakes": ["Den Plan durchziehen, obwohl die Lage sich geändert hat.", "Nach einem frühen Kill zu lange warten.",
                     "Ohne Zeit im Blick zu spät angreifen."],
        "drill": {"where": "Eigene Demo",
                  "steps": ["Halte nach jedem ersten Kill einer Runde an.", "Beantworte die vier Fragen und sag, was du entschieden hättest.",
                            "Spiel weiter und vergleiche."],
                  "done": "Du stellst dir die vier Fragen nach dem ersten Kontakt automatisch."},
        "cue": "Zahlen, Zeit, Ort", "ask": "Was hat sich nach dem ersten Kill geändert, und habt ihr neu entschieden?",
        "quiz": [
            {"id": "mr1", "q": "Ihr holt einen frühen Kill auf A. Die CTs rotieren nach A. Was kann jetzt klug sein?",
             "options": ["Weiter stur auf A", "Auf B wechseln, weil dort jetzt einer fehlt", "Sparen und auf die nächste Runde warten"],
             "a": 1, "why": "Rotieren die CTs, wird der andere Spot schwächer. Neu entscheiden schlägt stur bleiben."},
        ],
        "lessons": ["outnumbered"], "links": ["playbook"],
    },
    "t_timing": {
        "area": "t", "title": "Tempo: Rush, schnell, langsam",
        "key": "Wer immer gleich schnell spielt, ist leicht zu lesen. Wechselt das Tempo, und die CTs müssen raten.",
        "teach": [
            "Ein Rush geht direkt zu Rundenbeginn auf einen Spot, bevor die CTs Granaten werfen oder sich verteilen. Ein "
            "langsamer Angriff nutzt die Zeit, um Infos zu sammeln und CTs zu ziehen.",
            "Beide haben ihren Platz. Gegen CTs, die früh aggressiv sind, hilft ein langsames Spiel. Gegen CTs, die "
            "spät rotieren, hilft Tempo.",
            "Achte auf die Uhr: Ein Angriff, der zu spät beginnt, lässt dir nach dem Plant kaum Zeit zum Verteidigen, und "
            "ein CT kann einfach auf Zeit spielen.",
        ],
        "example": [
            "In den letzten Runden habt ihr immer langsam gespielt, und die CTs warteten auf euch.",
            "Diese Runde geht ihr direkt mit Tempo auf B.",
            "Die CTs sind noch nicht bereit. Ihr planted, bevor Hilfe kommt.",
        ],
        "mistakes": ["Jede Runde gleich schnell spielen.", "Zu spät angreifen, sodass keine Zeit bleibt."],
        "drill": {"where": "Nächstes Match",
                  "steps": ["Sprecht ab: Nach zwei langsamen Runden kommt eine schnelle.", "Schaut nach dem Match, ob die schnelle Runde funktioniert hat."],
                  "done": "Ihr wechselt euer Tempo bewusst."},
        "cue": "Tempo wechseln", "ask": "Konnte der Gegner euer Tempo vorhersagen?",
        "quiz": [
            {"id": "tt1", "q": "Warum lohnt es sich, das Tempo zu wechseln?",
             "options": ["Weil die CTs sonst wissen, wann ihr kommt", "Weil langsame Runden mehr Loss-Bonus bringen", "Gar nicht, ein festes Tempo gibt dem Team Sicherheit"],
             "a": 0, "why": "Ein vorhersehbares Team ist leicht zu verteidigen."},
        ],
        "lessons": [], "links": ["playbook"],
    },
    # --- CT-Seite --------------------------------------------------------------------------------------------
    "ct_setup": {
        "area": "ct", "title": "Setup: Anker und Rotator",
        "key": "Der Anker hält seinen Spot bis Hilfe kommt. Der Rotator hilft dort, wo es brennt.",
        "teach": [
            "Ein CT-Setup verteilt die fünf Spieler auf die Map. Ein Anker spielt auf einem Bombspot und bleibt dort. "
            "Seine Aufgabe ist, Zeit zu kaufen und Infos zu geben, nicht zu sterben.",
            "Rotatoren stehen so, dass sie schnell beide Seiten erreichen können, oft in der Mitte. Sie gehen dorthin, wo "
            "die Ts angreifen.",
            "Im Playbook für CT siehst du, wie die Pros sich auf deiner Map verteilen.",
        ],
        "example": [
            "Du bist Anker auf B. Du hörst den Angriff der Ts.",
            "Du callst, wie viele kommen, und fällst etwas zurück, statt sofort zu sterben.",
            "Die Rotatoren kommen. Zusammen nehmt ihr den Spot zurück.",
        ],
        "mistakes": ["Als Anker allein gegen fünf kämpfen und sterben, bevor Hilfe kommt.", "Als Rotator bei jedem Geräusch rotieren."],
        "drill": {"where": "Playbook CT deiner Map",
                  "steps": ["Schau dir an, wo die Pros als Anker stehen.", "Sprecht ab, wer von euch Anker und wer Rotator ist."],
                  "done": "Jeder weiß auf jeder Map, ob er Anker oder Rotator ist."},
        "cue": "Zeit kaufen", "ask": "Hast du als Anker Zeit gekauft oder bist du schnell gestorben?",
        "quiz": [
            {"id": "cs_1", "q": "Was ist die wichtigste Aufgabe des Ankers, wenn fünf Ts kommen?",
             "options": ["Die Position um jeden Preis halten", "Info geben und Zeit kaufen, bis Hilfe da ist", "Sofort zum anderen Spot rotieren"],
             "a": 1, "why": "Allein gegen fünf gewinnt er selten. Info und Zeit lassen das Team zurückkommen."},
        ],
        "lessons": ["outnumbered"], "links": ["playbook"],
    },
    "crossfire": {
        "area": "ct", "title": "Crossfire",
        "key": "Zwei CTs schauen aus verschiedenen Winkeln auf dieselbe Stelle. Wer einen anschaut, wird vom anderen getroffen.",
        "teach": [
            "In einem Crossfire halten zwei Spieler denselben Bereich aus unterschiedlichen Richtungen. Ein T kann nur "
            "einen von beiden ansehen. Der andere hat einen freien Schuss.",
            "Wichtig ist, dass die beiden nicht so weit auseinanderstehen, dass sie einzeln sterben, und nicht so nah, "
            "dass eine Granate beide trifft.",
            "Ein Crossfire funktioniert auch beim Post-Plant und Retake.",
        ],
        "example": [
            "Du und dein Bruder haltet einen Ausgang als CT.",
            "Du schaust von links, er von rechts auf dieselbe Stelle.",
            "Ein T kommt raus und dreht sich zu dir. Dein Bruder trifft ihn von der Seite.",
        ],
        "mistakes": ["Beide aus derselben Richtung halten.", "Zu weit auseinander stehen."],
        "drill": {"where": "Offline-Server zu zweit",
                  "steps": ["Sucht für euren Lieblingsspot ein Crossfire.", "Einer läuft als T durch und sagt, wen er zuerst sieht."],
                  "done": "Ihr habt für jeden Spot ein Crossfire."},
        "cue": "Zwei Winkel, ein Ziel", "ask": "Hätte der Gegner euch beide gleichzeitig sehen müssen?",
        "quiz": [
            {"id": "cf1", "q": "Was macht ein Crossfire stark?",
             "options": ["Der T kann nur einen der beiden CTs ansehen", "Beide CTs stehen direkt nebeneinander", "Beide können sich gegenseitig Granaten geben"],
             "a": 0, "why": "Während der T sich zu einem dreht, hat der andere einen freien Schuss."},
        ],
        "lessons": ["angle", "alone"], "links": ["playbook", "mapbook"],
    },
    "rotation": {
        "area": "ct", "title": "Rotieren",
        "key": "Rotiere bei echten Infos, nicht bei jedem Geräusch, und zusammen statt einzeln.",
        "teach": [
            "Ein CT rotiert, wenn er von einem Spot zum anderen geht, weil dort die Ts angreifen. Zu früh rotieren lässt "
            "den eigenen Spot offen. Zu spät rotieren lässt den Anker allein.",
            "Gute Infos zum Rotieren sind: mehrere Ts gesehen, mehrere Granaten auf einen Spot, die Bombe gesehen.",
            "Rotiere nicht durch den Weg, den die Ts benutzen, und nicht einzeln. Wer allein in einen Spot voller Ts läuft, "
            "stirbt.",
        ],
        "example": [
            "Ihr hört einen Granaten auf A. Der Anker auf A sagt aber: Nur einer, die Bombe habe ich nicht gesehen.",
            "Die Rotatoren bleiben in der Mitte.",
            "Kurz danach greifen die Ts B an. Die Rotatoren sind nah genug, um zu helfen.",
        ],
        "mistakes": ["Bei jedem Geräusch rotieren.", "Allein in einen Spot voller Ts laufen.", "Den Weg der Ts zum Rotieren nehmen."],
        "drill": {"where": "Eigene Demo",
                  "steps": ["Schau dir die Runden an, in denen du rotiert bist.", "Welche Info hatte das Team? War sie stark genug?"],
                  "done": "Du kannst sagen, auf welche Info hin ihr rotiert."},
        "cue": "Echte Info, dann gehen", "ask": "Welche Info hat dich rotieren lassen?",
        "quiz": [
            {"id": "ro1", "q": "Welche Info reicht am ehesten zum Rotieren?",
             "options": ["Ein einzelner Schritt", "Mehrere Ts und die Bombe gesehen", "Ein Geräusch, das man nicht zuordnen kann"],
             "a": 1, "why": "Viele Ts und die Bombe zeigen den echten Angriff. Einzelne Geräusche können ein Fake sein."},
        ],
        "lessons": ["outnumbered"], "links": ["playbook"],
    },
    "ct_aggression": {
        "area": "ct", "title": "Info-Peeks und Aggression als CT",
        "key": "Ein früher Info-Peek kann eine ganze Runde verraten. Aber nur, wenn du zurückkommst.",
        "teach": [
            "Als CT weißt du zu Rundenbeginn wenig. Ein früher Peek, oft mit einer Flash oder aus einer unerwarteten "
            "Position, zeigt, wohin die Ts gehen.",
            "Aggression ist ein Risiko. Stirbst du dabei, seid ihr vier gegen fünf. Deshalb peekt man kurz, holt die Info "
            "und geht zurück.",
            "Aggression wirkt am besten, wenn sie selten und unvorhersehbar ist.",
        ],
        "example": [
            "Zu Rundenbeginn wirfst du als CT eine Flash und peekst kurz in den Zugang der Ts.",
            "Du siehst drei Ts und gehst sofort zurück.",
            "Du callst: Drei kommen. Dein Team kann früh rotieren.",
        ],
        "mistakes": ["Jede Runde gleich aggressiv spielen.", "Nach der Info nicht zurückgehen."],
        "drill": {"where": "Nächstes Match",
                  "steps": ["Plant eine Info-Peek-Runde pro Hälfte mit Flash.", "Nach der Info sofort zurück."],
                  "done": "Du holst mit einem Peek eine Info und überlebst."},
        "cue": "Info holen, zurück", "ask": "Bist du nach der Info zurückgegangen?",
        "quiz": [
            {"id": "ca_1", "q": "Was ist das Ziel eines frühen Info-Peeks als CT?",
             "options": ["Info holen und zurückgehen", "Allein alle Ts töten", "Den ersten Kill holen, egal was es kostet"],
             "a": 0, "why": "Die Info hilft dem Team. Ein Tod beim Info-Peek kostet mehr, als die Info bringt."},
        ],
        "lessons": ["alone"], "links": ["playbook"],
    },
    "ct_stack": {
        "area": "ct", "title": "Stacken und Spot aufgeben",
        "key": "Manchmal ist es klug, einen Spot fast leer zu lassen und auf Retake zu spielen.",
        "teach": [
            "Stacken heißt: mehr CTs als üblich auf einen Spot, weil man dort den Angriff erwartet. Das ist ein Risiko, "
            "aber es kann einen Gegner brechen, der immer denselben Spot angreift.",
            "Bei einem starken Angriff kann es auch richtig sein, einen Spot nicht zu verteidigen, sondern zu warten, bis "
            "die Ts planten, und dann gemeinsam zurückzunehmen.",
            "Solche Entscheidungen funktionieren nur mit Absprache und Infos aus früheren Runden.",
        ],
        "example": [
            "Die Ts haben fünf Runden in Folge B angegriffen.",
            "Ihr stellt drei CTs auf B.",
            "Der nächste Angriff auf B trifft auf drei bereite Verteidiger.",
        ],
        "mistakes": ["Stacken ohne Grund.", "Einen Spot aufgeben, ohne dass alle es wissen."],
        "drill": {"where": "Eigene Demos",
                  "steps": ["Zählt nach dem Match, wie oft der Gegner welchen Spot angegriffen hat.", "Gab es ein Muster?"],
                  "done": "Ihr erkennt Muster im Spiel des Gegners."},
        "cue": "Muster lesen", "ask": "Hat der Gegner ein Muster, das man ausnutzen kann?",
        "quiz": [
            {"id": "st1", "q": "Wann ist Stacken sinnvoll?",
             "options": ["Wenn der Gegner immer denselben Spot angreift", "Wenn ihr gerade eine Eco spielt", "Nach jeder verlorenen Pistolenrunde"],
             "a": 0, "why": "Ein Muster beim Gegner lässt sich ausnutzen. Ohne Muster ist Stacken ein großes Risiko."},
        ],
        "lessons": [], "links": ["playbook"],
    },
    # --- Bombe ---------------------------------------------------------------------------------------------
    "plant_postplant": {
        "area": "bomb", "title": "Plant und Post-Plant",
        "key": "Nach dem Plant muss der CT zu dir kommen. Du wartest in Crossfire-Positionen, nicht auf der Bombe.",
        "teach": [
            "Nach dem Plant läuft die Uhr für den CT: 40 Sekunden bis zur Explosion, davon 10 zum Entschärfen ohne Kit "
            "und 5 mit Kit. Der T muss nicht mehr angreifen, sondern nur noch verhindern, dass entschärft wird.",
            "Die stärksten Post-Plant-Positionen schauen von verschiedenen Seiten auf die Bombe. Wer entschärft, steht "
            "still und ist leicht zu treffen.",
            "Hör auf das Entschärfen-Geräusch. Mit Molotov oder HE kannst du einen Entschärfer stoppen, ohne zu peeken. "
            "Wird die Bombe geplantet, bekommen die Ts auch bei einer Niederlage zusätzliches Geld.",
        ],
        "example": [
            "Ihr habt geplanted. Du stellst dich an eine Stelle mit Blick auf die Bombe, dein Bruder an eine andere.",
            "Ein CT kommt und beginnt zu entschärfen.",
            "Du hörst das Geräusch, peekst und triffst den stillstehenden Entschärfer.",
        ],
        "mistakes": ["Direkt neben der Bombe stehen.", "Nach dem Plant noch Duelle suchen, statt auf Zeit zu spielen.",
                     "Keine Molotov für die Bombe behalten."],
        "drill": {"where": "Retake-Server als T",
                  "steps": ["Spiel nach dem Plant immer von einer Stelle mit Blick auf die Bombe, aber nicht neben ihr.",
                            "Nutz das Entschärfen-Geräusch als Signal zum Peek."],
                  "done": "Du kennst pro Spot zwei Post-Plant-Positionen."},
        "cue": "Die Uhr spielt für mich", "ask": "Wo hast du nach dem Plant gestanden, und musste der CT zu dir kommen?",
        "quiz": [
            {"id": "pp1", "q": "Was ist nach dem Plant die Aufgabe der Ts?",
             "options": ["Weiter angreifen", "Verhindern, dass entschärft wird", "Die Bombe bewachen, direkt daneben stehend"],
             "a": 1, "why": "Die Zeit spielt für die Ts. Der CT muss zur Bombe kommen und still stehen."},
            {"id": "pp2", "q": "Der CT beginnt zu entschärfen und du hörst es. Was nutzt du?",
             "options": ["Das Geräusch als Signal zum Peek oder für eine Molotov", "Nichts, du wartest", "Du wechselst die Position und wartest auf den nächsten CT"],
             "a": 0, "why": "Wer entschärft, steht still. Ein Peek oder eine Molotov in diesem Moment rettet die Runde."},
        ],
        "lessons": ["outnumbered", "utility"], "links": ["playbook"],
    },
    "retake": {
        "area": "bomb", "title": "Retake",
        "key": "Ein Retake kommt zusammen, mit Granaten und aus mehreren Richtungen. Einzelne CTs sterben einzeln.",
        "teach": [
            "Wenn die Ts geplantet haben, sammeln sich die CTs und nehmen den Spot gemeinsam zurück. Zeit ist knapp, aber "
            "wer einzeln losläuft, verliert die Duelle nacheinander.",
            "Zuerst schneiden Smokes Positionen ab, dann blenden Flashes die Ts, dann gehen alle gleichzeitig. Wer ein Kit "
            "hat, entschärft, die anderen schützen ihn.",
            "Rechne die Zeit: Ohne Kit brauchst du 10 Sekunden. Ist es zu spät, ist Saven besser als ein sinnloser Tod.",
        ],
        "example": [
            "Die Bombe liegt auf A. Ihr seid drei CTs.",
            "Ihr sammelt euch kurz an zwei Zugängen. Eine Smoke schneidet eine T-Position ab.",
            "Flash über den Spot, alle gehen gleichzeitig rein. Der mit Kit entschärft.",
        ],
        "mistakes": ["Einzeln losrennen.", "Ohne Granaten retaken.", "Zu spät losgehen, sodass die Zeit nicht reicht."],
        "drill": {"where": "Retake-Server",
                  "steps": ["Wartet vor jedem Retake kurz aufeinander.", "Werft vor dem Reingehen eine Flash."],
                  "done": "Ihr geht in den meisten Retakes gemeinsam rein."},
        "cue": "Zusammen rein", "ask": "Seid ihr beim Retake gleichzeitig gekommen?",
        "quiz": [
            {"id": "rt1", "q": "Ihr seid zwei CTs, die Bombe liegt. Was ist meist besser?",
             "options": ["Einzeln aus verschiedenen Richtungen losrennen, sobald man da ist", "Kurz sammeln und mit Granaten gemeinsam kommen", "Der mit Kit geht allein vor, der andere wartet"],
             "a": 1, "why": "Gemeinsam mit Granaten seid ihr stark. Einzeln verliert ihr nacheinander."},
        ],
        "lessons": ["outnumbered", "alone"], "links": [],
    },
    "defuse": {
        "area": "bomb", "title": "Entschärfen und Fake-Defuse",
        "key": "Rechne: Reicht die Zeit? Mit einem kurzen Fake-Defuse kannst du einen T aus der Deckung locken.",
        "teach": [
            "Ohne Kit dauert das Entschärfen 10 Sekunden, mit Kit 5. Die Bombe zündet 40 Sekunden nach dem Plant. "
            "Bricht man ab, beginnt der Vorgang beim nächsten Mal von vorne.",
            "Ein Fake-Defuse heißt: Du fängst an zu entschärfen und hörst sofort wieder auf. Der T hört das Geräusch und "
            "peekt. Du hast schon das Fadenkreuz dort, wo er kommt.",
            "Ist ein T in der Nähe, entschärfst du nur, wenn du Deckung oder einen Mitspieler hast, der dich schützt.",
        ],
        "example": [
            "Du bist allein gegen einen T, die Bombe läuft, du hast ein Kit.",
            "Du tippst kurz Entschärfen an und hörst auf.",
            "Der T peekt auf das Geräusch. Du triffst ihn und entschärfst dann in Ruhe.",
        ],
        "mistakes": ["Ohne Kit zu spät anfangen.", "Entschärfen, obwohl ein T frei auf dich schaut.", "Nicht wissen, wie viel Zeit noch ist."],
        "drill": {"where": "Retake-Server",
                  "steps": ["Nutz in einer 1-gegen-1-Lage einen kurzen Fake-Defuse.", "Merk dir, wie der Gegner reagiert."],
                  "done": "Du nutzt den Fake-Defuse bewusst."},
        "cue": "Zeit reicht?", "ask": "Reichte die Zeit noch, als du angefangen hast?",
        "quiz": [
            {"id": "df1", "q": "Wozu ist ein Fake-Defuse gut?",
             "options": ["Um den T zum Peeken zu bringen", "Um schneller zu entschärfen", "Um die Uhr der Bombe kurz anzuhalten"],
             "a": 0, "why": "Der T hört das Geräusch und peekt. Du wartest schon mit dem Fadenkreuz."},
        ],
        "lessons": ["outnumbered"], "links": [],
    },
    # --- Runden lesen ---------------------------------------------------------------------------------------
    "man_advantage": {
        "area": "round", "title": "Überzahl ausspielen",
        "key": "In Überzahl spielt ihr zusammen und tradet. Ein Vorteil geht meist durch einzelne, unnötige Duelle verloren.",
        "teach": [
            "Ein Spieler mehr ist ein großer Vorteil, aber nur, wenn ihr ihn nutzt. In Überzahl lohnt es sich, Duelle "
            "zu zweit zu nehmen und den Gegner einzeln zu isolieren.",
            "Viele Runden gehen verloren, weil ein Spieler in Überzahl allein einen Gegner sucht und stirbt. Danach ist "
            "es wieder ausgeglichen.",
            "Als T in Überzahl heißt das oft: planten und gemeinsam auf Zeit spielen. Als CT: zusammen retaken, nicht "
            "einzeln jagen.",
        ],
        "example": [
            "Ihr seid vier gegen zwei. Ein Gegner ist irgendwo auf der Map.",
            "Statt allein zu suchen, geht ihr zu zweit auf jeden Bereich.",
            "Der Gegner trifft immer auf zwei, und ihr gewinnt.",
        ],
        "mistakes": ["In Überzahl allein jagen.", "Nach einem Vorsprung leichtsinnig werden."],
        "drill": {"where": "Eigene Demos",
                  "steps": ["Such Runden, in denen ihr in Überzahl wart und verloren habt.", "Wo kam der erste unnötige Tod?"],
                  "done": "Du erkennst unnötige Duelle in Überzahl."},
        "cue": "Überzahl heißt zusammen", "ask": "Wart ihr in Überzahl und habt den Vorteil verspielt?",
        "quiz": [
            {"id": "ma1", "q": "Ihr seid vier gegen zwei. Was ist der häufigste Fehler?",
             "options": ["Zu langsam spielen", "Allein auf die Jagd gehen und sterben", "Zu viele Granaten werfen"],
             "a": 1, "why": "Einzelne Tode in Überzahl machen die Runde wieder ausgeglichen."},
        ],
        "lessons": ["alone", "outnumbered"], "links": ["stats"],
    },
    "clutch": {
        "area": "round", "title": "Clutch",
        "key": "Im Clutch nimmst du die Gegner einzeln, nutzt Zeit und Geräusche und bleibst ruhig.",
        "teach": [
            "Allein gegen mehrere gewinnst du nur, wenn du nie gegen zwei gleichzeitig kämpfst. Du wählst die Stelle, an "
            "der nur einer zu dir kommen kann.",
            "Zeit kann für oder gegen dich spielen. Als CT ohne Plant spielt die Zeit für dich. Nach einem Plant spielt "
            "sie gegen dich. Geräusche helfen dir, die Gegner zu orten, und ein Fake-Defuse kann einen locken.",
            "Ruhe ist der größte Vorteil. Atme aus, sammle die Infos, die dein Team dir gibt, und entscheide dann.",
        ],
        "example": [
            "Du bist als T allein gegen zwei, die Bombe ist geplantet.",
            "Du versteckst dich an einer Stelle mit Blick auf die Bombe, an der nur ein CT dich gleichzeitig sehen kann.",
            "Du hörst Entschärfen, peekst und tötest einen. Dann wechselst du die Position für den zweiten.",
        ],
        "mistakes": ["Gegen zwei gleichzeitig peeken.", "Hektisch werden und Geräusche machen.", "Die Uhr vergessen."],
        "drill": {"where": "Retake-Server",
                  "steps": ["Spiel jede 1-gegen-mehr-Lage mit einer Frage: Wo kann nur einer gleichzeitig zu mir kommen?"],
                  "done": "Du suchst im Clutch automatisch Einzelduelle."},
        "cue": "Einer nach dem anderen", "ask": "Hast du im Clutch die Gegner einzeln genommen?",
        "quiz": [
            {"id": "cl1", "q": "Du bist allein gegen zwei. Was suchst du?",
             "options": ["Eine Stelle, an der nur einer gleichzeitig kommen kann", "Eine offene Stelle mit Blick auf beide", "Den kürzesten Weg zu beiden"],
             "a": 0, "why": "Zwei gleichzeitig gewinnst du fast nie. Einzeln hast du eine echte Chance."},
            {"id": "cl2", "q": "Als CT ist noch nicht geplantet und die Uhr läuft. Für wen spielt die Zeit?",
             "options": ["Für die Ts", "Für dich als CT", "Für beide gleich"],
             "a": 1, "why": "Ohne Plant gewinnen die CTs, wenn die Zeit abläuft. Die Ts müssen kommen."},
        ],
        "lessons": ["outnumbered", "low_hp"], "links": ["stats"],
    },
    "low_hp_play": {
        "area": "round", "title": "Spielen mit wenig HP",
        "key": "Mit wenig HP bist du Info und Trade, nicht der erste Peek.",
        "teach": [
            "Mit wenig HP reicht dem Gegner ein Treffer, egal mit welcher Waffe. Deshalb nimmst du keine neuen Duelle, "
            "sondern gibst Infos, spielst hinter einem Mitspieler oder auf Zeit.",
            "Mit wenig HP kannst du auch Positionen spielen, die der Gegner nicht erwartet, weil er dich vorne vermutet.",
            "Sag deinem Team, wie viel HP du hast. Dann weiß es, dass es dich nicht als Ersten peeken lassen sollte.",
        ],
        "example": [
            "Du hast nach einem Duell nur noch wenig HP.",
            "Du callst: Ich bin bei 20.",
            "Dein Bruder peekt zuerst, du spielst den Trade hinter ihm.",
        ],
        "mistakes": ["Mit wenig HP einen neuen Peek suchen.", "Das Team nicht über die HP informieren."],
        "drill": {"where": "Retake-Server",
                  "steps": ["Spiel unter 50 HP nur noch Trades oder Infos.", "Sag die HP jedes Mal an."],
                  "done": "Du nimmst mit wenig HP keine ersten Duelle mehr."},
        "cue": "Info, nicht Duell", "ask": "Hast du mit wenig HP ein neues Duell gesucht?",
        "quiz": [
            {"id": "lh1", "q": "Du hast nur noch 15 HP. Was ist meist richtig?",
             "options": ["Den nächsten Peek nehmen", "Infos geben und hinter einem Mitspieler spielen", "Allein eine neue Position suchen und dort halten"],
             "a": 1, "why": "Mit 15 HP reicht jeder Treffer. Hinter einem Mitspieler bist du der Trade statt der erste Tote."},
        ],
        "lessons": ["low_hp"], "links": [],
    },
    "time": {
        "area": "round", "title": "Die Uhr lesen",
        "key": "Wer die Uhr im Blick hat, weiß, wer kommen muss. Wer kommen muss, ist im Nachteil.",
        "teach": [
            "Ohne Plant müssen die Ts kommen, bevor die Zeit abläuft. Nach dem Plant müssen die CTs zur Bombe. Wer kommen "
            "muss, kann nicht einfach warten.",
            "Das heißt: Als CT spät in der Runde ohne Plant musst du kein Duell suchen. Als T nach dem Plant auch nicht.",
            "Gegen Ende der Runde rechnest du: Reicht die Zeit noch für den Plant? Reicht sie für das Entschärfen?",
        ],
        "example": [
            "Es ist spät in der Runde, die Ts haben noch nicht geplantet.",
            "Du hältst als CT den Spot und wartest, statt zu peeken.",
            "Die Ts müssen kommen und laufen in dein Fadenkreuz.",
        ],
        "mistakes": ["Als CT spät in der Runde peeken, obwohl die Ts kommen müssen.", "Als T zu spät angreifen."],
        "drill": {"where": "Nächstes Match",
                  "steps": ["Schau bei jedem Duell kurz auf die Uhr und frag: Wer muss kommen?"],
                  "done": "Du weißt in jeder Lage, für wen die Zeit spielt."},
        "cue": "Wer muss kommen?", "ask": "Wer musste in dieser Lage kommen, und hast du das genutzt?",
        "quiz": [
            {"id": "ti1", "q": "Die Bombe ist geplantet. Wer muss kommen?",
             "options": ["Die Ts", "Die CTs", "Beide gleich"], "a": 1,
             "why": "Nach dem Plant läuft die Uhr gegen die CTs. Sie müssen zur Bombe."},
        ],
        "lessons": ["outnumbered"], "links": [],
    },
    # --- Rollen und Team -----------------------------------------------------------------------------------
    "roles": {
        "area": "team", "title": "Rollen im Team",
        "key": "Entry, Support, Lurker, AWPer, IGL: Jeder weiß, was seine Aufgabe in der Runde ist.",
        "teach": [
            "Der Entry geht als Erster auf den Spot und sucht das erste Duell. Der Support wirft Granaten für ihn und "
            "tradet. Der Lurker spielt abseits und fängt Rotationen ab. Der AWPer hält lange Linien. Der IGL sagt die "
            "Taktik an.",
            "Rollen helfen, weil niemand mehr raten muss. Wer weiß, dass er Support ist, hat seine Flash bereit, statt "
            "selbst als Erster zu peeken.",
            "In Premier mit zufälligen Mitspielern sind Rollen oft unklar. Zu zweit könnt ihr trotzdem feste Rollen haben: "
            "einer Entry, einer Support.",
        ],
        "example": [
            "Ihr macht ab: Dein Bruder ist Entry, du bist Support.",
            "Vor dem Angriff wirfst du eine Flash für ihn.",
            "Er peekt, du tradest, falls er stirbt.",
        ],
        "mistakes": ["Beide wollen Entry sein und peeken gleichzeitig ohne Granaten.", "Niemand übernimmt Granaten."],
        "drill": {"where": "Nächstes Match",
                  "steps": ["Legt eure Rollen zu zweit vor dem Match fest.", "Sprecht nach dem Match: Hat jeder seine Rolle gespielt?"],
                  "done": "Ihr habt feste Rollen und haltet euch daran."},
        "cue": "Meine Rolle", "ask": "Welche Rolle hattest du in dieser Runde, und hast du sie gespielt?",
        "quiz": [
            {"id": "rl1", "q": "Was ist die Aufgabe des Supports beim Angriff?",
             "options": ["Als Erster peeken", "Granaten für den Entry werfen und ihn traden", "Allein auf der anderen Seite spielen"],
             "a": 1, "why": "Der Support macht den Weg für den Entry frei und tradet ihn."},
        ],
        "lessons": ["alone", "utility"], "links": [],
    },
    "duo_play": {
        "area": "team", "title": "Zu zweit spielen",
        "key": "Zu zweit seid ihr ein kleines Team: zusammen peeken, zusammen traden, Calls nur für euch.",
        "teach": [
            "In Premier kennt ihr eure Mitspieler oft nicht. Aber zu zweit könnt ihr euch aufeinander verlassen. Wer "
            "zusammen spielt, tradet sich gegenseitig.",
            "Sprecht ab, auf welchen Positionen ihr auf welcher Map spielt, damit ihr nah beieinander seid. Auf T: dieselbe "
            "Seite der Map. Auf CT: benachbarte Positionen, von denen ihr euch helfen könnt.",
            "Nach dem Match: Eine gemeinsame kurze Runde aus der Demo ansehen, in der es nicht geklappt hat.",
        ],
        "example": [
            "Ihr macht vor dem Match ab: Auf T sind wir immer zusammen.",
            "Jede Runde geht ihr zu zweit auf denselben Bereich.",
            "Jeder Tod ist ein möglicher Trade.",
        ],
        "mistakes": ["Getrennt auf verschiedenen Seiten der Map spielen.", "Keine Absprachen vor dem Match."],
        "drill": {"where": "Nächstes Match",
                  "steps": ["Macht eine Duo-Absprache für jede Map: wo ihr auf T und CT spielt.", "Prüft nach dem Match in der App, ob ihr zusammen wart."],
                  "done": "Ihr spielt in den meisten Runden zusammen."},
        "cue": "Wir zwei zusammen", "ask": "Wart ihr in dieser Runde nah genug für einen Trade?",
        "quiz": [
            {"id": "du1", "q": "Was ist der größte Vorteil, wenn ihr zu zweit spielt?",
             "options": ["Ihr könnt euch gegenseitig traden und genau absprechen", "Ihr trefft in Premier auf schwächere Gegner", "Ihr müsst weniger callen"],
             "a": 0, "why": "Zwei, die sich kennen, können sich verlassen. Das ist in Premier ein großer Vorteil."},
        ],
        "lessons": ["alone"], "links": ["briefing"],
    },
    # --- Training und Kopf ---------------------------------------------------------------------------------
    "coach_review": {
        "area": "mind", "title": "Demos ansehen wie ein Coach",
        "key": "Ein Coach hält die Demo an und fragt: Was wusstest du, was hast du entschieden, was wäre besser?",
        "teach": [
            "Coaches schauen Demos nicht einfach durch. Sie halten an den Momenten an, in denen sich die Runde entschied, "
            "und fragen den Spieler, bevor sie selbst etwas sagen. So muss der Spieler die Lage selbst lesen.",
            "Die Fragen sind immer ähnlich: Was wusstest du in dem Moment? Was hast du gesehen oder gehört? Warum hast "
            "du so entschieden? Was machst du nächstes Mal? Genau so funktionieren die Szenen in deiner Session.",
            "Coaches arbeiten an einer Sache auf einmal. Wer zehn Fehler gleichzeitig korrigieren will, korrigiert keinen. "
            "Deshalb hat der Coach in der App immer ein Thema.",
        ],
        "example": [
            "Du schaust deine Demo und hältst an, als du stirbst.",
            "Du spulst drei Sekunden zurück. Was wusstest du? Wo war dein Mitspieler?",
            "Du sagst laut, was du anders machen würdest, bevor du weiterschaust.",
        ],
        "mistakes": ["Die ganze Demo in doppelter Geschwindigkeit durchschauen.", "Nur auf Kills achten statt auf Entscheidungen.",
                     "Zu viele Themen auf einmal."],
        "drill": {"where": "Eigene Demo, etwa 15 Minuten",
                  "steps": ["Wähle drei Runden, die ihr verloren habt.", "Halte jeweils vor dem ersten Tod an und beantworte die vier Fragen.",
                            "Schreib eine Sache auf, die du nächstes Mal anders machst."],
                  "done": "Du hast nach der Review eine einzige, klare Sache für das nächste Match."},
        "cue": "Anhalten, fragen", "ask": "Was war der Moment, in dem sich diese Runde entschied?",
        "quiz": [
            {"id": "cr1", "q": "Was macht ein Coach bei einer Demo-Review zuerst, wenn ein wichtiger Moment kommt?",
             "options": ["Er erklärt sofort, was falsch war", "Er hält an und fragt den Spieler, was er wusste und warum er so entschied", "Er zeigt zuerst, wie ein Pro die Runde gespielt hätte"],
             "a": 1, "why": "Wer selbst die Lage lesen muss, lernt mehr, als wer nur die Lösung hört."},
            {"id": "cr2", "q": "Wie viele Themen nimmt ein guter Coach in ein Match mit?",
             "options": ["Ein Thema", "Drei bis vier Themen", "Alle, die er sieht"],
             "a": 0, "why": "An einer Sache kann man sich im Spiel erinnern. An zehn nicht."},
        ],
        "lessons": [], "links": [],
    },
    "deliberate_practice": {
        "area": "mind", "title": "Gezielt üben",
        "key": "Gezielt üben heißt: eine Schwäche, eine klare Aufgabe, sofortige Rückmeldung, viele Wiederholungen.",
        "teach": [
            "Nur Matches spielen macht besser, aber langsam. Gezieltes Üben setzt an einer Schwäche an, hat ein klares "
            "Ziel, sagt dir sofort, ob es geklappt hat, und wiederholt es oft. Das ist die Idee des deliberate practice.",
            "In Studien erklärt die Menge an gezieltem Üben einen Teil der Unterschiede zwischen guten und weniger guten "
            "Spielern, bei Spielen etwa ein Viertel. Üben ist also wichtig, aber nicht alles.",
            "Die Übungen im Kurs und hier im CS-Wissen sind so gebaut: eine Aufgabe, ein Ziel, ein Zeichen, woran du "
            "merkst, dass es sitzt.",
        ],
        "example": [
            "Dein Thema ist Counter-Strafe.",
            "Statt nur Deathmatch zu spielen, machst du zehn Minuten Aim Botz mit genau dieser Aufgabe.",
            "Du zählst die Kopftreffer pro zwanzig Stopps und siehst, ob du besser wirst.",
        ],
        "mistakes": ["Ohne Ziel Deathmatch spielen.", "Nur das üben, was schon gut klappt.", "Zu lange üben, ohne Pause."],
        "drill": {"where": "Vor dem nächsten Match",
                  "steps": ["Nimm die Übung deiner aktuellen Lektion.", "Mach sie zehn Minuten mit einem klaren Ziel und zähl mit."],
                  "done": "Du hast für dein aktuelles Thema eine Zahl, die besser wird."},
        "cue": "Ein Ziel, mitzählen", "ask": "Was genau hast du heute geübt, und woran hast du gemerkt, ob es klappt?",
        "quiz": [
            {"id": "dp1", "q": "Was gehört zu gezieltem Üben?",
             "options": ["Eine klare Aufgabe und Rückmeldung, ob es geklappt hat", "Möglichst viele Matches ohne Plan", "Nur das, was schon gut klappt"],
             "a": 0, "why": "Ohne Aufgabe und Rückmeldung ist Üben nur Spielen."},
        ],
        "lessons": [], "links": [],
    },
    "tilt_focus": {
        "area": "mind", "title": "Ruhig bleiben",
        "key": "Nach zwei verlorenen Runden: ausatmen, abhaken, eine feste Aufgabe für die nächste Runde.",
        "teach": [
            "Tilt heißt, dass Ärger die Entscheidungen übernimmt. Man peekt schneller, spielt allein und vergisst den Plan. "
            "Das kann jedem passieren, aber man kann es bemerken und abfangen.",
            "Eine kurze Routine hilft: langsam ausatmen, abhaken, was du nicht kontrollieren konntest, und eine feste "
            "Aufgabe für die nächste Runde. Zum Beispiel: Wir zwei zusammen.",
            "Ob du nach Niederlagen anders spielst, zeigt dir der Tilt-Check der Session aus deinen eigenen Matches.",
        ],
        "example": [
            "Ihr verliert zwei Runden in Folge knapp.",
            "In der Kaufzeit atmest du zweimal langsam aus.",
            "Du sagst dir: Abgehakt. Nächste Runde: zusammen mit dem Bruder.",
        ],
        "mistakes": ["Über die letzte Runde schimpfen, während die nächste beginnt.", "Nach einer Niederlage allein alles lösen wollen."],
        "drill": {"where": "Nächstes Match",
                  "steps": ["Nimm die Reset-Routine aus der Session in deinen Plan.", "Nutze sie nach jeder zweiten verlorenen Runde in Folge."],
                  "done": "Die Routine läuft nach Niederlagen von selbst."},
        "cue": "Ausatmen, abhaken", "ask": "Hast du nach der verlorenen Runde anders gespielt als vorher?",
        "quiz": [
            {"id": "tf1", "q": "Was hilft nach zwei verlorenen Runden am meisten?",
             "options": ["Über die Mitspieler schimpfen", "Langsam ausatmen, abhaken, eine feste Aufgabe für die nächste Runde", "Aggressiver spielen, um das Momentum zurückzuholen"],
             "a": 1, "why": "Langsames Atmen senkt die Erregung. Eine feste Aufgabe lenkt den Kopf auf das Nächste."},
        ],
        "lessons": [], "links": [],
    },
    "warmup_routine": {
        "area": "mind", "title": "Aufwärmen vor dem Match",
        "key": "Ein festes Aufwärmen bringt Hand und Kopf ins Spiel: Aim kurz, Plan im Kopf, ein Gedanke für das Match.",
        "teach": [
            "Viele Spieler starten kalt ins Match und brauchen die ersten Runden, um reinzukommen. Ein kurzes Aufwärmen "
            "vorher kann das verkürzen.",
            "Ein gutes Aufwärmen hat zwei Teile: die Hand (etwas Deathmatch oder Aim Botz) und den Kopf (dein Plan, ein "
            "paar Entscheidungen aus früheren Szenen). Das Warm-up der App kümmert sich um den Kopf.",
            "Es lohnt sich, jedes Mal dasselbe zu machen. So wird es eine Routine, die dich ins Spiel bringt.",
        ],
        "example": [
            "Zehn Minuten vor dem Match: fünf Minuten Deathmatch mit Counter-Strafe.",
            "Danach das Warm-up in der App: Plan lesen, drei Szenen entscheiden, ein kurzer Wissens-Check.",
            "Dann ins Match mit deinem Schlüsselwort im Kopf.",
        ],
        "mistakes": ["Kalt ins Match starten.", "So lange aufwärmen, dass man schon müde ist."],
        "drill": {"where": "Vor jedem Match",
                  "steps": ["Fünf bis zehn Minuten Aim.", "Das Warm-up der App."],
                  "done": "Du wärmst vor jedem Match gleich auf."},
        "cue": "Hand und Kopf", "ask": "Wie waren deine ersten drei Runden, mit und ohne Aufwärmen?",
        "quiz": [
            {"id": "wr1", "q": "Was gehört zu einem guten Aufwärmen?",
             "options": ["Nur Aim", "Aim und den Plan im Kopf", "Möglichst lange Deathmatch, mindestens eine Stunde"],
             "a": 1, "why": "Hand und Kopf müssen ins Spiel. Das Warm-up der App kümmert sich um den Kopf."},
        ],
        "lessons": [], "links": [],
    },
}

# Kurs-Lektion -> passende Themen im CS-Wissen (aus TOPICS[...]["lessons"] abgeleitet, Reihenfolge wie in TOPICS)
def topics_for_lesson(lesson: str) -> list[str]:
    return [k for k, t in TOPICS.items() if lesson in (t.get("lessons") or [])]
