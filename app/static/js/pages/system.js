/* System pages: settings, notifications */
(function () {
  const S = window.Scarlet;

  S.pages["settings"] = function () {
    document.querySelectorAll("tr[data-key]").forEach((row) => {
      const key = row.dataset.key, type = row.dataset.type, input = row.querySelector(".setting-input");
      const save = row.querySelector("[data-save]"), reset = row.querySelector("[data-reset]");
      save.addEventListener("click", async () => {
        const value = type === "bool" ? input.checked : (type === "int" ? Number(input.value) : input.value);
        const production = /PROD_|AUTO_ROLLBACK|REMEDIATE/.test(key);
        if (production) {
          const a = await S.confirm({ title: S.t("Change") + " " + key, danger: true, requirePhrase: false, showReason: true, requireReason: false, body: S.t("<p>This setting affects production safety controls or automatic remote changes.</p>"), details: { [S.t("New value")]: "<code>" + S.esc(String(value)) + "</code>" } });
          if (!a) return;
        }
        try { await S.api("PUT", "/api/settings/" + key, { value }); S.toast(key + " saved", "success"); setTimeout(() => location.reload(), 500); } catch (e) { S.showError(e, S.t("Save setting")); }
      });
      if (reset) reset.addEventListener("click", async () => { try { await S.api("DELETE", "/api/settings/" + key); location.reload(); } catch (e) { S.showError(e); } });
    });
  };

  S.pages["notifications"] = function () {
    async function load() {
      try {
        const res = await S.api("GET", "/api/notifications");
        const list = document.getElementById("notif-list");
        list.innerHTML = res.data.items.length ? res.data.items.map((n) => '<li class="list-group-item ' + (n.read ? "" : "fw-semibold") + '"><div class="d-flex justify-content-between"><span>' + S.badge(n.level) + " " + (n.link ? '<a href="' + S.esc(n.link) + '">' + S.esc(n.title) + "</a>" : S.esc(n.title)) + '</span><span class="small text-muted">' + S.fmtDate(n.created_at) + "</span></div>" + (n.message ? '<div class="small text-muted fw-normal">' + S.esc(n.message) + "</div>" : "") + "</li>").join("") : '<li class="list-group-item text-muted">No notifications.</li>';
      } catch (e) { S.showError(e, S.t("Notifications")); }
    }
    document.getElementById("btn-mark-all").addEventListener("click", async () => { try { await S.api("POST", "/api/notifications/read", {}); load(); S.refreshNavbar(); } catch (e) { S.showError(e); } });
    load();
  };
})();
