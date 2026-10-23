#!/bin/sh
# Stop-Hook: Wurde Code unter backend/ geändert (committet seit der letzten STATUS.md-Änderung oder noch offen),
# ohne STATUS.md mitzuziehen, wird das Ende einmal blockiert mit dem Hinweis, STATUS.md zu aktualisieren.
input=$(cat)
case "$input" in *'"stop_hook_active":true'*|*'"stop_hook_active": true'*) exit 0 ;; esac
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}" 2>/dev/null || exit 0
git rev-parse --git-dir >/dev/null 2>&1 || exit 0
[ -n "$(git status --porcelain -- STATUS.md)" ] && exit 0
last=$(git log -1 --format=%H -- STATUS.md 2>/dev/null)
committed=""
[ -n "$last" ] && committed=$(git diff --name-only "$last" HEAD -- backend 2>/dev/null)
open=$(git status --porcelain -- backend 2>/dev/null)
if [ -n "$committed$open" ]; then
  echo '{"decision":"block","reason":"Code unter backend/ wurde geändert, STATUS.md aber nicht. Bitte STATUS.md aktualisieren (betroffene Abschnitte und Änderungsprotokoll) und mit committen."}'
fi
exit 0
