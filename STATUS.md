# cstaktik – Projektstand

Diese Datei ist die Quelle für den Stand des Projekts. Vor jeder Änderung zuerst hier lesen, nicht den Chat-Verlauf.
Nach jeder Änderung im selben Commit aktualisieren (Abschnitte "Funktionen", "Offen", "Änderungsprotokoll").

Stand: 2026-11-04 · Branches `ccr-cd3bec95-38h7uj` und `ccr-b08d5abb-e1pzde` (Server) gleich · Tests: 475 grün (`cd backend && python -m pytest -q`)

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
| memeclip.py | Prototyp Meme-Clip (eigener Bereich, noch ohne Seite): eigene Kills im hochgeladenen Video über den roten Killfeed-Rahmen finden (`detect`, `kills_from_counts`), Schnittplan (`plan`: Anlauf normal ohne Zoom; `hit` = Zoom schlägt kurz vor dem Kill zu, Kill läuft in Zeitlupe 0,4x aus, Zähler/Killfeed/Sound genau im Kill-Moment; `hold` nur am Ende mit Summe; Totzeit fällt weg; kein Wackeln, kein langsamer Zoom), Aufbau: Spielbild als Quadrat in der Mitte auf unscharfem Hintergrund, Killfeed darüber, Zähler darunter (`_vf`), Rendern mit ffmpeg ins Hochformat 1080x1920 (`make`). Aufruf: `python -m cstaktik.memeclip clip.mp4 out.mp4`. Sound selbst erzeugt, keine KI |
| clips.py | Clips in der App: Aufträge je Nutzer in data/clips/<nutzer>/<id>/ (in.*, music.*, out.mp4, state.json), Schnitt im Hintergrund-Thread (immer nur einer gleichzeitig), letzte 12 bleiben; ohne Musik `memeclip.make`, mit Musik `memeclip.make_beat` |
| wall_text.py | Songtext auf Wänden (nur numpy + Pillow): `place_on_wall` sucht glatte, einfarbige Flächen (Zellraster, ohne Bildmitte/Himmel/Boden/Waffe), misst Ober- und Unterkante der Fläche, beide laufen zum Fluchtpunkt auf dem Horizont; Wort liegt groß zwischen ihnen im Winkel der Wand (Höhe links/rechts bis 2,2:1, Neigung bis 0,45). Bild mit `inner` (nur Vorderseite wird eingepasst, `full_quad`). Verfolgung per Blockvergleich + Ähnlichkeit; Wand verloren = Wort flach. Alte Kanten-Suche `place` nur noch für Tests. Zweiter Durchgang über das fertige Video (`apply`)  Mit onnxruntime: Wände über Tiefenkarte (`depth_map`, `depth_regions`, Modell in `data/models/`). |
| beats.py | Beat eines Musikstücks finden (ffmpeg + numpy): Onset-Stärke je 10 ms, Tempo per Autokorrelation (70–180 BPM), gleichmäßiges Beat-Raster (`beats`, `beat_grid`) |
| memeclip.py (Beat-Edit) | `make_beat(src oder [srcs], music, out, music_ss, words)`: mehrere Clips (`detect_all`), `plan_beat`: erster Kill früh (Schlag 2), Kills im festen Abstand von 4 Schlägen (bei wenig Musik 2), je Kill `ramp` (Tempo gleitet von 2,4x auf 0,45x, `ramp_fit` füllt die Lücke genau) + `hit` (ein Schlag in Zeitlupe) + am Ende `hold`; Schnitte nur auf Schlägen; leichte Farbkorrektur. Songtext: je Wort ein Bild (`word_png`, Pillow, mitgelieferte Schrift Anton unter static/fonts, OFL): fette schräge Großbuchstaben mit Rand und farbigem Schatten, Farbe/Drehung/Höhe wechseln, Aufploppen; während eines Kills kein Text. Grundlage: Schnitte auf dem Schlag wirken angenehmer (Wenberg & Carlgren 2021; UCLA-Studie zu Schnitt und Beat) |
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
- `/clips` (Kachel „Clips“): ein bis 8 Videos (je ein Auswahlfeld, in0.*, in1.* ...) und optional Musik, Startsekunde und Songtext hochladen; Status lädt alle 5 s neu;
  Upload in Stücken von 768 KB per JS (`POST /clips/new`, `/clips/{id}/chunk?kind=video|music`, `/clips/{id}/start`), weil
  nginx große Uploads abbrach (ERR_FAILED am Handy); mit Fortschritt und Wiederholung bei Funkloch.
  Fertiges Video ansehen (`/clips/{id}/video`), herunterladen, löschen (`POST /clips/{id}/delete`). Nur eigene Clips.
  Braucht ffmpeg auf dem Server (`apt install -y ffmpeg`), die Seite meldet, wenn es fehlt.
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

- Meme-Clip Beat-Edit: `sung_words` (faster-whisper) ist ungetestet, bis der Nutzer es auf dem Server installiert; Text perspektivisch auf Wänden, Farbeffekte, mehrere Clips, Upload-Seite fehlen.
  Musik-Rechte liegen beim Nutzer. Test-Musik war der Ton aus der TikTok-Aufnahme des Nutzers (nicht im Repo).
- Meme-Clip: Urteil des Nutzers zum ersten Edit abwarten; danach ggf. Upload-Seite, weitere Vorlagen, eigene Sounds,
  Tode/Fails erkennen. ffmpeg muss auf dem Server installiert sein (noch nicht geprüft).

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
- 2026-11-18: Nach 3 s kein Songtext mehr (Nutzer): `align_local` ließ Wörter vor dem ersten / nach dem letzten erkannten Wort weg, wenn sie mehr als 8 s entfernt waren oder dort kein Gesang erkannt wurde; erkennt die Spracherkennung später nichts mehr (laute Musik), verschwand der ganze Rest. Jetzt: an den Rändern läuft die Verschiebung des nächsten Ankers weiter (kein Weglassen); weggelassen wird nur noch zwischen zwei Ankern mit Sprung (Datei anders geschnitten), wenn an keiner Seite Gesang erkannt ist. `LOCAL_HOLD_S` entfernt. Test: Erkennung nur in den ersten 3 s → Text bis zum Ende, Verschiebung durchgehend.
- 2026-11-18: Songtext läuft nach ein paar Sekunden asynchron (Nutzer-Video "Heartbeat", Start 110 s): nachgestellt mit Refrain alle 4 s und Datei, die ab einer Stelle 13 s anders liegt. `align_local` verteilte Wörter über die Lücke (Text, wo nichts gesungen wird) und ordnete grob falsche Refrain-Wiederholungen zu. Jetzt `_anchors` zweistufig (grob bis 20 s, Ausreißer gegen Median ±6 s Songzeit, dann fein bis 1,2 s um die geglättete Verschiebung), bei Sprung zwischen Nachbar-Ankern keine Verteilung über die Lücke: Wort bekommt die Verschiebung der Seite, an der dort Gesang erkannt ist, sonst weg. Test: Median-Fehler < 0,05 s, kein Text in der Pause. Echter Gesang hier nicht prüfbar (Spracherkennung-Download vom Sicherheitsfilter blockiert).
- 2026-11-18: Wort blinkt (Nutzer: taucht auf, verschwindet kurz, taucht wieder auf): Wand-Wort blendete bei kurz verlorener Verfolgung aus und sofort wieder ein, oder sprang nach flach. Jetzt `wall_text.apply`: Wand verloren → Wort bleibt fest an der letzten Stelle stehen (Zustand "frozen"), kein Aus-/Einblenden, kein Wechsel nach flach. Messung am Testvideo (Text-Pixel fertig vs. ohne Text, 30 fps): Blinker bei 0,93 s und 5,67 s weg; übrige Lücken sind Wechsel zwischen verschiedenen Wörtern (Bild für Bild geprüft).
- 2026-11-18: LRCLIB-Text abschnittsweise auf den Gesang (Nutzer-Clip "Heartbeat", Start Sekunde 14: Gesang ab Clip-Sekunde 2, Text erst ab 15; Datei anders geschnitten als die LRCLIB-Version "dirty", eine einzige Verschiebung ließ den Anfang vor dem Videostart). `lrclib.align_local`: LRCLIB-Wörter ±30 s um die Schätzung, unscharf in Reihenfolge den erkannten Wörtern zugeordnet (bis 20 s daneben), Ausreißer (Refrain-Wiederholung) über Nachbar-Median raus, jedes Wort bekommt die Korrektur seiner Nachbarn, Zeilen bis 8 s vor/nach dem ersten/letzten Anker. Unter 3 Ankern wie bisher (`refine`). Test mit nachgebildetem Gesang (zwei Abschnitte, 13 s Unterschied); echter Gesang hier nicht prüfbar (keine Spracherkennung, LRCLIB gesperrt).
- 2026-11-17: Musik-Start an der gewünschten Stelle (Nutzer: "er soll die Passage erkennen, ich will die Hook nehmen"): Feld "Musik ab" leer + Text eingefügt oder Song gewählt → `clips.find_start`: LRCLIB-Suche (Songname, sonst erste Textzeile), nur bei ganzer Songdatei (Länge ±4 s). Mit Text: `lrclib.find_passage` (erste 8 Wörter unscharf gegen den Songtext, erste beste Stelle ≥ 0,7), ohne Text: `lrclib.hook_start` (häufigste Zeile ab 3 Wörtern, erstes Vorkommen); Start 0,25 s vor dem ersten Wort (`LEAD_S`). Gefunden → Wortzeiten von LRCLIB statt ein Wort je Schlag; nicht gefunden → ab Dateianfang mit Grund im Auftrag (`music_found`). Hier nur mit nachgebildeten LRCLIB-Daten getestet (lrclib.net in der Cloud-Sitzung gesperrt).
- 2026-11-17: Wand-Kandidaten: `WALL_MAX_ASPECT` 3,6 → 7,0 (misst seit dem 3D-Schild nur die Vorderseite, dadurch fielen fast alle Wörter raus: Testlauf 2 von 14 Kandidaten). Ob die Wand groß genug ist, entscheidet `wall_text.wall_quad` (Mindesthöhe 7 % des Spielbilds), sonst flach.
- 2026-11-17: Wände über Tiefenkarte (Nutzer: Wörter fast nie an Wänden): Depth Anything V2 Small (Apache-2.0, ONNX aus GitHub-Release fabio-sim/Depth-Anything-ONNX, ~100 MB, SHA-256 geprüft, wird beim ersten Gebrauch nach `data/models/` geladen, nicht im Repo) über onnxruntime (CPU ~0,55 s je Bild). `wall_text.depth_regions`: je Zelle Ebene in der Disparität, Wand = keine Steigung nach oben/unten (Boden: Steigung nach unten), Fluchtpunkt aus dem Abfall der Disparität. 54 Testbilder der 3 Nutzer-Clips: Wand in 34 statt 19, auch schräge Steinmauern im richtigen Winkel. Wort höchstens 55 % der Bildbreite. Ohne onnxruntime: alte Farb-Suche (`DEPTH_NOTE`). Tests laden das Modell nie (conftest).
- 2026-11-17: Nutzer-Video (Jason Derulo): (1) "let" kam mitten in der Pause nach "when I say": eingefügter Text verlor die Zeilen (alles zu einer Zeile). Jetzt bleiben Zeilen erhalten (`clips.lyrics_text`, bis 1500 Zeichen), letztes Wort je Zeile trägt die Zeilenende-Marke (`clips.typed_words`); `align_lyrics` legt nicht erkannte Wörter einer neuen Zeile direkt vor das nächste erkannte Wort (`WORD_PACE_S` 0,28 s) statt gleichmäßig in die Pause. (2) Fast nur flache Wörter, "LET" blass an der Wand und dann flach: Wandsuche lockerer (`CALM_PCT` 75, `COLOR_TOL` 28, `MIN_WALL_CELLS` 18; 54 Testbilder: 13 → 19 mit Wand), Verfolgung bei Kameradrehung mit Perspektiv-Abbildung (`ransac_h`) statt nur Verschiebung, Wand nach >0,3 s verloren → ausblenden statt flach; Wand-Wörter bis 50 % (`wall_picks`).
- 2026-11-17: Musik-Start (Nutzer: Jason Derulo, Datei beginnt mit dem gewünschten Teil, Programm nahm den Drop mitten im Lied): Feld "Musik ab" leer + Songtext eingefügt oder Song gewählt → Musik ab Anfang der Datei (Hinweis im Auftrag); nur ohne Songtext/Song wird der Drop gesucht. Wand-Wort-Grenze `WALL_MAX_ASPECT` misst jetzt die Vorderseite des 3D-Schilds (vorher mit Leuchtrand zu schmal gerechnet).
- 2026-11-17: Wand-Wörter wie Vorbild "TALK" und Story-Modus (Nutzer: Wörter im richtigen Winkel auf der Wand; Vorbild zeigt am Anfang jedes Wort, später nur wichtige). Neue Wandsuche `wall_text.place_on_wall` (Fläche + Kanten + Fluchtpunkt statt fester Stelle im Seitenbereich; an 54 Standbildern der 3 Nutzer-Clips vorher Wort immer an derselben Stelle, jetzt nur auf echten Wänden, ~25 % der Bilder). Wand-Wort als gelbes 3D-Schild (`memeclip.sign_png`: Tiefe, Leuchten). `split_walls`: ohne Wand zu Wortbeginn wird das Wort normal in der Textspur gezeigt. `story_keep`: bis zum ersten Kill jedes Wort, danach nur Zeilenende, gezogene Wörter und Inhaltswörter (Füllwörter `STOPWORDS` weg), Wort bleibt dann bis zu 1,2 s länger (`STORY_HOLD_S`).

- 2026-11-18: Songtext-Timing am fertigen Video nachjustieren (Nutzer: Versatz-Feld + neuer Durchgang ineffizient): `make_beat` speichert Video ohne Text (`out.base.mp4`) + Wörter (`out.lyrics.json`), Text wird getrennt darübergelegt (`apply_lyrics`, mit Versatz wiederholbar). /clips: "Songtext-Timing nachjustieren" mit Vorschau (Video ohne Text, Text live per JS darüber, Regler −1,5..+1,5 s), "Übernehmen" → `clips.relyric` blendet nur den Text neu ein. Routen /clips/font.ttf, /clips/{id}/base, /clips/{id}/lyrics, POST /clips/{id}/lyrics-shift. Echter Clip: Schnitt 97 s, Nachjustieren 41 s, Text genau +0,50 s verschoben; Vorschau im Browser geprüft.

- 2026-11-18: Songtext-Design nach Vorbild (Bildfolgen): Farbe je Wort nach Hintergrund-Helligkeit (`mark_dark_text`: Bild aus dem Segment zur Wortmitte, Textbereich; > 150 → schwarze Schrift mit hellem Schein, sonst weiß mit Schatten), weiches Einblenden (`FADE_IN_S` 0,08), Ausblenden am Zeilenende mit Unschärfe (`BLUR_OUT_PX` 10). Timing: Versuch, Wortzeiten im Vorbild mit Einsatz-Erkennung zu prüfen, nicht aussagekräftig (Abstände wie Zufall); Installation der Spracherkennung in der Cloud-Session abgelehnt → nicht messbar. Stattdessen Feld "Songtext früher/später" (`lyrics_shift`, −2..2 s, `shift_words`).

- 2026-11-17: Songtext-Timing (Nutzer: noch nicht on point): `lrclib.refine` ordnet erkannte Wörter jetzt unscharf zu (`fuzzy_align`: Ausrichtung in Reihenfolge, Schreibähnlichkeit ≥0,6, ≤1,5 s Abstand) statt nur exakt gleiche; wiedergefundene Wörter bekommen Start UND Ende aus dem Gesang (Tipp-Tempo). Nur mit nachgebildeten Erkennungen getestet (keine Spracherkennung in der Cloud-Session); Wirkung zeigt der Hinweis "Wortzeiten über N erkannte Wörter angepasst".

- 2026-11-17: Songtext Wort für Wort wie gesungen (Nutzer: "Papa-paparazzi" kam auf einmal, bevor "paparazzi" gesungen wurde): `lrclib.split_sung` trennt Bindestrich-Wörter, `timed_words` verteilt die Zeile nach Silben (`syllables`, 0,21 s/Silbe) statt gleichmäßig je Wort; Buchstaben bauen sich über die Singdauer des Worts auf (0,8×, 0,12–0,6 s) statt fest 0,22 s. Geprüft: PAPA 0,3–0,8 s, PAPARAZZI tippt 0,8–1,4 s, Zeilenende blendet aus.

- 2026-11-17: Ton geht wieder (Nutzer-Video −11,3 LUFS). Songtext näher am Vorbild: flache Wörter im Spielbild, oberes Viertel (`lyric_pos`: Hochformat BOX_Y+24 % der Box, Querformat 28 % der Höhe), über dem Fadenkreuz; Wand-Wörter höchstens 30 % (`wall_picks`); abgerissene Wand-Verfolgung zeigt das Wort flach weiter statt es auszublenden (`wall_text`). Erste Wörter fehlten (Nutzer): Video beginnt am ersten Schlag, Wort davor wurde verworfen → `clip_words` zeigt Wörter, die bis 0,6 s vor dem Start beginnen, ab 0 (`EARLY_S`). Echter Lauf 3 Clips: Text ab Beginn, 34 Wörter (3 Wand).

- 2026-11-17: Kein Ton (Nutzer-Diagnose: Spielton −16, Musik −10, Mischung −70 LUFS): ffmpeg-Filter-Mischung (aevalsrc-/volume-Formeln, amix) ergab auf dem Server Stille, lokal nicht (vermutlich andere ffmpeg-Version). Mischen jetzt in Python/numpy (`mix_audio`, `_read_audio`, `music_gain`, `sfx_wave`): Spielton je Segment exakt platziert mit 6-ms-Fades, Musik mit Kill-/Schuss-Absenkung, Riser/Impact/Whoosh als Samples; ffmpeg nur noch Lesen/Schreiben. Alte Filter-Mischung entfernt. Echter Clip: gleiche Lautheit (−11,4 LUFS), Korrelation zur alten Mischung 0,98, kein Versatz.

- 2026-11-17: Kein Ton im Clip (Nutzer): Videos vom Server ab 06:22 haben eine flache Tonspur (Gleichspannung −1,26, fast still), vorher normal; dazwischen nur Kill-Erkennung geändert, aber andere Musikdatei. Vermutung: Mischung war still, `level_chain` hob +24 dB an. Lokal nicht nachstellbar (eigene Läufe normal). Jetzt: `loudness`, stille Mischung (< −45 LUFS) = Fehlermeldung statt stummes Video, highpass 20 Hz gegen Versatz, Ton-Diagnose (Spielton/Musik/Mischung in LUFS) unter dem Video (`audio_note`). Ursache offen bis Musikdatei/Diagnose vorliegt.

- 2026-11-17: Songtext neu nach Vorbild (Nutzer: poppt auf und verschwindet, wirkt doppelt; Vorbild Bild für Bild: ein Wort zur Zeit, fester Platz, gleiche Größe, bleibt bis zum nächsten, Zeilenende länger + weich aus). Neue Textspur `render_lyric_track` (Python/Pillow → RGBA-qtrle, 30 fps, ein Overlay): Buchstabe für Buchstabe (`TYPE_S` 0,22 s), kein Zoom/Drehen/Schrägstellen/Höhensprung, weiße Schrift mit weichem Schatten, Schrift Montserrat ExtraBold (OFL, aus @fontsource/montserrat, woff→ttf, Lizenz beigelegt), Größe 170 px, nur zu lange Wörter kleiner. `lyric_schedule`: Wort endet, wenn das nächste (auch Wand-Wort) beginnt → nie zwei gleichzeitig; Zeilenende (LRCLIB-Marke ¶ in `timed_words`, `eol` in `word_list`) hält ≥1,2 s, blendet 0,3 s aus. Wand-Wörter gleiche Schrift, weiß. Echter Lauf (3 Nutzer-Clips, 23 s): 0 Überlappungen, 35 Wörter (11 Wand), Render ~6,5 min.

- 2026-11-17: Kill-Erkennung grundlegend überarbeitet, mit den 3 Original-Clips des Nutzers (9 Kills, Lösung Bild für Bild bestimmt) + 4 eigenen Testclips als Prüfstand: vorher 17/23 richtig, 7 Fehlalarme, 6 verpasst (Nutzer-Clips: 3/9); jetzt 23/23, 0 Fehlalarme, Zeit ±0,1 s. Ursachen: (1) `_boxes` hielt vor orangem/rotem Hintergrund (Mirage-Tuch) alles für Rahmen → Einträge bis 3 s zu spät/gar nicht, Hintergrund als Einträge; jetzt Rahmen = rote Kante (röter als ±3 px), Linienstück vom rechten Rand (`_run_from_right`), Ober-/Unterkante gleich lang, Innen dunkler als Umgebung + helle Schrift. (2) Fingerabdruck trennte nicht (gleich 0,71–0,91 vs. verschieden 0,69–0,87); jetzt Kantenbild des Gegnernamens (`_sig`/`_ncc`, gleich 0,98–1,0 vs. ~0,8), Wiedererkennung über letzte 6 Bilder, gleicher Platz/Breite bis 1,5 s = derselbe, Hochrutschen um einen Platz, Hereinwachsen. (3) Zeit beim Erscheinen: `_first_seen` sucht rückwärts bis 1 s nach der ersten Rahmenkante am Platz beim ersten Erscheinen (`box0`). (4) Schalldämpfer-Schüsse (M4A1-S) werden im Ton nicht erkannt: `kill_start` ohne Schuss 0,35 s vor dem Killfeed (`KILL_NO_SHOT`). Voller Schnitt mit den 3 Clips: 9/9 Kills, jedes Stück vorwärts, Killfeed nach dem Schuss.

- 2026-11-17: Killfeed zu spät / Kill abgeschnitten (Nutzer-Video: Schuss 4,4 s, Killfeed-Einblendung 5,3 s). Ursache in `_boxes`: stehen zwei Einträge direkt untereinander, teilen sie eine rote Linie; die wurde nur einmal verwendet, der untere Eintrag fehlte, bis der obere verschwand. Nachgestellt mit echtem Clip (zweiter Eintrag direkt darunter): erkannt bei 5,8 statt 5,0 s. Jetzt darf jede Linie Unter- und Oberkante sein, Kasten braucht dunklen Grund UND helle Schrift (>3 %). Neu 5,0 s; echte Clips (Original/1366/SAR) weiter 3/3, nachgestellter Ablösefall 4/4.

- 2026-11-17: Clips einfacher Schnitt mit festen Regeln (Nutzer: Zeitlupe zu viel, springt vor/zurück, Szenen doppelt, Killfeed 1–2 s vor dem Kill). `CLEAN_EDIT` (Standard) → `plan_clean`/`_render_clip`: echtes Tempo, jede Clip-Stelle höchstens einmal vorwärts, je Kill ein Stück 1,2 s vor Kill-Schuss bis 1 s nach Killfeed (Kills < 3 s auseinander = ein Stück), Stücke ganze Schläge lang, erster Kill-Schuss auf einem Schlag, Musik ab erstem Schlag (`music_shift`), harte Schnitte (keine Zoom-Übergänge), Killfeed-Einblendung ab Erscheinen im Spiel für 1,8 s, Sync-Anzeige misst nur Kill-Schüsse. Alter Schnitt: `CLEAN_EDIT=False`. Echter Clip: Regeln eingehalten, Kill-Schüsse 0–1 ms (Plan) bzw. ≤7 ms (Schläge in der fertigen Tonspur) auf dem Beat, kein Bild länger als 2x, Render 69 s.

- 2026-11-17: Kills weggeschnitten (Nutzer-Video: bei 9,3 s Killfeed, davor nur Nachladen, der Kill selbst fehlt). Ursache: Kill-Zeitlupe begann pauschal 0,1 s vor dem Killfeed-Eintrag, der Eintrag kommt aber erst nach dem Treffer (echter Clip: Kill-Schuss 0,14–0,34 s davor, beim Nutzer offenbar deutlich mehr). Jetzt `kill_start`: Zeitlupe beginnt 0,08 s vor dem letzten Schuss bis 1,5 s vor dem Eintrag (ohne Schuss wie bisher). Echter Clip: Treffer und fallender Gegner in der Zeitlupe; Sync gemessen 6/9 (vorher 7/7), Kill-Erkennung unverändert.

- 2026-11-17: Songtext doppelt/verzögert (Nutzer): (1) Nutzer-Video Bild für Bild: Wand-Wort lief über einen Schnitt und wurde in der neuen Szene an anderer Wand neu gesetzt → wirkte doppelt. Jetzt `one_scene`: Wand-Wort nur im längsten Stück ohne Schnitt (sonst flach in voller Länge). Echter Clip: 0 Wand-Wörter über Schnitte. (2) Verzögerung: LRCLIB hat nur Zeilen-Zeiten, Wörter waren gleichmäßig verteilt (bis ~1 s daneben). Jetzt `lrclib.refine`: Spracherkennung (Server) setzt Wortzeiten für wiedergefundene Wörter (≤1 s Abweichung), übrige linear nachgezogen, Reihenfolge bleibt; Hinweis zeigt Anzahl. Ohne Spracherkennung hier nur mit nachgebildeten Erkennungen getestet.

- 2026-11-17: Kill clean statt verwischt (Nutzer: zu viel Edit, alles verwischt, Killfeed fehlt): Nutzer-Video Bild für Bild: berechnete Zwischenbilder (mci) zerfallen bei schnellen Bewegungen in verschmierte Blöcke. Jetzt `INTERP` "none" (nur echte Bilder; `interp_vf`), `DEDUP` leer (gemessen gleichmäßigster Takt: Bild steht 1x/2x/3x = 107/35/1), `HIT_SLOW` und `HIT_SLOW_LAST` 0,75, `RAMP_V1` 0,75, `KILL_FX` aus (kein Schwarz-Weiß/Kontrast), `SHOW_FEED`: eigener Killfeed-Eintrag im Hochformat oben im Spielbild (Querformat ist er ohnehin sichtbar); breite Wandfläche erst ab 10 % Höhe. Echter Clip geprüft.

- 2026-11-16: Songtext verdeckte Kills (Nutzer): flache Wörter nie mehr in der Bildmitte (`lyric_pos`: Hochformat über dem Spielbild, frei seit Zähler weg; Querformat unteres Fünftel, kleiner). Wand-Suche hält Bereich ums Fadenkreuz frei (Seiten bis 40 % / ab 60 %, breite Fläche nur obere 5–38 %, dort Wort bis 60 % der Höhe). An 2 Nutzer-Videos gemessen: Wand in jedem Bild, Höhe 121–178 px, 1 von 90 Bildern berührt den Mittelbereich knapp. Echter Clip beide Formate geprüft.

- 2026-11-16: Kill-Erkennung (Nutzer: 6 von 9 erkannt): bisher nur Anzahl roter Einträge gezählt (+2,5 s Lückenfüllung) → verschwand ein alter Eintrag, während ein neuer kam, ging der Kill verloren. Nachgestellt mit echtem Clip (echter Eintrag eingeblendet, als der alte verschwand): alt 2 von 4, neu 4 von 4. Jetzt `kills_from_boxes`: Fingerabdruck je Eintrag (`_sig`: Rahmenbreite + Spaltenprofil heller Schrift, rechtsbündig; `_same`: Breite ±12 px, Profil ±2 Streifen), neuer Fingerabdruck = neuer Kill, gleicher nach Aussetzer = derselbe. Echte Clips (Original, 1366er, SAR) weiter 3/3. Nutzer-Clips mit 9 Kills nicht vorhanden → dort ungeprüft.

- 2026-11-16: Clips lange Wörter nicht auf Wände (Nutzer-Video: "PAPA-PAPARAZZI" winzig): gemessen Schrifthöhe auf Wand NO 193 px, KNOW 161, PROMISE 101, PAPA-PAPARAZZI 59 px. Jetzt `WALL_MAX_ASPECT` 3,6 (Seitenverhältnis des Wort-Bilds, `png_aspect`): breitere Wörter groß in der Mitte. Echter Clip: 14 Wörter, 6 auf Wänden, lange flach lesbar.

- 2026-11-16: Song-Vorschläge laufen beim Nutzer (echte LRCLIB-/Deezer-Daten). Aufgeräumt: `clean_title` entfernt Künstlernamen aus Nutzer-Uploads ("Lady Gaga - Bad Romance", "Poker Face Lady GaGa"), Doppelte nach dem Aufräumen weg, Einträge mit echtem Albumnamen zuerst, Künstler als Album nicht angezeigt.

- 2026-11-16: Song-Vorschläge erschienen beim Nutzer nicht (Ursache von hier nicht prüfbar, Hosts gesperrt): Fehler jetzt sichtbar statt stumm ("Suche …", Grund bei Fehler: LRCLIB/Deezer nicht erreichbar, kein JSON + Status), `suggest_full` mit Fehlertext, LRCLIB und Deezer parallel, Fehler nicht gecacht, Endpunkt fängt Ausnahmen ab. Diagnose: /clips/song-suggest?q=Paparazzi im Browser öffnen.

- 2026-11-16: Clips Song-Vorschläge beim Tippen (Nutzer-Wunsch): `GET /clips/song-suggest?q=` (Login nötig) → `lrclib.suggest` (LRCLIB-Suche, nur Songs mit syncedLyrics, doppelte weg; Bild = Künstlerfoto aus der Deezer-Suche api.deezer.com, sonst Albumcover, nur https; 10 min Cache). Liste unter dem Songname-Feld: rundes Bild, Titel, Künstler · Album, Länge; Maus/Tippen oder Pfeiltasten+Enter; externe Daten nur per textContent. Gesendet wird nur der Suchtext (LRCLIB, Deezer); Bilder lädt der Browser direkt von Deezer (no-referrer). In der Cloud-Session beide Hosts gesperrt: mit nachgebildeten Antworten getestet, Liste im Browser (Playwright) geprüft.

- 2026-11-16: Clips Wand-Wörter (Nutzer: viele gute Wände ungenutzt; LRCLIB-Text "Paparazzi" kam korrekt): Messung am Nutzer-Video: Wand in 100 % der Bilder gefunden, Wort aber nur 31 % der Spielbildbreite, dazu 25-%-Grenze. `wall_text.place` prüft zusätzlich breite Fläche (8–92 %), bevorzugt bei ≥1,2× Halt, Wortbreite 80–85 % der Fläche → Ø 47 %; `wall_picks` wieder 60 %; flache Ersatz-Wörter 80 % Breite. Echter Clip: 7/12 Wörter auf Wänden, 0 Standbilder.

- 2026-11-16: Clips nach Vorbild (Nutzer-Wunsch, alle drei): Format-Auswahl beim Hochladen (`fmt` hoch/quer; `set_layout`: quer = 1920x1080 ganzes Spielbild ohne Hintergrund, Wand-Suche im mittleren Quadrat `BOX_X` 420; `wall_text.apply` mit size/box_x), kein Zähler/Killfeed/"N KILLS" mehr (`SHOW_COUNTER` False), Songtext groß in Bildmitte (Schrift 240, bis 80 % Bildbreite; während Kill tiefer/kleiner), Wand-Wörter höchstens 25 % (`wall_picks`). Echter Clip beide Formate: richtige Größe, 0 Standbilder, Sync 8/8, 12 Wörter (3 Wand); Rechenzeit mit Songtext ~190–210 s.

- 2026-11-16: Clips Ton nach Vorbild (Nutzer-Video, viraler CS2-Edit; gemessen −10,8 LUFS, LRA 3,9, 0,9 herausstechende Schüsse/s; wir −12,7 LUFS, LRA 1,4, 0,2/s). Ton jetzt eigener Graph → mix.wav, Lautheit gemessen und per `level_chain` gleichmäßig auf `TARGET_LUFS` −11 (+ Limiter −1 dBFS) statt loudnorm-Kompression; `GAME_VOL` 0,6, `SHOT_VOL` 1,15, `KILL_VOL` 2,0, `KILL_DUCK` 0,6, Musik bei jedem gemessenen Schuss kurz −45 % (`SHOT_DIP`). Echter Clip: 0,7 Schüsse/s hörbar, −11,1 LUFS, Kill-Schuss +0,7–1,0 dB über Umgebung. Stärkerer Spielton (0,85) getestet: kein Gewinn, verworfen.

- 2026-11-16: Clips Songtext von LRCLIB (Nutzer-Wunsch, Spracherkennung bei Gesang unbrauchbar): neues Modul `lrclib.py` (Suche lrclib.net/api/search per urllib, nur Songname wird gesendet; LRC-Zeilen → Wörter je Zeile verteilt; Stelle im Song: Musikdatei ≈ Songlänge (±4 s) = ganzer Song, sonst Versatz aus ≥3 erkannten Wörtern per Median). Feld "Songname und Künstler" auf /clips, `song` in State/API/make_beat. Ohne Netz/Treffer: Hinweis und bisheriges Verhalten. lrclib.net in der Cloud-Session gesperrt → Abruf nur mit nachgebildeter Antwort getestet; echter Clip + Musik: 11 Wörter zeitlich korrekt eingeblendet (6 auf Wänden). Tests: test_lrclib.py.

- 2026-11-16: Clips Absturz beim Nutzer (concat: SAR 0:1 vs 1280:1281): `setsar=1` am Ende jedes Segments und vor concat. Fehler lokal nicht exakt nachgestellt (Testclips behielten SAR nicht), Korrektur zielt direkt auf die Bedingung der Fehlermeldung. Kill-Verlust geprüft: Planung (guter Stand 1792319 vs. jetzt, 5–9 Kills, 13 s Musik) identisch, Erkennung seit 1792319 unverändert; Nutzer-Videos vor/nach den letzten Änderungen mit denselben Clips beide 5 Kills, 13,07 s. Ursache offen, Original-Clips nötig.

- 2026-11-16: Clips Verschwimmen + Vorspulen (Nutzer-Video: Doppelbilder bei 8,5 s und 11 s im Anlauf vor dem Kill): tmix-Bewegungsunschärfe entfernt (`BLUR` leer), Anlauf/Schnitt/Schluss mit berechneten Zwischenbildern statt Überblenden (`SMOOTH` = `MCI_VF`, Schnitt mit `DEDUP`), Übergang ohne gblur (nur Zoom, Lanczos). Tempo begrenzt: `RAMP_V0` 1,6→1,3, `SHOT_SPEED` 1,25→1,15, `SYNC_MAX` 1,7→1,4, Reststück ≤ 1,1×SYNC_MAX. Echter Clip: höchstes Tempo 1,60→1,30×, Schärfe Median 352→446, unschärfste 5 % 132→174, 0 Standbilder, Sync 8/9; Rechenzeit 84→122 s.

- 2026-11-16: Clips: Segmente parallel rendern (`render_workers`, Kerne bis 4, ThreadPool). Echter Clip, 4 Kerne: 122 s → 81 s, Ergebnis bildgleich (Abweichung 0,0). Geprüft und verworfen: Übersteuerung (Messfehler durch Mono-Mischung; Stereo-Spitze −1,8 dBFS, ok), Kill-Schuss lauter/Riser-Lücke/stärkeres Ducking (gemessen kein Gewinn, da vor dem Kill gleich laute Schüsse liegen). Musik-Stille am Anfang liegt in der Musikdatei selbst.

- 2026-11-16: Clips Kill "weggeschmissen" (Nutzer-Video analysiert): am Ende jedes Kills (außer dem letzten) sprang die Bewegung auf das 4–6-Fache, verursacht durch Velocity-Bogen (30 %, 2×) plus Hineinzoomen 80 ms vor dem Schnitt. Jetzt `OUT_FRAC` 0,2 / `OUT_V` 1,4, kein Bogen bei kurzen Kills (< 1,5 Schläge), Zoom-Übergang nur nach dem Schnitt (`TR_Z` 0,14, Unschärfe sigma 5). Am echten Clip gemessen: letzte Bilder vor dem Schnitt 14–28 → 4–8 (normale Bewegung der Aufnahme), Sync 9/10, 0 Standbilder.

- 2026-11-16: Clips, gemessen am echten Clip: (1) Schärfe: Spielbild wurde bilinear 1,5× hochgerechnet (Laplace-Varianz Quelle 286 → 106); jetzt Lanczos + `SHARPEN` (unsharp 0,5) → 283; fertiges Video 2,4× schärfer. (2) Je Video 4–7 doppelte Einzelbilder kurz nach Schnitten: Segmentlängen nicht auf ganzen Bildern (`frame_grid`, max. 8 ms Verschiebung ohne Aufsummieren) und AAC-Ton länger als das Bild beim gemeinsamen concat (Ton je Segment auf Bildlänge, apad/atrim) → 0 doppelte Bilder, Bild/Ton gleich lang. Verworfen nach Messung: mehrere schlaglange Schnitte vor jedem Kill (kaum mehr sichtbare Schnitte, Sync 7/10, 16 Standbilder); Szenen-Erkennung (scdet) ungeeignet für Schnitte auf derselben Map.

- 2026-11-16: Clips Schuss-Sync nachgemessen statt nur geplant (echter Clip): Spielton der Segmente wie im Video zusammengesetzt, Schüsse neu erkannt, Abstand zum Raster. Vorher 7/9 auf Achtel, 2 je 112 ms daneben (einer im kurzen Schnitt, einer zu dicht im Anlauf). `sync_anchors` rastet jetzt auch auf Sechzehntel ein (Achtel bevorzugt) → 8/8, max. 37 ms. Messung fest in `make_beat` (`sync_report`, ±45 ms, Achtel/Sechzehntel) und auf /clips angezeigt ("Nachgemessen: x von y Schüssen").

- 2026-11-16: Clips, Test mit echtem Material (Original-Clip des Nutzers, 18 s, + Musik, + TikTok-Vorbild; Dateien nur lokal im Scratchpad): Original-Clip hat 35 % doppelte Bilder (40 fps Inhalt) → `DEDUP` (mpdecimate, Standard-Schwellen) vor Anlauf/Kill/Schluss, nicht vor dem kurzen Schnitt (dort entstanden sonst Doppelbilder); Kill-Zeitlupe 5–20 % gleichmäßiger, keine Standbilder. Farbe gemessen: Vorbild Sättigung 0,48 / Wärme 0,23, wir 0,28 / 0,06 → `SAT` 1,6 + `GRADE` (colorbalance), am echten Clip 0,44 / 0,17. Geprüft und verworfen: Anfang zu ruhig (gemessen: unser Anfang hat mehr Bewegung als das Vorbild).

- 2026-11-16: Clips End-to-End-Test (künstliche Clips mit Killfeed + Musik mit Drop bei 12 s, ganze Pipeline): Kills 3/3 erkannt, Drop 12,0 s gefunden, keine stehenden Bilder, −13,8 LUFS. Gefundene Fehler behoben: (1) erster Kill lag einen Schlag nach dem Drop (Beat auf Sekunde 0 wird nicht erkannt) → `beats.drop_start`: Start (k+0,5) Schläge vor dem Drop, jetzt 11,97 s; `clips.DROP_LEAD_S` entfernt. (2) Vignette zu stark (Ecken −46 %) → PI/10 (−19 %). (3) Vignette zeichnete bei nicht quadratischen Pixeln eine harte schwarze Ellipse → `setsar=1` davor.

- 2026-11-16: Clips Velocity-Bogen: Kill-Zeitlupe (außer letztem Kill) beschleunigt in den letzten 30 % linear auf 2× (`OUT_FRAC`, `OUT_V`, `hit_pts`), Schnitt zur nächsten Szene in der Bewegung (Smith & Henderson 2008). Alle Segmente mit `settb=1/60000` vor setpts: bei grobem Zeitraster der Quelle bekamen Bilder sonst denselben Zeitstempel und wurden verworfen.

- 2026-11-16: Clips Sound beim Kill (Nutzer: klingt komisch; Spektrum zeigte den steigenden Sinus im Riser als Pfeifen): Riser nur noch anschwellendes Rauschen, Impact `IMPACT` tiefer und kürzer ohne Knack-Rauschen, `SFX_VOL` 0,45.

- 2026-11-16: Clips Text-Fehler aus Nutzer-Video: Kästchen statt Buchstabe ("MY") → `printable` (NFKC, Doppelgänger aus Kyrillisch u. ä. → Latein, typografische Anführungszeichen, unsichtbare Zeichen weg, Zeichen ohne Glyph weglassen, Prüfung per Pillow-Maske gegen Ersatzkästchen); Wand-Wort extrem perspektivisch verzerrt ("INFORMATION") → `wall_text.limit_perspective` (Höhe links/rechts max. 1,3:1, Neigung max. 0,45).

- 2026-11-16: Clips Laggen behoben (Analyse eines Nutzer-Videos: 13 Stellen mit 3–10 stehenden Bildern, danach Sprung): jedes Segment friert am Ende ein, weil Zwischenbilder nur bis zum letzten Quellbild entstehen und tpad den Rest mit dem letzten Bild füllt (Test: Anlauf 9, Kill 3, Schluss 5 Bilder). Jetzt `_margin`: 0,15 s mehr Quelle einlesen, genau abschneiden (beim Anlauf begrenzt, damit die Tempo-Formel gültig bleibt) → 0 stehende Bilder. MCI ohne Szenenwechsel-Erkennung (`scd=none`), die bei schnellen Schwenks Bilder doppelte.

- 2026-11-16: Clips "nächstes Level": Musikstart leer = automatisch am Drop (`beats.find_drop`/`drop_time`: Bass-Energie 4 s danach vs. davor; `api._music_start` → -1; `clips.DROP_LEAD_S` 1 s vor dem Drop; Anzeige "Musik ab Sekunde …"); Kill-Zeitlupe mit echten Zwischenbildern (`MCI`, minterpolate mci, ca. 15 s Rechenzeit je Kill im Test, `MCI=False` = alt); Höhepunkt: letzter Kill langsamer (`HIT_SLOW_LAST` 0,35), Kill-Abstände eher kürzer werdend (kill_beats). Quellen: Teixeira u. a. 2012, Kahneman 1993.

- 2026-11-16: Clips "gewisses Etwas" (Nutzer wählte Sound-Design + Übergänge): Effekt-Tonspur `sfx_expr` (Riser 1,5 Schläge vor jedem Kill, Impact auf dem Kill, Whoosh am Szenenwechsel, `SFX_VOL`); Zoom-Durchflug mit Unschärfe an Szenenwechseln nach einem Kill (`transition_cuts`, `transition_vf`, auf dem fertigen Bild vor dem Songtext). Quelle Solberg 2014 auf /clips. Test-Korrektur nachgezogen (war im ersten Commit rot).

- 2026-11-16: Gesicherter Stand als Branch `stand-2026-11-16-clips-gut` (1792319). Clips Look/Ende/Ton (Nutzer: Look, Anfang/Ende, Ton stören): Helligkeit je Clip angeglichen (`luma`, `brightness_offsets`, ±0,08) + leichte Vignette (`LOOK`); Schluss ohne Standbild und ohne BOOM, Szene läuft in Zeitlupe weiter (`_render_end`), Ende auf Taktanfang (`end_hold`, Huron 2006); Kill-Schuss in echtem Tempo statt atempo-gestreckt (`KILL_SND_S`); Musik-Ducking weich (40 ms/300 ms) statt Sprung; 6 ms Fades an jedem Schnitt gegen Knacken; Musik-Ausblendung 0,12 s. Quellen auf /clips ergänzt (Smith 2012, Tatler 2007, Huron 2006).

- 2026-11-16: Clips: Ruckeln in der Zeitlupe vor dem Kill beseitigt: Anlauf mit Zwischenbildern (minterpolate blend, wie beim Kill) statt doppelter Bilder; Schuss-Einrasten nur noch mit Tempo 0,5–1,7 und höchstens 2,5-fachem Tempowechsel zum Nachbarstück (`SYNC_JUMP`), vorher waren harte Sprünge 0,35↔2,3 möglich (Nutzer: wirkt ab und zu wie Laggen).

- 2026-11-16: Clips: erfundene Erkennungs-Sätze ("Thanks for watching" u. ä., unsicher + keine Sprache) werden verworfen; Ton vor der Erkennung auf Stimmbereich gefiltert; eingefügter Songtext geht als Vorgabe (initial_prompt) in die Erkennung (Nutzer: bei Diva nur "thanks for watching" erkannt).

- 2026-11-16: Clips: eingefügter Songtext wird mit der Spracherkennung auf den Gesang gelegt (`align_lyrics`, difflib), verpasste Wörter zwischen die Nachbarn verteilt, Text bleibt der eingefügte. Hinweis auf /clips: Text am besten einfügen.

- 2026-11-16: Spracherkennung bei Musik robuster (beam 5, kein Abbruch bei unsicheren Stücken,
  condition_on_previous_text aus); /clips zeigt, wie viele Wörter von wann bis wann erkannt wurden (Nutzer: Lyrics nur
  in den ersten 3 s bei einem neuen Lied).

- 2026-11-16: Schüsse auf dem Beat: `shots` erkennt Schüsse im Spielton (Onset-Spitzen), `sync_anchors` rastet
  Schüsse im Anlauf auf Achtelschläge ein (Tempo je Stück 0,35–2,3x), `_piecewise_pts` verbiegt die Zeit stückweise,
  Schuss-Sounds werden einzeln an ihren Beat-Punkt gesetzt. Peak-End: bei mehreren Clips kommt der mit den meisten
  Kills zuletzt. /clips zeigt „n Schüsse auf dem Beat“ und weitere Quellen (Vroomen & Keetels 2010, Kahneman u. a.
  1993, Berger & Milkman 2012).

- 2026-11-16: Clips, fünf Verbesserungen: Kills auf betonte Schläge (`kill_beats`, Beat-Stärke aus beats.py),
  abwechselnde Abstände 3–6 Schläge statt starr 4 (Cutting, DeLong & Nothelfer 2010, 1/f-Rhythmus der
  Einstellungslängen); gesungene Wörter 40 ms früher (`WORD_LEAD_S`, ITU-R BT.1359: +45/−125 ms); nahtlose Schleife
  (letzte 0,3 s blendet das erste Bild ein, `LOOP_S`); Bewegungsunschärfe in schnellen Teilen (`BLUR`, tmix).

- 2026-11-16: Wand-Text stabil: Verfolgung als Verschiebung + Größe (`wall_text.similarity`, robust, geglättet)
  statt voller Homographie (zitterte), bei kurzem Verlust 0,15 s Ausblenden statt Sprung; Wort kleiner und immer im
  Spielbild; bei einem Schnitt im Zeitfenster sucht das Wort im neuen Bild eine neue Wand (`cuts`), Wörter dürfen auch
  in Kills an die Wand; mehr Wand-Wörter (`wall_picks`: ab 0,28 s gezogen oder 0,2 s Pause, bis 60 %).

- 2026-11-16: /clips zeigt unten den laufenden Code-Stand (`api._code_version`, git-Commit beim Start), um zu sehen,
  ob ein Update auf dem Server angekommen ist.

- 2026-11-16: Wand-Wörter nach Gesang: Spracherkennung liefert Start und Ende je Wort ("a-e:WORT", `word_list`),
  `wall_picks` wählt Wörter, die gezogen werden (ab 0,35 s) oder vor einer Pause stehen (ab 0,25 s), höchstens 40 %;
  diese bleiben an der Wand bis zum nächsten Wort (max. 2,5 s, endet beim Schnitt). Gezogene Wörter werden nicht mehr
  mit dem vorigen zusammengefasst. Eingetippter Text: weiter jedes zweite passende Wort.

- 2026-11-16: Wand-Text auch bei Wörtern, deren Zeitfenster einen Schnitt überspannt (endet dann beim Schnitt,
  mind. `WALL_MIN_S` 0,22 s); vorher fielen mit erkanntem Gesang fast alle Wörter heraus. /clips zeigt je Video, wie
  viele Wörter auf Wänden standen und bei wie vielen keine Wand gefunden wurde.

- 2026-11-16: Test für `wall_text.edge_slopes` mit weichen Kanten (harte Treppenkanten waren unrealistisch);
  Kantenschwelle in `edge_slopes` auf 80. Perzentil (>=), vorher fielen echte Kanten heraus.

- 2026-11-16: Songtext auf Wänden (`wall_text.py`, `memeclip.WALL_TEXT`): jedes zweite passende Wort (kein Schnitt,
  kein Kill im Zeitfenster, mind. 0,3 s, mind. 3 Buchstaben) klebt im Winkel einer Wand und folgt der Kamera.
  OpenCV durfte in der Cloud-Sitzung nicht installiert werden, deshalb eigene Umsetzung ohne neue Abhängigkeit.

- 2026-11-16: Clips: Songtext deutlich kleiner (höchstens 150 px Schrift, 640 px breit) im unteren Drittel des
  Spielbilds statt in der Mitte, schwächeres Aufploppen; verdeckte vorher den Kill.

- 2026-11-16: Clips nach Studien und Plattform-Vorgaben: Schnittpunkte dort, wo Bewegung einsetzt (`motion`,
  `onset_cut`; Smith & Henderson 2008, Edit Blindness), 60 fps, Lautheit -14 LUFS / -1 dBTP (`LOUDNORM`), Musik beim
  Kill kurz -4 dB (Ducking), Zähler und Killfeed oben statt unten (Oberfläche von TikTok/Shorts), zu kurz
  aufeinanderfolgende Wörter werden zu zwei Wörtern zusammengefasst (`MIN_WORD_S`); Erklärung mit Quellen auf /clips.

- 2026-11-16: Clips, Wackeln beim Kill: kein Zoom-Schlag mehr im Anlauf direkt vor dem Kill, Zoom-Schlag bei den
  Schnitten davor halbiert, Kill-Zeitlupe 0,5x statt 0,3x (`HIT_SLOW`) mit überblendeten Zwischenbildern
  (minterpolate blend) statt verdoppelter Bilder.

- 2026-11-16: `sung_words` liest den Ton selbst per ffmpeg ein und übergibt ihn als Array (auf dem Server scheiterte
  die Erkennung an einer alten PyAV-Version: open() ... metadata_errors).

- 2026-11-16: Clips: genauer Grund, wenn kein Songtext erkannt wurde (`memeclip.SUNG_NOTE`: nicht installiert mit
  Python-Pfad der App und Installationsbefehl, fehlgeschlagen mit Fehlertext, oder keine Wörter erkannt).

- 2026-11-16: Clips: beim Kill kein Zoom und kein weißer Blitz mehr (`Z_HIT` 1.0), das Bild sprang; der Kill wird nur
  noch durch Zeitlupe, Schwarzweiß-Moment, Zähler und Killfeed betont.

- 2026-11-16: Beat-Schnitt als Takt-Montage: je Kill `shot` (eigener Schnitt, 1 Schlag) + `ramp` (1 Schlag) + `hit`
  (2 Schläge), jeder Bildwechsel auf einem Schlag mit Zoom-Schlag (`CUT_POP`), Kill beginnt schwarzweiß und wird farbig;
  Songtext automatisch aus dem Gesang (`sung_words`, nur wenn faster-whisper auf dem Server installiert ist, hier
  ungetestet: Installation in der Cloud-Sitzung abgelehnt), sonst eingetragener Text.

- 2026-11-16: Beat-Schnitt nach Rückmeldung: Anlauf höchstens 1,6x (vorher 2,4x), Kill bleibt zwei Schläge in
  Zeitlupe 0,3x (`HIT_SLOW`), Spielton im Anlauf leiser; Songtext wird während des Kills nicht mehr ausgeblendet,
  sondern klein am unteren Rand gezeigt; Hinweis auf /clips, dass Songtext eingetragen werden muss.

- 2026-11-16: Clips: je Clip ein eigenes Auswahlfeld statt Mehrfach-Auswahl (Android meldete „network error“ beim
  Lesen), Knopf „+ Weiteren Clip“; Hinweis im Fehlertext. `backend/data/clips/` steht jetzt in .gitignore, versehentlich
  committete Testdateien wurden wieder entfernt (liegen noch im Verlauf, Bereinigung braucht die Erlaubnis des Nutzers).

- 2026-11-16: Clips-Upload liest Dateien per stream, wenn das Handy Größe 0 meldet (vorher kam kein Stück an);
  klare Meldung, wenn eine Datei wirklich 0 Bytes liefert (z. B. nur in der Cloud).

- 2026-11-16: Clips-Upload: genaue Fehlermeldungen je Ursache; `CLIPS_API` (api.py) gegen `v` in clips.html meldet,
  wenn nach einem Update der Neustart fehlt (Templates kommen frisch von der Platte, der Python-Code nicht).

- 2026-11-16: Clips nehmen Dateien unabhängig von der Endung an (`clips.safe_ext`; Handy-Namen ohne Endung führten zu
  „Video bitte als .mp4 …“); unlesbare Dateien melden sich erst beim Schnitt als Fehler.

- 2026-11-16: Clips: mehrere Videos je Auftrag, gleitendes Tempo statt Sprüngen, fester Kill-Abstand im Takt,
  Songtext als gestaltete Schrift (Pillow + Anton); neue Abhängigkeit pillow (Server: pip install -e backend).

- 2026-11-16: Clip-Upload in Stücken mit Fortschrittsanzeige (behebt ERR_FAILED beim Hochladen).

- 2026-11-16: Clips in der App (`clips.py`, `/clips`); Schnitt ruhiger (kein Zoom-Stoß je Schlag, Kill-Zoom 1,12),
  Songtext größer mit Schatten und wechselnder Höhe.

- 2026-11-15: Beat-Edit (`beats.py`, `memeclip.make_beat`): Kills auf den Beat, Songtext Wort für Wort.

- 2026-11-15: Meme-Clip v2 nach Rückmeldung: Zoom-Schlag statt langsamem Zoom, Kill in Zeitlupe sichtbar, kein
  Wackeln, Quadrat-Aufbau, damit der Gegner nicht aus dem Bild fällt.

- 2026-11-15: Prototyp Meme-Clip (`memeclip.py`): Kill-Erkennung im Video und automatischer Hochformat-Edit.

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
