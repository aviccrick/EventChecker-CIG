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
    <div class="status" id="status">Loading status...</div>
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
      statusEl.textContent = `State: ${data.state} | Last: ${data.last_run || "-"} | Next: ${data.next_run || "-"}`;
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
