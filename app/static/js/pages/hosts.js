/* Hosts pages: list, detail, form, groups, environments */
(function () {
  const S = window.Scarlet;

  S.pages["hosts-list"] = function () {
    const root = document.getElementById("hosts-table");
    new S.DataTable(root, (h) => {
      const keyBadge = h.ssh_host_key_status === "APPROVED" ? '<span class="text-success" title="' + S.esc(h.ssh_fingerprint) + '"><i class="fa-solid fa-fingerprint"></i> approved</span>' : S.badge(h.ssh_host_key_status);
      return "<tr>" +
        '<td><a href="/hosts/' + h.id + '"><b>' + S.esc(h.name) + "</b></a>" + (!h.has_credential ? ' <i class="fa-solid fa-key text-danger" title="No SSH credential"></i>' : "") + "</td>" +
        '<td class="small">' + S.esc(h.hostname) + (h.ip_address ? '<br><span class="text-muted">' + S.esc(h.ip_address) + "</span>" : "") + ":" + h.ssh_port + "</td>" +
        "<td>" + S.envBadge(h.environment, h.is_production) + "</td>" +
        "<td>" + S.runtimeIcon(h.runtime_type) + (h.runtime_version ? ' <span class="text-muted small">' + S.esc(h.runtime_version) + "</span>" : "") + "</td>" +
        "<td>" + S.badge(h.status) + "</td>" +
        '<td class="small">' + keyBadge + "</td>" +
        '<td class="small">' + (h.groups || []).map(S.esc).join(", ") + "</td>" +
        '<td class="small text-muted">' + S.fmtDate(h.last_seen_at) + "</td>" +
        '<td class="text-end text-nowrap">' +
          (S.can("host.test") ? '<button class="btn btn-xs btn-outline-primary btn-sm" data-action="host-op" data-op="test-connection" data-host="' + h.id + '" title="Test connection"><i class="fa-solid fa-plug"></i></button> ' : "") +
          (S.can("host.test") ? '<button class="btn btn-xs btn-outline-primary btn-sm" data-action="host-op" data-op="discover" data-host="' + h.id + '" title="Discover"><i class="fa-solid fa-magnifying-glass"></i></button> ' : "") +
          '<a class="btn btn-sm btn-outline-secondary" href="/hosts/' + h.id + '" title="Details"><i class="fa-solid fa-eye"></i></a>' +
        "</td></tr>";
    }, { autoRefresh: 30000 }).load();
  };

  S.pages["host-detail"] = function (root) {
    const hostId = root.dataset.hostId, production = root.dataset.production === "1", name = root.dataset.hostName, env = root.dataset.env;
    const approve = document.getElementById("btn-approve-key");
    if (approve) approve.addEventListener("click", async () => {
      const fp = document.getElementById("pending-fingerprint").textContent.trim();
      const answer = await S.confirm({ title: "Approve SSH host key", danger: true, requirePhrase: true, phrase: fp, requireReason: false, showReason: true, body: "<p>Confirm that you verified this fingerprint through an independent channel (server console, provisioning record). Approving a wrong key would allow a man-in-the-middle to receive SCARLET credentials and commands.</p>", details: { Host: S.esc(name), Fingerprint: "<code>" + S.esc(fp) + "</code>" }, okLabel: "Approve" });
      if (!answer) return;
      try { await S.api("POST", "/api/hosts/" + hostId + "/host-key/approve", { fingerprint: fp }); S.toast("Host key approved", "success"); setTimeout(() => location.reload(), 600); } catch (e) { S.showError(e, "Approve host key"); }
    });
    const scan = document.getElementById("btn-scan-key");
    if (scan) scan.addEventListener("click", async () => {
      scan.disabled = true;
      try { const res = await S.api("POST", "/api/hosts/" + hostId + "/host-key/scan"); S.toast("Fingerprint " + res.data.fingerprint + " (" + res.data.status + ")", res.data.status === "MATCHES_APPROVED" ? "success" : "warning", 8000); setTimeout(() => location.reload(), 1200); } catch (e) { S.showError(e, "Scan host key"); } finally { scan.disabled = false; }
    });
    const reconcile = document.getElementById("btn-reconcile");
    if (reconcile) reconcile.addEventListener("click", async () => { try { await S.api("POST", "/api/hosts/" + hostId + "/reconcile"); S.toast("Reconciliation queued", "success"); } catch (e) { S.showError(e, "Reconcile"); } });
    const toggle = async (enable) => {
      const answer = await S.confirm({ title: (enable ? "Enable" : "Disable") + " host " + name, production: production && !enable, operation: "DISABLE", requirePhrase: false, showReason: true, requireReason: production && !enable, danger: !enable, body: enable ? "<p>The host will be included again in deployments and reconciliation.</p>" : "<p>Disabled hosts are excluded from deployments, lifecycle operations and reconciliation. Running applications are not touched.</p>" });
      if (!answer) return;
      try { await S.api("POST", "/api/hosts/" + hostId + (enable ? "/enable" : "/disable")); location.reload(); } catch (e) { S.showError(e); }
    };
    const disable = document.getElementById("btn-disable"); if (disable) disable.addEventListener("click", () => toggle(false));
    const enable = document.getElementById("btn-enable"); if (enable) enable.addEventListener("click", () => toggle(true));
    const del = document.getElementById("btn-delete");
    if (del) del.addEventListener("click", async () => {
      const answer = await S.confirm({ title: "Delete host " + name, production, operation: "DELETE", danger: true, showReason: true, requireReason: production, requirePhrase: production, body: "<p>The host record and its credentials will be removed from SCARLET. Nothing is changed on the remote server. Hosts with deployment history cannot be deleted (disable them instead).</p>", details: { Host: S.esc(name), Environment: S.envBadge(env, production) } });
      if (!answer) return;
      try { await S.api("DELETE", "/api/hosts/" + hostId, { reason: answer.reason, confirmation: answer.confirmation }); S.toast("Host deleted", "success"); window.location.href = "/hosts"; } catch (e) { S.showError(e, "Delete host"); }
    });
  };

  S.pages["host-form"] = function (root) {
    const form = document.getElementById("host-form");
    const hostId = root.dataset.hostId;
    const rt = document.getElementById("runtime_type");
    const toggleK8s = () => document.querySelectorAll(".k8s-only").forEach((el) => el.classList.toggle("d-none", rt.value !== "KUBERNETES"));
    rt.addEventListener("change", toggleK8s); toggleK8s();
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      if (!form.checkValidity()) { form.classList.add("was-validated"); return; }
      const fd = new FormData(form);
      const payload = {
        name: fd.get("name"), hostname: fd.get("hostname"), ip_address: fd.get("ip_address") || null, ssh_port: Number(fd.get("ssh_port")), ssh_username: fd.get("ssh_username"),
        environment_id: Number(fd.get("environment_id")), runtime_type: fd.get("runtime_type"), kubernetes_namespace: fd.get("kubernetes_namespace") || null, kubernetes_context: fd.get("kubernetes_context") || null,
        remote_base_path: fd.get("remote_base_path") || null, description: fd.get("description"), enabled: form.querySelector('[name="enabled"]').checked, group_ids: fd.getAll("group_ids").map(Number),
      };
      const btn = form.querySelector('button[type="submit"]'); btn.disabled = true;
      try {
        const res = hostId ? await S.api("PUT", "/api/hosts/" + hostId, payload) : await S.api("POST", "/api/hosts", payload);
        S.toast(hostId ? "Host updated" : "Host created. Now add an SSH credential and approve the host key.", "success");
        window.location.href = "/hosts/" + res.data.id;
      } catch (e) { S.showError(e, "Save host"); btn.disabled = false; }
    });
  };

  S.pages["host-groups"] = function () {
    const form = document.getElementById("group-form");
    const reset = () => { if (!form) return; form.reset(); form.querySelector('[name="id"]').value = ""; form.querySelector('[name="name"]').disabled = false; document.getElementById("group-form-title").textContent = "New host group"; };
    document.querySelectorAll("[data-edit-group]").forEach((btn) => btn.addEventListener("click", () => {
      const g = JSON.parse(btn.closest("tr").dataset.group);
      form.querySelector('[name="id"]').value = g.id; form.querySelector('[name="name"]').value = g.name; form.querySelector('[name="name"]').disabled = true;
      form.querySelector('[name="description"]').value = g.description || "";
      const envSel = form.querySelector('[name="environment_id"]'); envSel.value = "";
      Array.from(envSel.options).forEach((o) => { if (o.textContent === g.environment) envSel.value = o.value; });
      Array.from(form.querySelector('[name="host_ids"]').options).forEach((o) => { o.selected = g.host_ids.includes(Number(o.value)); });
      document.getElementById("group-form-title").textContent = "Edit " + g.name;
    }));
    document.querySelectorAll("[data-delete-group]").forEach((btn) => btn.addEventListener("click", async () => {
      const g = JSON.parse(btn.closest("tr").dataset.group);
      const answer = await S.confirm({ title: "Delete host group " + g.name, danger: true, requirePhrase: false, requireReason: false, body: "<p>Hosts are not deleted; only the grouping is removed.</p>" });
      if (!answer) return;
      try { await S.api("DELETE", "/api/host-groups/" + g.id); location.reload(); } catch (e) { S.showError(e); }
    }));
    if (form) {
      document.getElementById("group-form-reset").addEventListener("click", reset);
      form.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const fd = new FormData(form);
        const payload = { name: fd.get("name"), description: fd.get("description"), environment_id: fd.get("environment_id") ? Number(fd.get("environment_id")) : null, host_ids: fd.getAll("host_ids").map(Number) };
        try {
          const id = fd.get("id");
          if (id) await S.api("PUT", "/api/host-groups/" + id, payload); else await S.api("POST", "/api/host-groups", payload);
          location.reload();
        } catch (e) { S.showError(e, "Save group"); }
      });
    }
  };

  S.pages["environments"] = function () {
    document.querySelectorAll(".env-form").forEach((form) => form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const payload = { name: form.querySelector('[name="name"]').value, max_parallel_deployments: Number(form.querySelector('[name="max_parallel_deployments"]').value), require_confirmation: form.querySelector('[name="require_confirmation"]').checked, require_approval: form.querySelector('[name="require_approval"]').checked, allow_rollback: form.querySelector('[name="allow_rollback"]').checked };
      try { await S.api("PUT", "/api/environments/" + form.dataset.envId, payload); S.toast("Environment updated", "success"); } catch (e) { S.showError(e, "Save environment"); }
    }));
  };
})();
