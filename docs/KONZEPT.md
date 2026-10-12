# CS2-Coach (cstaktik) - Konzept

Stand: 2026-10-12. Eigenständiges Tool, keine Erweiterung von Videclip.

Hinweis zur Herkunft: Das ursprüngliche, ausführlichere Konzept-Dokument (Chat vom 10.09.2026) liegt nicht mehr vor. Diese Fassung fasst die getroffenen Entscheidungen zusammen und enthält Teile des alten Konzepts, die aus dem Chat-Verlauf rekonstruiert wurden. Alles, was hier nicht steht, ist offen und wird nicht angenommen.

## 1. Ziel

Das Tool ersetzt einen Coach. Der Nutzer spielt mit seinem Bruder zusammen (Premier). Nach einem klar verlorenen Match wertet das Tool die eigene Demo aus, schreibt Positionsfehler und andere Fehler auf und gibt Tipps, wie man besser hätte spielen können.

Der Nutzer bedient das Tool am Handy. Demos kann er nur am PC herunterladen, Ergebnisse und Report will er am Handy nutzen.

## 2. Funktionen

Kernfunktion (Phase 1): Post-Match-Demo-Analyse der eigenen Matches.

Weitere gewünschte Funktionen:
- Automatische Strategie-Erstellung aus Pro-Demos (Demo-Analyse von Pro-Runden als primäre Quelle, Pipeline zuerst, kein Editor)
- Anzeige auf 2D-Karten
- Laufwege pro Spieler
- Pop-ups für Granaten-Lineups
- Pro-Team-Taktiken, zu Beginn die Standard-Taktiken jeder Map
- Live-Coaching per GSI (Game State Integration) als Wunschziel, zuletzt umzusetzen

Manuelle Strat-Erstellung ist nur ein optionales Zusatzfeature. Der Nutzer will keine Taktiken oder Lineups selbst einspielen.

## 3. Maps

Start: Mirage, Dust 2, Inferno.

## 4. Harte Regeln

- Nichts erfinden: keine Koordinaten, Timings, Lineups oder Statistiken ohne Quelle in den geparsten Demo-Daten. Fehlen Daten, klar melden.
- Taktik-Infos kurz und aussagekräftig.
- Keine In-Game-Screenshots mit Fadenkreuz-Referenz: Aus Demo-Daten lassen sich nur Kartenposition und Wurfart automatisch erzeugen.
- Live-Coaching nur über die offizielle GSI-Schnittstelle (nur eigene Spielerdaten). Keine Gegnerpositionen.
- Pro-Demos filtern auf das Fokus-Team (aktuell MOUZ, siehe `backend/data/demos_raw/README.md`). Runden des Gegner-Teams fließen nicht in Strat-Kandidaten ein.

## 5. Pro-Strat-Pipeline (aus dem alten Konzept)

- Parsen mit `awpy`
- Erfolgsfilter: nur Runden, die zum erfolgreichen Site-Take geführt haben
- Ähnliche Runden clustern, daraus Strat-Entwürfe ableiten
- Automatische Freigabe erst ab Mindestgröße des Clusters (damals: mindestens 8 ähnliche Runden)
- Lineup-Daten automatisch aus Granaten-Events
- Datenbasis damals eingeschätzt: 50 bis 100 Pro-Runden pro Map und Site

## 6. Strat-Card (aus dem alten Konzept)

Ziel: in unter 5 Sekunden lesbar, etwa in der Freeze-Time.
Felder: Name, Wann, Ziel, Rollen, Utility-Timing, Trigger, Fallback. Maximal 60 Wörter. Tag `five_stack_only` für Strats, die in Solo-Queue nicht funktionieren.

## 7. Technik

Backend: Python, `awpy` (getestet: 2.0.2 installiert sich). Ursprünglich geplant: FastAPI, React/TypeScript, PostgreSQL. Das ist nicht final entschieden.
Betrieb: lokal bzw. ohne eigenen Server (der frühere Videclip-Server existiert nicht mehr).
Report: mobil optimiertes HTML.

## 8. Phasen

1. Demo-Parser und Datenmodell
2. Post-Match-Report für eigene Premier-Demos (regelbasierte Fehlererkennung, nachvollziehbar, mit Beleg aus den Daten)
3. Pro-Strat-Pipeline für Mirage, Dust 2, Inferno
4. 2D-Karten, Laufwege, Lineup-Pop-ups
5. Live-Overlay per GSI

## 9. Offene Punkte

- Woher kommen die Demos? Der Nutzer kann sie nur am PC herunterladen. Eine Upload-Möglichkeit wird gebraucht. Ob Git LFS genutzt wird, ist offen (im Repo ist `.gitattributes` dafür vorhanden, aber noch keine `.dem` abgelegt).
- Fehlerregeln der Post-Match-Analyse müssen noch festgelegt werden.
- Entwicklung findet am Handy über Claude Code statt. Echte Demos stehen erst zur Verfügung, wenn der Nutzer Zugriff auf einen PC hat. Bis dahin Tests mit synthetischen Daten.
