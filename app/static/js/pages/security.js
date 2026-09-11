/* Security pages: users, roles, credentials, tokens */
(function () {
  const S = window.Scarlet;

  S.pages["users"] = function () {
    const form = document.getElementById("user-form");
    const reset = () => { form.reset(); form.querySelector('[name="id"]').value = ""; form.querySelector('[name="username"]').readOnly = false; document.getElementById("password-group").classList.remove("d-none"); form.querySelector('[name="password"]').required = true; document.getElementById("user-form-title").textContent = "New user"; };
    document.getElementById("user-form-reset").addEventListener("click", reset);
    document.querySelectorAll("[data-edit-user]").forEach((b) => b.addEventListener("click", () => {
      const u = JSON.parse(b.closest("tr").dataset.user);
      form.querySelector('[name="id"]').value = u.id; form.querySelector('[name="username"]').value = u.username; form.querySelector('[name="username"]').readOnly = true;
      form.querySelector('[name="full_name"]').value = u.full_name || ""; form.querySelector('[name="email"]').value = u.email || "";
      document.getElementById("password-group").classList.add("d-none"); form.querySelector('[name="password"]').required = false;
      form.querySelectorAll('[name="roles"]').forEach((c) => { c.checked = u.roles.includes(c.value); });
      form.querySelector('[name="is_active"]').checked = u.is_active; form.querySelector('[name="unlock"]').checked = false;
      document.getElementById("user-form-title").textContent = "Edit " + u.username;
    }));
    document.querySelectorAll("[data-reset-user]").forEach((b) => b.addEventListener("click", async () => {
      const u = JSON.parse(b.closest("tr").dataset.user);
      const pwd = prompt("New temporary password for " + u.username + " (min 12 chars, 3 classes). The user must change it at next login:");
      if (!pwd) return;
      try { await S.api("POST", "/api/users/" + u.id + "/reset-password", { new_password: pwd, must_change_password: true }); S.toast("Password reset", "success"); } catch (e) { S.showError(e, "Reset password"); }
    }));
    document.querySelectorAll("[data-delete-user]").forEach((b) => b.addEventListener("click", async () => {
      const u = JSON.parse(b.closest("tr").dataset.user);
      const a = await S.confirm({ title: "Delete user " + u.username, danger: true, requirePhrase: true, phrase: "DELETE " + u.username, requireReason: false, body: "<p>Audit records keep the username. Consider deactivating instead.</p>" });
      if (!a) return;
      try { await S.api("DELETE", "/api/users/" + u.id); location.reload(); } catch (e) { S.showError(e, "Delete user"); }
    }));
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const fd = new FormData(form);
      const roles = fd.getAll("roles");
      const id = fd.get("id");
      try {
        if (id) await S.api("PUT", "/api/users/" + id, { full_name: fd.get("full_name"), email: fd.get("email") || null, roles, is_active: form.querySelector('[name="is_active"]').checked, unlock: form.querySelector('[name="unlock"]').checked });
        else await S.api("POST", "/api/users", { username: fd.get("username"), password: fd.get("password"), full_name: fd.get("full_name"), email: fd.get("email") || null, roles, must_change_password: true });
        location.reload();
      } catch (e) { S.showError(e, "Save user"); }
    });
  };

  S.pages["roles"] = function () {
    const form = document.getElementById("role-form");
    const reset = () => { form.reset(); form.querySelector('[name="id"]').value = ""; form.querySelector('[name="name"]').readOnly = false; document.getElementById("role-form-title").textContent = "New role"; };
    document.getElementById("role-form-reset").addEventListener("click", reset);
    document.querySelectorAll("[data-edit-role]").forEach((b) => b.addEventListener("click", () => {
      const r = JSON.parse(b.closest(".card").dataset.role);
      form.querySelector('[name="id"]').value = r.id; form.querySelector('[name="name"]').value = r.name; form.querySelector('[name="name"]').readOnly = true; form.querySelector('[name="description"]').value = r.description || "";
      form.querySelectorAll('[name="permissions"]').forEach((c) => { c.checked = r.permissions.includes(c.value); });
      document.getElementById("role-form-title").textContent = "Edit " + r.name;
      form.scrollIntoView({ behavior: "smooth" });
    }));
    document.querySelectorAll("[data-delete-role]").forEach((b) => b.addEventListener("click", async () => {
      const r = JSON.parse(b.closest(".card").dataset.role);
      const a = await S.confirm({ title: "Delete role " + r.name, danger: true, requirePhrase: false, requireReason: false });
      if (!a) return;
      try { await S.api("DELETE", "/api/roles/" + r.id); location.reload(); } catch (e) { S.showError(e, "Delete role"); }
    }));
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const fd = new FormData(form);
      const payload = { name: fd.get("name"), description: fd.get("description"), permissions: fd.getAll("permissions") };
      try { if (fd.get("id")) await S.api("PUT", "/api/roles/" + fd.get("id"), payload); else await S.api("POST", "/api/roles", payload); location.reload(); } catch (e) { S.showError(e, "Save role"); }
    });
  };

  S.pages["credentials"] = function () {
    const modalEl = document.getElementById("cred-modal"), form = document.getElementById("cred-form");
    const type = document.getElementById("cred-type");
    const update = () => {
      const t = type.value;
      document.getElementById("cred-secret-label").textContent = t === "PASSWORD" ? "Password" : t === "KUBECONFIG" ? "kubeconfig (YAML)" : "Private key (PEM / OpenSSH)";
      document.getElementById("cred-pass-group").classList.toggle("d-none", t !== "PRIVATE_KEY");
    };
    type.addEventListener("change", update);
    document.querySelectorAll("[data-add-cred]").forEach((b) => b.addEventListener("click", () => {
      form.reset(); form.querySelector('[name="host_id"]').value = b.dataset.addCred; document.getElementById("cred-host").textContent = b.dataset.hostName;
      type.value = "PRIVATE_KEY"; update();
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }));
    document.querySelectorAll("[data-revoke-cred]").forEach((b) => b.addEventListener("click", async () => {
      const [host, cred] = b.dataset.revokeCred.split("/");
      const a = await S.confirm({ title: "Revoke credential", danger: true, requirePhrase: false, showReason: true, requireReason: false, body: "<p>The host will be unreachable until a new credential is added.</p>" });
      if (!a) return;
      try { await S.api("DELETE", "/api/hosts/" + host + "/credentials/" + cred); location.reload(); } catch (e) { S.showError(e, "Revoke"); }
    }));
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const fd = new FormData(form);
      const btn = form.querySelector('button[type="submit"]'); btn.disabled = true;
      try {
        await S.api("POST", "/api/hosts/" + fd.get("host_id") + "/credentials", { credential_type: fd.get("credential_type"), secret: fd.get("secret"), passphrase: fd.get("passphrase") || null, username: fd.get("username") || null });
        form.reset();
        bootstrap.Modal.getInstance(modalEl).hide();
        S.toast("Credential stored (encrypted)", "success");
        setTimeout(() => location.reload(), 500);
      } catch (e) { S.showError(e, "Save credential"); } finally { btn.disabled = false; }
    });
  };

  S.pages["tokens"] = function () {
    async function load() {
      try {
        const res = await S.api("GET", "/api/auth/tokens");
        document.getElementById("tokens-body").innerHTML = res.data.length ? res.data.map((t) => "<tr><td><b>" + S.esc(t.name) + "</b></td><td><code>" + S.esc(t.prefix) + "…</code></td><td class=\"small\">" + (t.expires_at ? S.fmtDate(t.expires_at) : "never") + '</td><td class="small">' + S.fmtDate(t.last_used_at) + "</td><td>" + (t.revoked ? S.badge("REVOKED") : '<span class="badge text-bg-success">ACTIVE</span>') + '</td><td class="text-end">' + (t.revoked ? "" : '<button class="btn btn-sm btn-outline-danger" data-revoke="' + t.id + '"><i class="fa-solid fa-ban"></i></button>') + "</td></tr>").join("") : '<tr><td colspan="6" class="text-muted text-center py-3">No tokens.</td></tr>';
        document.querySelectorAll("[data-revoke]").forEach((b) => b.addEventListener("click", async () => { try { await S.api("DELETE", "/api/auth/tokens/" + b.dataset.revoke); load(); } catch (e) { S.showError(e); } }));
      } catch (e) { S.showError(e, "Tokens"); }
    }
    document.getElementById("token-form").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const fd = new FormData(ev.target);
      try {
        const res = await S.api("POST", "/api/auth/tokens", { name: fd.get("name"), expires_days: fd.get("expires_days") ? Number(fd.get("expires_days")) : null, description: fd.get("description") });
        document.getElementById("new-token").classList.remove("d-none");
        document.getElementById("new-token-value").textContent = res.data.token;
        ev.target.reset(); load();
      } catch (e) { S.showError(e, "Create token"); }
    });
    load();
  };
})();
