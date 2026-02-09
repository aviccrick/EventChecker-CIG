from __future__ import annotations

import re


def build_toolbar_html() -> str:
    return """
<div id="helper-controls" class="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_280px] gap-4 mb-6">
  <div class="stat-box bg-white p-4 rounded-lg shadow-sm border border-slate-100">
    <div class="text-xs uppercase font-bold text-slate-400">Report & Schedule</div>
    <div class="mt-2 flex flex-wrap gap-2">
      <button class="btn btn-sm btn-primary" id="run-btn">Generate Report</button>
      <button class="btn btn-sm" id="pause-btn">Pause Scheduled Runs</button>
      <button class="btn btn-sm btn-error" id="stop-btn">Stop App</button>
    </div>
    <div class="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
      <span class="badge badge-outline" id="state-badge">Idle</span>
      <span id="status-last">Last: —</span>
      <span>•</span>
      <span id="status-next">Next: —</span>
    </div>
    <div id="error-banner" class="alert alert-error mt-3 hidden">
      <span id="error-text">An error occurred.</span>
    </div>
  </div>
  <div class="stat-box bg-white p-4 rounded-lg shadow-sm border border-slate-100">
    <div class="text-xs uppercase font-bold text-slate-400">Next Scheduled Run</div>
    <div class="text-lg font-medium" id="next-run">—</div>
  </div>
</div>
"""


def build_toolbar_script() -> str:
    return """
<script id="helper-script">
  let helperCountdownTarget = null;
  let helperCountdownPaused = false;
  async function post(path, body) {
    const res = await fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body || {}) });
    return res.json();
  }
  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }
  function setBadge(state) {
    const badge = document.getElementById("state-badge");
    if (!badge) return;
    badge.textContent = state === "running" ? "Running" : "Idle";
    badge.classList.remove("badge-outline", "badge-warning", "badge-success");
    badge.classList.add(state === "running" ? "badge-warning" : "badge-outline");
  }
  function setCountdownValue(el, value) {
    if (!el) return;
    const v = Math.max(0, value | 0);
    el.style.setProperty("--value", v);
    el.setAttribute("aria-label", String(v));
    el.textContent = String(v);
  }
  function formatNextRun(isoString) {
    if (!isoString) return "—";
    const dt = new Date(isoString);
    if (Number.isNaN(dt.getTime())) return isoString;
    const parts = new Intl.DateTimeFormat("en-GB", {
      weekday: "short",
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false
    }).formatToParts(dt);
    const getPart = (type) => {
      const found = parts.find((part) => part.type === type);
      return found ? found.value : "";
    };
    return `${getPart("weekday")} ${getPart("day")} ${getPart("month")} ${getPart("year")}, ${getPart("hour")}:${getPart("minute")}`;
  }
  function tickHelperCountdown() {
    const wrap = document.getElementById("helper-next-run-countdown");
    if (!wrap) return;

    if (!helperCountdownTarget || !Number.isFinite(helperCountdownTarget)) {
      wrap.innerHTML = helperCountdownPaused ? "<span>Scheduling paused.</span>" : "<span>Not scheduled.</span>";
      return;
    }

    const hEl = document.getElementById("helper-cd-hours");
    const mEl = document.getElementById("helper-cd-mins");
    const sEl = document.getElementById("helper-cd-secs");
    if (!hEl || !mEl || !sEl) return;

    const now = Math.floor(Date.now() / 1000);
    let remaining = helperCountdownTarget - now;
    if (remaining <= 0) {
      wrap.innerHTML = "<span>Next run is due.</span>";
      return;
    }

    const hours = Math.floor(remaining / 3600);
    remaining %= 3600;
    const mins = Math.floor(remaining / 60);
    const secs = remaining % 60;

    setCountdownValue(hEl, hours);
    setCountdownValue(mEl, mins);
    setCountdownValue(sEl, secs);
  }
  async function refreshStatus() {
    const res = await fetch("/status");
    const data = await res.json();

    setBadge(data.state);
    setText("status-last", `Last: ${data.last_run || "—"}`);
    setText("status-next", `Next: ${formatNextRun(data.next_run)}`);
    setText("next-run", formatNextRun(data.next_run));
    setText("helper-next-run", formatNextRun(data.next_run));

    const pauseBtn = document.getElementById("pause-btn");
    if (pauseBtn) {
      pauseBtn.textContent = data.paused ? "Resume Scheduled Runs" : "Pause Scheduled Runs";
    }

    const errorBanner = document.getElementById("error-banner");
    if (errorBanner) {
      if (data.last_error) {
        setText("error-text", data.last_error);
        errorBanner.classList.remove("hidden");
      } else {
        errorBanner.classList.add("hidden");
      }
    }

    helperCountdownPaused = Boolean(data.paused);
    if (data.next_run) {
      helperCountdownTarget = Math.floor(new Date(data.next_run).getTime() / 1000);
    } else {
      helperCountdownTarget = null;
    }
    tickHelperCountdown();

    if (data.refresh_report) {
      window.location.hash = window.location.hash;
    }
  }
  const runBtn = document.getElementById("run-btn");
  if (runBtn) {
    runBtn.onclick = async () => { await post("/run"); await refreshStatus(); };
  }
  const pauseBtn = document.getElementById("pause-btn");
  if (pauseBtn) {
    pauseBtn.onclick = async () => { await post("/pause"); await refreshStatus(); };
  }
  const stopBtn = document.getElementById("stop-btn");
  if (stopBtn) {
    stopBtn.onclick = async () => {
      const ok = confirm("Stop everything? This will close the local app and scheduled checks. To restart, run start.command or log out/in.");
      if (ok) { await post("/shutdown"); }
    };
  }
  refreshStatus();
  setInterval(refreshStatus, 5000);
  setInterval(tickHelperCountdown, 1000);
</script>
"""


def inject_toolbar(report_html: str) -> str:
    if "id=\"helper-controls\"" in report_html:
        return report_html

    html = report_html
    toolbar = build_toolbar_html()
    marker = '<div class="max-w-7xl mx-auto p-4 md:p-8">'
    if marker in html:
        html = html.replace(marker, marker + "\n" + toolbar, 1)
    else:
        body_idx = html.find("<body")
        if body_idx != -1:
            body_end = html.find(">", body_idx)
            if body_end != -1:
                html = html[: body_end + 1] + "\n" + toolbar + html[body_end + 1 :]
            else:
                html = toolbar + html
        else:
            html = toolbar + html

    if "id=\"helper-script\"" not in html:
        script = build_toolbar_script()
        if "</body>" in html:
            html = html.replace("</body>", script + "\n</body>", 1)
        else:
            html = html + script

    html = replace_spreadsheet_box(html)
    return add_column_gap(html)


def replace_spreadsheet_box(report_html: str) -> str:
    replacement = """
    <div class="stat-box bg-white p-4 rounded-lg shadow-sm border border-slate-100">
      <div class="text-xs uppercase font-bold text-slate-400">Next Scheduled Run</div>
      <div class="text-lg font-medium" id="helper-next-run">—</div>
      <div class="text-xs text-slate-500 mt-1">
        <span class="mr-2">Next run in</span>
        <span id="helper-next-run-countdown">
          <span class="countdown font-mono"><span id="helper-cd-hours" style="--value:0;" aria-live="polite" aria-label="0">0</span></span>h
          <span class="countdown font-mono ml-2"><span id="helper-cd-mins" style="--value:0;" aria-live="polite" aria-label="0">0</span></span>m
          <span class="countdown font-mono ml-2"><span id="helper-cd-secs" style="--value:0;" aria-live="polite" aria-label="0">0</span></span>s
        </span>
      </div>
    </div>
    """
    pattern = re.compile(
        r'(<div class="stat-box[^>]*>\s*'
        r'<div class="text-xs uppercase font-bold text-slate-400">Spreadsheet Data</div>\s*'
        r'.*?'
        r'</div>\s*)',
        re.DOTALL,
    )
    return pattern.sub(replacement, report_html, count=1)


def add_column_gap(report_html: str) -> str:
    return report_html.replace(
        'class="grid gap-6 lg:grid-cols-[460px_minmax(0,1fr)]"',
        'class="grid gap-8 lg:grid-cols-[460px_minmax(0,1fr)]"',
    )


def render_empty_page() -> str:
    toolbar = build_toolbar_html()
    script = build_toolbar_script()
    return f"""<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>CrickNet Checker</title>
  <link href=\"https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Spectral:wght@400;500;600&display=swap\" rel=\"stylesheet\" />
  <link href=\"https://cdn.jsdelivr.net/npm/daisyui@4.12.14/dist/full.min.css\" rel=\"stylesheet\" type=\"text/css\" />
  <script src=\"https://cdn.tailwindcss.com\"></script>
  <style>
    :root {{
      --col-blue: #628395;
      --text-main: #2d3748;
    }}
    body {{
      font-family: \"Spectral\", serif;
      background: radial-gradient(circle at top left, #f2efe6 0%, #f7f4ec 45%, #eef4f7 100%);
      color: var(--text-main);
    }}
    h1, h2, h3, .stat-value {{
      font-family: \"Space Grotesk\", sans-serif;
      color: var(--text-main);
      letter-spacing: -0.01em;
    }}
  </style>
</head>
<body>
  <nav class=\"navbar bg-base-100 shadow-sm sticky top-0 z-50 px-4 py-2 mb-6\" style=\"background-color: rgba(255,255,255,0.95); backdrop-filter: blur(4px);\">
    <div class=\"flex-1\">
      <span class=\"text-xl font-bold tracking-tight\" style=\"color: var(--col-blue)\">CrickNet Checker</span>
    </div>
  </nav>
  <div class=\"max-w-7xl mx-auto p-4 md:p-8\">
    {toolbar}
    <div class=\"card bg-base-100 shadow\">
      <div class=\"card-body\">
        <div class=\"text-slate-500\">No report generated yet. Click Run now to create one.</div>
      </div>
    </div>
  </div>
  {script}
</body>
</html>
"""
