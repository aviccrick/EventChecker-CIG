# LaunchAgent + Localhost UI Design (macOS)

Date: 2026-02-05
Owner: CrickNet Checker
Status: Approved

## Goals
- Make report generation usable for non-technical users.
- Provide both manual runs and scheduled runs.
- Avoid admin privileges and keep macOS-only flow.
- Preserve existing `checker.py` behavior and report output.

## Non-goals
- Cross-platform support.
- Rewriting the report renderer or changing report content.
- Replacing `checker.py` or Playwright login flow.

## Summary
Add a user-level LaunchAgent that runs a lightweight local helper server. The server exposes a localhost UI where users can run the report on demand and enable/disable scheduling. It serves the existing `reports/latest.html` and adds controls and status. A full stop shuts down the helper without auto-restart until next login. A `start.command` allows manual restart. Logging out/in also restarts the helper.

## Architecture
- `setup.command` installs the venv and installs a LaunchAgent plist in `~/Library/LaunchAgents/`.
- LaunchAgent runs the helper at login (`RunAtLoad=true`, `KeepAlive=false`).
- Helper hosts a small localhost UI at `http://localhost:8765`.
- Helper triggers `checker.py` via the venv and serves the generated report.

## Components
- `helper.py`
  - HTTP server (Flask or minimal stdlib) hosting UI and status endpoints.
  - Subprocess runner for `checker.py`.
  - In-process scheduler (threading/timers).
- `config.json` (e.g., `~/.cricknet-checker/config.json`)
  - Stores schedule interval and pause state.
  - Stores last run timestamp and last error message.
- LaunchAgent plist
  - User-level agent to run helper on login.
- `start.command`
  - Starts the LaunchAgent immediately without logout/login.

## UI/UX
- Control header (pinned):
  - `Run now` (primary action).
  - `Pause scheduling` toggle.
  - `Stop helper` (danger).
  - Status chip: last run, next run/paused, current state.
- Report content below (embedded `reports/latest.html`).
- Errors shown inline with simple guidance.
- Stop confirmation modal: “This stops the local app and scheduled checks. To restart, run `start.command` or log out/in.”

## Data Flow
1. User opens `http://localhost:8765`.
2. UI loads status from `/status`.
3. `Run now` calls `POST /run`.
4. Helper runs `checker.py` in venv, updates status, captures logs.
5. On completion, UI refreshes report and timestamps.
6. Scheduler triggers periodic runs unless paused.

## Scheduling
- Default interval: 6 hours.
- `Pause scheduling` disables the timer but keeps UI and manual runs.
- Unpausing schedules next run immediately from “now + interval”.

## Stop/Restart
- `Stop helper` calls `/shutdown` and terminates the server.
- With `KeepAlive=false`, helper will not auto-restart until next login.
- Restart options:
  - Double-click `start.command`.
  - Log out/in (auto-start at login).

## Error Handling
- Concurrent run guard: ignore new runs while running.
- Missing report: show empty state until first run.
- Login required: surface message and allow manual run to open browser.
- Network failure: show last error, preserve last report.
- Port conflict: use fixed port 8765 and show clear error if bound fails.

## Testing Checklist
- Setup installs venv, playwright, LaunchAgent, and helper starts on login.
- Manual run updates report and status.
- Pause/unpause prevents/allows scheduled runs.
- Stop helper shuts down and does not auto-restart until login.
- `start.command` restarts helper without logout.
- Errors are visible and do not crash the UI.

## Rollout
- Update repo and instruct users to re-run `setup.command` once.
- Share new entry point: `http://localhost:8765`.
- Keep `run.command` as a fallback.
