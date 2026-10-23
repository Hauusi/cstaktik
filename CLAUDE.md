# Arbeitsweise in diesem Repo

1. Vor jeder Änderung zuerst `STATUS.md` lesen. Sie enthält Stand, Struktur, Regeln, Server-Befehle und offene
   Punkte. Nicht den Chat-Verlauf durchsuchen, um den Stand zu rekonstruieren; nur gezielt Code lesen, den die
   Aufgabe betrifft.
2. Nach jeder Änderung `STATUS.md` im selben Commit aktualisieren: betroffene Abschnitte (Funktionen, Seiten,
   Module, Offen, Entscheidungen) und eine Zeile im Änderungsprotokoll. Ein Stop-Hook
   (`.claude/hooks/status-check.sh`) blockiert das Ende, wenn Code unter `backend/` geändert wurde, ohne dass
   `STATUS.md` mitgezogen ist.
3. Die festen Regeln stehen in `STATUS.md`, Abschnitt 2. Sie gelten immer.
