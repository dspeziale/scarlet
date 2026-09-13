/* Audit log and security events */
(function () {
  const S = window.Scarlet;

  S.pages["audit-list"] = function () {
    const root = document.getElementById("audit-table");
    const table = new S.DataTable(root, (a) => "<tr>" +
      '<td class="small text-nowrap">' + S.fmtDate(a.timestamp) + "</td>" +
      "<td><b>" + S.esc(a.username || S.t("system")) + "</b></td>" +
      "<td><code>" + S.esc(a.action) + "</code></td>" +
      '<td class="small">' + S.esc(a.entity_type || "") + (a.entity_id ? " #" + S.esc(a.entity_id) : "") + "</td>" +
      '<td class="small">' + (a.target_name ? '<a href="/hosts/' + a.target_id + '">' + S.esc(a.target_name) + "</a>" : "-") + "</td>" +
      '<td class="small">' + (a.application_code ? '<a href="/applications/' + a.application_id + '">' + S.esc(a.application_code) + "</a>" : "-") + "</td>" +
      "<td>" + (a.environment ? S.envBadge(a.environment) : "-") + "</td>" +
      "<td>" + S.badge(a.result) + "</td>" +
      '<td class="small text-muted">' + S.esc(a.ip_address || "-") + "</td>" +
      '<td><button class="btn btn-xs btn-sm btn-outline-secondary" data-audit=\'' + S.esc(JSON.stringify(a)) + "'><i class=\"fa-solid fa-eye\"></i></button></td></tr>", {
      afterLoad: () => document.querySelectorAll("[data-audit]").forEach((b) => b.addEventListener("click", () => { document.getElementById("audit-modal-body").textContent = JSON.stringify(JSON.parse(b.dataset.audit), null, 2); bootstrap.Modal.getOrCreateInstance(document.getElementById("audit-modal")).show(); })),
    });
    table.load();
    S.api("GET", "/api/audit/actions").then((res) => { document.getElementById("action-list").innerHTML = res.data.map((a) => '<option value="' + S.esc(a) + '">').join(""); }).catch(() => {});
    document.querySelectorAll("[data-export]").forEach((b) => b.addEventListener("click", () => {
      const p = table.params(); p.delete("page"); p.delete("per_page"); p.set("format", b.dataset.export);
      window.location.href = "/api/audit/export?" + p.toString();
    }));
  };

  S.pages["security-events"] = function () {
    const table = new S.DataTable(document.getElementById("events-table"), (e) => "<tr>" +
      '<td class="small text-nowrap">' + S.fmtDate(e.timestamp) + "</td>" +
      "<td>" + S.badge(e.severity) + "</td>" +
      "<td><code>" + S.esc(e.event_type) + "</code></td>" +
      '<td class="small">' + S.esc(e.message) + "</td>" +
      '<td class="small">' + (e.target_id ? '<a href="/hosts/' + e.target_id + '">host #' + e.target_id + "</a>" : "-") + "</td>" +
      '<td class="small text-muted">' + S.esc(e.ip_address || "-") + "</td>" +
      "<td>" + (e.acknowledged ? '<i class="fa-solid fa-check text-success"></i>' : '<span class="text-muted">-</span>') + "</td>" +
      '<td class="text-end">' + (!e.acknowledged && S.can("system.manage") ? '<button class="btn btn-sm btn-outline-secondary" data-ack="' + e.id + '" title="Acknowledge"><i class="fa-solid fa-check"></i></button>' : "") + "</td></tr>", {
      afterLoad: () => document.querySelectorAll("[data-ack]").forEach((b) => b.addEventListener("click", async () => { try { await S.api("POST", "/api/security-events/" + b.dataset.ack + "/acknowledge", {}); table.load(); } catch (err) { S.showError(err); } })),
    });
    table.load();
  };
})();
