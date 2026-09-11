# Security

SCARLET can execute privileged operations on production servers, so its security posture is
restrictive by default. This document lists the threat model, the controls and the defaults.

## Threat model (summary)

| Threat | Control |
|---|---|
| Stolen SSH credentials from the database or backups | Fernet (AES-128-CBC + HMAC) encryption with an external key; never exposed by API/UI/logs/audit; rotation supported |
| Man-in-the-middle on SSH | Strict host-key verification; unknown keys must be approved by an administrator; mismatch blocks the host and raises a CRITICAL security event |
| Command injection through host names, versions, manifests, log filters | argv-only `RemoteCommand`, `shlex.quote` on every argument, executable allow-list, strict regex validators on every value that reaches a command |
| Malicious release package (path traversal, symlinks, zip bombs) | member-by-member tar inspection without extraction, link/device/setuid rejection, size and count limits, strict manifest schema |
| Accidental or unauthorised production change | `prod.*` permissions, mandatory reason, typed confirmation phrase, optional second-person approval, per-app/host lock, PROD badges |
| Privilege escalation in the UI | RBAC enforced in every route and service; UI hiding is cosmetic only |
| Web attacks (XSS, CSRF, clickjacking, session fixation) | Jinja autoescape + CSP without inline scripts, CSRF token for session requests, `frame-ancestors 'none'`, session cleared and rotated on login, secure/HttpOnly/SameSite cookies |
| Credential stuffing / brute force | login rate limit (5/min/IP by default), account lockout, Argon2id hashing, identical error messages |
| Information leakage | no stack traces to clients, request id for correlation, log redaction of passwords/keys/tokens, secrets masked in configuration API |
| Arbitrary remote execution by operators | no generic "execute command" feature; diagnostic shell disabled and refused in production configuration |

## Authentication & sessions

- Passwords: Argon2id (`argon2-cffi`), policy min 12 chars + 3 classes, common-password list,
  forced change at first login/admin reset. Changing a password bumps `session_generation`,
  invalidating every other session.
- Sessions: Flask-Login with `session_protection=strong`, `SESSION_COOKIE_SECURE` (mandatory in
  production), `HttpOnly`, `SameSite=Lax`, lifetime `SCARLET_SESSION_LIFETIME_SECONDS` (8 h).
  `session.clear()` before login prevents fixation.
- API tokens: `scl_` prefixed, SHA-256 hashed at rest, per-user, expiring, revocable; carry the
  user's permissions; exempt from CSRF (bearer auth) but audited.
- Lockout: `SCARLET_MAX_FAILED_LOGINS` (10) → `SCARLET_LOCKOUT_MINUTES` (15) + security event.

## Authorization (RBAC)

Roles ADMIN, OPERATOR, PROD_OPERATOR, VIEWER, AUDITOR (custom roles allowed). Granular permissions
(`host.*`, `application.*`, `package.*`, `deployment.*`, `lifecycle.*`, `logs.*`, `health.*`,
`configuration.*`, `audit.*`, `user.manage`, `system.manage`). For PROD hosts the matching
`prod.<permission>` is additionally required (`ProductionGuard.authorize`). Approvers cannot
approve their own deployments.

## SSH

- Paramiko with `allow_agent=False`, `look_for_keys=False`, explicit host key, `RejectPolicy`
  semantics (`ScarletHostKeyPolicy`): strict by default; `tofu` only outside production.
- Every command has a timeout; stdout/stderr/exit code/duration captured; output redacted before
  storage.
- SFTP upload to `.part` + rename, size check, then `sha256sum` comparison before extraction.
- The remote user should be unprivileged; SCARLET never requests sudo.

## Command execution

`app/ssh/command.py`: allow-listed binaries (`cat uname nproc free df id hostname readlink ls stat
test sha256sum command which systemctl getenforce timeout true mkdir mv rm ln tar cp chmod find sh
docker podman kubectl helm curl nc`); `sh`/`timeout`/`find` usable only by trusted builders
(`builder.*` command types); path validation under `SCARLET_REMOTE_BASE_PATH`; `rm -rf` refused
above application sub-directories; hooks restricted to `release/scripts/*.sh` with `SCARLET_*`
environment only.

## Packages

See `docs/package-format.md`. Uploaded bytes go to an incoming area outside the web root with
generated names; validation never extracts; only VALID packages become immutable releases whose
checksum is re-verified at deployment time and on demand (checksum mismatch → CRITICAL event).

## Secrets

`SecretProvider` abstraction; default `EncryptedDatabaseSecretProvider` (Fernet). Configuration
SECRET entries are write-only (API returns `********`), snapshots store only a hash, audit stores
keys not values. Environment files rendered on targets are 0600 (SFTP chmod) and contain the
merged configuration for the SSH user only.

## Web

Security headers (`app/security/headers.py`): CSP (`default-src 'self'`, scripts from self and the
configured CDN only, no inline scripts; `style-src 'unsafe-inline'` is required by AdminLTE),
`X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`,
`Cross-Origin-Opener-Policy`, HSTS when served over HTTPS, `Cache-Control: no-store` on the API.
Set `SCARLET_ASSET_MODE=local` (with `scripts/fetch-vendor-assets.sh`) to remove the CDN origin.

## Audit & security events

Append-only `audit_logs` (the repository exposes no update/delete); details scrubbed of secret-like
keys. `security_events` for host key mismatches, lockouts, checksum mismatches. Exports honour
`audit.export` and neutralise spreadsheet formula injection.

## Configuration validation

`build_config()` refuses to start in production when: secret keys are missing/short/equal, SQLite
is used, debug is on, cookies are insecure, CSRF is off, host-key policy is not strict, Celery is
eager, or the diagnostic shell flag is set. `flask scarlet check-config` reports connectivity.

## Defaults

| Setting | Default |
|---|---|
| PROD confirmation / reason | enabled |
| PROD approval | disabled (opt-in) |
| Auto rollback | disabled (opt-in) |
| Reconciler auto-remediation | disabled, never on PROD |
| Host key policy | strict |
| Diagnostic shell | disabled, refused in production |
| Upload limit | 2048 MB |
| API docs | enabled in development, disabled in production |
| Log format | JSON with redaction |

## Reporting

Security-relevant defects should be reported to the platform security team with the request id
and audit references; do not attach credentials or `.env` files to tickets.
