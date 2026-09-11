/* Monitoring: health overview and log viewer */
(function () {
  const S = window.Scarlet;

  S.pages["monitoring-health"] = function () {
    document.getElementById("btn-reload").addEventListener("click", () => location.reload());
    const all = document.getElementById("btn-check-all");
    if (all) all.addEventListener("click", async () => {
      const buttons = Array.from(document.querySelectorAll('[data-action="lifecycle"][data-op="HEALTH"]'));
      all.disabled = true;
      let queued = 0;
      for (const b of buttons) {
        try { await S.api("POST", "/api/applications/" + b.dataset.app + "/health", { host_id: Number(b.dataset.host) }); queued++; } catch (e) { /* skip */ }
      }
      S.toast(queued + " health check(s) queued; reload in a few seconds to see results", "success");
      all.disabled = false;
    });
  };

  S.pages["monitoring-logs"] = function (root) {
    const instance = document.getElementById("instance"), out = document.getElementById("log-output"), meta = document.getElementById("log-meta");
    const download = document.getElementById("btn-download");
    let lastOperationId = null, timer = null;
    if (root.dataset.preselectApp && root.dataset.preselectHost) instance.value = root.dataset.preselectApp + ":" + root.dataset.preselectHost;
    document.getElementById("wrap").addEventListener("change", (e) => { out.style.whiteSpace = e.target.checked ? "pre-wrap" : "pre"; });
    async function fetchLogs() {
      if (!instance.value) return;
      const [app, host] = instance.value.split(":");
      const params = { lines: Number(document.getElementById("lines").value), since: document.getElementById("since").value, search: document.getElementById("search").value.trim() };
      out.textContent = "Fetching logs from the target host…";
      try {
        const res = await S.api("POST", "/api/applications/" + app + "/logs", { host_id: Number(host), parameters: params });
        let op = res.data;
        if (!op.is_terminal) { const done = await S.poll("/api/operations/" + op.id, (r) => r.data.is_terminal, { interval: 1500 }); op = done.data; }
        lastOperationId = op.id; download.disabled = false;
        if (op.status !== "SUCCESS") { out.innerHTML = '<span class="log-line-error">' + S.esc(op.error_code || "ERROR") + ": " + S.esc(op.error_message || "failed") + "</span>"; return; }
        const lines = op.result.lines || [];
        const search = params.search.toLowerCase();
        out.innerHTML = lines.length ? lines.map((l) => { let cls = /error|fatal|exception/i.test(l) ? "log-line-error" : (/warn/i.test(l) ? "log-line-warn" : ""); let html = S.esc(l); if (search) { const idx = l.toLowerCase().indexOf(search); if (idx >= 0) html = S.esc(l.slice(0, idx)) + "<mark>" + S.esc(l.slice(idx, idx + search.length)) + "</mark>" + S.esc(l.slice(idx + search.length)); } return '<div class="' + cls + '">' + html + "</div>"; }).join("") : '<span class="text-muted">(no log lines)</span>';
        meta.textContent = lines.length + " line(s) from " + (op.result.source || "runtime") + (op.result.truncated ? " (truncated to the requested count)" : "") + " · " + S.fmtDate(op.completed_at);
        out.scrollTop = out.scrollHeight;
      } catch (e) { out.innerHTML = '<span class="log-line-error">' + S.esc(e.message) + "</span>"; }
    }
    document.getElementById("log-form").addEventListener("submit", (ev) => { ev.preventDefault(); fetchLogs(); });
    download.addEventListener("click", () => { if (lastOperationId) window.location.href = "/api/operations/" + lastOperationId + "/download"; });
    document.getElementById("auto-refresh").addEventListener("change", (e) => { if (timer) { clearInterval(timer); timer = null; } if (e.target.checked) timer = setInterval(() => { if (document.visibilityState === "visible") fetchLogs(); }, 10000); });
    if (instance.value) fetchLogs();
  };
})();
