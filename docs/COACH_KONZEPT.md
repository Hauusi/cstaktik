# Vom Analyse-Tool zum Coach – Konzept

Stand: 2026-10-12. Grundlage: aktueller Stand des Tools (Report, Replay, Tod-Analyse, Fortschritt).

## 1. Ehrliche Bestandsaufnahme

Was das Tool heute ist: ein **Fehler-Detektor mit Replay**. Es findet Symptome (Tod ohne Trade,
ungenutzte Utility, Economy) und zeigt sie einzeln.

Was ein Coach anders macht:

| Coach | Tool heute |
|---|---|
| Nennt die 1–2 **Ursachen**, die das Match gekostet haben | listet 10–30 Symptome gleichwertig |
| Sagt, **was es gekostet hat** (Runden) | keine Gewichtung nach Wirkung |
| Zeigt, **was stattdessen** richtig gewesen wäre | Standardtipp ohne Alternative |
| Sieht **Muster über Wochen** und Gewohnheiten | Verlauf erst angefangen |
| Arbeitet am **Duo** (ihr zwei als Einheit) | bewertet Spieler einzeln |
| Trennt **Entscheidung** und **Mechanik** | nur Entscheidungen/Positionen |
| Gibt **Hausaufgaben** und prüft sie beim nächsten Mal | Hausaufgaben ohne Kontrolle |
| **Briefing vor dem Match** | nichts vor dem Spiel |

Kernproblem: zu viel Information, zu wenig Urteil. Ein Coach reduziert.

## 2. Der rote Faden (Coaching-Kreislauf)

```
Match verloren → Upload → DEBRIEF (30 s Urteil) → 3 SCHLÜSSELMOMENTE im Replay
      ↑                                                     ↓
 BRIEFING vor dem nächsten Match ← TRAINING ← 1–3 FOKUS-ZIELE (messbar)
      ↓
 nächstes Match → ZIEL-CHECK automatisch → neue Ziele
```

Jede Seite der App gehört zu genau einem Schritt dieses Kreislaufs. Alles andere
(Detailbefunde, Statistik) ist "Mehr anzeigen".

## 3. Was dafür gebaut werden muss

### A. Diagnose statt Liste (größter Hebel)

1. **Runden-Wirkung**: Jeder Fehler bekommt einen Preis. Beispiel: Fokus-Spieler stirbt als
   Erster ungetradet und die Runde geht verloren → zählt als "kostete Runde". Ergebnis:
   "Opening-Tode ohne Trade: 5 Runden verloren".
2. **Vorteil verspielt**: Runden, die in Überzahl (z. B. 4v2) verloren gingen. Aus Kill-Reihenfolge
   exakt bestimmbar. Für Coaches einer der wichtigsten Punkte.
3. **Ursachen-Bündelung**: Symptome auf wenige Ursachen abbilden (z. B. Allein + Opening + ohne
   Utility → "Ihr spielt die Map getrennt und trocken").
4. **30-Sekunden-Urteil**: "Verloren wegen: 1) … (x Runden), 2) … (y Runden). Gut: …"
5. **Schlüsselmomente**: Coach-Tour nur über die 3–5 teuersten Momente, nicht alle Fehler.

### B. Duo-Coaching (ihr zwei)

- Abstand zwischen euch pro Runde, gegenseitige Trades, wer stirbt zuerst, getrennte Sites.
- Ergebnis z. B. "In 14 von 21 Runden wart ihr über 1500 Units getrennt; zusammen habt ihr 4 von 5
  dieser Runden gewonnen, getrennt 3 von 16." (alles aus Positionen und Rundenergebnis)

### C. Utility-Wirkung

- **Team-Flashes**: `player_blind` mit Werfer = Mitspieler. Exakt messbar.
- Gegner geblendet (Dauer, Anzahl), HE-/Molotov-Schaden, Smokes vor Execute vs. zu spät.
- Ergebnis: "Deine Flashes: 6 geworfen, 2 Gegner geblendet, 3 Mitspieler geblendet."

### D. Mechanik aus der Demo

- **Schießen in Bewegung**: Geschwindigkeit beim Schuss (`weapon_fire` + Velocity-Props).
  Schwelle muss kalibriert werden, nicht raten.
- **Trefferquote / Spray**: Schüsse vs. Treffer pro Duell.
- **Reaktion**: Zeit vom ersten erlittenen Schaden bis zum eigenen ersten Schuss.
- **Peek-Art**: rund um jeden Tod Positionen in voller Tickrate parsen (statt 4/s) → weiter Peek,
  Jiggle, gehalten.
- **Crosshair-Placement / Sichtlinien**: braucht Kartengeometrie (awpy-Visibility). Bezugsquelle
  noch zu prüfen (awpy-data Releases). Ohne Geometrie nicht seriös machbar.

### E. "Was stattdessen" – Referenz

1. **Eigene Referenz zuerst**: eure gewonnenen Runden auf derselben Map/Seite/Site als Vorbild
   ("Runde 7 habt ihr B mit 2 Spielern in Bench/Van gehalten und gewonnen").
2. **Pro-Referenz** (alte Phase 3): Standard-Setups und Lineups aus Pro-Demos. Erst damit kann der
   Coach sagen, wo man hätte stehen sollen.

### F. Lern-Loop

- **Fokus-Ziele (max. 3)** automatisch aus der Diagnose, mit Messwert und Ziel
  ("Opening-Tode ungetradet: 5 → ≤ 2").
- **Training** passend zum Ziel (Deathmatch-Fokus, Prefire-Maps, Utility-Lineups lernen).
  Konkrete Workshop-Maps erst nach Prüfung nennen, nicht erfinden.
- **Ziel-Check** beim nächsten Upload automatisch: erreicht / nicht erreicht.
- **Briefing vor dem Match** pro Map: "Mirage CT: 6x in Connector gestorben. Heute: Jungle mit
  Bruder halten." 20 Sekunden Lesezeit, am Handy vor dem Queue.

### G. Bedienbarkeit (App-Struktur)

1. **Start = Coach**: aktuelle Fokus-Ziele, letztes Urteil, Upload-Knopf.
2. **Debrief**: Urteil → Schlüsselmomente → (aufklappbar) alle Details.
3. **Training**: Ziele + Übungen.
4. **Briefing**: Map wählen → persönliche Hinweise.
5. **Fortschritt**: Ziele und Trends.

## 4. Grenzen (ehrlich)

- Kein Voice/Kommunikation, keine Absichten. Ein Coach fragt "warum hast du das gemacht?" – das
  Tool kann nur zeigen, was passiert ist.
- 3 Randoms im Team: Team-Taktik nur begrenzt coachbar, Fokus auf euch zwei.
- Bewertungen ("gut/schlecht") bleiben Heuristiken und müssen an echten Demos kalibriert werden.
- Pro-Referenz braucht Pro-Demos (manueller Download) und die Pipeline aus Phase 3.

## 5. Reihenfolge (Vorschlag)

1. Diagnose + Urteil + Schlüsselmomente + Duo + Team-Flashes (nur bestehende Daten, größter Effekt)
2. Lern-Loop: Ziele, Ziel-Check, Briefing vor dem Match, neue Startseite
3. Mechanik (Schüsse, Reaktion, Peek-Art)
4. Referenz: eigene Siegrunden, danach Pro-Pipeline
