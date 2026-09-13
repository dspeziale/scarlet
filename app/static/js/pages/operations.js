/* Operations: list, detail, jobs */
(function () {
  const S = window.Scarlet;

  S.pages["operations-list"] = function () {
    new S.DataTable(document.getElementById("operations-table"), (o) => "<tr>" +
      '<td><a href="/operations/' + o.id + '"><code>' + S.esc(o.reference) + "</code></a></td>" +
      "<td><b>" + S.esc(o.operation_type) + "</b></td>" +
      "<td>" + (o.application_code ? '<a href="/applications/' + o.application_id + '">' + S.esc(o.application_code) + "</a>" : "-") + "</td>" +
      "<td>" + (o.target_name ? '<a href="/hosts/' + o.target_id + '">' + S.esc(o.target_name) + "</a>" : "-") + "</td>" +
      "<td>" + (o.environment ? S.envBadge(o.environment) : "-") + "</td>" +
      "<td>" + S.badge(o.status) + "</td>" +
      '<td class="small">' + (o.result_code ? S.badge(o.result_code) : "") + (o.error_message ? '<div class="text-danger text-truncate-200" title="' + S.esc(o.error_message) + '">' + S.esc(o.error_message) + "</div>" : "") + "</td>" +
      '<td class="small">' + S.esc(o.requested_by || S.t("system")) + "</td>" +
      '<td class="small text-muted">' + S.fmtDate(o.created_at) + "</td>" +
      '<td class="small">' + S.fmtDuration(o.duration_seconds) + "</td>" +
      '<td class="text-end"><a class="btn btn-sm btn-outline-secondary" href="/operations/' + o.id + '"><i class="fa-solid fa-eye"></i></a></td></tr>', { autoRefresh: 15000 }).load();
  };

  S.pages["operation-detail"] = function (root) {
    const id = root.dataset.operationId;
    const cancel = document.getElementById("btn-cancel-op");
    if (cancel) cancel.addEventListener("click", async () => { try { await S.api("POST", "/api/operations/" + id + "/cancel", {}); location.reload(); } catch (e) { S.showError(e); } });
    if (root.dataset.terminal === "1") return;
    S.poll("/api/operations/" + id, (r) => r.data.is_terminal, { interval: 2000, onTick: (r) => {
      const o = r.data;
      document.getElementById("op-status").innerHTML = S.badge(o.status);
      const tbody = document.querySelector("#op-log tbody");
      if (o.logs && o.logs.length) tbody.innerHTML = o.logs.map((l) => '<tr><td class="text-muted">' + S.fmtDate(l.timestamp).slice(11, 19) + "</td><td>" + S.esc(l.level) + "</td><td>" + S.esc(l.message) + (l.command ? '<div class="text-primary">$ ' + S.esc(l.command) + "</div>" : "") + (l.stdout ? '<details><summary class="text-muted">stdout</summary><pre class="scarlet-log">' + S.esc(l.stdout) + "</pre></details>" : "") + (l.stderr ? '<details><summary class="text-warning-emphasis">stderr</summary><pre class="scarlet-log">' + S.esc(l.stderr) + "</pre></details>" : "") + "</td><td>" + (l.exit_code == null ? "" : l.exit_code) + "</td><td>" + (l.duration_seconds == null ? "" : l.duration_seconds) + "</td></tr>").join("");
    } }).then(() => location.reload()).catch((e) => S.showError(e, S.t("Live update")));
  };

  S.pages["jobs"] = function () {
    const refresh = async () => {
      try {
        const res = await S.api("GET", "/api/operations/active");
        const tbody = document.querySelector("#active-ops tbody");
        tbody.innerHTML = res.data.length ? res.data.map((o) => '<tr><td><a href="/operations/' + o.id + '"><code>' + S.esc(o.reference) + "</code></a></td><td>" + S.esc(o.operation_type) + "</td><td>" + S.esc(o.application_code || "-") + "</td><td>" + S.esc(o.target_name || "-") + "</td><td>" + S.badge(o.status) + "</td><td>" + S.esc(o.requested_by || S.t("system")) + '</td><td class="small text-muted">' + S.fmtDate(o.created_at) + "</td></tr>").join("") : '<tr><td colspan="7" class="text-center text-muted py-3">No active operations.</td></tr>';
        const deps = await S.api("GET", "/api/deployments?status=RUNNING&per_page=50");
        const queued = await S.api("GET", "/api/deployments?status=QUEUED&per_page=50");
        const all = deps.data.concat(queued.data);
        document.querySelector("#active-deps tbody").innerHTML = all.length ? all.map((d) => '<tr><td><a href="/deployments/' + d.id + '"><code>' + S.esc(d.reference) + "</code></a></td><td>" + S.esc(d.application_code) + "</td><td>" + S.esc(d.version) + "</td><td>" + S.esc(d.target_name) + "</td><td>" + S.badge(d.status) + '</td><td class="small text-muted">' + S.fmtDate(d.created_at) + "</td></tr>").join("") : '<tr><td colspan="6" class="text-center text-muted py-3">No deployments in progress.</td></tr>';
      } catch (e) { /* ignore */ }
    };
    setInterval(() => { if (document.visibilityState === "visible") refresh(); }, 5000);
    document.getElementById("job-lookup").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const id = new FormData(ev.target).get("job_id");
      try { const res = await S.api("GET", "/api/jobs/" + encodeURIComponent(id)); const pre = document.getElementById("job-result"); pre.classList.remove("d-none"); pre.textContent = JSON.stringify(res.data, null, 2); } catch (e) { S.showError(e, S.t("Job lookup")); }
    });
  };
})();
