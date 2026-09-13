#!/usr/bin/env python3
"""Second i18n pass for the browser code.

Wraps the strings the automatic pass left behind: titles built by concatenation,
confirmation bodies and toast messages. Also repairs one object literal where the first
pass produced an invalid computed key (``{ S.t("x"): ... }`` instead of ``{ [S.t("x")]: ... }``).
Idempotent: a replacement is skipped when its English form is already gone.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "app" / "static" / "js"

PATCHES: dict[str, list[tuple[str, str]]] = {
    "pages/applications.js": [
        (
            'title: "Delete application " + root.dataset.appCode',
            'title: S.t("Delete application") + " " + root.dataset.appCode',
        ),
        (
            'body: "<p>Only possible when no deployment history exists. Nothing is changed on remote hosts.</p>"',
            'body: S.t("<p>Only possible when no deployment history exists. Nothing is changed on remote hosts.</p>")',
        ),
        (
            'title: "Remove " + b.dataset.delKey + " from " + env',
            'title: S.t("Remove") + " " + b.dataset.delKey + " " + S.t("from") + " " + env',
        ),
        (
            'title: "Deactivate version " + b.dataset.version',
            'title: S.t("Deactivate version") + " " + b.dataset.version',
        ),
        (
            'body: "<p>Deactivated versions cannot be deployed or used for rollback. The artifact is kept. Versions currently deployed cannot be deactivated.</p>"',
            'body: S.t("<p>Deactivated versions cannot be deployed or used for rollback. The artifact is kept. Versions currently deployed cannot be deactivated.</p>")',
        ),
    ],
    "pages/hosts.js": [
        (
            'body: "<p>Confirm that you verified this fingerprint through an independent channel (server console, provisioning record). Approving a wrong key would allow a man-in-the-middle to receive SCARLET credentials and commands.</p>"',
            'body: S.t("<p>Confirm that you verified this fingerprint through an independent channel (server console, provisioning record). Approving a wrong key would allow a man-in-the-middle to receive SCARLET credentials and commands.</p>")',
        ),
        (
            'S.toast("Fingerprint " + res.data.fingerprint',
            'S.toast(S.t("Fingerprint") + " " + res.data.fingerprint',
        ),
        ('title: "Delete host " + name', 'title: S.t("Delete host") + " " + name'),
        (
            'body: "<p>The host record and its credentials will be removed from SCARLET. Nothing is changed on the remote server. Hosts with deployment history cannot be deleted (disable them instead).</p>"',
            'body: S.t("<p>The host record and its credentials will be removed from SCARLET. Nothing is changed on the remote server. Hosts with deployment history cannot be deleted (disable them instead).</p>")',
        ),
        ('+ " host " + name', '+ " " + S.t("host") + " " + name'),
        (
            'body: enable ? "<p>The host will be included again in deployments and reconciliation.</p>" : "<p>Disabled hosts are excluded from deployments, lifecycle operations and reconciliation. Running applications are not touched.</p>"',
            'body: enable ? S.t("<p>The host will be included again in deployments and reconciliation.</p>") : S.t("<p>Disabled hosts are excluded from deployments, lifecycle operations and reconciliation. Running applications are not touched.</p>")',
        ),
        ('textContent = "Edit " + g.name', 'textContent = S.t("Edit") + " " + g.name'),
        ('title: "Delete host group " + g.name', 'title: S.t("Delete host group") + " " + g.name'),
        (
            'body: "<p>Hosts are not deleted; only the grouping is removed.</p>"',
            'body: S.t("<p>Hosts are not deleted; only the grouping is removed.</p>")',
        ),
        ('S.toast("Environment updated"', 'S.toast(S.t("Environment updated")'),
    ],
    "pages/packages.js": [
        (
            'S.toast("Released version " + res.data.version',
            'S.toast(S.t("Released version") + " " + res.data.version',
        ),
        (
            'body: "<p>Only unreleased/invalid packages can be deleted.</p>"',
            'body: S.t("<p>Only unreleased/invalid packages can be deleted.</p>")',
        ),
        (
            'S.toast("File exceeds the maximum upload size of " + root.dataset.maxMb + " MB"',
            'S.toast(S.t("File exceeds the maximum upload size of") + " " + root.dataset.maxMb + " MB"',
        ),
        (
            'S.toast("Released " + res.data.version',
            'S.toast(S.t("Released") + " " + res.data.version',
        ),
    ],
    "pages/security.js": [
        ('textContent = "Edit " + u.username', 'textContent = S.t("Edit") + " " + u.username'),
        ('title: "Delete user " + u.username', 'title: S.t("Delete user") + " " + u.username'),
        (
            'body: "<p>Audit records keep the username. Consider deactivating instead.</p>"',
            'body: S.t("<p>Audit records keep the username. Consider deactivating instead.</p>")',
        ),
        ('textContent = "Edit " + r.name', 'textContent = S.t("Edit") + " " + r.name'),
        ('title: "Delete role " + r.name', 'title: S.t("Delete role") + " " + r.name'),
        (
            'body: "<p>The host will be unreachable until a new credential is added.</p>"',
            'body: S.t("<p>The host will be unreachable until a new credential is added.</p>")',
        ),
        (
            'prompt("New temporary password for " + u.username + " (min 12 chars, 3 classes). The user must change it at next login:")',
            'prompt(S.t("New temporary password for") + " " + u.username + " " + S.t("(min 12 chars, 3 classes). The user must change it at next login:"))',
        ),
        (
            "'<span class=\"badge text-bg-success\">ACTIVE</span>'",
            '\'<span class="badge text-bg-success">\' + S.t("ACTIVE") + "</span>"',
        ),
        ('S.t("never")) + \'</td>', 'S.t("never")) + \'</td>'),
    ],
    "pages/system.js": [
        ('title: "Change " + key', 'title: S.t("Change") + " " + key'),
        (
            'body: "<p>This setting affects production safety controls or automatic remote changes.</p>"',
            'body: S.t("<p>This setting affects production safety controls or automatic remote changes.</p>")',
        ),
        ('details: { S.t("New value"):', 'details: { [S.t("New value")]:'),
    ],
    "pages/deployments.js": [
        (
            '\'<div class="text-muted"><div class="spinner-border spinner-border-sm me-2"></div>Loading…</div>\'',
            '\'<div class="text-muted"><div class="spinner-border spinner-border-sm me-2"></div>\' + S.t("Loading…") + "</div>"',
        ),
        (
            '\'<div class="text-muted"><div class="spinner-border spinner-border-sm me-2"></div>Connecting to target host(s) and checking runtime, disk, memory, ports…</div>\'',
            '\'<div class="text-muted"><div class="spinner-border spinner-border-sm me-2"></div>\' + S.t("Connecting to target host(s) and checking runtime, disk, memory, ports…") + "</div>"',
        ),
        (
            '\'<div class="text-muted"><div class="spinner-border spinner-border-sm me-2"></div>Queuing deployment…</div>\'',
            '\'<div class="text-muted"><div class="spinner-border spinner-border-sm me-2"></div>\' + S.t("Queuing deployment…") + "</div>"',
        ),
        (
            '\'<div class="alert alert-warning"><i class="fa-solid fa-user-check me-2"></i>Deployment(s) created and waiting for approval by another authorized user. \'',
            '\'<div class="alert alert-warning"><i class="fa-solid fa-user-check me-2"></i>\' + S.t("Deployment(s) created and waiting for approval by another authorized user.") + " "',
        ),
        (
            "'<div class=\"alert alert-warning\">Pending approval.</div>'",
            '\'<div class="alert alert-warning">\' + S.t("Pending approval.") + "</div>"',
        ),
        (
            'body: "<p>You confirm that this change is authorized. Execution starts immediately after approval.</p>"',
            'body: S.t("<p>You confirm that this change is authorized. Execution starts immediately after approval.</p>")',
        ),
    ],
}


def main() -> int:
    applied = skipped = 0
    for rel, patches in PATCHES.items():
        path = JS / rel
        text = original = path.read_text(encoding="utf-8")
        for old, new in patches:
            if old in text and old != new:
                text = text.replace(old, new)
                applied += 1
            elif new not in text:
                print(f"MISS {rel}: {old[:70]!r}")
                skipped += 1
        if text != original:
            path.write_text(text, encoding="utf-8", newline="\n")
    print(f"applied {applied}, missed {skipped}")
    return 1 if skipped else 0


if __name__ == "__main__":
    raise SystemExit(main())
