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

Die Grenzwerte in ``measure`` entsprechen der Erkennung in rules/death_review.py, coach_voice.lesson_id und
config/rules.yaml (1 Unit = 2,54 cm, also 600 Units etwa 15 m, 1000 Units etwa 25 m, 80 Units/s etwa 2 m/s).
"""

STAGES = [
    {"key": "shoot", "title": "Schießen",
     "intro": ("Hier fängt alles an: Ein Schuss trifft nur, wenn du stehst und dein Fadenkreuz schon dort ist, wo der "
               "Kopf des Gegners auftaucht. Solange das nicht sitzt, hilft dir keine Taktik, weil du die Duelle am Ende "
               "trotzdem verlierst. Deshalb kümmern wir uns zuerst um diese zwei Grundlagen.")},
    {"key": "duel", "title": "Duelle",
     "intro": ("Wenn du sauber schießt, geht es um die Frage, wie du überhaupt in ein Duell kommst. Viele Duelle sind "
               "entschieden, bevor jemand abdrückt: durch die Stelle, an der du stehst, und die Art, wie du um eine "
               "Ecke kommst. In dieser Stufe lernst du, Duelle so anzunehmen, dass sie für dich günstig sind.")},
    {"key": "utility", "title": "Granaten",
     "intro": ("Mit Granaten machst du ein faires Duell unfair, und zwar zu deinen Gunsten. Diese Stufe kommt nach den "
               "Duellen, weil eine Flash nur dann etwas bringt, wenn du danach auch sauber peekst und triffst. Du lernst, "
               "deine eigenen Granaten zu nutzen und die des Gegners ins Leere laufen zu lassen.")},
    {"key": "team", "title": "Zusammenspiel",
     "intro": ("Ab jetzt spielst du nicht mehr nur für dein eigenes Duell, sondern für das deines Teams. CS ist ein "
               "Spiel, in dem fünf Spieler zusammen mehr erreichen als fünf Einzelkämpfer. Der wichtigste Baustein dafür "
               "ist der Trade, und genau darum geht es hier.")},
    {"key": "round", "title": "Runden lesen",
     "intro": ("Zum Schluss schaust du über das einzelne Duell hinaus auf die ganze Runde. Mit wenig HP oder in "
               "Unterzahl gelten andere Regeln als zu Rundenbeginn. Wer das erkennt, verschenkt keine Runden mehr, die "
               "noch zu retten gewesen wären.")},
]

# Reihenfolge innerhalb einer Stufe = Reihenfolge im Kurs
LESSONS: dict[str, dict] = {
    "moving_shot": {
        "stage": "shoot",
        "title": "Erst stoppen, dann schießen",
        "goal": "Du stoppst vor jedem Schuss mit einem Counter-Strafe und triffst dadurch auch aus der Bewegung heraus.",
        "what": ("In CS2 fliegen Kugeln aus der Bewegung nicht dorthin, wo dein Fadenkreuz zeigt, sondern streuen "
                 "stark. Erst wenn du fast stillstehst, ist deine Waffe wieder genau. Am schnellsten kommst du mit einem "
                 "Counter-Strafe zum Stehen: Du lässt die Bewegungstaste los und tippst kurz die Gegenrichtung an."),
        "why": ("Ein Gegner, der steht, trifft mit seinem ersten Schuss, während deine Kugeln aus dem Laufen daneben "
                "gehen. Du kannst also besser zielen als er und verlierst trotzdem. Mit sauberem Stoppen holst du dir "
                "genau diese Duelle zurück."),
        "spot": ("Es zählt immer dann, wenn du beim Peeken oder Laufen einen Gegner siehst und sofort schießen willst. "
                 "Wenn du im Match denkst, dass du eigentlich auf dem Kopf warst und trotzdem nicht getroffen hast, war "
                 "das meist ein Schuss aus der Bewegung."),
        "how": [
            "Bewege dich seitlich mit A oder D, denn dabei bist du schwer zu treffen und stoppst am schnellsten.",
            "Sobald du schießen willst, lass die Taste los und tippe kurz die Gegenrichtung an.",
            "Schieß im Moment des Stillstands ein bis drei Kugeln und lauf danach wieder los.",
            "Halte die linke Maustaste nie gedrückt, während du noch eine Bewegungstaste hältst.",
        ],
        "drill": {
            "name": "Counter-Strafe auf Aim Botz",
            "where": "Workshop-Map „Aim Botz – Training“, danach Deathmatch",
            "minutes": 10,
            "steps": [
                "Abonniere „Aim Botz – Training“ im Steam-Workshop und starte die Map über Workshop-Maps.",
                "Lauf vor einer Reihe Bots mit A und D hin und her, ohne zu schießen, bis sich der Rhythmus locker anfühlt.",
                "Bau jetzt bei jedem Richtungswechsel den Stopp ein: loslassen, Gegenrichtung antippen, ein Schuss auf den Kopf.",
                "Wechsle danach für fünf Minuten ins Deathmatch mit der Regel, nur zu schießen, wenn du stehst.",
            ],
            "done": ("Die Übung sitzt, wenn du auf Aim Botz zwanzig Stopps hintereinander machst und dabei mindestens "
                     "fünfzehn Kopftreffer landest, ohne an den Rhythmus denken zu müssen."),
        },
        "measure": ("Der Coach zählt deine Tode, bei denen dein letzter Schuss in den drei Sekunden davor aus der "
                    "Bewegung kam, schneller als etwa zwei Meter pro Sekunde."),
    },
    "crosshair": {
        "stage": "shoot",
        "title": "Fadenkreuz vorher auf den Spot",
        "goal": "Dein Fadenkreuz liegt auf Kopfhöhe an der nächsten Kante, bevor dort ein Gegner auftaucht.",
        "what": ("Gutes Crosshair-Placement heißt, dass dein Fadenkreuz beim Laufen und Halten immer dort wartet, wo "
                 "der nächste Gegner erscheinen kann. Dieses Vorzielen nennt man auch Pre-Aim. Es geht nicht um "
                 "schnelle Flicks, sondern darum, dass du gar nicht erst weit nachziehen musst."),
        "why": ("Jeder Grad, den du nachziehen musst, kostet dich Zeit, und diese Zeit nutzt der Gegner für seinen "
                "Schuss. Wenn dein Fadenkreuz schon auf seinem Kopf liegt, musst du nur noch klicken. Dadurch gewinnst "
                "du Duelle auch gegen Spieler, die schneller reagieren als du."),
        "spot": ("Achte darauf, wohin du schaust, während du läufst oder einen Winkel hältst. Zeigt dein Fadenkreuz "
                 "auf den Boden, auf eine Wand mitten im Raum oder in die Luft, wartet es an der falschen Stelle."),
        "how": [
            "Halte dein Fadenkreuz immer auf Kopfhöhe, also ungefähr auf der Höhe, auf der ein stehender Gegner seinen Kopf hat.",
            "Leg es an die Kante, hinter der als Nächstes ein Gegner auftauchen kann, und nicht in die Mitte des Raums.",
            "Wenn du um eine Ecke gehst, schiebst du das Fadenkreuz an der Kante entlang mit, statt es erst danach zu bewegen.",
        ],
        "drill": {
            "name": "Kopfhöhe auf deinen Laufwegen",
            "where": "Offline-Server deiner Map, danach Deathmatch",
            "minutes": 10,
            "steps": [
                "Starte deine Map offline und gib in der Konsole sv_cheats 1, bot_kick und mp_warmup_end ein.",
                "Lauf deine üblichen Wege für T und CT ab und bleib an jeder Ecke kurz stehen.",
                "Prüfe dort, ob dein Fadenkreuz auf Kopfhöhe an der Kante liegt, und korrigiere es, wenn nicht.",
                "Spiel danach fünf Minuten Deathmatch und achte nur darauf, dass dein Fadenkreuz beim Laufen nie zum Boden sinkt.",
            ],
            "done": ("Die Übung sitzt, wenn du im Deathmatch bei den meisten Kills nur noch ein kleines Stück "
                     "nachziehen musst, statt quer über den Bildschirm zu ziehen."),
        },
        "measure": ("Der Coach zählt verlorene Duelle, bei denen dein Fadenkreuz in dem Moment, als der Gegner zu "
                    "schießen begann, 20 Grad oder mehr neben seinem Kopf lag. Ab 60 Grad zählt der Tod unter „Nicht offen "
                    "in mehrere Winkel stehen“."),
    },
    "no_shot_close": {
        "stage": "duel",
        "title": "Ecke vorzielen statt reinlaufen",
        "goal": "Du gehst um nahe Ecken so, dass du einen Gegner dahinter sofort im Fadenkreuz hast.",
        "what": ("Ein Peek ist der Moment, in dem du aus der Deckung trittst und in einen Winkel schaust. Auf kurze "
                 "Distanz entscheidet dabei fast nur, ob dein Fadenkreuz schon an der richtigen Stelle ist. Statt in "
                 "eine Ecke hineinzulaufen, schneidest du sie Stück für Stück auf und prüfst einen Spot nach dem anderen."),
        "why": ("Wer eine Ecke hält, muss nur klicken, während du beim Reinlaufen erst suchen, zielen und klicken musst. "
                "Deshalb stirbst du oft, ohne einen einzigen Schuss abzugeben. Mit vorgezieltem Fadenkreuz drehst du "
                "dieses Verhältnis um."),
        "spot": ("Es zählt bei jeder Ecke, hinter der auf kurze Distanz ein Gegner sitzen kann, zum Beispiel an "
                 "Kisten, Türen oder Plant-Spots. Gerade beim Clearen eines Bombenplatzes stehen viele solcher Ecken "
                 "hintereinander."),
        "how": [
            "Bleib vor der Ecke stehen und überleg dir, wo dort ein Gegner sitzen kann.",
            "Leg dein Fadenkreuz auf Kopfhöhe genau an die Kante dieses Spots.",
            "Schneide die Ecke in kleinen Schritten seitlich auf, sodass immer nur ein Spot auf einmal sichtbar wird.",
            "Wenn eine Ecke zu viele Spots hat, prüf sie lieber mit einer Flash oder Molotov, statt hineinzulaufen.",
        ],
        "drill": {
            "name": "Prefire-Durchgang",
            "where": "Prefire-Map deiner Map aus dem Steam-Workshop, zum Beispiel von yprac",
            "minutes": 10,
            "steps": [
                "Such im Steam-Workshop nach „prefire“ und dem Namen deiner Map und abonniere eine Prefire-Map.",
                "Lauf den ersten Weg langsam ab und leg vor jedem Bot das Fadenkreuz auf Kopfhöhe an die Kante.",
                "Bewege dich erst, wenn das Fadenkreuz liegt, und schneide die Ecke dann seitlich auf.",
                "Stirbst du oder musst du weit nachziehen, starte den Abschnitt neu und mach ihn langsamer.",
            ],
            "done": ("Die Übung sitzt, wenn du einen ganzen Weg ohne Tod schaffst und jeder Bot schon in deinem "
                     "Fadenkreuz ist, wenn er sichtbar wird."),
        },
        "measure": ("Der Coach zählt Tode, vor denen du in den letzten drei Sekunden keinen Schuss abgegeben hast und "
                    "der Gegner näher als etwa 15 Meter war."),
    },
    "seen_first": {
        "stage": "duel",
        "title": "Sehen, bevor du gesehen wirst",
        "goal": "Du wählst deine Position so, dass du den Gegner siehst, bevor er dich sieht.",
        "what": ("Ein Duell beginnt in dem Moment, in dem einer den anderen sieht. Wer zuerst sieht, hat Zeit zum "
                 "Zielen, der andere muss erst reagieren. Ob du zuerst siehst, hängt vor allem davon ab, wo du stehst "
                 "und wie du in einen Winkel kommst."),
        "why": ("Diesen Zeitvorsprung holst du mit Aim kaum wieder auf, weil der Gegner schon zielt, während du ihn "
                "noch entdeckst. Wenn du dagegen zuerst siehst, gewinnst du auch gegen Spieler, die besser zielen als "
                "du. Die Position ist hier also wichtiger als die Hand."),
        "spot": ("Es zählt immer, wenn du einen Winkel hältst und auf einen Peek wartest. Wenn du oft stirbst, kaum "
                 "dass du den Gegner überhaupt gesehen hast, hat er dich meistens schon vorher im Blick gehabt."),
        "how": [
            "Kleb beim Halten nicht direkt an der Kante, sondern steh ein Stück dahinter, damit der Gegner weiter herauskommen muss.",
            "Nutze einen Off-Angle, also eine Stelle, an der der Gegner dich nicht erwartet und nicht vorzielt.",
            "Wechsle nach einem Kill oder einem Info-Call die Position, damit er dich nicht an derselben Stelle findet.",
            "Wenn du selbst peekst, nimm einen Winkel nach dem anderen, statt mehrere gleichzeitig aufzumachen.",
        ],
        "drill": {
            "name": "Sichtlinien von der Gegenseite",
            "where": "Offline-Server deiner Map mit einem Bot",
            "minutes": 10,
            "steps": [
                "Starte deine Map offline und gib sv_cheats 1, bot_kick, bot_add, bot_stop 1 und mp_warmup_end ein.",
                "Geh zu der Stelle, von der der Gegner normalerweise peekt, ziel auf deine übliche Halte-Position und gib bot_place ein.",
                "Lauf den Weg des Gegners langsam nach und merk dir, ab wann du den Bot siehst.",
                "Setz den Bot an eine Stelle weiter hinten oder auf einen Off-Angle und vergleiche, wie viel später er jetzt sichtbar wird.",
            ],
            "done": ("Die Übung sitzt, wenn du für zwei deiner Standard-Positionen je eine Stelle gefunden hast, an "
                     "der der Gegner deutlich weiter herauskommen muss, bevor er dich sieht."),
        },
        "measure": ("Der Coach zählt verlorene Duelle, in denen der Gegner dich laut Demo mindestens 0,3 Sekunden "
                    "früher gesehen hat als du ihn, oder in denen du ihn gar nicht gesehen hast."),
    },
    "angle": {
        "stage": "duel",
        "title": "Nicht offen in mehrere Winkel stehen",
        "goal": "Du stellst dich so hin, dass dich möglichst nur aus einer Richtung ein Gegner treffen kann.",
        "what": ("Ein Winkel ist jede Richtung, aus der ein Gegner auf dich schießen kann. Du kannst immer nur in eine "
                 "davon schauen. Stehst du an einer Stelle, die aus zwei oder drei Winkeln sichtbar ist, kommt der "
                 "Gegner früher oder später aus dem, den du gerade nicht prüfst."),
        "why": ("Ein Tod aus einem Winkel, in den du nicht geschaut hast, ist kein Aim-Problem, denn du hattest nie "
                "eine Chance. Wer nur einen Winkel offen hat, kann sein Fadenkreuz genau dort hinlegen. Damit wird aus "
                "einem Glücksspiel ein Duell, das du gewinnen kannst."),
        "spot": ("Es zählt, sobald du eine Position hältst oder auf einem Bombenplatz stehst. Frag dich dort, aus wie "
                 "vielen Richtungen dich ein Gegner sehen kann."),
        "how": [
            "Zähl beim Beziehen einer Position die Richtungen, aus denen ein Gegner kommen kann.",
            "Sind es mehr als eine, such eine Stelle mit Deckung im Rücken oder an der Seite, die einen davon schließt.",
            "Sprich mit deinem Team ab, wer welchen Winkel übernimmt, oder schließ einen mit einer Smoke oder Molotov.",
        ],
        "drill": {
            "name": "Winkel zählen",
            "where": "Offline-Server deiner Map, ohne Bots",
            "minutes": 10,
            "steps": [
                "Starte deine Map offline und gib sv_cheats 1, bot_kick und mp_warmup_end ein.",
                "Stell dich auf jede deiner drei Standard-Positionen und dreh dich einmal im Kreis.",
                "Zähl die Richtungen, aus denen dich ein Gegner sehen kann, und schreib sie dir auf.",
                "Such für jede Position mit mehr als einem Winkel eine Stelle in der Nähe, an der nur noch einer offen ist.",
            ],
            "done": ("Die Übung sitzt, wenn du für jede deiner Positionen eine Stelle kennst, an der nur ein Winkel "
                     "offen ist, oder weißt, wer oder was den zweiten abdeckt."),
        },
        "measure": ("Der Coach zählt Tode, bei denen dein Fadenkreuz beim Start des Duells 60 Grad oder mehr vom "
                    "Gegner weg zeigte, er also aus einer Richtung kam, in die du nicht geschaut hast."),
    },
    "no_shot_far": {
        "stage": "duel",
        "title": "Lange Linien nicht offen kreuzen",
        "goal": "Du kreuzt lange, offene Linien nur noch mit Smoke, mit Flash oder gar nicht.",
        "what": ("Eine lange Linie ist ein offener Bereich, den ein Gegner aus großer Entfernung beobachten kann, oft "
                 "mit einer AWP. Wer dort offen hinüberläuft, gibt ihm einen freien Schuss. Bevor du kreuzt, nimmst du "
                 "ihm die Sicht oder suchst dir einen anderen Weg."),
        "why": ("Der Gegner, der die Linie hält, hat sein Fadenkreuz schon dort und muss nur warten, bis du auftauchst. "
                "Du dagegen weißt nicht, wo er steht, und kommst deshalb meist gar nicht zum Schuss. Eine einzige Smoke "
                "nimmt ihm diesen Vorteil komplett."),
        "spot": ("Es zählt an jedem Übergang, an dem du ein großes offenes Stück überqueren musst, etwa eine Mitte, "
                 "einen langen Gang oder den Weg zwischen zwei Bombenplätzen."),
        "how": [
            "Frag dich vor jeder offenen Linie, ob dort jemand mit einem Gewehr oder einer AWP warten kann.",
            "Wenn ja, wirf zuerst eine Smoke, die ihm die Sicht nimmt, und lauf erst dann hinüber.",
            "Hast du keine Smoke, nimm einen anderen Weg oder warte, bis ein Mitspieler die Linie für dich zumacht.",
            "Musst du trotzdem kreuzen, lauf mit voller Geschwindigkeit hinüber und bleib nicht in der Mitte stehen.",
        ],
        "drill": {
            "name": "Zwei Smokes für deine Wege",
            "where": "Offline-Server deiner Map",
            "minutes": 10,
            "steps": [
                "Such dir die zwei Linien deiner Map aus, an denen du am häufigsten ohne Gegenwehr stirbst.",
                "Starte die Map offline und gib sv_cheats 1, sv_infinite_ammo 1, mp_buy_anywhere 1, mp_buytime 9999 und sv_grenade_trajectory_prac_pipreview 1 ein.",
                "Lern für jede Linie eine Smoke, die sie zumacht, zum Beispiel aus einem Lineup-Video oder der Lineups-Seite der App.",
                "Wirf jede Smoke so oft, bis sie fünfmal hintereinander an derselben Stelle landet.",
            ],
            "done": "Die Übung sitzt, wenn beide Smokes fünfmal in Folge sitzen und du sie im nächsten Match wirklich benutzt.",
        },
        "measure": ("Der Coach zählt Tode, vor denen du in den letzten drei Sekunden keinen Schuss abgegeben hast und "
                    "der Gegner 15 Meter oder weiter entfernt war."),
    },
    "moving": {
        "stage": "duel",
        "title": "Nicht laufend in den Winkel",
        "goal": "Du kommst kontrolliert und stehend in einen Winkel statt mitten im Laufen.",
        "what": ("Wer mit voller Geschwindigkeit in einen gehaltenen Winkel läuft, ist für den Gegner ein leichtes Ziel "
                 "und kann selbst nicht genau schießen. Besser ist es, vor dem Winkel kurz zu stoppen und ihn erst mit "
                 "einem Jiggle-Peek zu prüfen. Dabei trittst du nur kurz heraus und sofort wieder zurück."),
        "why": ("Ein kurzer Jiggle-Peek verrät dir, ob dort jemand steht, ohne dass du dich festlegen musst. Weißt du, "
                "wo der Gegner ist, kannst du mit vorgezieltem Fadenkreuz und stehend in das Duell gehen. Das gewinnt "
                "dir viele Duelle, die du sonst im Laufen verloren hättest."),
        "spot": ("Es zählt an jedem Winkel, den ein Gegner halten kann, vor allem beim Clearen eines Platzes und beim "
                 "Vorlaufen nach einem Kill."),
        "how": [
            "Bremse vor dem Winkel ab, statt mit voller Geschwindigkeit hineinzulaufen.",
            "Mach einen kurzen Jiggle-Peek, also kurz raus und sofort zurück, um zu sehen, ob dort jemand steht.",
            "Geh erst dann richtig hinein und stopp mit einem Counter-Strafe, bevor du schießt.",
        ],
        "drill": {
            "name": "Jiggle-Peek gegen Bots",
            "where": "Offline-Server deiner Map mit Bots",
            "minutes": 10,
            "steps": [
                "Starte deine Map offline und gib sv_cheats 1, bot_kick, bot_add, bot_add, bot_add, bot_stop 1 und mp_warmup_end ein.",
                "Setz die Bots mit bot_place hinter drei verschiedene Ecken, an denen du oft vorbeiläufst.",
                "Geh an jede Ecke heran, mach zuerst einen Jiggle-Peek und merk dir, wo der Bot steht.",
                "Peek danach richtig, stopp vor dem Schuss und triff den Bot mit dem ersten Schuss.",
            ],
            "done": ("Die Übung sitzt, wenn du an allen drei Ecken zuerst jigglest und den Bot dann stehend mit dem "
                     "ersten Schuss triffst."),
        },
        "measure": ("Der Coach zählt Tode, bei denen du im Moment des Todes schneller als etwa drei Meter pro Sekunde "
                    "unterwegs warst. Das misst er nur, wenn die Demo keine Schussdaten enthält; sonst zählt die Lektion "
                    "„Erst stoppen, dann schießen“."),
    },
    "utility": {
        "stage": "utility",
        "title": "Erst Utility, dann Duell",
        "goal": "Du wirfst vor einem geplanten Duell deine Flash oder Molotov, statt mit ihr in der Tasche zu sterben.",
        "what": ("Utility ist der Sammelbegriff für deine Granaten. Eine Flash blendet den Gegner, damit du ihn peeken "
                 "kannst, und eine Molotov zwingt ihn aus einer Ecke heraus. Beides wirkt nur, wenn du es vor dem Duell "
                 "wirfst und nicht erst, wenn es schon zu spät ist."),
        "why": ("Wer mit einer Flash in der Tasche stirbt, hat für einen Vorteil bezahlt und ihn nie benutzt. Mit "
                "Granate gewinnst du ein Duell, das ohne sie offen gewesen wäre. Smoke und HE darfst du oft aufheben, "
                "Flash und Molotov sind aber genau für diesen Moment da."),
        "spot": ("Es zählt immer dann, wenn du weißt oder ahnst, wo ein Gegner steht, und gleich in ein Duell gehst. "
                 "Hast du in diesem Moment eine Flash oder Molotov dabei, gehört sie zuerst in den Winkel."),
        "how": [
            "Überleg dir vor jedem geplanten Duell, ob eine Flash oder Molotov es leichter macht.",
            "Wirf eine Pop-Flash, also eine Flash, die direkt über der Kante explodiert, sodass der Gegner kaum Zeit zum Wegdrehen hat.",
            "Peek sofort, nachdem die Flash explodiert ist, solange der Gegner noch geblendet ist.",
            "Nutze eine Molotov, um einen engen Spot zu räumen, statt dort hineinzulaufen.",
        ],
        "drill": {
            "name": "Eine Pop-Flash pro Position",
            "where": "Offline-Server deiner Map",
            "minutes": 10,
            "steps": [
                "Starte deine Map offline und gib sv_cheats 1, sv_infinite_ammo 1, mp_buy_anywhere 1 und mp_buytime 9999 ein.",
                "Wähle zwei Stellen, an denen du oft in ein Duell gehst.",
                "Lern für jede Stelle eine Flash, die du selbst werfen und sofort danach peeken kannst.",
                "Üb den Ablauf als Ganzes: werfen, kurz warten, bis sie explodiert, dann peeken.",
            ],
            "done": ("Die Übung sitzt, wenn beide Flashes fünfmal hintereinander direkt über der Kante explodieren und "
                     "du ohne Zögern hinterherpeekst."),
        },
        "measure": ("Der Coach zählt Tode, bei denen du noch eine Flash oder Molotov im Inventar hattest. Smokes und HE "
                    "zählen nicht, weil es oft richtig ist, sie aufzuheben. Fehlt das Inventar in der Demo, zählt stattdessen "
                    "ein erstes Duell der Runde, vor dem du gar keine Granate geworfen hast."),
    },
    "blind": {
        "stage": "utility",
        "title": "Bei Flash sofort wegdrehen",
        "goal": "Du drehst dich bei einer gegnerischen Flash sofort weg und gehst hinter Deckung.",
        "what": ("Eine Flash blendet dich am stärksten, wenn du direkt in sie hineinschaust. Drehst du dich rechtzeitig "
                 "weg, sodass sie hinter dir explodiert, bist du nur kurz oder gar nicht geblendet. Wichtig ist, dass "
                 "du dabei auch einen Schritt aus dem Winkel herausgehst."),
        "why": ("Wer geblendet im Winkel stehen bleibt, ist für den Gegner ein geschenkter Kill. Wer dagegen wegdreht "
                "und zurückgeht, überlebt und kann danach den peekenden Gegner bekämpfen oder traden lassen. So wird die "
                "Flash des Gegners zu einer verschwendeten Granate."),
        "spot": ("Es zählt, sobald du das Geräusch einer geworfenen oder aufprallenden Flash hörst oder sie über eine "
                 "Kante fliegen siehst. Gerade beim Halten eines Platzes ist das oft der Moment kurz vor einem Angriff."),
        "how": [
            "Hör auf die Flash: Sobald du sie fliegen siehst oder aufprallen hörst, drehst du dich weg.",
            "Dreh dich so weit, dass die Flash hinter dir explodiert, und geh gleichzeitig hinter Deckung.",
            "Dreh dich erst zurück, wenn sie explodiert ist, und peek dann wieder mit vorgezieltem Fadenkreuz.",
        ],
        "drill": {
            "name": "Flash-Reflex",
            "where": "Offline-Server deiner Map",
            "minutes": 5,
            "steps": [
                "Starte deine Map offline und gib sv_cheats 1, sv_infinite_ammo 1, mp_buy_anywhere 1 und mp_buytime 9999 ein.",
                "Wirf eine Flash hoch gegen eine Wand, sodass sie zurück in dein Blickfeld fliegt.",
                "Dreh dich weg, sobald du sie aufprallen hörst, und mach einen Schritt zur Seite.",
                "Wiederhole das, bis die Bewegung ohne Nachdenken kommt.",
            ],
            "done": "Die Übung sitzt, wenn du zehnmal hintereinander gar nicht oder nur ganz kurz geblendet wirst.",
        },
        "measure": ("Der Coach zählt Tode, bei denen dich in den drei Sekunden davor eine gegnerische Flash mindestens "
                    "eine halbe Sekunde geblendet hat und die Blendung beim Start des Duells noch wirkte."),
    },
    "alone": {
        "stage": "team",
        "title": "Nicht ohne Trade-Partner peeken",
        "goal": "Du gehst nur in Duelle, in denen ein Mitspieler nah genug ist, um dich zu traden.",
        "what": ("Ein Trade bedeutet, dass ein Mitspieler den Gegner tötet, der dich gerade getötet hat, und zwar so "
                 "schnell, dass der Gegner nicht wieder in Deckung kommt. Dafür muss er nah bei dir sein, etwa einen "
                 "Körper hinter dir oder höchstens zwei Sekunden entfernt. Steht niemand in dieser Reichweite, stirbst du "
                 "ohne Gegenleistung."),
        "why": ("Ein getradeter Tod kostet dein Team nichts, weil der Gegner auch einen Spieler verliert. Ein Tod ohne "
                "Trade dagegen bringt euch in Unterzahl. Teams, die ihre Tode zuverlässig traden, gewinnen deutlich mehr "
                "Runden, auch ohne besseres Aim."),
        "spot": ("Es zählt vor jedem Peek, vor allem beim Angreifen eines Platzes und beim Vorstoßen auf der CT-Seite. "
                 "Wenn du dich umdrehst und keinen Mitspieler in der Nähe siehst, bist du gerade allein."),
        "how": [
            "Schau vor dem Peek, wo dein nächster Mitspieler steht, und ob er dich in zwei Sekunden erreichen kann.",
            "Sag deinen Peek kurz an, zum Beispiel „ich peeke jetzt Banane“, damit dein Mitspieler bereit ist.",
            "Lauf als Zweiter mit etwa einem Körper Abstand hinter dem Ersten, damit du sofort nachziehen kannst.",
            "Ist niemand in der Nähe, halt lieber deine Position und sammle Info, statt allein zu peeken.",
        ],
        "drill": {
            "name": "Peek nur zu zweit",
            "where": "Wingman mit einem Freund oder Retake-Community-Server",
            "minutes": 15,
            "steps": [
                "Spiel Wingman mit einem Freund oder geh auf einen Retake-Server aus dem Community-Server-Browser.",
                "Vereinbart die Regel, dass keiner peekt, ohne dass der andere direkt dahinter steht.",
                "Der Erste peekt, der Zweite zieht sofort nach, sobald der Erste stirbt oder den Gegner trifft.",
                "Sprecht nach jeder Runde kurz darüber, ob ein Trade möglich gewesen wäre.",
            ],
            "done": "Die Übung sitzt, wenn ihr zehn Runden hintereinander keinen einzigen Peek allein gemacht habt.",
        },
        "measure": ("Der Coach zählt Tode, bei denen dein nächster Mitspieler mehr als etwa 25 Meter entfernt war und "
                    "dein Gegner in den drei Sekunden danach nicht getötet wurde."),
    },
    "low_hp": {
        "stage": "round",
        "title": "Mit wenig HP kein neues Duell",
        "goal": "Mit wenig HP suchst du kein neues Duell, sondern spielst für Info und den Trade deiner Mitspieler.",
        "what": ("Mit weniger als der Hälfte deiner HP reicht dem Gegner oft ein einziger Treffer, egal mit welcher "
                 "Waffe. Dein Wert für das Team liegt dann nicht mehr im nächsten Duell. Er liegt in der Info, die du "
                 "gibst, und darin, dass du am Leben bleibst."),
        "why": ("Wer mit wenig HP ein neues Duell sucht, verliert es fast immer und schenkt dem Gegner einen Kill. "
                "Bleibst du dagegen hinten und gibst Info, kann dein Team mit vollem Leben in die Duelle gehen. Und später "
                "in der Runde bist du noch da, wenn dein Team jeden Spieler braucht."),
        "spot": ("Es zählt nach jedem Duell, in dem du getroffen wurdest, und nach Schaden durch Granaten. Schau nach "
                 "einem Schusswechsel kurz auf deine HP, bevor du weiterspielst."),
        "how": [
            "Schau nach jedem Duell oder jeder Granate auf deine HP.",
            "Unter 50 HP fällst du einen Schritt zurück in Deckung und sagst an, wo der Gegner ist.",
            "Spiel ab jetzt auf den Trade: Lass einen Mitspieler mit vollem Leben vorgehen und zieh hinter ihm nach.",
        ],
        "drill": {
            "name": "Wenig-HP-Runden",
            "where": "Retake-Community-Server",
            "minutes": 10,
            "steps": [
                "Geh auf einen Retake-Server aus dem Community-Server-Browser und spiel zehn Runden.",
                "Sobald du unter 50 HP fällst, gehst du zurück in Deckung und callst nur noch, wo die Gegner sind.",
                "Du gehst erst wieder ins Duell, wenn ein Mitspieler direkt neben dir ist oder ihr gemeinsam reingeht.",
            ],
            "done": "Die Übung sitzt, wenn du in zehn Runden kein einziges Mal unter 50 HP allein ein neues Duell gesucht hast.",
        },
        "measure": ("Der Coach zählt Tode in einem Duell, in das du mit weniger als 50 HP gegangen bist. Das erste "
                    "Duell der Runde zählt dabei nicht."),
    },
    "outnumbered": {
        "stage": "round",
        "title": "In Unterzahl zusammenbleiben",
        "goal": "In Unterzahl spielst du mit deinen Mitspielern zusammen oder auf Zeit, statt allein Duelle zu suchen.",
        "what": ("Unterzahl heißt, dass dein Team in der Runde mehr Spieler verloren hat als der Gegner. Jetzt hat er "
                 "mehr Leute, mehr Waffen und mehr Möglichkeiten, dich in ein Kreuzfeuer zu nehmen. Einzelduelle zu "
                 "suchen, macht die Lage dann fast immer schlimmer."),
        "why": ("Allein triffst du in Unterzahl oft auf zwei Gegner gleichzeitig, und dieses Duell ist kaum zu gewinnen. "
                "Zusammen mit einem Mitspieler könnt ihr euch gegenseitig traden und die Zahlen wieder ausgleichen. Als "
                "CT kann außerdem die Zeit für euch arbeiten, weil der Gegner die Bombe legen muss."),
        "spot": ("Es zählt, sobald auf der Anzeige oben mehr Gegner als Mitspieler leben. Schau nach jedem Tod eines "
                 "Mitspielers kurz auf diese Anzeige."),
        "how": [
            "Schau nach jedem Tod auf die Anzeige oben und prüf, ob ihr in Unterzahl seid.",
            "Geh in Unterzahl zum nächsten Mitspieler und spielt gemeinsam auf einen Spot, statt getrennt zu suchen.",
            "Als CT lass die Zeit für dich laufen und zwinge die Terroristen, zu dir zu kommen.",
            "Als T nutzt ihr eure übrige Utility zusammen, bevor ihr gemeinsam auf einen Platz geht.",
        ],
        "drill": {
            "name": "Unterzahl-Runden nachspielen",
            "where": "Deine letzte Demo, danach Retake-Community-Server",
            "minutes": 15,
            "steps": [
                "Öffne deine letzte Demo und such drei Runden, in denen ihr in Unterzahl geraten seid.",
                "Schau dir an, wo dein nächster Mitspieler war und ob ihr hättet zusammenspielen können.",
                "Geh danach auf einen Retake-Server und lauf in jeder Unterzahl-Situation sofort zum nächsten Mitspieler.",
                "Geht gemeinsam auf einen Spot und sucht keine getrennten Duelle.",
            ],
            "done": "Die Übung sitzt, wenn du auf dem Retake-Server zehn Unterzahl-Situationen ohne ein einziges Solo-Duell gespielt hast.",
        },
        "measure": ("Der Coach zählt Tode, bei denen ihr in Unterzahl wart und diese Unterzahl erst während der Runde "
                    "entstanden ist. Das erste Duell der Runde zählt nicht."),
    },
}


def path() -> list[str]:
    """Lektionen in Kursreihenfolge (Stufe für Stufe)."""
    order = [s["key"] for s in STAGES]
    return sorted(LESSONS, key=lambda k: (order.index(LESSONS[k]["stage"]), list(LESSONS).index(k)))
