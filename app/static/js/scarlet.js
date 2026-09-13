/* SCARLET core front-end: API client, toasts, confirmation modal, polling, data tables.
 * No inline scripts are used (CSP). Pages declare behaviour through data-* attributes
 * and page modules register under Scarlet.pages[name].
 */
(function () {
  "use strict";

  const csrfToken = () => (document.querySelector('meta[name="csrf-token"]') || {}).content || "";

  // --- i18n ------------------------------------------------------------------------------------
  // The server injects the active catalogue (English source -> localised text) as JSON.
  let catalogue = {};
  try {
    const node = document.getElementById("scarlet-i18n");
    if (node) catalogue = JSON.parse(node.textContent || "{}");
  } catch (e) { catalogue = {}; }
  /** Translate a source string; unknown strings fall back to the English text. */
  function t(text, vars) {
    let out = catalogue[text] != null ? catalogue[text] : text;
    if (vars) Object.keys(vars).forEach((k) => { out = out.split("{" + k + "}").join(vars[k]); });
    return out;
  }
  const lang = () => (document.querySelector('meta[name="scarlet-lang"]') || {}).content || "en";
  const permissions = new Set(((document.querySelector('meta[name="scarlet-permissions"]') || {}).content || "").split(",").filter(Boolean));
  const prodPhrase = (document.querySelector('meta[name="scarlet-prod-phrase"]') || {}).content || "DEPLOY TO PROD";

  // --- helpers ---------------------------------------------------------------------------------
  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function fmtDate(iso) {
    if (!iso) return "-";
    const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
    if (isNaN(d.getTime())) return iso;
    return d.toISOString().replace("T", " ").substring(0, 19) + " UTC";
  }
  function fmtBytes(n) {
    n = Number(n || 0);
    const units = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return (i === 0 ? n : n.toFixed(1)) + " " + units[i];
  }
  function fmtDuration(s) {
    if (s == null) return "-";
    s = Number(s);
    if (s < 60) return s.toFixed(1) + "s";
    const m = Math.floor(s / 60), r = Math.floor(s % 60);
    if (m < 60) return m + "m " + r + "s";
    return Math.floor(m / 60) + "h " + (m % 60) + "m";
  }
  const STATUS_CLASS = {
    ONLINE: "success", OFFLINE: "danger", UNKNOWN: "secondary", DISABLED: "dark",
    RUNNING: "success", STOPPED: "secondary", STARTING: "info", STOPPING: "info", FAILED: "danger", NOT_INSTALLED: "light text-dark",
    HEALTHY: "success", UNHEALTHY: "danger",
    SUCCESS: "success", QUEUED: "secondary", CREATED: "secondary", PENDING_APPROVAL: "warning text-dark", APPROVED: "info", CANCELLED: "dark", REJECTED: "dark", TIMEOUT: "danger",
    ROLLED_BACK: "warning text-dark", ROLLBACK_REQUIRED: "warning text-dark", ROLLING_BACK: "warning text-dark",
    PENDING: "light text-dark", SKIPPED: "secondary",
    VALID: "success", INVALID: "danger", VALIDATING: "info", UPLOADED: "secondary", QUARANTINED: "danger",
    MISMATCH: "danger", REVOKED: "dark", DENIED: "warning text-dark", INFO: "info", FAILURE: "danger",
    DEV: "success", PROD: "danger", LOW: "secondary", MEDIUM: "info", HIGH: "warning text-dark", CRITICAL: "danger",
    PASS: "success", WARN: "warning text-dark", FAIL: "danger", SKIP: "secondary",
  };
  function badge(status, extra) {
    const s = String(status || "UNKNOWN");
    const cls = STATUS_CLASS[s.toUpperCase()] || (s.toUpperCase().endsWith("ING") ? "info" : (s.toUpperCase().includes("FAIL") ? "danger" : "secondary"));
    return '<span class="badge text-bg-' + cls + ' ' + (extra || "") + '" data-status="' + esc(s) + '">' + esc(t(s.replace(/_/g, " "))) + "</span>";
  }
  function envBadge(code, isProd) {
    const prod = isProd != null ? isProd : String(code).toUpperCase() === "PROD";
    return '<span class="badge text-bg-' + (prod ? "danger" : "success") + ' env-badge"><i class="fa-solid ' + (prod ? "fa-triangle-exclamation" : "fa-flask") + ' me-1"></i>' + esc(code || "?") + "</span>";
  }
  function runtimeIcon(rt) {
    const icons = { DOCKER: "fa-brands fa-docker", PODMAN: "fa-solid fa-cube", KUBERNETES: "fa-solid fa-dharmachakra", NONE: "fa-solid fa-ban" };
    rt = String(rt || "NONE").toUpperCase();
    return '<i class="' + (icons[rt] || "fa-solid fa-question") + ' me-1"></i>' + esc(rt);
  }
  function can(perm, production) {
    if (!permissions.has(perm)) return false;
    const prodSensitive = ["deployment.execute", "deployment.rollback", "lifecycle.start", "lifecycle.stop", "lifecycle.restart", "configuration.update", "host.delete", "host.update"];
    if (production && prodSensitive.includes(perm)) return permissions.has("prod." + perm);
    return true;
  }

  // --- toasts -----------------------------------------------------------------------------------
  function toast(message, level, delay) {
    const container = document.getElementById("toast-container");
    if (!container) { alert(message); return; }
    const colors = { success: "text-bg-success", danger: "text-bg-danger", error: "text-bg-danger", warning: "text-bg-warning", info: "text-bg-primary" };
    const el = document.createElement("div");
    el.className = "toast align-items-center border-0 " + (colors[level] || colors.info);
    el.setAttribute("role", "alert");
    el.innerHTML = '<div class="d-flex"><div class="toast-body">' + esc(t(message)) + '</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>';
    container.appendChild(el);
    const t = new bootstrap.Toast(el, { delay: delay || (level === "danger" || level === "error" ? 9000 : 4500) });
    t.show();
    el.addEventListener("hidden.bs.toast", () => el.remove());
  }

  // --- API client ----------------------------------------------------------------------------------
  class ApiError extends Error {
    constructor(status, body) {
      const err = (body && body.error) || {};
      super(err.message || ("HTTP " + status));
      this.status = status; this.code = err.code || "HTTP_ERROR"; this.errors = err.errors || {}; this.details = err.details || {}; this.requestId = err.request_id;
    }
  }
  async function api(method, url, body, options) {
    options = options || {};
    const headers = { "Accept": "application/json", "X-CSRFToken": csrfToken() };
    let payload;
    if (body instanceof FormData) { payload = body; }
    else if (body !== undefined && body !== null) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
    const response = await fetch(url, { method, headers, body: payload, credentials: "same-origin", signal: options.signal });
    if (response.status === 401) { window.location.href = "/login?next=" + encodeURIComponent(window.location.pathname + window.location.search); throw new ApiError(401, {}); }
    const text = await response.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
    if (!response.ok) throw new ApiError(response.status, data || { error: { message: text.slice(0, 300) } });
    return data;
  }
  function showError(err, prefix) {
    let msg = (prefix ? t(prefix) + ": " : "") + (err && err.message ? err.message : String(err));
    if (err && err.errors && Object.keys(err.errors).length) {
      msg += " " + Object.entries(err.errors).map(([k, v]) => k + ": " + (Array.isArray(v) ? v.join(" ") : v)).join(" | ");
    }
    if (err && err.requestId) msg += " (request " + err.requestId + ")";
    toast(msg, "danger");
    console.error(err);
  }

  // --- confirmation modal -----------------------------------------------------------------------------
  /**
   * confirm({title, body, details:{k:v}, production:bool, operation:'DEPLOY'|'STOP'..., requireReason:bool, requirePhrase:bool, phrase, danger:bool, okLabel})
   * resolves {reason, confirmation} or null when cancelled.
   */
  function confirm(opts) {
    return new Promise((resolve) => {
      const modalEl = document.getElementById("confirm-modal");
      const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
      const title = document.getElementById("confirm-modal-title");
      const bodyEl = document.getElementById("confirm-modal-body");
      const details = document.getElementById("confirm-modal-details");
      const prodBanner = document.getElementById("confirm-modal-prod-banner");
      const reasonGroup = document.getElementById("confirm-modal-reason-group");
      const reasonInput = document.getElementById("confirm-modal-reason");
      const reasonRequired = document.getElementById("confirm-modal-reason-required");
      const phraseGroup = document.getElementById("confirm-modal-phrase-group");
      const phraseInput = document.getElementById("confirm-modal-phrase");
      const phraseExpected = document.getElementById("confirm-modal-phrase-expected");
      const okBtn = document.getElementById("confirm-modal-ok");
      const header = document.getElementById("confirm-modal-header");

      const production = !!opts.production;
      const op = (opts.operation || "CONFIRM").toUpperCase();
      const expected = opts.phrase || (op === "DEPLOY" ? prodPhrase : op + " PROD");
      const requirePhrase = opts.requirePhrase != null ? opts.requirePhrase : production;
      const requireReason = opts.requireReason != null ? opts.requireReason : production;
      const showReason = opts.showReason != null ? opts.showReason : (production || opts.reasonOptional);

      title.textContent = t(opts.title || "Confirm operation");
      bodyEl.innerHTML = opts.body || "";
      details.innerHTML = Object.entries(opts.details || {}).map(([k, v]) => '<dt class="col-4 text-muted">' + esc(t(k)) + '</dt><dd class="col-8">' + v + "</dd>").join("");
      prodBanner.classList.toggle("d-none", !production);
      header.className = "modal-header " + (production || opts.danger ? "text-bg-danger" : "");
      okBtn.className = "btn " + (production || opts.danger ? "btn-danger" : "btn-primary");
      okBtn.textContent = t(opts.okLabel || "Confirm");
      reasonGroup.classList.toggle("d-none", !showReason);
      reasonRequired.classList.toggle("d-none", !requireReason);
      reasonInput.value = "";
      phraseGroup.classList.toggle("d-none", !requirePhrase);
      phraseExpected.textContent = expected;
      phraseInput.value = "";

      const validate = () => {
        let ok = true;
        if (requireReason && !reasonInput.value.trim()) ok = false;
        if (requirePhrase && phraseInput.value.trim() !== expected) ok = false;
        okBtn.disabled = !ok;
      };
      validate();
      let settled = false;
      const done = (value) => { if (settled) return; settled = true; cleanup(); resolve(value); };
      const onOk = () => { validate(); if (okBtn.disabled) return; modal.hide(); done({ reason: reasonInput.value.trim(), confirmation: requirePhrase ? phraseInput.value.trim() : null }); };
      const onHide = () => done(null);
      const cleanup = () => { okBtn.removeEventListener("click", onOk); modalEl.removeEventListener("hidden.bs.modal", onHide); reasonInput.removeEventListener("input", validate); phraseInput.removeEventListener("input", validate); };
      okBtn.addEventListener("click", onOk);
      modalEl.addEventListener("hidden.bs.modal", onHide);
      reasonInput.addEventListener("input", validate);
      phraseInput.addEventListener("input", validate);
      modal.show();
      setTimeout(() => (requirePhrase ? phraseInput : reasonInput).focus(), 300);
    });
  }

  // --- polling ------------------------------------------------------------------------------------------
  async function poll(url, isDone, options) {
    options = options || {};
    const interval = options.interval || 2000;
    const maxMs = options.timeout || 45 * 60 * 1000;
    const start = Date.now();
    for (;;) {
      const data = await api("GET", url);
      if (options.onTick) options.onTick(data);
      if (isDone(data)) return data;
      if (Date.now() - start > maxMs) throw new Error("Polling timed out");
      await new Promise((r) => setTimeout(r, interval));
    }
  }

  // --- operation runner: POST -> 202 -> poll operation -> modal ----------------------------------------------
  function renderOperationResult(op) {
    const result = op.result || {};
    if (op.operation_type === "LOGS" && result.lines) {
      return '<pre class="scarlet-log">' + result.lines.map(esc).join("\n") + "</pre>";
    }
    if (op.operation_type === "DISCOVER" && result.os) {
      const rts = Object.entries(result.runtimes || {}).map(([k, v]) => "<li>" + runtimeIcon(k) + " " + (v.available ? badge("ONLINE") + " " + esc(v.version || "") + (v.rootless != null ? (v.rootless ? " rootless" : " rootful") : "") : badge("OFFLINE") + ' <span class="text-muted small">' + esc((v.details && v.details.reason) || v.error || "not available") + "</span>") + "</li>").join("");
      return '<dl class="row small"><dt class="col-4">OS</dt><dd class="col-8">' + esc(result.os.pretty_name || result.os.name) + "</dd><dt class=\"col-4\">Kernel / arch</dt><dd class=\"col-8\">" + esc(result.architecture || "") + "</dd><dt class=\"col-4\">CPU</dt><dd class=\"col-8\">" + esc(result.cpu_count) + "</dd><dt class=\"col-4\">Memory</dt><dd class=\"col-8\">" + esc((result.memory || {}).available_mb) + " / " + esc((result.memory || {}).total_mb) + " MB available</dd><dt class=\"col-4\">Disk</dt><dd class=\"col-8\">" + esc((result.disk || {}).available_mb) + " / " + esc((result.disk || {}).total_mb) + " MB free</dd><dt class=\"col-4\">SELinux</dt><dd class=\"col-8\">" + esc(result.selinux || "n/a") + "</dd></dl><h6>Runtimes</h6><ul class=\"list-unstyled\">" + rts + "</ul>" + (result.suggested_runtime ? '<div class="alert alert-info py-2 small">Host runtime is NONE; detected <b>' + esc(result.suggested_runtime) + "</b>. Edit the host to set it.</div>" : "");
    }
    if (op.operation_type === "HEALTH") {
      return "<p>" + badge(result.status) + " " + esc(result.message || "") + ' <span class="text-muted small">(' + esc(result.attempts) + " attempt(s))</span></p>";
    }
    if (op.operation_type === "STATUS" || op.operation_type === "VERSION" || op.operation_type === "START" || op.operation_type === "STOP" || op.operation_type === "RESTART" || op.operation_type === "SCALE") {
      let html = "<p>" + (result.state ? badge(result.state) : "") + (op.result_code ? " " + badge(op.result_code) : "") + (result.version ? ' version <code>' + esc(result.version) + "</code>" : "") + (result.message ? ' <span class="text-muted">' + esc(result.message) + "</span>" : "") + "</p>";
      if (result.drift) html += "<p>Drift: " + (result.drift.detected ? '<span class="drift-flag"><i class="fa-solid fa-triangle-exclamation"></i> ' + esc(result.drift.drift_type) + "</span>" : '<span class="text-success">none</span>') + "</p>";
      if (result.details && Object.keys(result.details).length) html += '<details><summary class="small text-muted">Details</summary><pre class="small">' + esc(JSON.stringify(result.details, null, 2)) + "</pre></details>";
      if (result.inspect) html += '<details><summary class="small text-muted">Inspect</summary><pre class="small">' + esc(JSON.stringify(result.inspect, null, 2)) + "</pre></details>";
      return html;
    }
    if (op.operation_type === "TEST_CONNECTION") {
      return "<p>" + badge(result.ok ? "ONLINE" : "OFFLINE") + " connected as <code>" + esc(result.remote_user) + "</code> to <code>" + esc(result.remote_hostname) + "</code> in " + esc(result.latency_ms) + " ms</p>";
    }
    return Object.keys(result).length ? '<pre class="small">' + esc(JSON.stringify(result, null, 2)) + "</pre>" : "";
  }

  function showOperationModal(op, opts) {
    opts = opts || {};
    const modalEl = document.getElementById("operation-modal");
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    const update = (o) => {
      document.getElementById("operation-modal-title").textContent = (o.operation_type || "Operation") + " " + (o.reference || "");
      document.getElementById("operation-modal-status").innerHTML = badge(o.status);
      document.getElementById("operation-modal-spinner").classList.toggle("d-none", !!o.is_terminal);
      document.getElementById("operation-modal-meta").innerHTML = [["Application", o.application_code], ["Target", o.target_name], ["Environment", o.environment ? envBadge(o.environment) : "-"], ["Requested by", o.requested_by], ["Started", fmtDate(o.started_at)], ["Duration", fmtDuration(o.duration_seconds)]].map(([k, v]) => '<dt class="col-4 text-muted">' + t(k) + '</dt><dd class="col-8">' + (v == null ? "-" : v) + "</dd>").join("");
      let res = "";
      if (o.status === "FAILED" || o.status === "TIMEOUT") res += '<div class="alert alert-danger py-2"><b>' + esc(o.error_code || "ERROR") + "</b> " + esc(o.error_message || "") + "</div>";
      if (o.is_terminal) res += renderOperationResult(o);
      document.getElementById("operation-modal-result").innerHTML = res;
      document.getElementById("operation-modal-log").textContent = (o.logs || []).map((l) => fmtDate(l.timestamp) + " [" + l.level + "] " + l.message + (l.command ? "\n    $ " + l.command + (l.exit_code != null ? "  (exit " + l.exit_code + ")" : "") : "") + (l.stderr ? "\n    ! " + l.stderr.split("\n").join("\n    ! ") : "")).join("\n");
      document.getElementById("operation-modal-link").href = "/operations/" + o.id;
    };
    update(op);
    modal.show();
    if (op.is_terminal) { if (opts.onDone) opts.onDone(op); return Promise.resolve(op); }
    return poll("/api/operations/" + op.id, (d) => d.data.is_terminal, { onTick: (d) => update(d.data) }).then((d) => {
      const final = d.data;
      toast(final.operation_type + " " + final.status + (final.result_code ? " (" + final.result_code + ")" : ""), final.status === "SUCCESS" ? "success" : "danger");
      if (opts.onDone) opts.onDone(final);
      return final;
    }).catch((e) => { showError(e, "Polling failed"); throw e; });
  }

  /** Run a lifecycle/host operation: confirm (if needed), POST, then follow in the modal. */
  async function runOperation(cfg) {
    // cfg: {url, body, title, operation, production, details, confirm:bool, onDone, method}
    let extra = {};
    if (cfg.confirm !== false) {
      const answer = await confirm({ title: cfg.title, body: cfg.body, details: cfg.details, production: cfg.production, operation: cfg.operation, danger: cfg.danger, okLabel: cfg.okLabel || cfg.operation, showReason: true, requireReason: cfg.production });
      if (!answer) return null;
      extra = { reason: answer.reason, confirmation: answer.confirmation };
    }
    const buttons = document.querySelectorAll("[data-op-button]");
    buttons.forEach((b) => b.classList.add("op-busy"));
    try {
      const res = await api(cfg.method || "POST", cfg.url, Object.assign({}, cfg.body || {}, extra));
      const op = res.data;
      if (op && op.operation_type) return await showOperationModal(op, { onDone: cfg.onDone });
      if (cfg.onDone) cfg.onDone(op);
      toast(cfg.successMessage || "Request accepted", "success");
      return op;
    } catch (e) {
      showError(e, cfg.title || "Operation failed");
      return null;
    } finally {
      buttons.forEach((b) => b.classList.remove("op-busy"));
    }
  }

  // --- data table --------------------------------------------------------------------------------------------
  class DataTable {
    constructor(root, renderRow, options) {
      this.root = root; this.renderRow = renderRow; this.options = options || {};
      this.endpoint = root.dataset.endpoint;
      this.state = { page: 1, per_page: Number(root.dataset.pageSize || 25), sort: root.dataset.sort || this.options.sort || "", direction: root.dataset.direction || this.options.direction || "desc", search: "" };
      this.body = root.querySelector('[data-role="body"]');
      this.filters = root.querySelector('[data-role="filters"]');
      const search = root.querySelector('[data-role="search"]');
      let t;
      if (search) search.addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => { this.state.search = search.value.trim(); this.state.page = 1; this.load(); }, 300); });
      root.querySelector('[data-role="refresh"]').addEventListener("click", () => this.load());
      root.querySelectorAll("th.sortable").forEach((th) => th.addEventListener("click", () => {
        const key = th.dataset.sort;
        if (this.state.sort === key) this.state.direction = this.state.direction === "asc" ? "desc" : "asc"; else { this.state.sort = key; this.state.direction = "desc"; }
        root.querySelectorAll("th.sortable").forEach((x) => x.classList.toggle("active", x === th));
        this.load();
      }));
      if (this.filters) this.filters.querySelectorAll("select, input").forEach((el) => el.addEventListener("change", () => { this.state.page = 1; this.load(); }));
      if (this.options.autoRefresh) this.timer = setInterval(() => { if (document.visibilityState === "visible") this.load(true); }, this.options.autoRefresh);
    }
    params() {
      const p = new URLSearchParams({ page: this.state.page, per_page: this.state.per_page, direction: this.state.direction });
      if (this.state.sort) p.set("sort", this.state.sort);
      if (this.state.search) p.set("search", this.state.search);
      if (this.filters) this.filters.querySelectorAll("select, input").forEach((el) => { if (el.value) p.set(el.name, el.value); });
      Object.entries(this.options.extraParams || {}).forEach(([k, v]) => { if (v != null && v !== "") p.set(k, v); });
      return p;
    }
    async load(silent) {
      const cols = this.root.querySelectorAll("thead th").length;
      if (!silent) this.body.innerHTML = '<tr><td colspan="' + cols + '" class="text-center text-muted py-4"><div class="spinner-border spinner-border-sm me-2"></div>Loading…</td></tr>';
      try {
        const res = await api("GET", this.endpoint + (this.endpoint.includes("?") ? "&" : "?") + this.params().toString());
        const items = res.data || [];
        const pg = (res.meta && res.meta.pagination) || { page: 1, pages: 1, total: items.length };
        this.body.innerHTML = items.length ? items.map((row) => this.renderRow(row)).join("") : '<tr><td colspan="' + cols + '" class="text-center text-muted py-4">' + esc(this.root.querySelector('[data-role="empty"]').textContent) + "</td></tr>";
        this.root.querySelector('[data-role="summary"]').textContent = pg.total + " " + t(pg.total === 1 ? "record" : "records");
        this.renderPagination(pg);
        if (this.options.afterLoad) this.options.afterLoad(items, this);
      } catch (e) {
        this.body.innerHTML = '<tr><td colspan="' + cols + '" class="text-danger py-3">' + esc(e.message) + "</td></tr>";
      }
    }
    renderPagination(pg) {
      const ul = this.root.querySelector('[data-role="pagination"]');
      const pages = pg.pages || 1, cur = pg.page || 1;
      if (pages <= 1) { ul.innerHTML = ""; return; }
      const items = [];
      const add = (p, label, disabled, active) => items.push('<li class="page-item' + (disabled ? " disabled" : "") + (active ? " active" : "") + '"><a class="page-link" href="#" data-page="' + p + '">' + label + "</a></li>");
      add(cur - 1, "&laquo;", cur <= 1);
      const start = Math.max(1, cur - 3), end = Math.min(pages, cur + 3);
      for (let p = start; p <= end; p++) add(p, p, false, p === cur);
      add(cur + 1, "&raquo;", cur >= pages);
      ul.innerHTML = items.join("");
      ul.querySelectorAll("a[data-page]").forEach((a) => a.addEventListener("click", (ev) => { ev.preventDefault(); const p = Number(a.dataset.page); if (p >= 1 && p <= pages) { this.state.page = p; this.load(); } }));
    }
  }

  // --- notifications & active ops in navbar ---------------------------------------------------------------------
  async function refreshNavbar() {
    try {
      if (permissions.has("notification.view")) {
        const res = await api("GET", "/api/notifications?unread=1");
        const count = res.data.unread || 0;
        const el = document.getElementById("notif-count");
        if (el) el.textContent = count ? String(count) : "";
        const items = document.getElementById("notif-items");
        if (items) items.innerHTML = res.data.items.length ? res.data.items.slice(0, 8).map((n) => '<a href="' + esc(n.link || "/notifications") + '" class="dropdown-item small"><i class="fa-solid ' + ({ ERROR: "fa-circle-xmark text-danger", WARNING: "fa-triangle-exclamation text-warning", SUCCESS: "fa-circle-check text-success" }[n.level] || "fa-circle-info text-info") + ' me-2"></i>' + esc(n.title) + '<span class="float-end text-muted fs-7">' + fmtDate(n.created_at).substring(11, 16) + "</span></a>").join("") : '<span class="dropdown-item text-muted small">' + t("No unread notifications") + '</span>';
      }
      if (permissions.has("deployment.view")) {
        const res = await api("GET", "/api/operations/active");
        const el = document.getElementById("active-ops-count");
        if (el) el.textContent = String(res.data.length);
      }
    } catch (e) { /* ignore navbar refresh errors */ }
  }

  // --- generic data-action buttons ---------------------------------------------------------------------------------
  // <button data-action="lifecycle" data-op="STOP" data-app="3" data-host="2" data-production="1" data-app-code=".." data-host-name="..">
  document.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-action]");
    if (!btn) return;
    const d = btn.dataset;
    const production = d.production === "1" || d.production === "true";
    if (d.action === "lifecycle") {
      ev.preventDefault();
      const op = d.op.toUpperCase();
      const readOnly = ["STATUS", "HEALTH", "VERSION", "LOGS"].includes(op);
      await runOperation({
        url: "/api/applications/" + d.app + "/" + op.toLowerCase(), body: { host_id: Number(d.host) }, title: op + " " + d.appCode, operation: op, production, confirm: !readOnly,
        body_html: "", details: { Application: "<b>" + esc(d.appCode) + "</b>", Target: esc(d.hostName), Environment: envBadge(d.env, production), Version: esc(d.version || "-") },
        danger: op === "STOP", onDone: () => { if (d.reload === "1") setTimeout(() => window.location.reload(), 800); },
      });
    } else if (d.action === "host-op") {
      ev.preventDefault();
      await runOperation({ url: "/api/hosts/" + d.host + "/" + d.op, confirm: false, title: d.op, onDone: () => { if (d.reload === "1") setTimeout(() => window.location.reload(), 800); } });
    } else if (d.action === "rollback") {
      ev.preventDefault();
      const answer = await confirm({ title: t("Rollback") + " " + d.appCode, operation: "ROLLBACK", production, danger: true, showReason: true, requireReason: production, details: { [t("Application")]: "<b>" + esc(d.appCode) + "</b>", [t("Target")]: esc(d.hostName), [t("Environment")]: envBadge(d.env, production), [t("Current version")]: esc(d.version || "-"), [t("Rollback to")]: esc(d.previousVersion || t("previous successful release")) }, body: "<p>The previous release will be re-activated and started; the current release directory is preserved.</p>" });
      if (!answer) return;
      try {
        const res = await api("POST", "/api/applications/" + d.app + "/rollback", { host_id: Number(d.host), reason: answer.reason, confirmation: answer.confirmation, version_id: d.targetVersion ? Number(d.targetVersion) : undefined });
        toast("Rollback " + res.data.reference + " queued", "success");
        window.location.href = "/deployments/" + res.data.id;
      } catch (e) { showError(e, "Rollback"); }
    }
  });

  // --- boot -----------------------------------------------------------------------------------------------------------
  const Scarlet = { t, lang, api, ApiError, esc, fmtDate, fmtBytes, fmtDuration, badge, envBadge, runtimeIcon, toast, confirm, poll, runOperation, showOperationModal, showError, DataTable, can, permissions, prodPhrase, pages: {}, refreshNavbar };
  window.Scarlet = Scarlet;
  document.addEventListener("DOMContentLoaded", () => {
    refreshNavbar();
    setInterval(() => { if (document.visibilityState === "visible") refreshNavbar(); }, 30000);
    const pageRoot = document.querySelector("[data-page]");
    if (pageRoot && Scarlet.pages[pageRoot.dataset.page]) Scarlet.pages[pageRoot.dataset.page](pageRoot);
  });
})();
