from __future__ import annotations


def build_toolbar_html() -> str:
    return """
<div id="helper-controls" class="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_280px] gap-4 mb-6">
  <div class="stat-box bg-white p-4 rounded-lg shadow-sm border border-slate-100">
    <div class="text-xs uppercase font-bold text-slate-400">Helper Controls</div>
    <div class="mt-2 flex flex-wrap gap-2">
      <button class="btn btn-sm btn-primary" id="run-btn">Run now</button>
      <button class="btn btn-sm" id="pause-btn">Pause scheduling</button>
      <button class="btn btn-sm btn-error" id="stop-btn">Stop helper</button>
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
  async function refreshStatus() {
    const res = await fetch("/status");
    const data = await res.json();

    setBadge(data.state);
    setText("status-last", `Last: ${data.last_run || "—"}`);
    setText("status-next", `Next: ${data.next_run || "—"}`);
    setText("next-run", data.next_run || "—");

    const pauseBtn = document.getElementById("pause-btn");
    if (pauseBtn) {
      pauseBtn.textContent = data.paused ? "Resume scheduling" : "Pause scheduling";
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

    return html


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
