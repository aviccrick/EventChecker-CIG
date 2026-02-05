from __future__ import annotations

from datetime import datetime, timezone
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
from typing import Optional

from helper_state import (
    HelperState,
    load_config,
    save_config,
    compute_next_run,
    DEFAULT_INTERVAL_MINUTES,
)
from helper_runner import build_run_command
from helper_ui import inject_toolbar, render_empty_page

REPO_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = Path.home() / ".cricknet-checker" / "config.json"
REPORT_PATH = REPO_ROOT / "reports" / "latest.html"

STATE = HelperState()
STATE_LOCK = threading.Lock()
STOP_EVENT = threading.Event()
LAST_REFRESH_AT: Optional[datetime] = None


def isoformat_or_none(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def build_status_payload(state: HelperState) -> dict:
    global LAST_REFRESH_AT
    refresh = False
    if state.last_run is not None:
        if LAST_REFRESH_AT is None or state.last_run > LAST_REFRESH_AT:
            refresh = True
            LAST_REFRESH_AT = state.last_run

    return {
        "state": "running" if state.running else "idle",
        "paused": state.paused,
        "last_run": isoformat_or_none(state.last_run),
        "next_run": isoformat_or_none(state.next_run),
        "last_error": state.last_error,
        "refresh_report": refresh,
    }


def run_checker_async() -> None:
    with STATE_LOCK:
        if STATE.running:
            return
        STATE.running = True
        STATE.last_error = ""

    def _worker() -> None:
        cmd = build_run_command(REPO_ROOT)
        result = subprocess.run(cmd, capture_output=True, text=True)
        now = datetime.now(timezone.utc)
        with STATE_LOCK:
            STATE.running = False
            STATE.last_run = now
            if result.returncode != 0:
                STATE.last_error = (result.stderr or result.stdout or "").strip()
            STATE.next_run = compute_next_run(
                now,
                STATE.interval_minutes,
                STATE.paused,
                STATE.last_run,
            )

    threading.Thread(target=_worker, daemon=True).start()


def scheduler_loop() -> None:
    while not STOP_EVENT.is_set():
        with STATE_LOCK:
            due = (
                (not STATE.paused)
                and (STATE.next_run is not None)
                and (datetime.now(timezone.utc) >= STATE.next_run)
                and (not STATE.running)
            )
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
            if REPORT_PATH.exists():
                html = inject_toolbar(REPORT_PATH.read_text(encoding="utf-8"))
            else:
                html = render_empty_page()
            self._send(200, html)
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
                STATE.next_run = compute_next_run(
                    datetime.now(timezone.utc),
                    STATE.interval_minutes,
                    STATE.paused,
                    STATE.last_run,
                )
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
        STATE.next_run = compute_next_run(
            datetime.now(timezone.utc),
            STATE.interval_minutes,
            STATE.paused,
            STATE.last_run,
        )

    threading.Thread(target=scheduler_loop, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
