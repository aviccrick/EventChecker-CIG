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

chmod +x run.command

echo ""
echo "------------------------------------------------"
echo "✅ Setup complete!"
echo "You can now run 'run.command' to generate reports."
echo "------------------------------------------------"
echo "Press Enter to exit..."
read