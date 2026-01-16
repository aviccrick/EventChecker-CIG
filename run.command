#!/bin/zsh
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "⚠️  Setup not found."
  echo "Please run 'setup.command' first."
  echo "Press Enter to exit..."
  read
  exit 1
fi

echo "Generating report... please wait..."

./.venv/bin/python3 checker.py "$@"

echo ""
if [ -f "reports/latest.html" ]; then
  echo "Opening report..."
  open "reports/latest.html"
else
  echo "❌ Report was not generated."
fi

echo "Done. Press Enter to close..."
read