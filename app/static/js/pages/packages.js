/* Packages: list and upload */
(function () {
  const S = window.Scarlet;

  function renderPackage(p) {
    const errors = (p.validation_errors || []).map((e) => '<li class="text-danger">' + S.esc(e) + "</li>").join("");
    const warnings = (p.validation_warnings || []).map((w) => '<li class="text-warning-emphasis">' + S.esc(w) + "</li>").join("");
    return '<dl class="row small">' +
      "<dt class=\"col-3\">Status</dt><dd class=\"col-9\">" + S.badge(p.status) + (p.scanner_result ? " scanner: " + S.esc(p.scanner_result) : "") + "</dd>" +
      "<dt class=\"col-3\">File</dt><dd class=\"col-9\">" + S.esc(p.original_filename) + " (" + S.fmtBytes(p.size_bytes) + ", " + (p.file_count || "?") + " members)</dd>" +
      "<dt class=\"col-3\">SHA-256</dt><dd class=\"col-9\"><code>" + S.esc(p.checksum_sha256) + "</code></dd>" +
      "<dt class=\"col-3\">Manifest</dt><dd class=\"col-9\">" + S.esc(p.manifest_application || "-") + " " + S.esc(p.manifest_version || "") + " " + (p.manifest_runtime ? S.runtimeIcon(p.manifest_runtime) : "") + "</dd>" +
      "<dt class=\"col-3\">Uploaded</dt><dd class=\"col-9\">" + S.fmtDate(p.created_at) + " by " + S.esc(p.uploaded_by || "-") + "</dd>" +
      "<dt class=\"col-3\">Release</dt><dd class=\"col-9\">" + (p.version_id ? '<span class="text-success"><i class="fa-solid fa-check"></i> version created</span>' : '<span class="text-muted">not released</span>') + "</dd></dl>" +
      (errors ? '<h6 class="text-danger">Errors</h6><ul class="small">' + errors + "</ul>" : "") +
      (warnings ? '<h6 class="text-warning-emphasis">Warnings</h6><ul class="small">' + warnings + "</ul>" : "") +
      (p.manifest ? '<details><summary class="small">Manifest</summary><pre class="manifest bg-body-tertiary p-2 rounded mt-2">' + S.esc(JSON.stringify(p.manifest, null, 2)) + "</pre></details>" : "");
  }

  S.pages["packages-list"] = function () {
    const table = new S.DataTable(document.getElementById("packages-table"), (p) => "<tr>" +
      '<td class="small"><a href="#" data-pkg="' + p.id + '">' + S.esc(p.original_filename) + "</a></td>" +
      "<td>" + (p.application_code ? '<a href="/applications/' + p.application_id + '"><code>' + S.esc(p.application_code) + "</code></a>" : '<span class="text-muted">' + S.esc(p.manifest_application || "-") + "</span>") + "</td>" +
      "<td><code>" + S.esc(p.manifest_version || "-") + "</code></td>" +
      "<td>" + (p.manifest_runtime ? S.runtimeIcon(p.manifest_runtime) : "-") + "</td>" +
      '<td class="small">' + S.fmtBytes(p.size_bytes) + "</td>" +
      '<td><code class="small" title="' + S.esc(p.checksum_sha256) + '">' + S.esc(p.checksum_sha256.slice(0, 12)) + "…</code></td>" +
      "<td>" + S.badge(p.status) + ((p.validation_errors || []).length ? ' <span class="badge text-bg-light text-dark border">' + p.validation_errors.length + " error(s)</span>" : "") + "</td>" +
      '<td class="small text-muted">' + S.fmtDate(p.created_at) + "</td>" +
      '<td class="small">' + S.esc(p.uploaded_by || "-") + "</td>" +
      '<td class="text-end text-nowrap"><button class="btn btn-sm btn-outline-secondary" data-pkg="' + p.id + '"><i class="fa-solid fa-eye"></i></button> ' +
        (p.status === "VALID" && !p.version_id && S.can("package.upload") ? '<button class="btn btn-sm btn-outline-success" data-release="' + p.id + '" title="Create release"><i class="fa-solid fa-tag"></i></button> ' : "") +
        (p.status !== "VALID" && S.can("package.upload") ? '<button class="btn btn-sm btn-outline-primary" data-revalidate="' + p.id + '" title="Re-validate"><i class="fa-solid fa-rotate"></i></button> ' : "") +
        (!p.version_id && S.can("package.delete") ? '<button class="btn btn-sm btn-outline-danger" data-delete="' + p.id + '" title="Delete"><i class="fa-solid fa-trash"></i></button>' : "") +
      "</td></tr>", {
      afterLoad: () => {
        document.querySelectorAll("[data-pkg]").forEach((el) => el.addEventListener("click", async (ev) => {
          ev.preventDefault();
          try { const res = await S.api("GET", "/api/packages/" + el.dataset.pkg); document.getElementById("package-modal-title").textContent = res.data.original_filename; document.getElementById("package-modal-body").innerHTML = renderPackage(res.data); bootstrap.Modal.getOrCreateInstance(document.getElementById("package-modal")).show(); } catch (e) { S.showError(e); }
        }));
        document.querySelectorAll("[data-release]").forEach((el) => el.addEventListener("click", async () => { try { const res = await S.api("POST", "/api/packages/" + el.dataset.release + "/release", {}); S.toast("Released version " + res.data.version, "success"); table.load(); } catch (e) { S.showError(e, "Release"); } }));
        document.querySelectorAll("[data-revalidate]").forEach((el) => el.addEventListener("click", async () => { try { await S.api("POST", "/api/packages/" + el.dataset.revalidate + "/revalidate", {}); table.load(); } catch (e) { S.showError(e, "Re-validate"); } }));
        document.querySelectorAll("[data-delete]").forEach((el) => el.addEventListener("click", async () => {
          const answer = await S.confirm({ title: "Delete package", danger: true, requirePhrase: false, requireReason: false, body: "<p>Only unreleased/invalid packages can be deleted.</p>" });
          if (!answer) return;
          try { await S.api("DELETE", "/api/packages/" + el.dataset.delete); table.load(); } catch (e) { S.showError(e, "Delete"); }
        }));
      },
    });
    table.load();
  };

  S.pages["package-upload"] = function (root) {
    const maxBytes = Number(root.dataset.maxMb) * 1024 * 1024;
    const dz = document.getElementById("dropzone"), input = document.getElementById("file-input");
    const info = document.getElementById("file-info"), resultCard = document.getElementById("result-card");
    let file = null;
    const pick = (f) => {
      if (!f) return;
      if (!/\.(tar\.gz|tgz)$/i.test(f.name)) { S.toast("Expected a .scarlet.tar.gz file", "warning"); return; }
      if (f.size > maxBytes) { S.toast("File exceeds the maximum upload size of " + root.dataset.maxMb + " MB", "danger"); return; }
      file = f;
      document.getElementById("fi-name").textContent = f.name;
      document.getElementById("fi-size").textContent = S.fmtBytes(f.size);
      info.classList.remove("d-none"); resultCard.classList.add("d-none");
      const sha = document.getElementById("fi-sha"); sha.textContent = "computing…";
      if (window.crypto && crypto.subtle && f.size <= 256 * 1024 * 1024) {
        f.arrayBuffer().then((buf) => crypto.subtle.digest("SHA-256", buf)).then((h) => { sha.textContent = Array.from(new Uint8Array(h)).map((b) => b.toString(16).padStart(2, "0")).join(""); }).catch(() => { sha.textContent = "n/a"; });
      } else sha.textContent = "computed server-side";
    };
    dz.addEventListener("click", () => input.click());
    dz.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") input.click(); });
    input.addEventListener("change", () => pick(input.files[0]));
    ["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("dragover"); }));
    ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("dragover"); }));
    dz.addEventListener("drop", (e) => pick(e.dataTransfer.files[0]));
    document.getElementById("btn-reset").addEventListener("click", () => { file = null; input.value = ""; info.classList.add("d-none"); resultCard.classList.add("d-none"); });
    document.getElementById("btn-upload").addEventListener("click", () => {
      if (!file) return;
      const fd = new FormData();
      fd.append("file", file, file.name);
      const appId = document.getElementById("application_id").value; if (appId) fd.append("application_id", appId);
      fd.append("release_notes", document.getElementById("release_notes").value);
      fd.append("auto_release", document.getElementById("auto_release").checked ? "true" : "false");
      const progress = document.getElementById("upload-progress"), bar = progress.querySelector(".progress-bar");
      progress.classList.remove("d-none"); document.getElementById("btn-upload").disabled = true;
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/packages/upload");
      xhr.setRequestHeader("X-CSRFToken", (document.querySelector('meta[name="csrf-token"]') || {}).content || "");
      xhr.setRequestHeader("Accept", "application/json");
      xhr.upload.onprogress = (e) => { if (e.lengthComputable) { const pct = Math.round((e.loaded / e.total) * 100); bar.style.width = pct + "%"; bar.textContent = pct + "%"; } };
      xhr.onload = () => {
        document.getElementById("btn-upload").disabled = false;
        let body = null; try { body = JSON.parse(xhr.responseText); } catch (e) { body = null; }
        if (xhr.status >= 200 && xhr.status < 300 && body && body.ok) { showResult(body.data); }
        else { const err = (body && body.error) || { message: "Upload failed (HTTP " + xhr.status + ")" }; S.toast(err.message + (err.errors ? " " + JSON.stringify(err.errors) : ""), "danger", 10000); }
      };
      xhr.onerror = () => { document.getElementById("btn-upload").disabled = false; S.toast("Network error during upload", "danger"); };
      xhr.send(fd);
    });
    function showResult(p) {
      resultCard.classList.remove("d-none");
      document.getElementById("result-status").innerHTML = S.badge(p.status);
      document.getElementById("result-meta").innerHTML = [["Application", p.application_code || p.manifest_application || "-"], ["Version", p.manifest_version || "-"], ["Runtime", p.manifest_runtime || "-"], ["Size", S.fmtBytes(p.size_bytes)], ["SHA-256", "<code>" + S.esc(p.checksum_sha256) + "</code>"], ["Members", p.file_count], ["Release", p.version_id ? '<span class="text-success">version created</span>' : "not released"]].map(([k, v]) => '<dt class="col-3">' + k + '</dt><dd class="col-9">' + v + "</dd>").join("");
      document.getElementById("result-errors").innerHTML = (p.validation_errors || []).length ? '<div class="alert alert-danger py-2"><b>Validation errors</b><ul class="mb-0 small">' + p.validation_errors.map((e) => "<li>" + S.esc(e) + "</li>").join("") + "</ul></div>" : (p.status === "VALID" ? '<div class="alert alert-success py-2"><i class="fa-solid fa-check me-1"></i>Package is valid.' + (p.version_id ? " Release created." : "") + "</div>" : "");
      document.getElementById("result-warnings").innerHTML = (p.validation_warnings || []).length ? '<div class="alert alert-warning py-2"><b>Warnings</b><ul class="mb-0 small">' + p.validation_warnings.map((w) => "<li>" + S.esc(w) + "</li>").join("") + "</ul></div>" : "";
      document.getElementById("result-manifest").textContent = p.manifest ? JSON.stringify(p.manifest, null, 2) : "(no manifest)";
      const actions = document.getElementById("result-actions");
      actions.innerHTML = "";
      if (p.status === "VALID" && p.version_id && p.application_id && S.can("deployment.execute")) actions.innerHTML = '<a class="btn btn-success" href="/deployments/new?application_id=' + p.application_id + '"><i class="fa-solid fa-rocket me-1"></i>Deploy this release</a>';
      if (p.status === "VALID" && !p.version_id && S.can("package.upload")) actions.innerHTML += '<button class="btn btn-outline-success" id="btn-release-now"><i class="fa-solid fa-tag me-1"></i>Create release</button>';
      actions.innerHTML += '<a class="btn btn-outline-secondary" href="/packages">All packages</a>';
      const rel = document.getElementById("btn-release-now");
      if (rel) rel.addEventListener("click", async () => { try { const res = await S.api("POST", "/api/packages/" + p.id + "/release", {}); S.toast("Released " + res.data.version, "success"); p.version_id = res.data.id; p.application_id = res.data.application_id; showResult(p); } catch (e) { S.showError(e, "Release"); } });
    }
  };
})();
