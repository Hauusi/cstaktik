# Rohdaten: Pro-Demos

`.dem`-Dateien werden per Git LFS getrackt (siehe `.gitattributes` im Repo-Root).

## Aktuell abgelegt

| Datei | Team im Fokus (Abschnitt 7.1: nur MOUZ-Taktiken, nicht Gegner) | Map | Quelle |
|---|---|---|---|
| _wird beim Upload ergänzt_ | MOUZ | - | HLTV/manueller Download |

## Hinweis (harte Regel, Abschnitt 10)

Diese Demos dienen ausschließlich als Rohdaten für die Pipeline (Abschnitt 7). Es werden
keine Koordinaten/Timings/Lineups erfunden — alles wird aus den geparsten Demo-Daten
abgeleitet. Die Pipeline filtert pro Demo auf das im Team-Filter angegebene Team; Runden
des Gegner-Teams fließen nicht in Strat-Kandidaten ein.

## Format

Dateiname-Konvention: `<map>_<team1>_vs_<team2>_<event-oder-datum>.dem`
Beispiel: `dust2_mouz_vs_spirit_2026-01-15.dem`
