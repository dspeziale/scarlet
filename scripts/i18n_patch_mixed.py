#!/usr/bin/env python3
"""Second i18n pass: wrap sentences the automatic pass skipped.

The first pass only handled plain text nodes, so sentences interrupted by inline markup
(``<code>``, ``<b>``) and single words glued to a Jinja expression stayed in English.
Translations may contain markup, so whole sentences are wrapped as one translatable unit.
Idempotent: each replacement is applied only if the English form is still present.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
T = ROOT / "app" / "templates"

PATCHES: dict[str, list[tuple[str, str]]] = {
    "applications/configuration.html": [
        ("{% block title %}Configuration ", "{% block title %}{{ _('Configuration') }} "),
        (
            ">Values are rendered to <code>shared/config/scarlet.env</code> on the target at deployment time. Secrets are encrypted at rest and never displayed after being saved. Manifest <code>environment</code> defaults are overridden by entries here.<",
            ">{{ _('Values are rendered to <code>shared/config/scarlet.env</code> on the target at deployment time. Secrets are encrypted at rest and never displayed after being saved. Manifest <code>environment</code> defaults are overridden by entries here.') }}<",
        ),
    ],
    "applications/detail.html": [
        ('me-1"></i>DRIFT: {{ i.drift_type }}', "me-1\"></i>{{ _('DRIFT') }}: {{ i.drift_type }}"),
        ('py-4">Not deployed anywhere yet. ', "py-4\">{{ _('Not deployed anywhere yet.') }} "),
    ],
    "applications/form.html": [
        (
            ">Must match <code>application:</code> in the package manifest. Immutable once versions exist.<",
            ">{{ _('Must match <code>application:</code> in the package manifest. Immutable once versions exist.') }}<",
        ),
        (
            ">Defaults used when the package manifest does not declare a <code>healthcheck</code> block.<",
            ">{{ _('Defaults used when the package manifest does not declare a <code>healthcheck</code> block.') }}<",
        ),
    ],
    "audit/list.html": [
        (
            "<option>FAILURE</option><option>DENIED</option><option>INFO</option>",
            "<option>{{ _('FAILURE') }}</option><option>{{ _('DENIED') }}</option><option>{{ _('INFO') }}</option>",
        ),
    ],
    "audit/security_events.html": [
        (">Audit</a>", ">{{ _('Audit log') }}</a>"),
    ],
    "dashboard/index.html": [
        (
            "{{ s.applications.running }} running<",
            "{{ s.applications.running }} {{ _('running') }}<",
        ),
        (
            "{{ s.deployments.running }} deployment(s) running now<",
            "{{ s.deployments.running }} {{ _('deployment(s) running now') }}<",
        ),
        ("</a> on {{ i.host_name }}", "</a> {{ _('on') }} {{ i.host_name }}"),
        (">DRIFT: {{ i.drift_type }}", ">{{ _('DRIFT') }}: {{ i.drift_type }}"),
        (">desired {{ i.desired.version }}", ">{{ _('desired') }} {{ i.desired.version }}"),
        (
            " actual {{ i.actual.version or '?' }}",
            " {{ _('actual') }} {{ i.actual.version or '?' }}",
        ),
    ],
    "deployments/detail.html": [
        (
            'me-1"></i>Rollback to {{ d.previous_version.version }}',
            "me-1\"></i>{{ _('Rollback to') }} {{ d.previous_version.version }}",
        ),
        (
            "|status_badge }} requested by {{ a.requested_by",
            "|status_badge }} {{ _('requested by') }} {{ a.requested_by",
        ),
        (
            "{% if a.decided_by %}, decided by <b>",
            "{% if a.decided_by %}, {{ _('decided by') }} <b>",
        ),
    ],
    "deployments/list.html": [
        (
            "<option>QUEUED</option><option>RUNNING</option><option>PENDING_APPROVAL</option>",
            "<option>{{ _('QUEUED') }}</option><option>{{ _('RUNNING') }}</option><option>{{ _('PENDING APPROVAL') }}</option>",
        ),
        (
            "<option>FAILED</option><option>ROLLED_BACK</option><option>CANCELLED</option>",
            "<option>{{ _('FAILED') }}</option><option>{{ _('ROLLED BACK') }}</option><option>{{ _('CANCELLED') }}</option>",
        ),
    ],
    "errors/error.html": [
        ("&middot; request id <code>", "&middot; {{ _('request id') }} <code>"),
    ],
    "hosts/detail.html": [
        (
            "me-2\"></i>SSH host key {{ 'MISMATCH' if host.ssh_host_key_status == 'MISMATCH' else 'pending approval' }}",
            "me-2\"></i>{{ _('SSH host key') }} {{ _('MISMATCH') if host.ssh_host_key_status == 'MISMATCH' else _('pending approval') }}",
        ),
        (
            "<p>The host presented a key different from the approved one (<code>{{ host.ssh_fingerprint }}</code>). Connections are blocked. Verify out-of-band (console, provisioning records) whether the server was reinstalled before approving the new key.</p>",
            "<p>{{ _('The host presented a key different from the approved one') }} (<code>{{ host.ssh_fingerprint }}</code>). {{ _('Connections are blocked. Verify out-of-band (console, provisioning records) whether the server was reinstalled before approving the new key.') }}</p>",
        ),
        (
            "<p>Verify this fingerprint out-of-band (e.g. <code>ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub</code> on the server console) before approving.</p>",
            "<p>{{ _('Verify this fingerprint out-of-band (e.g. <code>ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub</code> on the server console) before approving.') }}</p>",
        ),
        (
            'me-1"></i>Last error: {{ host.last_error }}',
            "me-1\"></i>{{ _('Last error') }}: {{ host.last_error }}",
        ),
        (
            ">last discovery {{ host.last_discovery_at|dt }}",
            ">{{ _('last discovery') }} {{ host.last_discovery_at|dt }}",
        ),
        (
            ">Disk (/) {% if disk_pct is not none %}{{ host.disk_available_mb }} MB free of {{ host.disk_total_mb }} MB",
            ">{{ _('Disk') }} (/) {% if disk_pct is not none %}{{ host.disk_available_mb }} {{ _('MB free of') }} {{ host.disk_total_mb }} MB",
        ),
    ],
    "hosts/environments.html": [
        (
            "{{ host_counts.get(e.code, 0) }} host(s)",
            "{{ host_counts.get(e.code, 0) }} {{ _('host(s)') }}",
        ),
        (
            'me-1"></i>Production controls also depend on the global settings <code>SCARLET_PROD_REQUIRE_CONFIRMATION</code> and <code>SCARLET_PROD_REQUIRE_APPROVAL</code>: the stricter of the two applies. Operators additionally need <code>prod.*</code> permissions.',
            "me-1\"></i>{{ _('Production controls also depend on the global settings <code>SCARLET_PROD_REQUIRE_CONFIRMATION</code> and <code>SCARLET_PROD_REQUIRE_APPROVAL</code>: the stricter of the two applies. Operators additionally need <code>prod.*</code> permissions.') }}",
        ),
    ],
    "hosts/form.html": [
        (
            "<li>Create the host record (this form).</li>",
            "<li>{{ _('Create the host record (this form).') }}</li>",
        ),
        (
            "<li>Add an SSH credential (private key recommended) under <b>Security → Credentials</b>.</li>",
            "<li>{{ _('Add an SSH credential (private key recommended) under <b>Security → Credentials</b>.') }}</li>",
        ),
        (
            "and approve the fingerprint after verifying it on the server console.</li>",
            "{{ _('and approve the fingerprint after verifying it on the server console.') }}</li>",
        ),
        ("to detect OS and runtime.</li>", "{{ _('to detect OS and runtime.') }}</li>"),
        (
            "<li>Set the runtime if it was NONE and start deploying.</li>",
            "<li>{{ _('Set the runtime if it was NONE and start deploying.') }}</li>",
        ),
        ("</b> (see docs/ssh.md):", "</b> ({{ _('see') }} docs/ssh.md):"),
        (
            "<li>can write to the base path (default <code>/opt/scarlet</code>)</li><li>can run <code>podman</code>/<code>docker</code>/<code>kubectl</code> (rootless Podman recommended)</li>",
            "<li>{{ _('can write to the base path (default <code>/opt/scarlet</code>)') }}</li><li>{{ _('can run <code>podman</code>/<code>docker</code>/<code>kubectl</code> (rootless Podman recommended)') }}</li>",
        ),
    ],
    "layout/bare.html": [
        ('<html lang="en">', '<html lang="{{ current_locale }}">'),
    ],
    "operations/list.html": [
        (
            "<option>QUEUED</option><option>RUNNING</option>",
            "<option>{{ _('QUEUED') }}</option><option>{{ _('RUNNING') }}</option>",
        ),
        (
            "<option>FAILED</option><option>TIMEOUT</option><option>CANCELLED</option>",
            "<option>{{ _('FAILED') }}</option><option>{{ _('TIMEOUT') }}</option><option>{{ _('CANCELLED') }}</option>",
        ),
    ],
    "packages/list.html": [
        (
            'class="breadcrumb-item active">Packages',
            "class=\"breadcrumb-item active\">{{ _('Packages') }}",
        ),
    ],
    "packages/upload.html": [
        (
            ">Maximum size {{ config.SCARLET_MAX_UPLOAD_MB }} MB. The package is validated before anything is stored as a release; nothing is ever executed.<",
            ">{{ _('Maximum size') }} {{ config.SCARLET_MAX_UPLOAD_MB }} MB. {{ _('The package is validated before anything is stored as a release; nothing is ever executed.') }}<",
        ),
    ],
    "partials/modals.html": [
        (
            "</strong> — this operation will modify a production system.",
            "</strong> — {{ _('this operation will modify a production system.') }}",
        ),
    ],
    "security/credentials.html": [
        (
            'me-1"></i>Secrets are encrypted at rest with <code>SCARLET_CREDENTIAL_ENCRYPTION_KEY</code> and never displayed, logged or returned by the API. Adding a credential deactivates the previous one of the same kind (rotation); history is kept for audit. SSH private keys (ed25519 recommended) are preferred over passwords.',
            "me-1\"></i>{{ _('Secrets are encrypted at rest with <code>SCARLET_CREDENTIAL_ENCRYPTION_KEY</code> and never displayed, logged or returned by the API. Adding a credential deactivates the previous one of the same kind (rotation); history is kept for audit. SSH private keys (ed25519 recommended) are preferred over passwords.') }}",
        ),
        (
            'text-bg-success">ACTIVE</span>{% else %}<span class="badge text-bg-secondary">INACTIVE</span>',
            "text-bg-success\">{{ _('ACTIVE') }}</span>{% else %}<span class=\"badge text-bg-secondary\">{{ _('INACTIVE') }}</span>",
        ),
    ],
    "security/roles.html": [
        ("{{ r.users|length }} user(s)", "{{ r.users|length }} {{ _('user(s)') }}"),
        (
            "</b> operations on PROD hosts require both the base permission (e.g. <code>deployment.execute</code>) and its <code>prod.*</code> variant. OPERATOR has DEV rights only; PROD_OPERATOR and ADMIN can act on PROD.",
            "</b> {{ _('operations on PROD hosts require both the base permission (e.g. <code>deployment.execute</code>) and its <code>prod.*</code> variant. OPERATOR has DEV rights only; PROD_OPERATOR and ADMIN can act on PROD.') }}",
        ),
    ],
    "security/tokens.html": [
        (
            ">Tokens inherit your permissions. Use them as <code>Authorization: Bearer scl_…</code>. Token calls are exempt from CSRF but still audited under your username.<",
            ">{{ _('Tokens inherit your permissions. Use them as <code>Authorization: Bearer scl_…</code>. Token calls are exempt from CSRF but still audited under your username.') }}<",
        ),
    ],
    "security/users.html": [
        (
            'text-bg-warning text-dark">LOCKED</span>{% else %}<span class="badge text-bg-success">ACTIVE</span>',
            "text-bg-warning text-dark\">{{ _('LOCKED') }}</span>{% else %}<span class=\"badge text-bg-success\">{{ _('ACTIVE') }}</span>",
        ),
    ],
    "system/about.html": [
        ("</b> — version {{ scarlet_version }}", "</b> — {{ _('version') }} {{ scarlet_version }}"),
        (
            ">SCARLET is a control plane: operators declare the <i>desired state</i> of an application on a target (version, running/stopped); the deployment engine drives the <i>actual state</i> toward it through a runtime adapter (Docker, Podman, Kubernetes) over SSH, and the reconciler reports drift.<",
            ">{{ _('SCARLET is a control plane: operators declare the <i>desired state</i> of an application on a target (version, running/stopped); the deployment engine drives the <i>actual state</i> toward it through a runtime adapter (Docker, Podman, Kubernetes) over SSH, and the reconciler reports drift.') }}<",
        ),
        (
            "{{ 'enabled' if config.SCARLET_PROD_REQUIRE_CONFIRMATION else 'disabled' }} (phrase <code>",
            "{{ _('enabled') if config.SCARLET_PROD_REQUIRE_CONFIRMATION else _('disabled') }} ({{ _('phrase') }} <code>",
        ),
        (
            "</b> — step-by-step operational procedures",
            "</b> — {{ _('step-by-step operational procedures') }}",
        ),
        (
            "</b> — package &amp; manifest contract for application teams",
            "</b> — {{ _('package &amp; manifest contract for application teams') }}",
        ),
    ],
}


def main() -> int:
    applied = skipped = 0
    for rel, patches in PATCHES.items():
        path = T / rel
        text = original = path.read_text(encoding="utf-8")
        for old, new in patches:
            if old in text:
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
