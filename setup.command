#!/bin/zsh
set -e
cd "$(dirname "$0")"

echo "------------------------------------------------"
echo "Starting Setup..."
echo "------------------------------------------------"

if ! xcode-select -p >/dev/null 2>&1; then
  echo "Apple Command Line Tools are missing."
  echo "Requesting install now..."
  xcode-select --install
  echo ""
  echo "IMPORTANT: A pop-up window has appeared."
  echo "Please click 'Install' on that pop-up."
  echo "Once the installation has FINISHED, run this script again."
  echo ""
  echo "Press Enter to close this window..."
  read
  exit 1
fi

rm -rf .venv

echo "Creating Python environment..."
python3 -m venv .venv
source .venv/bin/activate

echo "Installing libraries (this may take a minute)..."
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

echo "Installing browser..."
python3 -m playwright install chromium

PLIST="$HOME/Library/LaunchAgents/com.cricknet.checker.plist"
LOG_DIR="$HOME/Library/Logs"
mkdir -p "$LOG_DIR"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.cricknet.checker</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(pwd)/.venv/bin/python3</string>
    <string>$(pwd)/helper.py</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <false/>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/CrickNetChecker.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/CrickNetChecker.err.log</string>
</dict>
</plist>
EOF

chmod +x run.command
chmod +x start.command

launchctl bootstrap "gui/$UID" "$PLIST" || true
launchctl kickstart -k "gui/$UID/com.cricknet.checker" || true

echo ""
echo "------------------------------------------------"
echo "✅ Setup complete!"
echo "Open http://localhost:8765 in your browser."
echo "To stop the helper, click 'Stop helper' in the UI."
echo "To restart, double-click 'start.command' or log out/in."
echo "You can still run 'run.command' to generate reports."
echo "------------------------------------------------"
echo "Press Enter to exit..."
read
