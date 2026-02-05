# Local Helper (LaunchAgent + Localhost UI) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a macOS LaunchAgent-backed localhost UI that lets users run reports on demand or via a schedule without using the terminal.

**Architecture:** A lightweight Python helper server (stdlib `http.server`) exposes a local UI and JSON endpoints. It runs `checker.py` in a subprocess and manages schedule state stored in a local config file. LaunchAgent starts the helper at login, with manual restart via `start.command`.

**Tech Stack:** Python 3 stdlib, zsh (`setup.command`, `start.command`), launchd LaunchAgent.

---

### Task 1: Add helper state/config module

**Files:**
- Create: `helper_state.py`
- Create: `tests/test_helper_state.py`

**Step 1: Write the failing tests**

```python
import unittest
from datetime import datetime, timedelta, timezone

class TestHelperState(unittest.TestCase):
    def test_default_config_values(self):
        from helper_state import load_config
        cfg = load_config("/tmp/nonexistent-config.json")
        self.assertEqual(cfg["interval_minutes"], 360)
        self.assertFalse(cfg["paused"])

    def test_compute_next_run_paused(self):
        from helper_state import compute_next_run
        now = datetime(2026, 2, 5, 12, 0, tzinfo=timezone.utc)
        self.assertIsNone(compute_next_run(now, 360, paused=True, last_run=None))

    def test_compute_next_run_from_last(self):
        from helper_state import compute_next_run
        now = datetime(2026, 2, 5, 12, 0, tzinfo=timezone.utc)
        last = now - timedelta(hours=1)
        nxt = compute_next_run(now, 360, paused=False, last_run=last)
        self.assertEqual(nxt, last + timedelta(minutes=360))

if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run tests to verify they fail**

Run: `python -m unittest tests/test_helper_state.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'helper_state'`

**Step 3: Write minimal implementation**

```python
# helper_state.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Optional, Dict, Any

DEFAULT_INTERVAL_MINUTES = 360  # 6 hours

@dataclass
class HelperState:
    running: bool = False
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    last_error: str = ""
    paused: bool = False
    interval_minutes: int = DEFAULT_INTERVAL_MINUTES


def load_config(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"interval_minutes": DEFAULT_INTERVAL_MINUTES, "paused": False}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {
            "interval_minutes": int(data.get("interval_minutes", DEFAULT_INTERVAL_MINUTES)),
            "paused": bool(data.get("paused", False)),
        }
    except Exception:
        return {"interval_minutes": DEFAULT_INTERVAL_MINUTES, "paused": False}


def save_config(path: str, interval_minutes: int, paused: bool) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"interval_minutes": int(interval_minutes), "paused": bool(paused)}
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def compute_next_run(
    now: datetime,
    interval_minutes: int,
    paused: bool,
    last_run: Optional[datetime],
) -> Optional[datetime]:
    if paused:
        return None
    if last_run is None:
        return now + timedelta(minutes=interval_minutes)
    return last_run + timedelta(minutes=interval_minutes)
```

**Step 4: Run tests to verify they pass**

Run: `python -m unittest tests/test_helper_state.py`
Expected: PASS (`OK`)

**Step 5: Commit**

```bash
git add helper_state.py tests/test_helper_state.py
git commit -m "feat: add helper state and config"
```

---

### Task 2: Add helper runner module

**Files:**
- Create: `helper_runner.py`
- Create: `tests/test_helper_runner.py`

**Step 1: Write the failing tests**

```python
import unittest
from pathlib import Path

class TestHelperRunner(unittest.TestCase):
    def test_build_command_uses_venv_python(self):
        from helper_runner import build_run_command
        cmd = build_run_command(Path("/tmp/repo"))
        self.assertEqual(cmd[0], "/tmp/repo/.venv/bin/python3")
        self.assertEqual(cmd[1], "/tmp/repo/checker.py")

if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run tests to verify they fail**

Run: `python -m unittest tests/test_helper_runner.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'helper_runner'`

**Step 3: Write minimal implementation**

```python
# helper_runner.py
from __future__ import annotations
from pathlib import Path
from typing import List


def build_run_command(repo_root: Path) -> List[str]:
    python_path = repo_root / ".venv" / "bin" / "python3"
    checker_path = repo_root / "checker.py"
    return [str(python_path), str(checker_path)]
```

**Step 4: Run tests to verify they pass**

Run: `python -m unittest tests/test_helper_runner.py`
Expected: PASS (`OK`)

**Step 5: Commit**

```bash
git add helper_runner.py tests/test_helper_runner.py
git commit -m "feat: add helper runner command builder"
```

---

### Task 3: Add helper UI renderer

**Files:**
- Create: `helper_ui.py`
- Create: `tests/test_helper_ui.py`

**Step 1: Write the failing tests**

```python
import unittest

class TestHelperUI(unittest.TestCase):
    def test_index_html_contains_controls(self):
        from helper_ui import render_index_html
        html = render_index_html()
        self.assertIn("Run now", html)
        self.assertIn("Pause scheduling", html)
        self.assertIn("Stop helper", html)

if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run tests to verify they fail**

Run: `python -m unittest tests/test_helper_ui.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'helper_ui'`

**Step 3: Write minimal implementation**

```python
# helper_ui.py
from __future__ import annotations

def render_index_html() -> str:
    return """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>CrickNet Checker</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 0; }
    header { position: sticky; top: 0; background: #111; color: #fff; padding: 12px 16px; display: flex; gap: 8px; align-items: center; }
    header button { padding: 8px 12px; border: 0; cursor: pointer; }
    header .primary { background: #2d7ef7; color: #fff; }
    header .danger { background: #c0392b; color: #fff; }
    header .status { margin-left: auto; font-size: 12px; opacity: 0.9; }
    main { height: calc(100vh - 56px); }
    iframe { width: 100%; height: 100%; border: 0; }
  </style>
</head>
<body>
  <header>
    <button class="primary" id="run-btn">Run now</button>
    <button id="pause-btn">Pause scheduling</button>
    <button class="danger" id="stop-btn">Stop helper</button>
    <div class="status" id="status">Loading status…</div>
  </header>
  <main>
    <iframe id="report-frame" src="/report"></iframe>
  </main>
  <script>
    async function post(path, body) {
      const res = await fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body || {}) });
      return res.json();
    }
    async function refreshStatus() {
      const res = await fetch("/status");
      const data = await res.json();
      const statusEl = document.getElementById("status");
      statusEl.textContent = `State: ${data.state} | Last: ${data.last_run || "—"} | Next: ${data.next_run || "—"}`;
      document.getElementById("pause-btn").textContent = data.paused ? "Resume scheduling" : "Pause scheduling";
      if (data.refresh_report) {
        document.getElementById("report-frame").src = "/report?ts=" + Date.now();
      }
    }
    document.getElementById("run-btn").onclick = async () => { await post("/run"); await refreshStatus(); };
    document.getElementById("pause-btn").onclick = async () => { await post("/pause"); await refreshStatus(); };
    document.getElementById("stop-btn").onclick = async () => {
      const ok = confirm("Stop everything? This will close the local app and scheduled checks. To restart, run start.command or log out/in.");
      if (ok) { await post("/shutdown"); }
    };
    refreshStatus();
    setInterval(refreshStatus, 5000);
  </script>
</body>
</html>
"""
```

**Step 4: Run tests to verify they pass**

Run: `python -m unittest tests/test_helper_ui.py`
Expected: PASS (`OK`)

**Step 5: Commit**

```bash
git add helper_ui.py tests/test_helper_ui.py
git commit -m "feat: add helper UI renderer"
```

---

### Task 4: Implement helper server and scheduler

**Files:**
- Create: `helper.py`
- Create: `tests/test_helper_server.py`
- Modify: `helper_state.py`

**Step 1: Write the failing tests**

```python
import unittest
from datetime import datetime, timezone

class TestHelperServer(unittest.TestCase):
    def test_status_payload_includes_fields(self):
        from helper_state import HelperState
        from helper import build_status_payload
        state = HelperState(running=False, paused=True)
        payload = build_status_payload(state)
        self.assertIn("state", payload)
        self.assertIn("paused", payload)
        self.assertIn("last_run", payload)
        self.assertIn("next_run", payload)

    def test_iso_formatting(self):
        from helper import isoformat_or_none
        dt = datetime(2026, 2, 5, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(isoformat_or_none(dt), "2026-02-05T12:00:00+00:00")

if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run tests to verify they fail**

Run: `python -m unittest tests/test_helper_server.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'helper'`

**Step 3: Write minimal implementation**

```python
# helper.py
from __future__ import annotations
from datetime import datetime, timezone
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
from typing import Optional

from helper_state import HelperState, load_config, save_config, compute_next_run, DEFAULT_INTERVAL_MINUTES
from helper_runner import build_run_command
from helper_ui import render_index_html

REPO_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = Path.home() / ".cricknet-checker" / "config.json"
REPORT_PATH = REPO_ROOT / "reports" / "latest.html"

STATE = HelperState()
STATE_LOCK = threading.Lock()
STOP_EVENT = threading.Event()


def isoformat_or_none(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def build_status_payload(state: HelperState) -> dict:
    return {
        "state": "running" if state.running else "idle",
        "paused": state.paused,
        "last_run": isoformat_or_none(state.last_run),
        "next_run": isoformat_or_none(state.next_run),
        "last_error": state.last_error,
        "refresh_report": False,
    }


def run_checker_async() -> None:
    with STATE_LOCK:
        if STATE.running:
            return
        STATE.running = True
        STATE.last_error = ""

    def _worker():
        cmd = build_run_command(REPO_ROOT)
        result = subprocess.run(cmd, capture_output=True, text=True)
        now = datetime.now(timezone.utc)
        with STATE_LOCK:
            STATE.running = False
            STATE.last_run = now
            if result.returncode != 0:
                STATE.last_error = (result.stderr or result.stdout or "").strip()
            STATE.next_run = compute_next_run(now, STATE.interval_minutes, STATE.paused, STATE.last_run)

    threading.Thread(target=_worker, daemon=True).start()


def scheduler_loop() -> None:
    while not STOP_EVENT.is_set():
        with STATE_LOCK:
            due = (not STATE.paused) and (STATE.next_run is not None) and (datetime.now(timezone.utc) >= STATE.next_run) and (not STATE.running)
        if due:
            run_checker_async()
        time.sleep(5)


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: str, content_type: str = "text/html") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def do_GET(self) -> None:
        if self.path == "/":
            self._send(200, render_index_html())
            return
        if self.path.startswith("/report"):
            if REPORT_PATH.exists():
                self._send(200, REPORT_PATH.read_text(encoding="utf-8"), "text/html")
            else:
                self._send(200, "<p>No report generated yet. Click Run now.</p>")
            return
        if self.path == "/status":
            with STATE_LOCK:
                payload = build_status_payload(STATE)
            self._send(200, json.dumps(payload), "application/json")
            return
        self._send(404, "Not found")

    def do_POST(self) -> None:
        if self.path == "/run":
            run_checker_async()
            with STATE_LOCK:
                payload = build_status_payload(STATE)
            self._send(200, json.dumps(payload), "application/json")
            return
        if self.path == "/pause":
            with STATE_LOCK:
                STATE.paused = not STATE.paused
                save_config(str(CONFIG_PATH), STATE.interval_minutes, STATE.paused)
                STATE.next_run = compute_next_run(datetime.now(timezone.utc), STATE.interval_minutes, STATE.paused, STATE.last_run)
                payload = build_status_payload(STATE)
            self._send(200, json.dumps(payload), "application/json")
            return
        if self.path == "/shutdown":
            self._send(200, json.dumps({"ok": True}), "application/json")
            STOP_EVENT.set()
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        self._send(404, "Not found")


def main() -> None:
    cfg = load_config(str(CONFIG_PATH))
    with STATE_LOCK:
        STATE.interval_minutes = int(cfg.get("interval_minutes", DEFAULT_INTERVAL_MINUTES))
        STATE.paused = bool(cfg.get("paused", False))
        STATE.next_run = compute_next_run(datetime.now(timezone.utc), STATE.interval_minutes, STATE.paused, STATE.last_run)

    threading.Thread(target=scheduler_loop, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
```

**Step 4: Run tests to verify they pass**

Run: `python -m unittest tests/test_helper_server.py`
Expected: PASS (`OK`)

**Step 5: Commit**

```bash
git add helper.py tests/test_helper_server.py helper_state.py
git commit -m "feat: add helper server and scheduler"
```

---

### Task 5: Add LaunchAgent + start command

**Files:**
- Create: `start.command`
- Modify: `setup.command`
- Modify: `run.command`

**Step 1: Write the failing tests**

No automated tests for shell scripts. Add a manual checklist after implementation.

**Step 2: Implement start command**

```bash
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
```

**Step 3: Update setup.command to install LaunchAgent**

```bash
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

chmod +x start.command
launchctl bootstrap "gui/$UID" "$PLIST" || true
launchctl kickstart -k "gui/$UID/com.cricknet.checker" || true
```

**Step 4: Update setup.command success message**

Add:
- “Open http://localhost:8765 in your browser”
- “To stop helper, click Stop helper in the UI”
- “To restart, double-click start.command or log out/in”

**Step 5: Update run.command message**

Add a note:
- “Tip: You can also use the local helper UI at http://localhost:8765”

**Step 6: Commit**

```bash
git add setup.command start.command run.command
git commit -m "feat: add LaunchAgent startup scripts"
```

---

### Task 6: Manual smoke test checklist

**Files:**
- Modify: `docs/plans/2026-02-05-local-helper-implementation-plan.md`

**Step 1: Add a checklist block**

Add a short manual checklist at the end of this plan:
- Setup installs LaunchAgent and starts helper
- UI loads at http://localhost:8765
- Run now triggers report generation and updates latest report
- Pause/resume scheduling works
- Stop helper shuts down UI and does not auto-restart until next login
- start.command restarts helper

**Step 2: Commit**

```bash
git add docs/plans/2026-02-05-local-helper-implementation-plan.md
git commit -m "docs: add helper smoke test checklist"
```

---

### Full Test Run

Run: `python -m unittest`
Expected: PASS (`OK`)

### Manual Smoke Test Checklist

- Setup installs LaunchAgent and starts helper
- UI loads at http://localhost:8765
- Run now triggers report generation and updates latest report
- Pause/resume scheduling works
- Stop helper shuts down UI and does not auto-restart until next login
- start.command restarts helper
