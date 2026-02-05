#!/bin/zsh
set -e
cd "$(dirname "$0")"

PLIST="$HOME/Library/LaunchAgents/com.cricknet.checker.plist"
LABEL="com.cricknet.checker"

if launchctl list | grep -q "$LABEL"; then
  launchctl kickstart -k "gui/$UID/$LABEL"
else
  launchctl bootstrap "gui/$UID" "$PLIST"
fi

echo "Helper started. Open http://localhost:8765"
