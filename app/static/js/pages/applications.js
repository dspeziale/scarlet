/* Applications pages: list, detail, form, configuration, releases */
(function () {
  const S = window.Scarlet;

  async function showManifest(appId, versionId) {
    try {
      const res = await S.api("GET", "/api/applications/" + appId + "/versions/" + versionId);
      const v = res.data;
      document.getElementById("manifest-title").textContent = (v.application_code || "") + " " + v.version;
      document.getElementById("manifest-body").textContent = JSON.stringify(v.manifest, null, 2);
      const integ = document.getElementById("manifest-integrity");
      integ.innerHTML = v.integrity ? (v.integrity.ok ? '<span class="text-success"><i class="fa-solid fa-check"></i> artifact checksum verified</span>' : '<span class="text-danger"><i class="fa-solid fa-triangle-exclamation"></i> ARTIFACT CHECKSUM MISMATCH</span>') + ' <code>' + S.esc(v.checksum_sha256) + "</code>" : '<span class="text-muted">no artifact stored (metadata-only version)</span>';
      bootstrap.Modal.getOrCreateInstance(document.getElementById("manifest-modal")).show();
    } catch (e) { S.showError(e, "Manifest"); }
  }

  S.pages["applications-list"] = function () {
    new S.DataTable(document.getElementById("apps-table"), (a) => "<tr>" +
      '<td><a href="/applications/' + a.id + '"><code>' + S.esc(a.code) + "</code></a></td>" +
      "<td><b>" + S.esc(a.name) + "</b><br><span class=\"small text-muted\">" + S.esc((a.description || "").slice(0, 80)) + "</span></td>" +
      '<td class="small">' + S.esc(a.owner || "-") + "</td>" +
      "<td>" + S.runtimeIcon(a.runtime_type) + "</td>" +
      '<td class="small">' + S.esc(a.healthcheck.type) + (a.healthcheck.url ? " " + S.esc(a.healthcheck.url) : "") + "</td>" +
      "<td>" + ((a.allowed_environments || []).length ? a.allowed_environments.map((e) => S.envBadge(e)).join(" ") : '<span class="small text-muted">any</span>') + "</td>" +
      '<td class="text-center">' + a.version_count + "</td>" +
      "<td>" + (a.enabled ? '<i class="fa-solid fa-check text-success"></i>' : S.badge("DISABLED")) + "</td>" +
      '<td class="text-end text-nowrap"><a class="btn btn-sm btn-outline-secondary" href="/applications/' + a.id + '"><i class="fa-solid fa-eye"></i></a> ' + (S.can("deployment.execute") ? '<a class="btn btn-sm btn-outline-success" href="/deployments/new?application_id=' + a.id + '" title="Deploy"><i class="fa-solid fa-rocket"></i></a>' : "") + "</td></tr>").load();
  };

  S.pages["application-detail"] = function (root) {
    const appId = root.dataset.appId;
    document.querySelectorAll("[data-show-manifest]").forEach((b) => b.addEventListener("click", () => showManifest(appId, b.dataset.showManifest)));
    const refresh = document.getElementById("btn-refresh-instances");
    if (refresh) refresh.addEventListener("click", () => location.reload());
    const del = document.getElementById("btn-delete-app");
    if (del) del.addEventListener("click", async () => {
      const answer = await S.confirm({ title: "Delete application " + root.dataset.appCode, danger: true, requirePhrase: true, phrase: "DELETE " + root.dataset.appCode, requireReason: false, body: "<p>Only possible when no deployment history exists. Nothing is changed on remote hosts.</p>" });
      if (!answer) return;
      try { await S.api("DELETE", "/api/applications/" + appId); window.location.href = "/applications"; } catch (e) { S.showError(e, "Delete"); }
    });
  };

  S.pages["application-form"] = function (root) {
    const form = document.getElementById("app-form");
    const appId = root.dataset.appId;
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      if (!form.checkValidity()) { form.classList.add("was-validated"); return; }
      const fd = new FormData(form);
      const num = (k) => (fd.get(k) ? Number(fd.get(k)) : null);
      const payload = {
        name: fd.get("name"), code: fd.get("code"), description: fd.get("description"), owner: fd.get("owner"), repository: fd.get("repository"), runtime_type: fd.get("runtime_type"), artifact_type: fd.get("artifact_type"),
        default_port: num("default_port"), healthcheck_type: fd.get("healthcheck_type"), healthcheck_url: fd.get("healthcheck_url"), healthcheck_port: num("healthcheck_port"), healthcheck_command: fd.get("healthcheck_command"),
        healthcheck_expected_status: num("healthcheck_expected_status"), healthcheck_timeout: num("healthcheck_timeout"), healthcheck_retries: num("healthcheck_retries"), healthcheck_interval: fd.get("healthcheck_interval") === "" ? null : Number(fd.get("healthcheck_interval")),
        allowed_environments: fd.getAll("allowed_environments"), allowed_runtimes: fd.getAll("allowed_runtimes"), allowed_host_group_ids: fd.getAll("allowed_host_group_ids").map(Number),
        allow_hooks: form.querySelector('[name="allow_hooks"]').checked, enabled: form.querySelector('[name="enabled"]').checked,
      };
      const btn = form.querySelector('button[type="submit"]'); btn.disabled = true;
      try {
        const res = appId ? await S.api("PUT", "/api/applications/" + appId, payload) : await S.api("POST", "/api/applications", payload);
        S.toast("Application saved", "success");
        window.location.href = "/applications/" + res.data.id;
      } catch (e) { S.showError(e, "Save application"); btn.disabled = false; }
    });
  };

  S.pages["application-configuration"] = function (root) {
    const appId = root.dataset.appId;
    let env = document.querySelector("#env-tabs .nav-link.active").dataset.env;
    let production = document.querySelector("#env-tabs .nav-link.active").dataset.production === "1";
    const canEdit = () => S.can("configuration.update", production);
    async function load() {
      try {
        const res = await S.api("GET", "/api/applications/" + appId + "/configuration/" + env);
        const c = res.data;
        document.getElementById("config-version").textContent = "v" + c.current_version_number;
        document.getElementById("config-body").innerHTML = c.entries.length ? c.entries.map((e) => "<tr>" +
          '<td><code>' + S.esc(e.key) + "</code></td>" +
          "<td>" + (e.is_secret ? '<span class="badge text-bg-dark"><i class="fa-solid fa-lock me-1"></i>SECRET</span>' : '<span class="badge text-bg-light text-dark border">CONFIG</span>') + "</td>" +
          '<td class="font-monospace-sm">' + (e.is_secret ? '<span class="secret-mask text-muted">••••••••</span>' : S.esc(e.value)) + "</td>" +
          '<td class="small">' + S.esc(e.description || "") + "</td>" +
          '<td class="small text-muted">' + S.fmtDate(e.updated_at) + "</td>" +
          '<td class="text-end text-nowrap">' + (canEdit() ? '<button class="btn btn-sm btn-outline-secondary" data-edit-key="' + S.esc(e.key) + '" data-type="' + e.value_type + '" data-desc="' + S.esc(e.description || "") + '"><i class="fa-solid fa-pen"></i></button> <button class="btn btn-sm btn-outline-danger" data-del-key="' + S.esc(e.key) + '"><i class="fa-solid fa-trash"></i></button>' : "") + "</td></tr>").join("") : '<tr><td colspan="6" class="text-center text-muted py-3">No configuration entries for ' + S.esc(env) + ".</td></tr>";
        document.getElementById("config-versions").innerHTML = (c.versions || []).map((v) => '<li class="list-group-item"><b>v' + v.version_number + "</b> " + (v.is_current ? '<span class="badge text-bg-success">current</span>' : "") + '<div class="text-muted">' + S.fmtDate(v.created_at) + " · " + S.esc(v.created_by || "system") + "</div><div>" + S.esc(v.change_summary) + '</div><div class="text-muted">keys: ' + v.keys.map(S.esc).join(", ") + "</div></li>").join("") || '<li class="list-group-item text-muted">No versions yet.</li>';
        document.querySelectorAll("[data-edit-key]").forEach((b) => b.addEventListener("click", () => openModal({ key: b.dataset.editKey, value_type: b.dataset.type, description: b.dataset.desc })));
        document.querySelectorAll("[data-del-key]").forEach((b) => b.addEventListener("click", async () => {
          const answer = await S.confirm({ title: "Remove " + b.dataset.delKey + " from " + env, production, operation: "DELETE", danger: true, showReason: true, requireReason: production, requirePhrase: false });
          if (!answer) return;
          try { await S.api("DELETE", "/api/applications/" + appId + "/configuration/" + env + "/" + encodeURIComponent(b.dataset.delKey)); load(); } catch (e) { S.showError(e); }
        }));
        const add = document.getElementById("btn-add-entry"); if (add) add.disabled = !canEdit();
      } catch (e) { S.showError(e, "Load configuration"); }
    }
    const modalEl = document.getElementById("entry-modal");
    const form = document.getElementById("entry-form");
    function openModal(entry) {
      form.reset();
      form.querySelector('[name="key"]').value = entry ? entry.key : "";
      form.querySelector('[name="key"]').readOnly = !!entry;
      form.querySelector('[name="value_type"]').value = entry ? entry.value_type : "CONFIG";
      form.querySelector('[name="description"]').value = entry ? entry.description : "";
      document.getElementById("entry-modal-title").textContent = entry ? "Edit " + entry.key : "Add entry";
      document.getElementById("entry-value-help").textContent = entry && entry.value_type === "SECRET" ? "Leave empty to keep the existing secret." : "Single line, max 8 KiB.";
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }
    const add = document.getElementById("btn-add-entry"); if (add) add.addEventListener("click", () => openModal(null));
    if (form) form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const fd = new FormData(form);
      const entry = { key: fd.get("key"), value_type: fd.get("value_type"), description: fd.get("description") };
      const value = fd.get("value");
      if (value !== "" || entry.value_type === "CONFIG") entry.value = value;
      if (production) {
        const answer = await S.confirm({ title: "Update PROD configuration", production, operation: "UPDATE", requirePhrase: false, showReason: true, requireReason: true, details: { Key: "<code>" + S.esc(entry.key) + "</code>", Environment: S.envBadge(env, true) } });
        if (!answer) return;
        fd.set("change_summary", (fd.get("change_summary") || "") + " " + answer.reason);
      }
      try { await S.api("PUT", "/api/applications/" + appId + "/configuration/" + env, { entries: [entry], change_summary: fd.get("change_summary") }); bootstrap.Modal.getInstance(modalEl).hide(); S.toast("Configuration saved", "success"); load(); } catch (e) { S.showError(e, "Save entry"); }
    });
    document.querySelectorAll("#env-tabs .nav-link").forEach((tab) => tab.addEventListener("click", (ev) => { ev.preventDefault(); document.querySelectorAll("#env-tabs .nav-link").forEach((t) => t.classList.remove("active")); tab.classList.add("active"); env = tab.dataset.env; production = tab.dataset.production === "1"; load(); }));
    load();
  };

  S.pages["releases"] = function () {
    document.querySelectorAll("[data-manifest]").forEach((b) => b.addEventListener("click", () => { const [a, v] = b.dataset.manifest.split("/"); showManifest(a, v); }));
    document.querySelectorAll("[data-deactivate]").forEach((b) => b.addEventListener("click", async () => {
      const [a, v] = b.dataset.deactivate.split("/");
      const answer = await S.confirm({ title: "Deactivate version " + b.dataset.version, danger: true, requirePhrase: false, requireReason: false, body: "<p>Deactivated versions cannot be deployed or used for rollback. The artifact is kept. Versions currently deployed cannot be deactivated.</p>" });
      if (!answer) return;
      try { await S.api("POST", "/api/applications/" + a + "/versions/" + v + "/deactivate"); location.reload(); } catch (e) { S.showError(e); }
    }));
  };
})();
