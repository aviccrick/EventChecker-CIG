from __future__ import annotations


def render_index_html() -> str:
    return """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CrickNet Checker</title>
  <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Spectral:wght@400;500;600&display=swap" rel="stylesheet" />
  <link href="https://cdn.jsdelivr.net/npm/daisyui@4.12.14/dist/full.min.css" rel="stylesheet" type="text/css" />
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    :root {
      --col-blue: #628395;
      --page-bg: #f8f9fa;
      --text-main: #2d3748;
    }
    body {
      font-family: "Spectral", serif;
      background: radial-gradient(circle at top left, #f2efe6 0%, #f7f4ec 45%, #eef4f7 100%);
      color: var(--text-main);
    }
    h1, h2, h3, .stat-value {
      font-family: "Space Grotesk", sans-serif;
      color: var(--text-main);
      letter-spacing: -0.01em;
    }
    .stat-box {
      background: #fff;
      border: 1px solid #f1f3f5;
    }
    iframe {
      width: 100%;
      border: 0;
      min-height: 70vh;
    }
  </style>
</head>
<body>
  <nav class="navbar bg-base-100 shadow-sm sticky top-0 z-50 px-4 py-2 mb-4" style="background-color: rgba(255,255,255,0.95); backdrop-filter: blur(4px);">
    <div class="flex-1">
      <span class="text-xl font-bold tracking-tight" style="color: var(--col-blue)">CrickNet Checker</span>
    </div>
    <div class="flex-none items-center gap-2">
      <button class="btn btn-sm btn-primary" id="run-btn">Run now</button>
      <button class="btn btn-sm" id="pause-btn">Pause scheduling</button>
      <button class="btn btn-sm btn-error" id="stop-btn">Stop helper</button>
      <div class="divider divider-horizontal mx-1"></div>
      <div class="hidden md:flex items-center gap-2 text-xs text-slate-500" id="status">
        <span class="badge badge-outline" id="state-badge">Idle</span>
        <span id="status-last">Last: —</span>
        <span>•</span>
        <span id="status-next">Next: —</span>
      </div>
    </div>
  </nav>

  <div class="max-w-7xl mx-auto px-4 md:px-8 pb-6">
    <div id="error-banner" class="alert alert-error shadow-sm mb-4 hidden">
      <span id="error-text">An error occurred.</span>
    </div>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
      <div class="stat-box p-4 rounded-lg shadow-sm">
        <div class="text-xs uppercase font-bold text-slate-400">Helper Status</div>
        <div class="text-lg font-medium" id="status-line">Loading status…</div>
      </div>
      <div class="stat-box p-4 rounded-lg shadow-sm">
        <div class="text-xs uppercase font-bold text-slate-400">Next Scheduled Run</div>
        <div class="text-lg font-medium" id="next-run">—</div>
      </div>
    </div>

    <div class="card bg-base-100 shadow">
      <div class="card-body p-2">
        <iframe id="report-frame" src="/report"></iframe>
      </div>
    </div>
  </div>

  <script>
    async function post(path, body) {
      const res = await fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body || {}) });
      return res.json();
    }
    function setText(id, value) {
      const el = document.getElementById(id);
      if (el) el.textContent = value;
    }
    async function refreshStatus() {
      const res = await fetch("/status");
      const data = await res.json();
      const stateLabel = data.state === "running" ? "Running" : "Idle";
      document.getElementById("state-badge").textContent = stateLabel;
      setText("status-last", `Last: ${data.last_run || "—"}`);
      setText("status-next", `Next: ${data.next_run || "—"}`);
      setText("status-line", `State: ${stateLabel} • Last: ${data.last_run || "—"}`);
      setText("next-run", data.next_run || "—");

      document.getElementById("pause-btn").textContent = data.paused ? "Resume scheduling" : "Pause scheduling";

      const errorBanner = document.getElementById("error-banner");
      if (data.last_error) {
        document.getElementById("error-text").textContent = data.last_error;
        errorBanner.classList.remove("hidden");
      } else {
        errorBanner.classList.add("hidden");
      }

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
