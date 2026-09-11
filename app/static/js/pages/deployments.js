/* Deployments: list, wizard, detail */
(function () {
  const S = window.Scarlet;

  S.pages["deployments-list"] = function (root) {
    const table = new S.DataTable(document.getElementById("deployments-table"), (d) => "<tr>" +
      '<td><a href="/deployments/' + d.id + '"><code>' + S.esc(d.reference) + "</code></a></td>" +
      "<td>" + (d.kind === "ROLLBACK" ? '<span class="badge text-bg-warning text-dark">ROLLBACK</span>' : '<span class="badge text-bg-light text-dark border">DEPLOY</span>') + "</td>" +
      '<td><a href="/applications/' + d.application_id + '">' + S.esc(d.application_code) + "</a></td>" +
      "<td><code>" + S.esc(d.version) + "</code>" + (d.previous_version ? ' <span class="small text-muted">← ' + S.esc(d.previous_version) + "</span>" : "") + "</td>" +
      '<td><a href="/hosts/' + d.target_id + '">' + S.esc(d.target_name) + "</a></td>" +
      "<td>" + S.envBadge(d.environment, d.is_production) + "</td>" +
      "<td>" + S.badge(d.status) + "</td>" +
      '<td class="small">' + S.esc(d.requested_by || "-") + "</td>" +
      '<td class="small text-muted">' + S.fmtDate(d.created_at) + "</td>" +
      '<td class="small">' + S.fmtDuration(d.duration_seconds) + "</td>" +
      '<td class="text-end"><a class="btn btn-sm btn-outline-secondary" href="/deployments/' + d.id + '"><i class="fa-solid fa-eye"></i></a></td></tr>', { autoRefresh: 15000, extraParams: { batch: root.dataset.preselectBatch } });
    if (root.dataset.preselectApp) document.querySelector('#deployments-table [name="application_id"]').value = root.dataset.preselectApp;
    table.load();
  };

  // --- wizard ---------------------------------------------------------------------------------------
  S.pages["deployment-wizard"] = function (root) {
    const state = { step: 1, app: null, version: null, hosts: [], hostData: {}, requirements: {}, preflight: null, batch: null, deployments: [] };
    const panes = document.querySelectorAll(".wizard-pane"), steps = document.querySelectorAll("#wizard-steps .wstep");
    const btnNext = document.getElementById("btn-next"), btnBack = document.getElementById("btn-back"), hint = document.getElementById("wizard-hint");
    const isProd = () => state.hosts.some((id) => state.hostData[id] && state.hostData[id].is_production);
    const prodEnvs = () => Array.from(new Set(state.hosts.map((id) => state.hostData[id].environment)));

    function show(step) {
      state.step = step;
      panes.forEach((p) => p.classList.toggle("active", Number(p.dataset.pane) === step));
      steps.forEach((s) => { const n = Number(s.dataset.step); s.classList.toggle("active", n === step); s.classList.toggle("done", n < step); });
      btnBack.disabled = step === 1 || step >= 7;
      btnNext.textContent = step === 6 ? "Deploy" : step >= 7 ? "Finish" : "Next";
      btnNext.className = "btn " + (step === 6 ? (isProd() ? "btn-danger" : "btn-success") : "btn-primary");
      validate();
    }
    function validate() {
      let ok = false;
      if (state.step === 1) ok = !!state.app;
      else if (state.step === 2) ok = !!state.version;
      else if (state.step === 3) ok = state.hosts.length > 0;
      else if (state.step === 4) ok = true;
      else if (state.step === 5) ok = !!state.preflight && state.preflight.ok;
      else if (state.step === 6) {
        const reqs = anyReq();
        const reason = document.getElementById("reason").value.trim();
        const phrase = document.getElementById("phrase").value.trim();
        ok = (!reqs.require_reason || reason) && (!reqs.require_confirmation || phrase === reqs.confirmation_phrase);
      } else ok = state.step === 9;
      btnNext.disabled = !ok;
    }
    function anyReq() {
      const out = { require_confirmation: false, require_reason: false, confirmation_phrase: S.prodPhrase, require_approval: false };
      Object.values(state.requirements).forEach((r) => { if (r.require_confirmation) { out.require_confirmation = true; out.confirmation_phrase = r.confirmation_phrase || out.confirmation_phrase; } if (r.require_reason) out.require_reason = true; if (r.require_approval) out.require_approval = true; });
      return out;
    }

    // step 1
    document.querySelectorAll("#app-list .host-pick").forEach((card) => card.addEventListener("click", () => {
      document.querySelectorAll("#app-list .host-pick").forEach((c) => c.classList.remove("selected"));
      card.classList.add("selected");
      state.app = { id: Number(card.dataset.appId), code: card.dataset.appCode, runtime: card.dataset.runtime };
      state.version = null; state.hosts = [];
      validate();
    }));
    if (root.dataset.preselectApp) { const c = document.querySelector('#app-list .host-pick[data-app-id="' + root.dataset.preselectApp + '"]'); if (c) c.click(); }

    // step 2
    async function loadVersions() {
      const list = document.getElementById("version-list");
      list.innerHTML = '<div class="text-muted"><div class="spinner-border spinner-border-sm me-2"></div>Loading…</div>';
      const res = await S.api("GET", "/api/applications/" + state.app.id + "/versions");
      const versions = res.data.filter((v) => v.is_active);
      list.innerHTML = versions.length ? versions.map((v) => '<div class="col-md-4"><div class="card host-pick h-100 mb-0 ' + (v.package_status && v.package_status !== "VALID" ? "incompatible" : "") + '" data-version-id="' + v.id + '" data-version="' + S.esc(v.version) + '"><div class="card-body py-2"><b>' + S.esc(v.version) + "</b> " + S.runtimeIcon(v.runtime_type) + '<div class="small text-muted">' + S.esc(v.image_name || "") + (v.image_tag ? ":" + S.esc(v.image_tag) : "") + "</div><div class=\"small\">" + (v.package_status ? S.badge(v.package_status) : '<span class="text-muted">no artifact</span>') + ' <span class="text-muted">' + S.fmtDate(v.created_at).slice(0, 10) + "</span></div></div></div></div>").join("") : '<div class="alert alert-warning">No active versions. Upload a package first.</div>';
      list.querySelectorAll(".host-pick:not(.incompatible)").forEach((card) => card.addEventListener("click", () => { list.querySelectorAll(".host-pick").forEach((c) => c.classList.remove("selected")); card.classList.add("selected"); state.version = { id: Number(card.dataset.versionId), version: card.dataset.version }; validate(); }));
    }
    // step 3
    async function loadHosts() {
      const list = document.getElementById("host-list");
      list.innerHTML = '<div class="text-muted"><div class="spinner-border spinner-border-sm me-2"></div>Loading…</div>';
      const res = await S.api("GET", "/api/applications/" + state.app.id + "/compatible-hosts?version_id=" + state.version.id);
      state.hostData = {};
      list.innerHTML = res.data.map((r) => { const h = r.host; state.hostData[h.id] = h; return '<div class="col-md-4"><div class="card host-pick h-100 mb-0 ' + (r.compatible ? "" : "incompatible") + (state.hosts.includes(h.id) ? " selected" : "") + '" data-host-id="' + h.id + '"><div class="card-body py-2"><b>' + S.esc(h.name) + "</b> " + S.envBadge(h.environment, h.is_production) + '<div class="small text-muted">' + S.runtimeIcon(h.runtime_type) + " " + S.esc(h.runtime_version || "") + " · " + S.badge(h.status) + "</div>" + (r.compatible ? "" : '<div class="small text-danger">' + r.problems.map(S.esc).join("<br>") + "</div>") + "</div></div></div>"; }).join("") || '<div class="alert alert-warning">No enabled hosts.</div>';
      list.querySelectorAll(".host-pick:not(.incompatible)").forEach((card) => card.addEventListener("click", () => { const id = Number(card.dataset.hostId); if (state.hosts.includes(id)) { state.hosts = state.hosts.filter((x) => x !== id); card.classList.remove("selected"); } else { state.hosts.push(id); card.classList.add("selected"); } validate(); }));
      if (root.dataset.preselectHost && !state.hosts.length) { const c = list.querySelector('.host-pick:not(.incompatible)[data-host-id="' + root.dataset.preselectHost + '"]'); if (c) c.click(); }
    }
    document.getElementById("group-select").addEventListener("change", (ev) => {
      const ids = (ev.target.selectedOptions[0].dataset.hosts || "").split(",").filter(Boolean).map(Number);
      document.querySelectorAll("#host-list .host-pick:not(.incompatible)").forEach((card) => { const id = Number(card.dataset.hostId); const want = ids.includes(id); if (want && !state.hosts.includes(id)) { state.hosts.push(id); card.classList.add("selected"); } if (!want && state.hosts.includes(id)) { state.hosts = state.hosts.filter((x) => x !== id); card.classList.remove("selected"); } });
      validate();
    });
    // step 4
    async function loadEnv() {
      state.requirements = {};
      for (const id of state.hosts) { const res = await S.api("GET", "/api/hosts/" + id + "/requirements"); state.requirements[id] = res.data; }
      const prod = isProd();
      document.getElementById("env-summary").innerHTML = '<div class="alert ' + (prod ? "alert-danger" : "alert-success") + '">' + (prod ? '<i class="fa-solid fa-triangle-exclamation me-2"></i><b>PRODUCTION deployment.</b> Typed confirmation and a reason are required. ' + (anyReq().require_approval ? "<b>Second-person approval is required before execution.</b>" : "") : '<i class="fa-solid fa-flask me-2"></i>Development deployment.') + "</div><p>Environments: " + prodEnvs().map((e) => S.envBadge(e)).join(" ") + " · Targets: " + state.hosts.map((id) => "<b>" + S.esc(state.hostData[id].name) + "</b>").join(", ") + "</p>";
    }
    // step 5
    async function runPreflight() {
      const box = document.getElementById("preflight-results");
      box.innerHTML = '<div class="text-muted"><div class="spinner-border spinner-border-sm me-2"></div>Connecting to target host(s) and checking runtime, disk, memory, ports…</div>';
      state.preflight = null; validate();
      try {
        const res = await S.api("POST", "/api/deployments/preflight", { application_id: state.app.id, version_id: state.version.id, host_ids: state.hosts, remote: true });
        state.preflight = res.data;
        box.innerHTML = res.data.hosts.map((h) => '<div class="card mb-2"><div class="card-header py-1"><b>' + S.esc(h.host.name) + "</b> " + S.envBadge(h.host.environment, h.host.is_production) + " " + (h.ok ? S.badge("PASS") : S.badge("FAIL")) + '</div><ul class="list-group list-group-flush small">' + h.checks.map((c) => '<li class="list-group-item d-flex justify-content-between align-items-start"><span>' + S.esc(c.label) + '<div class="text-muted">' + S.esc(c.message) + "</div></span>" + S.badge(c.status) + "</li>").join("") + "</ul></div>").join("") + (res.data.ok ? '<div class="alert alert-success py-2">All pre-flight checks passed.</div>' : '<div class="alert alert-danger py-2">Pre-flight failed. Fix the problems above and re-run.</div><button class="btn btn-sm btn-outline-primary" id="btn-rerun-preflight">Re-run checks</button>');
        const rerun = document.getElementById("btn-rerun-preflight"); if (rerun) rerun.addEventListener("click", runPreflight);
      } catch (e) { box.innerHTML = '<div class="alert alert-danger">' + S.esc(e.message) + '</div><button class="btn btn-sm btn-outline-primary" id="btn-rerun-preflight">Re-run checks</button>'; document.getElementById("btn-rerun-preflight").addEventListener("click", runPreflight); }
      validate();
    }
    // step 6
    function loadConfirm() {
      const reqs = anyReq(), prod = isProd();
      document.getElementById("confirm-summary").innerHTML = '<div class="alert ' + (prod ? "alert-danger" : "alert-info") + '"><p class="mb-1">You are deploying <b>' + S.esc(state.app.code) + " " + S.esc(state.version.version) + "</b> to:</p><ul class=\"mb-1\">" + state.hosts.map((id) => "<li><b>" + S.esc(state.hostData[id].name) + "</b> " + S.envBadge(state.hostData[id].environment, state.hostData[id].is_production) + "</li>").join("") + "</ul>" + (prod ? "<p class=\"mb-0\"><b>This operation will modify a production system.</b></p>" : "") + "</div><p class=\"small text-muted\">Strategy: " + document.getElementById("strategy").value + " · auto rollback: " + (document.getElementById("auto_rollback").value || "system default") + "</p>";
      document.getElementById("reason-required").classList.toggle("d-none", !reqs.require_reason);
      document.getElementById("phrase-group").classList.toggle("d-none", !reqs.require_confirmation);
      document.getElementById("phrase-expected").textContent = reqs.confirmation_phrase;
    }
    document.getElementById("reason").addEventListener("input", validate);
    document.getElementById("phrase").addEventListener("input", validate);
    // step 7-9
    async function execute() {
      const view = document.getElementById("execution-view");
      view.innerHTML = '<div class="text-muted"><div class="spinner-border spinner-border-sm me-2"></div>Queuing deployment…</div>';
      const reqs = anyReq();
      try {
        const res = await S.api("POST", "/api/deployments", { application_id: state.app.id, version_id: state.version.id, host_ids: state.hosts, strategy: document.getElementById("strategy").value, reason: document.getElementById("reason").value.trim(), confirmation: reqs.require_confirmation ? document.getElementById("phrase").value.trim() : null, auto_rollback: document.getElementById("auto_rollback").value === "" ? null : document.getElementById("auto_rollback").value === "true", stop_on_failure: document.getElementById("stop_on_failure").checked });
        state.batch = res.data;
        state.deployments = res.data.deployments;
        if (state.deployments.some((d) => d.status === "PENDING_APPROVAL")) {
          view.innerHTML = '<div class="alert alert-warning"><i class="fa-solid fa-user-check me-2"></i>Deployment(s) created and waiting for approval by another authorized user. ' + state.deployments.map((d) => '<a href="/deployments/' + d.id + '"><code>' + S.esc(d.reference) + "</code></a>").join(", ") + "</div>";
          show(9); document.getElementById("result-view").innerHTML = '<div class="alert alert-warning">Pending approval.</div>'; btnNext.disabled = false; return;
        }
        await followBatch();
      } catch (e) { view.innerHTML = '<div class="alert alert-danger">' + S.esc(e.message) + (e.errors ? "<br>" + S.esc(JSON.stringify(e.errors)) : "") + "</div>"; btnBack.disabled = false; }
    }
    function renderSteps(d) {
      return '<div class="card mb-2"><div class="card-header py-1"><a href="/deployments/' + d.id + '"><code>' + S.esc(d.reference) + "</code></a> · <b>" + S.esc(d.target_name) + "</b> " + S.badge(d.status) + '</div><div class="card-body py-2"><ul class="step-list">' + (d.steps || []).map((s) => '<li class="step-' + s.status + '"><span class="step-icon">' + ({ SUCCESS: '<i class="fa-solid fa-circle-check"></i>', FAILED: '<i class="fa-solid fa-circle-xmark"></i>', RUNNING: '<i class="fa-solid fa-spinner fa-spin"></i>', SKIPPED: '<i class="fa-solid fa-forward"></i>' }[s.status] || '<i class="fa-regular fa-circle"></i>') + "</span><span>" + S.esc(s.label) + (s.error_message ? '<div class="text-danger small">' + S.esc(s.error_message) + "</div>" : "") + '</span><span class="step-duration">' + (s.duration_seconds != null ? S.fmtDuration(s.duration_seconds) : "") + "</span></li>").join("") + "</ul>" + (d.error_message ? '<div class="alert alert-danger py-1 small mb-0">' + S.esc(d.error_message) + "</div>" : "") + "</div></div>";
    }
    async function followBatch() {
      const view = document.getElementById("execution-view");
      const ids = state.deployments.map((d) => d.id);
      const finals = [];
      for (const id of ids) {
        const data = await S.poll("/api/deployments/" + id, (r) => r.data.is_terminal, { interval: 2000, onTick: (r) => { const d = r.data; const others = finals.map(renderSteps).join(""); view.innerHTML = others + renderSteps(d); if (["HEALTH_CHECKING", "STARTED"].includes(d.status) && state.step === 7) show(8); document.getElementById("health-view").innerHTML = d.steps ? (d.steps.filter((s) => s.name === "health").map((s) => "<p>" + S.badge(s.status) + " " + S.esc((s.details && s.details.message) || s.error_message || "") + (s.details && s.details.attempts ? " after " + s.details.attempts + " attempt(s)" : "") + "</p>").join("") || '<p class="text-muted">Health check not started yet.</p>') : ""; } });
        finals.push(data.data);
      }
      view.innerHTML = finals.map(renderSteps).join("");
      const allOk = finals.every((d) => d.status === "SUCCESS");
      show(9);
      document.getElementById("result-view").innerHTML = (allOk ? '<div class="alert alert-success"><h5><i class="fa-solid fa-circle-check me-2"></i>SUCCESS</h5>Version <b>' + S.esc(state.version.version) + "</b> of <b>" + S.esc(state.app.code) + "</b> deployed successfully to " + finals.map((d) => S.esc(d.target_name)).join(", ") + ".</div>" : '<div class="alert alert-danger"><h5><i class="fa-solid fa-circle-xmark me-2"></i>Deployment finished with errors</h5>' + finals.filter((d) => d.status !== "SUCCESS").map((d) => "<div><b>" + S.esc(d.target_name) + "</b>: " + S.badge(d.status) + " " + S.esc(d.error_message || "") + "</div>").join("") + "</div>") + finals.map((d) => '<a class="btn btn-sm btn-outline-secondary me-1" href="/deployments/' + d.id + '">' + S.esc(d.reference) + "</a>").join("");
      btnNext.disabled = false;
    }

    btnNext.addEventListener("click", async () => {
      if (btnNext.disabled) return;
      try {
        if (state.step === 1) { show(2); await loadVersions(); }
        else if (state.step === 2) { show(3); await loadHosts(); }
        else if (state.step === 3) { show(4); await loadEnv(); }
        else if (state.step === 4) { show(5); await runPreflight(); }
        else if (state.step === 5) { show(6); loadConfirm(); }
        else if (state.step === 6) { btnNext.disabled = true; show(7); await execute(); }
        else if (state.step >= 7) { window.location.href = state.deployments.length === 1 ? "/deployments/" + state.deployments[0].id : "/deployments"; }
      } catch (e) { S.showError(e); }
    });
    btnBack.addEventListener("click", () => { if (state.step > 1 && state.step < 7) show(state.step - 1); });
    hint.textContent = "Select an application to begin.";
    show(1);
  };

  // --- detail -----------------------------------------------------------------------------------------
  S.pages["deployment-detail"] = function (root) {
    const id = root.dataset.deploymentId;
    const production = root.dataset.production === "1";
    const cancel = document.getElementById("btn-cancel");
    if (cancel) cancel.addEventListener("click", async () => { const a = await S.confirm({ title: "Cancel deployment", danger: true, requirePhrase: false, showReason: true, requireReason: false }); if (!a) return; try { await S.api("POST", "/api/deployments/" + id + "/cancel", { reason: a.reason }); location.reload(); } catch (e) { S.showError(e); } });
    const approve = document.getElementById("btn-approve");
    if (approve) approve.addEventListener("click", async () => { const a = await S.confirm({ title: "Approve production deployment", production, operation: "APPROVE", requirePhrase: true, phrase: "APPROVE", showReason: true, requireReason: true, okLabel: "Approve", body: "<p>You confirm that this change is authorized. Execution starts immediately after approval.</p>" }); if (!a) return; try { await S.api("POST", "/api/deployments/" + id + "/approve", { comment: a.reason }); location.reload(); } catch (e) { S.showError(e); } });
    const reject = document.getElementById("btn-reject");
    if (reject) reject.addEventListener("click", async () => { const a = await S.confirm({ title: "Reject deployment", danger: true, requirePhrase: false, showReason: true, requireReason: true, okLabel: "Reject" }); if (!a) return; try { await S.api("POST", "/api/deployments/" + id + "/reject", { comment: a.reason }); location.reload(); } catch (e) { S.showError(e); } });
    if (root.dataset.terminal === "1") return;
    S.poll("/api/deployments/" + id + "/steps", (r) => r.data.is_terminal, { interval: 2000, onTick: (r) => {
      const d = r.data;
      document.getElementById("dep-status").innerHTML = S.badge(d.status);
      const list = document.getElementById("step-list");
      if (d.steps.length) list.innerHTML = d.steps.map((s) => '<li class="step-' + s.status + '"><span class="step-icon">' + ({ SUCCESS: '<i class="fa-solid fa-circle-check"></i>', FAILED: '<i class="fa-solid fa-circle-xmark"></i>', RUNNING: '<i class="fa-solid fa-spinner fa-spin"></i>', SKIPPED: '<i class="fa-solid fa-forward"></i>' }[s.status] || '<i class="fa-regular fa-circle"></i>') + '</span><div class="flex-grow-1"><div><b>' + S.esc(s.label) + '</b> <span class="small text-muted">' + s.status + "</span>" + (s.error_message ? '<div class="text-danger small">' + S.esc(s.error_message) + "</div>" : "") + "</div>" + (s.stdout || s.stderr ? '<details class="small"><summary class="text-muted">output</summary><pre class="scarlet-log mt-1">' + S.esc(s.stdout || "") + (s.stderr ? "\n--- stderr ---\n" + S.esc(s.stderr) : "") + "</pre></details>" : "") + '</div><span class="step-duration">' + (s.duration_seconds != null ? S.fmtDuration(s.duration_seconds) : "") + "</span></li>").join("");
      if (d.error_message) { document.getElementById("dep-error").classList.remove("d-none"); document.getElementById("dep-error-msg").textContent = d.error_message; }
    } }).then(() => { document.getElementById("poll-indicator").textContent = "finished"; setTimeout(() => location.reload(), 1500); }).catch((e) => S.showError(e, "Live update"));
  };
})();
