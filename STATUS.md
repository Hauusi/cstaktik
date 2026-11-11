# cstaktik – Projektstand

Diese Datei ist die Quelle für den Stand des Projekts. Vor jeder Änderung zuerst hier lesen, nicht den Chat-Verlauf.
Nach jeder Änderung im selben Commit aktualisieren (Abschnitte "Funktionen", "Offen", "Änderungsprotokoll").

Stand: 2026-11-04 · Branches `ccr-cd3bec95-38h7uj` und `ccr-b08d5abb-e1pzde` (Server) gleich · Tests: 412 grün (`cd backend && python -m pytest -q`)

## 1. Was das Projekt ist

Selbst gehosteter CS2-Coach nach dem Match für zwei Spieler (Brüder). Demos der eigenen Matches werden
automatisch geholt, geparst und ausgewertet. Die App (PWA, am Handy) bespricht jedes Match wie ein Coach: was
passiert ist, das eine Thema, eine Abmachung fürs nächste Match, ein Kurs mit Lektionen, Pro-Taktiken und Lineups.

- Spieler: "Hausi" (Steam-Name cntoz, 76561199689755671) und Bruder (entozs, 76561199203948380).
- Ziel des Nutzers: "perfekter Coach" – ein roter Faden, ganze Sätze, ein Coach, der CS beibringt. Keine
  Ansammlung von Infos.

## 2. Feste Regeln (immer einhalten)

- Nichts erfinden: keine Koordinaten, Timings, Lineups oder Statistiken ohne Quelle in den geparsten Demo-Daten.
  Fehlen Daten, klar melden statt raten. Gilt auch für den KI-Coach (Prompt und Runden-Prüfung).
- Demos, `players.yaml`, `secret.key`, `cstaktik.db`, `data/` (außer README) werden nie committet.
- Passwörter, SSH-Schlüssel, API-Schlüssel nie im Code, im Repo oder im Chat. Den Nutzer nie danach fragen.
- Keine Umgehung von HLTV-Cloudflare, keine Tricks gegen Steam-Sicherheit (kein VPN-Trick).
- Tests schreiben nie echte Daten (conftest isoliert alle Pfade, Accounts, API-Schlüssel).
- Nur committen, wenn alle Tests grün sind. Nur auf den Branch der aktuellen Sitzung pushen (zuletzt
  `ccr-cd3bec95-38h7uj`), kein PR ohne Auftrag.
- Commit-Trailer genau so:
  ```
  Co-Authored-By: <Modell der Sitzung> <noreply@anthropic.com>
  Claude-Session: <Link der aktuellen Sitzung>
  ```
  Sonst nirgends Modellnamen (Code, Kommentare, Texte).
- Antworten an den Nutzer: Deutsch, klar, ehrlich, kurz, keine Emojis, bei Unklarheit nachfragen.

## 3. Server und Betrieb

- Hetzner, IP 62.238.39.31, Hostname PeakClip. Domain https://cs2coach.duckdns.org hinter nginx (auf demselben
  nginx läuft noch eine andere Website), Zertifikat über certbot.
- App läuft als Nutzer `cstaktik` in `/home/cstaktik/cstaktik`, systemd-Dienst `cstaktik`, auf 127.0.0.1:8000.
- KI-Schlüssel: `/etc/cstaktik-ai.env` (`ANTHROPIC_API_KEY=...`, chmod 600), eingebunden per Drop-in
  `/etc/systemd/system/cstaktik.service.d/ai.conf` mit `EnvironmentFile=`.
- Root-git meldet "dubious ownership": git immer mit `runuser -u cstaktik --`.

Befehle für den Nutzer (als root):
- Normal: `cd /home/cstaktik/cstaktik && runuser -u cstaktik -- git pull && systemctl restart cstaktik`
- Mit Neuberechnung (neue Felder im Verlauf, Reports neu bauen):
  `cd /home/cstaktik/cstaktik && runuser -u cstaktik -- git pull && cd backend && runuser -u cstaktik -- .venv/bin/cstaktik pro-update && systemctl restart cstaktik`
- Neue Abhängigkeiten zusätzlich: `runuser -u cstaktik -- backend/.venv/bin/pip install -q -e backend`
  (bisher nachträglich dazugekommen: cryptography, zstandard, anthropic).

Automatischer Download (Valve-Matches): Docker-Container `cs-demo-downloader` (claabs, MIT), Bot-Account
"Hausii1995", Image fest auf `@sha256:4f8346bc...`, eigene korrigierte `steam-gc.js` aus
`backend/cstaktik/vendor/cs_demo_downloader/` wird hineingelegt (GC-Anmeldung, 30 s Warten nicht fatal,
requestGame alle 10 s bis 90 s). Läuft alle 20 Minuten. QR- und Passwort-Login mit dem eigenen Account wurden
entfernt (Steam blockte). FACEIT-Demos (.dem.zst) werden beim Upload entpackt.

## 4. Technik

- Python 3.13, FastAPI + Jinja2, awpy 2.0.2 / demoparser2, pydantic, SQLite (Accounts), PWA mit Service Worker
  und Web Push (RFC 8291/8292, `notify.py`). KI: offizielles `anthropic`-SDK (1.x).
- Paket: `backend/cstaktik`, Tests: `backend/tests` (pytest, `synth.py` baut synthetische Matches).
- Daten (`backend/data/`, gitignored): `demos_raw/`, `cache/` (geparste Matches, `CACHE_SCHEMA` 16 = mit Assists),
  `history/` (ein JSON je Match), `reports/` (HTML je Match), `pro/`, `pro_demos/`, `maps/`, `icons/`, `fonts/`,
  `autodl/`, `ai/` (KI-Gespräche, Notizen, Kosten), `drills/` (Plan, Entscheidungen, Sessions, Warm-ups je Spieler), `coaching.json`, `goals.json`, `cstaktik.db`, `secret.key`.
- Konfiguration: `backend/cstaktik/config/rules.yaml` (Abschnitte parser, report, rules, utility_cmp, mapbook,
  situation, coach, goals, course, mechanics, faceit, playbook, ai), `players.yaml` (gitignored, Vorlage
  `players.example.yaml`).
- Sichtbarkeit: Mit Accounts sieht jeder eingeloggte Nutzer nur Matches, in denen seine SteamID mitspielte
  (`_visible`, `_me()`, `_mine()`). Ohne Accounts alles. POSTs prüfen die Herkunft (Origin/Referer).

### Ablauf einer Demo (`pipeline.run`)
Demo (auch .bz2/.gz/.zst/.zip/.rar) -> `parser/awpy_adapter.py` -> `MatchData` (`model.py`, gecacht) ->
Regeln (`rules/`) + Coach (`coach.py`, `coach_voice.py`, `situation.py`, `duels.py`, `impact.py` ...) ->
`history.summarize` (Verlauf-Eintrag) -> Ziele/Kurs-Auftrag (`goals.py`, `coaching.py`, `course.py`) ->
Report-HTML (`report/render.py`) -> Push-Nachricht.

### Wichtige Felder im Verlauf-Eintrag (`history.summarize`)
players (K/D, ADR, Opening, Utility-Zähler), score_by, by_round [Runde, Seite, gewonnen, Kills, gestorben,
Schaden], lessons {sid: {lektion: anzahl}}, scenes (Tod-Szenen mit happened/next/frame/snap und clip =
Wiederholung der letzten Sekunden mit `dec` = Entscheidungsmoment, siehe scene_clip.py), moments (beste
Momente, die zwei besten je Spieler mit clip), duel_stats, mech,
util_stats, nade_eff (Granaten-Wirkung), board (Scoreboard-Rohzahlen für Stats), impact, moments, clutch, plays/ct_plays (Taktiken), timeline, deaths,
duo (zusammen/getrennt, Trades je SteamID, ab diesem Update; ältere Matches nach Neuberechnung), focus_check (Auftrag-Check), goal_check, lead/lead_by (das eine Thema je Spieler).

## 5. Module (backend/cstaktik)

| Modul | Zweck |
|---|---|
| api.py | FastAPI-App, alle Seiten und Endpunkte (siehe Abschnitt 6) |
| pipeline.py | Gemeinsamer Ablauf CLI/Web, Pfade (DATA_DIR, AI_DIR ...), Neuberechnung `rerender_reports` |
| cli.py | `cstaktik` analyze, players, maps, pro, diagnose, check-spotted, pro-update, faceit-test, faceit-sync, icons, progress, user, steam-sync, https-adresse, serve |
| parser/awpy_adapter.py, parser/loader.py | Einzige Stelle mit awpy; MatchData <-> JSON |
| model.py | Datenmodell (Kill, Damage, Blind, GrenadeThrow, UtilityArea, Duel, Round ...) |
| rules/ | Einzelregeln: death_review, untraded_death, unused_utility, entry_deaths, no_damage_death, repeated_death_spot, economy, positives |
| coach.py, coach_voice.py | Diagnose und Coach-Ansagen je Tod, Lektions-IDs (`LESSONS`) |
| situation.py, duels.py, impact.py, clutch.py, mechanics.py, stats.py, tilt.py (summary über Matches, match_facts je Match, progress) | Lagebild/Gewinnchance, Duell-Werte, Win Probability Added, Clutches, Mechanik, Statistik, Tilt |
| scene_clip.py | Szenen-Clip je Tod: Positionen aller Spieler bis 8 s (max. 12 s) davor bis 1 s danach, Kills, Smokes/Molotovs/Flashes; Weltkoordinaten, Zeit relativ zum Tod |
| academy.py, academy_texts.py | CS-Wissen: 11 Bereiche (`AREAS`), 47 Themen (`TOPICS`) mit Kernsatz, Erklärung, Beispiel in Schritten, Fehlern, Übung, Schlüsselwort, Frage für die eigene Demo, Wissens-Check; `answer` (Abstände 1/3/7/21 Tage, falsch = morgen), `due` (falsche zuerst, neue nur aus gelesenen Themen oder der aktuellen Lektion, Bereiche gemischt), `overview`, `related` (Lektion -> Themen), `mine` ("Bei dir": Kennzahlen aus dem Spielerprofil laut `MEASURES`, Stand der verwandten Lektionen, bis 2 eigene Szenen, T/CT-Siegquote laut `SIDE_TOPICS`). Lernstand in data/drills/<sid>.json unter `quiz` und `read` |
| drills.py | Coaching-Session und Warm-up: Wenn-dann-Plan mit Hindernis (set_plan, plan_before), Selbsteinschätzung (attach_check, rate_plan), Plan-Verlauf mit gemessenen Fehlern gegen das Auftragsziel (plan_log), Begründung je Entscheidung (record reason/cue_ok), Tilt-Check (set_tilt, tilt_state: Gefühl je Match, Reset an/aus), Entscheidungen (record), fällige Szenen mit Abständen 1/3/7/21 Tage und gemischten Lektionen (due), erledigte Sessions, Warm-up-Serie |
| evening.py | Spielabend: Rating je Match-Nummer des Tages (curve), Rat "Pause nach k Matches" erst ab 3 Tagen mit 2+ Matches und Abfall >= 0,10; index_today |
| coach_memory.py | Gedächtnis für Entscheidungen: je Lage (Unterzahl/Überzahl/gleich) häufigste Wahl, wie oft wie die Pros, Treffer bei „worauf es ankam“; erst ab 5 Szenen je Lage. In Session (Schritt „muster“) und Warm-up |
| coach_story.py | Der Coach spricht, ohne KI: Eröffnung (Ergebnis, Rating gegen Schnitt), Rückblick auf den Plan (gemessen), das eine Muster mit Belegen (Runden, verlorene, Seite, Ort, Abstand zum Mitspieler, Granaten in der Tasche, Vergleich mit deinen Matches davor), Weg seit Lektionsstart (Gedächtnis), Ansage zur Szene, Plan, Übung, was im nächsten Match geprüft wird; `home_message` für die Startseite, `milestones` (Lektion geschafft, Rückfall, neues Thema, bestes Rating seit ≥5 Matches, Warm-up-Serie 3/7/14/30), `pick` (Formulierungen je Match abwechselnd), `map_brief` (Ansprache oben im Briefing: Bilanz auf der Map, T/CT, häufigster Fehler, häufigster Todesort, Abmachungen, Schlüsselwort). Keine „pro 10 Runden“ in Sätzen, nur Anzahl in Runden |
| duo.py | Gemeinsame Abmachung (`PLANS`, `get_plan`/`set_plan` in data/drills/duo_<a>_<b>.json, `recommend` aus den Duo-Zahlen, `plan_check` seit der Abmachung, `partner`); Duo über die letzten 10 Matches mit demselben Partner: Runden zusammen/getrennt mit Siegquote, Anteil zusammen, Ø Abstand, gegenseitige Trades, erste Tode; Aussage erst ab 20 Runden je Gruppe und 10 Punkten Abstand. Daten je Match: `h["duo"]` (coach.duo mit `sids`, `trades_by`, `first_by`), nur bei genau zwei Fokus-Spielern |
| notify.py (Ergänzung) | `_pause_line`: Push nach dem Match mit Pausen-Hinweis, wenn dieses Match das k-te des Tages ist und die eigene Spielabend-Kurve danach deutlich sinkt |
| weekly.py | Wochenrückblick: letzte 7 Tage gegen die 28 Tage davor (Ergebnisse, Rating, klar besser/schlechter aus spielerprofil.METRICS, Lektion, Geschafftes, Warm-ups/Sessions, Entscheidungs-Muster, nächste Woche); Seite `/woche`, Push sonntags ab 19 Uhr einmal je Kalenderwoche (`reminder.weekly_check`, Setting `weekly_sent:<user>`) |
| reminder.py | Erinnerung vor dem Match: Push 15 min vor der eingestellten Spielzeit (/konto#erinnerung, Setting `reminder:<user>`), einmal am Tag (`reminder_sent:<user>`), nicht nach dem Warm-up; Hintergrund-Schleife jede Minute (`_start_reminder`) |
| dayplan.py | Tagesplan der Startseite: Session, Übung der Lektion, Thema im CS-Wissen, Warm-up; erledigt nur aus gespeicherten Daten (Session markiert, Übung heute, Thema heute geöffnet/beantwortet, Warm-up heute) |
| spielerprofil.py | Spielerprofil „Wo du stehst“ (oben auf /progress): 6 Bereiche wie im CS-Wissen, Urteil aus den Kurs-Lektionen des Bereichs (Baustelle/Stärke/Im Rahmen/Zu wenig Daten, Economy ohne Urteil), Kennzahlen mit Verlauf gegen die 10 Matches davor, 50 % als Bezug nur bei Duellen, T/CT-Siegquote |
| stats_view.py | Stats-Seite: Kennzahlen je Match (Verlauf), Vergleich mit gleich vielen Matches davor (ab 3, nur bei klarem Abstand `METRICS`), Sparklines, T gegen CT aus `by_round` (ab 10 Runden je Seite), Maps, Multi-Kills |
| scoreboard.py | Stats: Rohzahlen je Match (K/D/A, Schaden, HS, KAST, 1K–5K, Openings, Trades), Summen über Matches, Kennzahlen inkl. HLTV-Rating 1.0 und Rating-2.0-Näherung (awpy-Formel, gegengeprüft: gleiche Werte wie awpy) |
| nade_effect.py | Granaten-Wirkung: Flash-Blendzeit, Flash-Assists, Team geblendet, HE/Molotov-Schaden, Tod mit Granaten |
| utility_cmp.py | Utility gegen Pros, Flash-Wirkung, Granaten vor dem ersten Duell |
| course.py, course_texts.py, curriculum.py | Kurs: 5 Stufen, 12 Lektionen, Einstufung aus den letzten Matches; `course_texts.PLANS`: je Lektion 3 Wenn-dann-Pläne; `CUEWORDS` (Schlüsselwort), `CUE`/`REASONS` (worauf es ankommt, für "Warum?"), `OBSTACLES` + `obstacle_line` (Hindernis und Gegenplan), `ROUTINE_BASE`/`ROUTINE_STEP` + `routine()` (Kaufzeit-Routine), `RESET` + `reset()` und `TILT_FEEL` (Tilt-Check) |
| coaching.py, goals.py, weekplan.py, session.py | Auftrag (aktuelle Lektion) und Check je Match, Ziele, Wochenplan, Spielabend |
| ai_coach.py | KI-Coach (Claude API): Fakten, Nachbesprechung (JSON-Schema), Fragen, Gedächtnis, Kosten |
| playbook.py, setups.py, lineups.py, mapbook.py, briefing.py, reference.py, pro.py, faceit.py | Pro-Taktiken (T/CT), Lineups, Map-Buch, Briefing, Vorbild-Runden, Pro-Demos |
| levers.py, review.py, report/progress.py | Größte Hebel, Review über mehrere Matches, Fortschritt |
| report/render.py, report/radar.py | Report-HTML mit 2D-Replay, Welt -> Radar-Pixel |
| callouts.py | Callouts, Spieluhr, Meter (Jinja-Filter `callout`, `clock`, `meters`) |
| accounts.py, steam_openid.py, steam_sync.py, autodl.py, notify.py | Login, Steam-Verbindung, Sharecodes, Auto-Download, Web Push |
| archive.py, fsutil.py, maps.py, icons.py, fonts.py, diagnose.py | Archive, atomares Schreiben, Radarbilder, Waffen-Icons, Schriften, Echtdaten-Check |

## 6. Seiten und Endpunkte (api.py)

- `/` Startseite: Coach-Karte mit Sprechblase des Coaches (`coach_story.home_message`; vor der Session Anreißer, danach Abmachung und Weg), darunter „Dein Tag“ (`dayplan.build`, Block `day`). Vor der Session: "Session starten" zum letzten Match. Danach: "Vor dem nächsten
  Match" mit Wenn-dann-Plan und Warm-up-Knopf (fällige Szenen). Darunter Kachel-Raster (`home_tiles.html`):
  Gespräch, Kurs, Granaten, Duelle, Taktiken, Lineups, Briefing, Warm-up, Matches, Fortschritt. Am PC Coach links, Kacheln rechts. Upload eingeklappt.
- `/coach/{report}` GET/POST: Nachbesprechung (`coach_talk.html`, `coach_assets.html`), Antwort auf die Frage
  des Coaches, weitere Fragen.
- `/m/{report}` Coaching-Session (Story, `api._session`, Coach-Sätze aus `s.story` in Sprechblasen; Reihenfolge Ergebnis, Moment, Kurz-Check, Thema, Szenen, Tilt, Plan mit Übung und Prüfung, Fertig): Ergebnis mit Rating und Schnitt (+ KI-Eröffnung), bester
  Moment als Wiederholung, Kurz-Check des alten Plans (Abruf, 3 Optionen, dann Selbsteinschätzung Ja/Teilweise/Nein,
  dann gemessene Zahlen), 2 Szenen "Entscheide selbst" (Wiederholung hält bei `dec`, Wahl, dann "Warum?" mit 4 Gründen,
  Auflösung inkl. worauf es ankam, läuft weiter), Thema mit Warum, Wenn-dann-Plan wählen + Hindernis mit Gegenplan +
  Schlüsselwort + Kaufzeit-Routine, Fertig (markiert Session). Tilt-Check (vor dem Thema, nur bei 3+ Runden nach
  2+ Niederlagen in Folge): erst "Wie warst du drauf?", dann Zahlen (als Erster / ohne Trade gestorben, gegen nach
  Siegen), Langzeit-Aussage ab 25 Runden je Gruppe, Reset-Routine in den Plan übernehmen. Im Thema: Fehler pro 10 Runden der letzten 6 Matches
  mit Ziellinie (`s.trend`). Im Ergebnis: Pausen-Hinweis, wenn dieses Match das k-te des Tages ist und die eigene
  Spielabend-Kurve ab dort deutlich sinkt (`s.evening`).
  Bausteine in `replay_box.html` (Makros replay, drill_choice), Logik in `coach_assets.html`.
- `/warmup`: „Zu zweit“ (gemeinsame Abmachung wählen, `POST /duo/plan`, Plan des Partners), Plan mit Gegenplan und Schlüsselwort, Kopfkino (`course_texts.imagery`) und "Zu zweit"-Satz,
  Wissens-Check (2 fällige Fragen), Kaufzeit-Routine, Reset-Routine (wenn übernommen oder Tilt belegt), Spielabend-Kurve (heute n Matches, ggf. Pause), 3 fällige Szenen zum Entscheiden, Tabelle "Deine letzten Pläne"
  (du sagst / gemessen); alle entschieden = Warm-up erledigt.
- `POST /session/answer|plan|rate|tilt|done`: Entscheidung, Plan, Session/Warm-up erledigt (nur eigener Spieler). `/reports/{datei}` Report mit 2D-Replay.
- `/wissen` CS-Wissen (Bereiche, Stand je Thema: neu/gelesen/noch üben/sitzt), `/wissen/{thema}` (Kern, Verstehen, Beispiel,
  Fehler, Üben, Prüfen, Weiter in der App), `POST /wissen/antwort` (nur eigener Spieler). Kachel "CS-Wissen" nach "Kurs".
  Session-Thema und Lektion verlinken passende Themen; der KI-Coach bekommt sie in den Fakten und darf sie nennen.
- `/kurs` Kurs-Übersicht (aktuelle Lektion, Lernpfad). `/kurs/{lektion}` Lektion (Verstehen, Bei dir, Bei den
  Pros, Üben, Prüfen).
- `/stats` (Reiter "Stats", `stats_view.py`): Form (Rating, Vergleich mit dem Zeitraum davor, Siege/Niederlagen, letzte 5),
  interaktiver Verlauf je Kennzahl (Punkte je Match, Schnitt über 5, Tooltip), 8 Kennzahl-Kacheln mit besser/schlechter
  und Sparkline (Antippen wechselt den Graphen), T gegen CT, Impact (Openings, 1K–5K, Clutches), Granaten, Map-Karten,
  Spielabend, „Ihr zwei“ (`duo.summary`), Match-Liste mit Rating-Balken und Tabelle. Filter: letzte 10/alle, Map. Farben T `#c78322`, CT `#4d8fe6`
  (mit Palette-Prüfung auf Farbsehschwäche und Kontrast).
- `/granaten`, `/duelle`: Statistik-Seiten mit letztem Match, Runde für Runde bzw. Kennzahlen, Verlauf.
- `/progress` beginnt mit dem Spielerprofil (`spielerprofil.build`), Links je Bereich zur Lektion und zu `/wissen#b-<bereich>`.
- `/matches`, `/progress`, `/progress/details`, `/progress/karte`, `/review`, `/highlights`.
- `/training`, `/training/situationen` (Szenen-Quiz), `/training/deal|done|plan`.
- `/playbook/{map}`, `/lineups/{map}`, `/briefing/{map}`, `/mapbook/{map}`, `/pro`, `/pro/sync`.
- `/konto` (Optionen, Steam, Bot, Push), `/spieler`, `/mehr` (Anleitung, `#wissenschaft` mit Studien), `/login`, `/setup`, `/auth/steam`, `/push/*`,
  `/analyze` (Upload), `/jobs/{id}`, `/api/jobs/{id}`.
- Navigation unten (am PC oben): Coach, Matches, Stats, Fortschritt; Einstellungen oben rechts.

## 7. KI-Coach (ai_coach.py)

- Schalter in /konto#ki (`ai_coach.auto_debrief`, Setting `ai_auto_debrief`), Standard aus: Nachbesprechung nur auf Knopfdruck.
  Fragen gehen auch ohne Nachbesprechung (Chat mit `qa: true`, günstiges Modell, Fakten + Frage in der ersten Nachricht).

- Aktiv nur mit `ANTHROPIC_API_KEY` auf dem Server. Ohne Schlüssel: Hinweis, Rest der App läuft normal.
- Nachbesprechung: `debrief_model` (Standard claude-sonnet-5-5, effort medium, max_tokens 7000) mit
  Structured Output (JSON-Schema): headline, summary, good[], topic{lesson, title, principle, scenes[]},
  agreement{text, check}, question{round, text}. Runden, die es im Match für den Spieler nicht gibt, werden
  entfernt (`_check_debrief`). Jede Szene wird als Wiederholung abgespielt (Player in `coach_assets.html`,
  Daten aus `clip`, umgerechnet in `api._clip_px`; startet von selbst, Regler, Tempo ½/1/2), sonst Standbild,
  dazu Link ins 2D-Replay.
- Fragen und Antworten: `model` (claude-haiku-5-5), kurze Antworten, Gespräch bleibt gespeichert.
- Fakten (`facts`): Ergebnis, Scoreboard, Impact, jede Runde, Duelle, Schießen, Granaten-Wirkung je Runde,
  Fehler je Lektion, aktuelle Kurs-Lektion, Clutches, Szenen, letzte 3 Matches, Notizen früherer Gespräche.
- Gedächtnis: `data/ai/notes/<sid>.json` (Abmachung, Frage, Antwort je Match). Gespräche:
  `data/ai/<report>/<sid>.json`. Kosten je Monat: `data/ai/costs.json`.
- Grenzen in `rules.yaml` -> `ai`: 2 $ pro Monat, 15 Fragen je Match, 500 Zeichen je Frage. Preise je Modell dort.
- Geschätzte Kosten: Nachbesprechung 3–8 US-Cent (Sonnet), Fragen unter 0,1 Cent (Haiku).
- Alte Fließtext-Gespräche werden mit Schlüssel neu geschrieben.

## 8. Lernprinzipien (Quellen auf /mehr#wissenschaft und /mehr#aufbau)

- App-Aufbau: kognitive Belastung (Sweller 1988), Gewohnheit durch festen Auslöser (Lally u. a. 2010),
  Selbstbestimmung inkl. Verbundenheit (Ryan & Deci 2000), Spielelemente sparsam (Sailer & Homner 2020).

- Entscheiden statt zuschauen: Temporal-Occlusion-Training (Müller u. a., Sports Medicine 2024, Meta-Analyse).
- Wenn-dann-Pläne: Durchführungsvorsätze (Gollwitzer & Sheeran 2006, d = 0,65 über 94 Tests). Gilt auch für die
  KI-Abmachung (Prompt verlangt "Wenn ..., dann ...").
- Abrufen statt Nochmal-Ansehen (Roediger & Karpicke 2006): Kurz-Check, Warm-up.
- Verteiltes Wiederholen (Cepeda u. a. 2006): Abstände 1/3/7/21 Tage, anders als Pros entschieden = zurück auf 1 Tag.
- Rückmeldung zur Aufgabe, nicht zur Person (Kluger & DeNisi 1996); im KI-Prompt festgelegt.
- Selbsterklärung (Bisra u. a. 2018, g = 0,55): "Warum?" nach jeder Entscheidung.
- Mentales Kontrastieren mit Wenn-dann-Plan (Wang u. a. 2021, g = 0,34): Hindernis und Gegenplan.
- Instruktives Selbstgespräch (Hatzigeorgiadis u. a. 2011, ES 0,48): Schlüsselwort je Lektion.
- Fortschritt beobachten und festhalten (Harkin u. a. 2016, d = 0,40): Selbsteinschätzung + Plan-Verlauf + Fehler-Verlauf.
- Gemischtes Üben (Brunmair & Richter 2019, g = 0,42): Warm-up mischt Lektionen.
- Pre-Performance-Routine (Rupprecht, Tran & Gröpel 2021): Kaufzeit-Routine.
- Mentale Ermüdung (Habay u. a. 2021, Sport; Esports nur kleine Studien): Pausen-Rat aus eigenen Daten.
- Tilt (Tilt-Skala, Frontiers 2024; Palomäki u. a. 2013, Poker): Tilt-Check nur aus eigenen Daten; Reset-Routine mit
  langsamem Atmen (Zaccaro u. a. 2018), Kontrollierbares abhaken, feste Runde zu zweit.
- Abfragen statt Nachlesen beim Wissen (Adesope u. a. 2017); ausgearbeitete Beispiele (van Gog & Rummel 2010).
- Wahrnehmen und Entscheiden trainieren (Mann u. a. 2007); gezielt üben (Macnamara u. a. 2014: bei Spielen ca. 26 %
  erklärte Varianz).
- Fokus nach außen in den Anweisungen (Chua u. a. 2021; Kritik McKay u. a. 2024 steht auf /mehr dabei).
- Feed up/back/forward als Aufbau der Session (Hattie & Timperley 2007); Rückmeldung nach Gutem (Chiviacowsky & Wulf 2007).
- Kopfkino vor dem Match (Toth u. a. 2020, Driskell u. a. 1994; kleiner Effekt). Erklären an den Bruder (Fiorella &
  Mayer 2013; Befunde gemischt).
- Geprüfte Spielwerte im CS-Wissen: Loss-Bonus 1400–3400 $, Pistolen-Niederlage 1900 $, Sieg 3250/3500 $, Kill-Prämien,
  Bombe 40 s, Entschärfen 10/5 s, Kit 400 $. Smoke-/Molotov-Dauer und Freeze-Time bewusst nicht genannt.
- Bester Moment zur Motivation; Wirkung eigener Highlight-Videos ist in Studien uneinheitlich, so steht es auch in der App.

## 8b. Kurs und Auftrag

- 5 Stufen (Schießen, Duelle, Granaten, Zusammenspiel, Runde), 12 Lektionen mit coach_voice-IDs.
- Einstufung über die letzten 5 Matches in Fehlern pro 10 Runden. Grenze 1,0, für seen_first, utility, alone,
  outnumbered 1,5. "Baustelle" ab min_count Vorkommen und 20 Runden, "sitzt" erst ab 60 Runden.
- Aktuelle Lektion = Auftrag; geschafft nach 2 Matches in Folge im Ziel.

## 9. Spielwiese zum Testen (nur in der Cloud-Sitzung)

Echte Demos in `/tmp/claude-0/-home-user-cstaktik/eafed715-4f9a-5fa9-80f5-0f3beed4cb51/scratchpad/demos_dl/`
(faceit_mirage, hltv_mirage, hltv_inferno, valve_mirage; aus awpy-fixtures). Script `scratchpad/mkplay.sh
<backend> <ziel> <port>` baut Nutzer Hausi und Bruder (Passwort Geheim-12345) und wertet aus. Screenshots mit
Playwright, Chromium unter `/opt/pw-browsers/chromium`. Server nie mit `pkill -f uvicorn` beenden (trifft die
eigene Shell), stattdessen neuen Port nehmen. Der Scratchpad überlebt eine neue Sitzung nicht.

## 10. Offen

- Mehrere echte Matches eines Spielers zum Testen fehlen in der Spielwiese (nur 1 FACEIT-Match mit unseren
  SteamIDs): Kurz-Check und Warm-up mit älteren Matches nur in Tests geprüft.

- Erste echte Nachbesprechung vom Nutzer ansehen (Screenshot), Ton und Länge abstimmen.
- Game State Integration (Live-Daten von Valve) prüfen: Aufwand und was erlaubt ist. Noch nicht entschieden.
- Knopf "Nachbesprechung neu schreiben" (vorgeschlagen, nicht entschieden).
- Ältere Matches nachladen (braucht einen älteren Sharecode vom Nutzer).

## 11. Entscheidungen

- Der Coach in der App läuft ohne KI (keine Kosten je Match). KI nur für Fragen und auf Wunsch für die Nachbesprechung.

- Kein Kachel-Zerlegen des Coach-Gesprächs: Coach-Karte oben, Kacheln nur als Übersicht.
- Taktiken, Lineups, Briefing bleiben (Nutzer findet sie sehr gut).
- Kein Repo-Wechsel des Parsers (awpy/demoparser2 bleibt); keine offene Lineup-Datenbank gefunden.
- Projektstand in dieser Datei im Repo, nicht in Obsidian.
- Playbook: "Gemeinsam/Zusammen" statt "Default", wenn mindestens 4 Spieler in mindestens der Hälfte der
  Prüfpunkte (16–46 s, alle 6 s) gemeinsam sind (Cluster-Abstand 700 Units).

## 12. Änderungsprotokoll (neueste oben)

- 2026-11-11: Qualitäts-Durchgang: alle 136 Seiten automatisch geprüft (kein Fehler, kein Überlauf am Handy);
  Startseite ohne doppelte Begrüßung und ohne doppeltes Thema; Warm-up mit Coach-Ansage, Duo-Vorschlag kompakt
  („Abgemacht“), Spielabend nur mit Aussage; 65 Quiz-Antworten durch plausible Denkfehler ersetzt; Session ohne
  doppeltes Rating, Lektions-Zahlen als Text statt dritter Sprechblase.

- 2026-11-05: Coach-Ansprache im Briefing je Map (`coach_story.map_brief`), Pausen-Hinweis in der Push nach dem Match.

- 2026-11-05: Wochenrückblick (`weekly.py`, `/woche`, Push sonntags), Link im Tagesplan.

- 2026-11-05: Coach merkt sich Entscheidungs-Muster (`coach_memory.py`), Meilensteine und wechselnde Formulierungen.

- 2026-11-05: Gemeinsame Duo-Abmachung (Warm-up, Startseite, Stats), Studien zum App-Aufbau auf /mehr#aufbau.

- 2026-11-05: Erinnerung vor dem Match per Push (`reminder.py`), `accounts.list_users`.

- 2026-11-05: Weniger auf einmal (kognitive Belastung): Startseite zeigt 4 Werkzeuge (Taktiken, Lineups, Briefing,
  Gespräch), Rest unter „Weitere Werkzeuge“; Stats: Duo oben, T/CT, Impact, Granaten, Maps, Spielabend unter „Mehr
  Auswertungen“; Spielerprofil: Zahlen je Bereich aufklappbar, bei Baustellen offen.

- 2026-11-04: Coach spricht ohne KI (`coach_story.py`) auf Startseite und in der Session, Thema vor den Szenen,
  Übung und Prüfung beim Plan; KI-Nachbesprechung als Schalter (Standard aus), Fragen ohne Nachbesprechung.

- 2026-11-04: Duo-Auswertung über Matches (`duo.py`, `h["duo"]`), Abschnitt „Ihr zwei“ auf /stats, Duo-Zahlen in den
  KI-Fakten. Ältere Matches bekommen sie mit der Neuberechnung.

- 2026-11-04: Tagesplan „Dein Tag“ auf der Startseite (`dayplan.py`).

- 2026-11-04: CS-Wissen zeigt je Thema „Bei dir“: eigene Zahlen mit Verlauf, Lektionsstand, eigene Szenen.

- 2026-11-04: Spielerprofil „Wo du stehst“ auf /progress (`spielerprofil.py`).

- 2026-11-04: Stats-Seite neu (`stats_view.py`): Form mit Vergleich, Verlauf als Graph, Kennzahl-Kacheln mit Trend,
  T gegen CT, Impact-Graphen, Map-Karten, neue Match-Liste.

- 2026-11-04: CS-Wissen (`academy.py`, `/wissen`): 47 Themen in 11 Bereichen mit Wissens-Check und Wiederholung mit
  Abstand; Wissens-Check, Kopfkino und Duo-Satz im Warm-up; Links aus Session, Lektion und KI-Coach; "Wie Coaches
  arbeiten" und neun weitere Studien auf /mehr.

- 2026-11-04: Tilt-Check als Session-Schritt (Selbsteinschätzung, Zahlen des Matches, Langzeit-Aussage), Reset-Routine
  in Plan und Warm-up, Studien auf /mehr.

- 2026-11-04: Kaufzeit-Routine, Spielabend-Kurve mit Pausen-Rat (`evening.py`), Fehler-Verlauf der Lektion in der
  Session, drei weitere Studien auf /mehr.

- 2026-11-04: "Warum?" nach jeder Entscheidung, Hindernis mit Gegenplan und Schlüsselwort beim Plan,
  Selbsteinschätzung im Kurz-Check, Plan-Verlauf im Warm-up, vier weitere Studien auf /mehr.

- 2026-11-04: Coaching-Session statt Match-Story (`/m`), Warm-up (`/warmup`), `drills.py`, Wenn-dann-Pläne
  (`course_texts.PLANS`), Entscheidungsmoment in Clips (`dec`), Highlight-Clips für beste Momente, Startseite mit
  Session/Plan/Warm-up, Kachel Warm-up, KI-Abmachung als Wenn-dann, Seite "Die Wissenschaft dahinter".
  Ältere Matches brauchen die Neuberechnung (Clips mit `dec` und Highlights).

- 2026-10-23: Stats-Reiter (`scoreboard.py`, `/stats`), Assists im Parser (Kill.assister_steamid,
  MatchData.assists_parsed), CACHE_SCHEMA 16: Neuberechnung liest Demos in data/demos_raw neu (ca. 1–2 min je
  Match); Matches ohne Demo zeigen Rating 1.0 statt 2.0 und kein KAST (422059b).
- 2026-10-23: Szenen-Wiederholung im Coach und in der Match-Story (`scene_clip.py`, Feld `clip` in scenes;
  ältere Matches brauchen den Befehl mit Neuberechnung).
- 2026-10-23: STATUS.md und CLAUDE.md angelegt, Stop-Hook prüft, dass STATUS.md mitgepflegt wird.
- 2026-10-22: Startseite als Kachel-Raster, `/kurs`, `/granaten`, `/duelle` (2c2f4a0).
- 2026-10-22: Granaten-Wirkung (`nade_effect.py`, `nade_eff` im Verlauf und in den KI-Fakten) (66b714e).
- 2026-10-22: Coach als Startseite, strukturierte Nachbesprechung, Abmachung, Frage, Gedächtnis (60f9ac2).
- 2026-10-21: KI-Coach über die Claude API, Kosten und Limits (8d3a34d).
- davor: Kurs statt Werkzeugkasten (76b434e), Match-Story, Playbook-Erkennung, Auto-Download mit Bot,
  FACEIT-Demos, PWA mit Push, Accounts mit Steam-Login.
