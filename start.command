#!/bin/zsh
set -e
cd "$(dirname "$0")"

PLIST="$HOME/Library/LaunchAgents/com.cricknet.checker.plist"
LABEL="com.cricknet.checker"

running=0
if launchctl print "gui/$UID/$LABEL" >/dev/null 2>&1; then
  running=1
fi

if [ "$running" -eq 1 ]; then
  echo "Helper already running."
else
  echo "Starting helper..."
  launchctl bootstrap "gui/$UID" "$PLIST"
fi

launchctl kickstart -k "gui/$UID/$LABEL" >/dev/null 2>&1 || true

ready=0
for _ in {1..20}; do
  if curl -fsS "http://127.0.0.1:8765/status" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 0.2
done

if [ "$ready" -ne 1 ]; then
  echo "Helper did not respond yet. You can still try:"
fi

echo "Open http://localhost:8765"
echo "If that fails, try http://127.0.0.1:8765"

if command -v open >/dev/null 2>&1; then
  open "http://localhost:8765"
fi
