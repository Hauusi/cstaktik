# cstaktik – CS2-Coach (Phase 1: Post-Match-Analyse)

Eigene CS2-Premier-Demo (`.dem` oder `.dem.bz2`, wird automatisch entpackt) hochladen → mobiler HTML-Report mit Fehlern pro Runde,
Beleg (Runde, Tick, Rohwerte) und einem kurzen Tipp. Alle Werte stammen aus der Demo;
fehlt etwas, steht es im Report unter „Datenlage“.

## Installation (PC, einmalig)

```bash
cd backend
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
awpy get maps                   # optional: Radarbilder + Kalibrierung (siehe "Kartenbilder")
cp cstaktik/config/players.example.yaml cstaktik/config/players.yaml
```

In `players.yaml` die SteamID64 von dir und deinem Bruder eintragen. Die IDs einer Demo
listet `cstaktik players <demo.dem>`.

## Nutzung

**Web (Upload am PC, Report am Handy):**

```bash
cstaktik serve                  # lauscht auf 0.0.0.0:8000
```

Am PC `http://localhost:8000` öffnen, Demo hochladen. Am Handy (gleiches WLAN)
`http://<PC-IP>:8000` öffnen → Liste der Reports.

**CLI:**

```bash
cstaktik analyze match.dem                          # Fokus aus players.yaml
cstaktik analyze match.dem --me 7656... --me 7656...
```

Report landet in `data/reports/<name>.html` (eine Datei, ohne externe Abhängigkeiten,
kann auch direkt aufs Handy geschickt werden). Geparste Demos werden als JSON in
`data/cache/` gecacht. Demos, Reports und Cache sind per `.gitignore` ausgeschlossen.

## Report und 2D-Replay

Pro Runde: Replay aller 10 Spieler (Positionen 4x pro Sekunde aus der Demo, interpoliert),
Blickrichtung, offizielles Waffen-Icon (Killfeed-Silhouette) in Blickrichtung (aus `active_weapon_name`; Icons lädt der Server aus github.com/Juknum/counter-strike-icons nach `data/icons/`, Rechte Valve; Vorab: `cstaktik icons`; unbekannte Waffe: einfache Form), Schüsse als Leuchtspur (Treffer: Linie zum
Getroffenen mit Schaden), Bombe, Killfeed. Granaten mit Wurfbahn (Projektil-Positionen aus der Demo);
Smoke/Molotov mit Ring und Sekunden für die Restdauer (Detonation bis Ablauf laut Demo-Events),
Flash/HE als kurzer Effekt beim Zünden. Die Größe der Smoke-/Molotov-Fläche ist nur Darstellung
(`report.*_draw_radius_units` in rules.yaml). Die Timeline markiert Tode und Befunde.
Beim Abspielen hält das Replay an jedem Befund an und zeigt den Tipp; der Todesort pulsiert.
Steuerung: Play, Fehler vor/zurück, Tempo (0.5x–4x), Karte mit zwei Fingern zoomen und
verschieben (Doppeltipp = zurück, am PC Mausrad), "Folgen" hält die Fokus-Spieler im Bild,
Spur (3 s oder ganze Runde). Direktlink auf eine Runde: `report.html#r12`.

## Coach-Funktionen

- **Vorbild aus euren Siegrunden** (`reference.py`): zu jedem Tod, wo derselbe Spieler auf
  derselben Seite zur selben Rundenzeit (5-s-Raster) in GEWONNENEN Runden stand, aus diesem
  Match und dem Verlauf derselben Map. Im Replay als grüner Geist "Sieg R7" mit Sprung in die
  Siegrunde an dieser Stelle. Das Briefing zeigt "So gewinnt ihr hier" (Position nach 0:20 in
  Siegrunden). Vergleich, kein Beweis.

- **Mechanik** (aus `weapon_fire` + Geschwindigkeit im Schuss-Tick, `player_hurt`, Kills):
  Anteil Schüsse im Laufen, Treffer pro Schuss, Headshot-Anteil der Kills, Tode ohne eigenen
  Schuss, Spray (Treffer Schuss 1–3 vs. ab 4). Fließt in die Tod-Analyse ein ("letzter Schuss
  im Laufen", "kein eigener Schuss"), in den Verlauf und in Mechanik-Ziele je Spieler.
  Schwellen unter `mechanics` in rules.yaml (Heuristiken, an echten Demos kalibrieren).

Lern-Kreislauf: Upload → Urteil + Schlüsselmomente → Ziele → Training → Briefing → nächstes Match → Ziel-Check.

- **Startseite = Coach**: aktive Ziele mit Check-Verlauf (grün/rot), Training je Ziel,
  Briefing-Auswahl je Map, Urteil des letzten Matches, Upload.
- **Ziele** (`data/goals.json`): bis zu 3, aus den Top-Ursachen. Messgröße: Anteil der Runden
  eines Matches mit dieser Ursache. Zielwert = Start x `goals.target_factor`. Bei jedem Upload
  automatisch geprüft; `goals.done_after` Matches in Folge erreicht = geschafft, neues Ziel rückt
  nach. Dieselbe Demo zweimal zählt nicht doppelt. Ergebnis steht als "Ziel-Check" im Report.
- **Briefing** (`/briefing/<map>`): eure Ziele, wo ihr auf der Map (je Seite) wiederholt
  sterbt (davon als Erster), häufigste Ursachen auf dieser Map. Nur aus eurem Verlauf.

- **Urteil + Ursachen** (oben im Report): Befunde werden zu wenigen Ursachen gebündelt
  (getrennt gespielt, erste Tode, geblendet, wenig HP, Unterzahl, im Laufen, Utility,
  Überzahl verspielt, Economy) und danach sortiert, in wie vielen **verlorenen** Runden sie
  vorkamen, verglichen mit gewonnenen Runden. Das ist ein Zusammenhang, kein Beweis.
- **Schlüsselmomente-Tour**: nur die teuersten Momente (je Top-Ursache einer + verspielte
  Überzahl), das Replay hält genau dort an. "Alle Fehler" bleibt als zweite Tour.
- **Duo**: Siegquote zusammen vs. getrennt (Ø Abstand pro Runde), Trades untereinander,
  wer zuerst stirbt.
- **Utility-Wirkung**: Gegner/Mitspieler geblendet (`player_blind`), Granatenschaden.
- Schwellen unter `coach` in rules.yaml.

- **Tod-Analyse (Situations-Coach)**: für jeden Tod eines Fokus-Spielers die Lage aus der Demo:
  Zahlenverhältnis, Opening-Duell, Blendung (`player_blind`), HP vor dem Duell (100 minus
  erlittener Schaden), Laufgeschwindigkeit aus den Positionen, nächster Mitspieler und deren Orte,
  eigener Schaden, geworfene und ungenutzte Utility, Trade, Gegner-Distanz. Der Tipp richtet sich
  nach dem wichtigsten erkannten Problem. Schwellen unter `rules.death_review`.
- **Fortschritt** (`/progress`, CLI: `cstaktik progress`): jede Auswertung legt eine Zusammenfassung
  in `data/history/` ab. Die Seite zeigt K/D, ADR, Opening-Duelle und getradete Tode je Match,
  Fehlerarten pro 10 Runden mit Trend (ab 4 Matches: letzte 2 gegen die davor) und je Map eine
  Karte aller Todesorte mit den häufigsten Orten. Datum = Auswertungszeitpunkt (die Demo enthält
  kein Spieldatum).

- **Coach-Tour**: spielt alle Fehler des Matches nacheinander ab (rundenübergreifend), hält an
  jedem an, "Weiter" springt zum nächsten.
- **Overlays beim Fehler**: Linie zum nächsten Mitspieler mit Abstand (Tod ohne Trade),
  frühere Tode am selben Ort als Geister-X mit Rundennummer, ungenutzte Granaten am Todesort.
- **Lob** (grün, hält das Replay nicht an): Trade gegeben, 3+ Kills, gewonnener Clutch.
- **Spieler-Dashboard**: K–D, ADR, Opening-Duelle, Anteil getradeter Tode, geworfene Utility.
- **Hausaufgaben**: je Spieler die 3 wichtigsten Fehler-Arten mit Tipp und Runden-Links.
- **Rundenzusammenfassung** und Live-Anzeige "CT 4 : 3 T" im Replay.

Smoke/Molotov-Dauer: Start- und Ende-Events werden selbst über die entityid gepaart
(awpy verwirft Enden nach 20 s). Fehlt das Ende, gilt das Rundenende und es wird keine
Restzeit angezeigt.

## Kartenbilder

Ohne Kartenbild zeichnet der Report den Kartenumriss aus den Laufwegen des Matches
(wo Spieler standen) und setzt die Ortsnamen aus der Demo. Mit Bild wird die
Radar-Kalibrierung genutzt. Gesucht wird in `data/maps/` (nicht im Repo) und `~/.awpy/maps/`:

- Bild: `<map>.png` oder `<map>_radar.png` (auch `.jpg`/`.webp`), z. B. `de_mirage.png`
- Kalibrierung: `map-data.json` im awpy-Format **oder** die CS2-Overview-Datei `<map>.txt`
  mit `pos_x`, `pos_y`, `scale`

Automatisch: Vor jedem Report lädt der Server fehlende Karten selbst herunter (Quelle:
github.com/MurkyYT/cs2-map-icons, dort automatisch aus dem offiziellen CS2-Depot gezogen;
Rechte bei Valve, deshalb nur lokal in `data/maps/`). Vorab alle laden: `cstaktik maps`.
`awpy get maps` lieferte am 12.10.2026 nur 403. Bild und
Kalibrierung müssen zusammenpassen, sonst liegen die Positionen falsch.

## Regeln

Konfiguration: `cstaktik/config/rules.yaml`. Alle Schwellen sind Heuristiken (Startwerte, keine Quelle).

| Regel | Auslöser | Datenquelle |
|---|---|---|
| Tod ohne Trade | Kein lebender Mitspieler innerhalb `trade_distance_units`, kein Gegen-Kill auf den Killer in `trade_window_s` | Kills, Positionen |
| Gleicher Todesort | ≥ `min_deaths` Tode am selben Place-Namen (Fallback: Radius) | Kills |
| Utility nicht genutzt | Granaten im Inventar 1 Tick vor dem Tod | Inventar (demoparser2) |
| Economy | Teil-Team Full-Buy, Teil-Team Save; Force verloren und Folgerunde kein Full-Buy | Equipment/Geld am Freeze-Ende + Offset |
| Oft erster Tod | ≥ `min_count` Runden als Erster gestorben | Kills |
| Tod ohne Schaden | ≥ `min_count` Tode ohne vorher Schaden in der Runde | Schaden (player_hurt) |
| Stark (Lob) | Trade gegeben, ≥ `multi_kill_min` Kills, Clutch gewonnen | Kills, Runden |

Pistolrunden (1, 13) und Overtime werden bei Economy ignoriert. Kann eine Regel mangels
Daten nicht laufen, steht sie im Report als „nicht auswertbar“.

## Tests

```bash
cd backend
pytest
```

Die Tests nutzen synthetische Mini-Matches (`tests/synth.py`, Orte mit Präfix `Synth`,
Koordinaten frei erfunden). `tests/fixtures/synth_match.json` ist dasselbe Match als
Datei: `cstaktik analyze tests/fixtures/synth_match.json --me 76561190000000001`.

## Architektur

```
.dem ─► parser/awpy_adapter.py ─► MatchData (model.py) ─► rules/* ─► Findings ─► report/render.py ─► HTML
                                      ▲
                     parser/loader.py (JSON: Cache + Tests)
```

Nur `awpy_adapter.py` kennt awpy. Regeln und Report arbeiten ausschließlich auf `MatchData`.

## Noch nicht mit echter Demo geprüft

Der Adapter ist gegen den Code von awpy 2.0.2 / demoparser2 0.42 geschrieben, aber noch nie
mit einer echten Premier-Demo gelaufen. Beim ersten Lauf prüfen:

- Tickrate (Config: 64)
- Inventar-Namen der Granaten (Keywords in `rules.yaml`)
- Economy-Sample-Tick (Freeze-Ende + 5 s)
