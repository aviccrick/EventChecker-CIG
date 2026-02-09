#!/bin/zsh
set -e
cd "$(dirname "$0")"

LABEL="com.cricknet.checker"

if curl -fsS -X POST "http://127.0.0.1:8765/shutdown" >/dev/null 2>&1; then
  echo "Helper shutdown requested."
else
  echo "Helper not responding on http://127.0.0.1:8765 (may already be stopped)."
fi

launchctl bootout "gui/$UID/$LABEL" >/dev/null 2>&1 || true

echo "Helper stopped."
