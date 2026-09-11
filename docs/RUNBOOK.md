# SCARLET Operations Runbook

Audience: system administrators and operators with limited container/Kubernetes experience.
Each procedure lists preconditions, steps, expected result, possible errors, recovery and
security considerations. UI paths are given as **Menu → Page**; API equivalents are in
`GET /api/docs`.

General rules
- Everything you do is written to **Audit → Audit Log** with your username, IP and request id.
- **PROD** targets are marked with a red badge. PROD actions require the `prod.*` permission, a
  reason and typing the confirmation phrase (`DEPLOY TO PROD`, `STOP PROD`, `ROLLBACK PROD`).
- Never work around SCARLET by SSH-ing into a server and changing an application by hand; the
  reconciler will report **DRIFT** and history becomes unreliable.
- When a procedure fails, the error message contains a *request id* (also in the footer). Give it to
  the SCARLET administrator: it links the UI error to the server log line.

---

## Part A — Setup procedures

### 1. Add a new Oracle Linux host

**Preconditions**
- Host runs Oracle Linux 8/9, reachable from the SCARLET server on the SSH port (firewall open).
- A dedicated Linux user for SCARLET exists on the host (see §2).
- You have the `host.create` permission (ADMIN).

**Steps**
1. **Infrastructure → Hosts → New host**.
2. Fill *Name* (short unique id, e.g. `prod-app-01`), *Hostname* (FQDN), optional *IP address*
   (if set, SSH connects to the IP), *SSH username*, *SSH port*, *Environment* (DEV/PROD),
   *Runtime* (PODMAN recommended; choose NONE if unknown and run Discover later).
3. Optionally add the host to a *Host group* and set a custom *Remote base path*
   (default `/opt/scarlet`).
4. Save. The host detail page opens with status **UNKNOWN**.
5. Continue with §2 (credential) and §3 (host key).

**Expected result**: host listed under Hosts, status UNKNOWN, host key status UNKNOWN.

**Possible errors**
- *Invalid hostname / IP*: only FQDNs and non-loopback IPs are accepted.
- *A host named … already exists*: choose another name.

**Recovery**: edit or delete the host (Hosts → host → Delete; PROD needs confirmation).

**Security**: hostnames and IPs are validated to prevent SSRF; loopback and multicast addresses
are refused. Creating a host does not contact it.

### 2. Configure SSH on the target host

**Preconditions**: root/sudo access to the target, SCARLET's public key (Security → Credentials
sidebar shows the setup commands).

**Steps** (on the target host)
```bash
sudo useradd -m scarlet
sudo mkdir -p /opt/scarlet && sudo chown scarlet:scarlet /opt/scarlet
sudo -u scarlet mkdir -p ~scarlet/.ssh && sudo -u scarlet chmod 700 ~scarlet/.ssh
echo "ssh-ed25519 AAAA... scarlet@scarlet-server" | sudo -u scarlet tee -a ~scarlet/.ssh/authorized_keys
sudo -u scarlet chmod 600 ~scarlet/.ssh/authorized_keys
sudo loginctl enable-linger scarlet              # rootless Podman keeps running after logout
sudo dnf install -y podman tar gzip nmap-ncat curl
```
Then in SCARLET: **Security → Credentials → host → Add / rotate**, type *SSH private key*, paste
the private key (and passphrase if any), save.

**Expected result**: credential listed as ACTIVE with the key fingerprint; the host detail shows
"Credential: PRIVATE_KEY".

**Possible errors**
- *The private key could not be loaded*: wrong format or passphrase. Use OpenSSH or PEM keys
  (ed25519 preferred).
- *Permission denied* later in Test connection: authorized_keys permissions or SELinux context
  (`restorecon -Rv ~scarlet/.ssh`).

**Recovery**: add a new credential (rotation deactivates the previous one) or revoke it.

**Security**: the private key is encrypted with `SCARLET_CREDENTIAL_ENCRYPTION_KEY` before it is
stored and is never shown again. Passwords are supported but discouraged. Do not reuse the key for
humans. Do not give the `scarlet` user sudo unless a runtime requires it (rootful Docker).

### 3. Approve the SSH host fingerprint

**Preconditions**: host created; you can read the host's real fingerprint out-of-band
(console: `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`, or the provisioning record).

**Steps**
1. Hosts → host → **Scan host key** (or run Test connection: in strict mode it records the
   pending key and fails).
2. The page shows *Pending fingerprint*. Compare it character by character with the out-of-band
   value.
3. Click **Approve fingerprint**, type the fingerprint in the confirmation dialog.

**Expected result**: host key status **APPROVED**; Test connection now succeeds.

**Possible errors**
- *Fingerprint mismatch*: what you typed differs from the pending key: re-check.
- *No pending host key*: run Scan first.

**Recovery**: **Revoke** the key from the host page and repeat.

**Security**: never approve a fingerprint you did not verify independently; approving a wrong key
would let an attacker on the network receive SCARLET's credentials and commands. Development
instances may use `SCARLET_SSH_HOST_KEY_POLICY=tofu` (trust-on-first-use); production always
`strict`.

### 4. Discover the runtime

**Preconditions**: credential + approved key, `host.test` permission.

**Steps**
1. Hosts → host → **Test connection** (expect ONLINE, remote user shown).
2. Click **Discover**. A modal follows the operation.

**Expected result**: OS, kernel, CPU, memory, disk, SELinux mode and detected runtimes
(PODMAN/DOCKER/KUBERNETES with version and rootless flag). If the host runtime was NONE, the
result suggests one: **Edit** the host and set it.

**Possible errors**
- *podman not found*: install it (`dnf install podman`).
- *SSH_HOST_KEY_ERROR*: see §3 / §31.

**Recovery**: fix the host, run Discover again. Discovery never modifies the host.

**Security**: discovery runs read-only commands only (`cat /etc/os-release`, `uname`, `free`, `df`,
`podman version`, ...).

### 5. Register an application

**Preconditions**: `application.create`.

**Steps**
1. **Applications → New application**. *Code* must match `application:` in the package
   manifest (lowercase, dashes; immutable once versions exist). Choose the primary *Runtime*.
2. Set health-check defaults (used when the manifest has no `healthcheck` block).
3. Target rules: allowed environments, runtimes, host groups. Leave empty for no restriction.
4. Enable **Allow deployment hooks** only if the team's packages contain `scripts/*.sh` hooks and
   the release pipeline is trusted (hooks run on the host as the SSH user).
5. Save.

**Expected result**: application listed; detail page shows no versions/instances yet.

**Possible errors**: invalid code, duplicate code, invalid health-check command (shell
metacharacters are refused).

**Security**: target rules are enforced server-side on every deployment.

### 6. Create a release (application team)

**Preconditions**: the team has the contract (`docs/APPLICATION_RELEASE_CONTRACT.md`), the
image is pushed to a registry reachable by the target host (or shipped as an archive).

**Steps**
1. Prepare a source directory with `manifest.yaml`, optional `config/`, `scripts/`,
   `docker-compose.yml` or `kubernetes/`.
2. Build: `python scripts/build-scarlet-package.py --source ./customer-api --version 2.5.0 --output dist/`
   (validates the package with the same rules SCARLET uses on upload).
3. Hand `dist/customer-api-2.5.0.scarlet.tar.gz` and its `.sha256` to operations.

**Expected result**: builder prints `package : …`, `sha256 : …`.

**Possible errors**: `manifest.yaml failed validation: …` lists every violation.

**Security**: versions are immutable; a changed package must get a new version number.

### 7. Upload a package

**Preconditions**: `package.upload`, application registered (§5), package file (§6).

**Steps**
1. **Applications → Packages → Upload**. Drag the file or click to choose. The local SHA-256 is shown.
2. Optionally select the application (cross-check) and release notes. Keep *Create the release
   automatically* on.
3. **Upload & validate**. The progress bar shows the transfer; the result card shows VALID/INVALID
   and every error/warning.

**Expected result**: status **VALID**, "Release created"; the version appears under
Applications → application → Versions and **Releases**.

**Possible errors**
- *Unsafe path in archive*, *Links are not allowed*: the package is rejected (security).
- *Application '…' … is not registered*: register it first or fix `application:`.
- *Version … already exists with a different checksum*: releases are immutable — bump the version.
- *The manifest declares deployment hooks but hooks are not enabled*: enable `allow_hooks` on the
  application or remove hooks.
- *413 Upload too large*: raise `SCARLET_MAX_UPLOAD_MB` and nginx `client_max_body_size`.

**Recovery**: delete INVALID packages (Packages → trash), fix, re-upload.

**Security**: archives are inspected without extraction; nothing from a package is ever executed
on the SCARLET server.

---

## Part B — Deployment procedures

### 8. Deploy to DEV

**Preconditions**: DEV host ONLINE with runtime set, application + version, `deployment.execute`.
Secrets declared by the manifest configured under Applications → application → Configuration → DEV.

**Steps**
1. **Operations → Deployments → New deployment** (or *Deploy* from the application page).
2. Wizard: pick application → version → target host(s) (incompatible hosts are greyed with the
   reason) → strategy (SEQUENTIAL/PARALLEL) → **pre-flight** runs automatically.
3. Review pre-flight (SSH, runtime, disk, memory, ports, secrets, conflicts). Fix FAIL items and re-run.
4. Confirmation: enter an optional reason, click **Deploy**.
5. Watch the live step list; the wizard moves to Health check and Result.

**Expected result**: `SUCCESS — Version x.y.z deployed successfully`. Application instance shows
desired = actual, health HEALTHY.

**Possible errors**: any failed step shows stdout/stderr of the remote command (Deployments →
deployment → Steps). Common: image pull failure (registry unreachable), port in use, health check
timeout (application slow to start: raise `healthcheck.retries`/`interval` in the manifest).

**Recovery**: the previous release stays installed; fix and redeploy, or Rollback (§16) if the
new release was activated.

### 9. Deploy to PROD

**Preconditions**: as §8 plus `prod.deployment.execute` (PROD_OPERATOR/ADMIN), a change ticket
/ reason, and — if `SCARLET_PROD_REQUIRE_APPROVAL` or the environment requires approval — a second
authorised user available.

**Steps**
1. Same wizard as §8; PROD hosts show a red banner. Prefer SEQUENTIAL for multi-host PROD.
2. Pre-flight must pass; the parallel limit for PROD is `SCARLET_PROD_MAX_PARALLEL_DEPLOYMENTS`
   (default 1).
3. Confirmation: **reason is mandatory**; type exactly `DEPLOY TO PROD`.
4. If approval is required the deployment stays **PENDING_APPROVAL**; another user with
   `deployment.approve` opens Deployments → deployment → **Approve** (typing `APPROVE`) or Reject.
   The requester cannot approve their own deployment.
5. Execution proceeds as in §8.

**Expected result**: SUCCESS; audit contains DEPLOYMENT_REQUESTED/APPROVED/STARTED/COMPLETED.

**Possible errors**: *Production confirmation failed* (exact phrase required), *Permission
'deployment.execute' on a PRODUCTION target is required*, *Another deployment is in progress*.

**Recovery**: cancel a queued/pending deployment (Cancel button) or roll back (§16). Consider
enabling `SCARLET_AUTO_ROLLBACK` for automatic rollback on failed health checks.

**Security**: PROD actions are impossible without the prod permission even if a button is visible;
the API enforces everything.

### 10. Start an application
**Preconditions**: instance exists (deployed at least once), `lifecycle.start` (+ `prod.` on PROD).
**Steps**: Applications → application → instance row → **Start** → confirm (reason/phrase on PROD).
**Expected**: modal shows `SUCCESS (STARTED)` or `ALREADY_RUNNING`; desired state = RUNNING.
**Errors**: `RUNTIME_ERROR` with the runtime's stderr (e.g. port already allocated).
**Recovery**: check logs (§14), fix the cause, retry. If the container is broken, Stop then Start recreates it.
**Security**: idempotent; the operation is locked per application/host so two operators cannot collide.

### 11. Stop an application
**Steps**: instance row → **Stop** → on PROD type `STOP PROD` and a reason.
**Expected**: `STOPPED` or `ALREADY_STOPPED`; desired state = STOPPED (the reconciler will not report drift for a deliberately stopped app).
**Errors**: timeout while stopping (container ignores SIGTERM) → SCARLET waits `stop_grace_period` then the runtime kills it.
**Recovery**: Start again.

### 12. Restart an application
**Steps**: instance row → **Restart** → confirm. Always performs a restart (stop + start or `restart`).
**Expected**: `RESTARTED`, state RUNNING.
**Errors/Recovery**: as §10.

### 13. Inspect status
**Steps**: instance row → **Status** (no confirmation). The modal shows actual state, version label,
container details, runtime inspect data and the **drift** verdict versus the desired state.
**Expected**: `RUNNING`, version equal to the desired version, "Drift: none".
**Errors**: `NOT_INSTALLED` means no container and no `current` symlink on the host.
**Recovery**: redeploy. If status shows DRIFT, see §25 / operations guide.

### 14. Inspect logs
**Steps**: **Monitoring → Logs**, choose the instance, lines (100–5000), since (10m/1h/…),
optional search text → **Fetch**. Auto-refresh every 10 s available; **Download** saves the result.
**Expected**: the last N lines from `podman logs`/`docker logs`/`kubectl logs` with timestamps.
**Errors**: *Unable to collect logs: no container* — application never started or was removed.
**Security**: only runtime log interfaces are used; no file paths can be requested.

### 15. Perform health checks
**Steps**: instance row → **Health**, or **Monitoring → Health → Check all running**. Health type
comes from the manifest (`http`, `tcp`, `command`, `container_status`, `kubernetes_status`).
**Expected**: HEALTHY with the probe detail (`HTTP 200`).
**Errors**: UNHEALTHY with the probe output; SCARLET raises a notification the first time.
**Recovery**: check logs (§14), restart (§12) or roll back (§16). A periodic health sweep runs every 10 minutes.

### 16. Rollback
**Preconditions**: a previous successful release exists for the instance (shown as *Previous*),
`deployment.rollback` (+ `prod.`), PROD rollback allowed (`SCARLET_PROD_ALLOW_ROLLBACK`).
**Steps**: instance row → **Rollback** → the dialog shows current and target version → reason →
`ROLLBACK PROD` on PROD → Confirm. A rollback deployment (`RBK-…`) is created and followed live.
**Expected**: `SUCCESS`; current version = previous version, the replaced release is kept on the
host and becomes the new *Previous*.
**Errors**: *No previous successful release*, *Previous release directory … is missing on the host*
(someone deleted it: redeploy the wanted version instead), health check failure of the old release.
**Security**: rollback is a first-class audited operation (`ROLLBACK_STARTED/COMPLETED`).

---

## Part C — Diagnosis procedures

### 17. Diagnose SSH failures
| Message | Cause | Action |
|---|---|---|
| `SSH_CONNECTION_ERROR … timed out` | firewall, wrong port/IP, host down | check `nc -vz host 22` from the SCARLET server; verify firewall (§installation) |
| `SSH_AUTHENTICATION_ERROR` | wrong key/password, `authorized_keys` perms, user locked | test with `ssh -i key scarlet@host` from the server; `restorecon -Rv ~/.ssh` |
| `SSH_HOST_KEY_ERROR … not approved` | new host | §3 |
| `HOST KEY MISMATCH` | server reinstalled or MITM | §31 |
| `Host … has no active SSH credential` | credential missing/revoked | §2 |
Also check `journalctl -u sshd` on the target and **Audit → Security Events**.

### 18. Diagnose Docker failures
- `permission denied while trying to connect to the Docker daemon socket`: add the SSH user to the
  `docker` group (`usermod -aG docker scarlet`) or use rootless Docker.
- `pull access denied` / `manifest unknown`: image name/tag wrong or registry credentials missing on
  the host (`docker login` as the SSH user).
- `port is already allocated`: §23.
- Use **Status → Inspect** for `RestartCount`, `State.ExitCode`; use §14 for application errors.

### 19. Diagnose Podman failures
- `cannot re-exec process` / `newuidmap` errors: missing subuid/subgid for the user
  (`usermod --add-subuids 100000-165535 --add-subgids 100000-165535 scarlet`).
- Containers stop after logout: `loginctl enable-linger scarlet`.
- `Error: crun: …permission denied` on volumes with SELinux enforcing: SCARLET mounts with `:Z`;
  ensure the shared directory is owned by the SSH user.
- `no space left on device` in `~/.local/share/containers`: §21, `podman system prune`.
- Rootless ports < 1024: set `net.ipv4.ip_unprivileged_port_start=80` or use ports ≥ 1024.

### 20. Diagnose Kubernetes failures
- `kubectl: command not found`: install kubectl on the host or attach a kubeconfig credential (API mode).
- `Unable to connect to the server`: kubeconfig context/cluster unreachable from the host/SCARLET.
- `forbidden`: the service account lacks RBAC for Deployments/Services/ConfigMaps/Secrets in the namespace.
- Rollout stuck in STARTING: `kubectl -n <ns> describe deployment <app>` (image pull, probes,
  resources). SCARLET's rollout timeout is `deployment.start_timeout`.
- Namespace mismatch: host namespace vs `kubernetes.namespace` in the manifest.

### 21. Diagnose disk-full conditions
Pre-flight fails with *Sufficient disk space*. On the host: `df -h /opt/scarlet ~/.local/share/containers`.
Free space: `podman image prune -a` (or `docker`), remove old releases via **cleanup** (only keeps
current/previous + retention count, never the active release), rotate application logs in
`shared/logs`. On the SCARLET server: `SCARLET_ARTIFACT_RETENTION_COUNT` and `flask scarlet cleanup`.

### 22. Diagnose memory problems
Pre-flight *Sufficient memory* WARN/FAIL compares `free -m` available memory with
`resources.memory`. Check `free -m`, look for OOM kills (`journalctl -k | grep -i oom`), lower
`resources.memory` or move the application. Containers killed by the OOM killer show `ExitCode 137`
in Status → Inspect.

### 23. Diagnose port conflicts
Pre-flight *Required ports* FAIL lists busy host ports. On the host: `ss -ltnp | grep :8080`.
Either stop the conflicting service, change `ports[].host` in a new package version, or bind to a
specific interface (`ports[].bind`).

### 24. Diagnose health-check failures
1. Status (§13) — is the container running? If not, logs (§14) will show the crash.
2. Probe type: `http` requires the application to listen on `127.0.0.1:<host port>` **on the host**
   (the probe runs on the target). Verify `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/health`.
3. Slow start: increase `healthcheck.retries`/`interval`/`timeout` in the manifest.
4. Wrong expected status: `healthcheck.expected_status`.
5. Missing configuration/secrets: check the rendered keys in the deployment "Render configuration" step.

### 25. Recover from a failed deployment
1. Open Deployments → deployment. The failed step shows the command, exit code and stderr.
2. If status is **ROLLBACK_REQUIRED** (failure after the new release was activated): click
   **Rollback to <previous>** or fix and redeploy. If `SCARLET_AUTO_ROLLBACK` is on, SCARLET already
   rolled back (status ROLLED_BACK).
3. If failure happened before activation (validation, transfer, install): the previous release is
   untouched and still running. Fix the cause and create a new deployment.
4. Verify with Status/Health (§13/§15). Check **Monitoring → Health** for DRIFT.
5. Stale staging files are cleaned by the next deployment/cleanup job.

---

## Part D — SCARLET platform recovery

### 26. Recover SCARLET itself
**Symptoms**: UI unavailable, `/api/ready` returns `not-ready`.
1. `docker compose ps` / `systemctl status scarlet`. Check `docker compose logs scarlet-web
   scarlet-worker postgres redis nginx`.
2. `/api/ready` reports which dependency fails (database, redis, workers).
3. Restart the failing service: `docker compose restart scarlet-web` (or `systemctl restart scarlet`).
4. Configuration errors abort startup with a clear list (`Invalid SCARLET configuration: …`):
   fix `.env` (`flask scarlet check-config`).
5. Deployments interrupted by a crash end as FAILED (*Worker time limit exceeded* / internal error)
   or remain RUNNING until the lock expires (`SCARLET_LOCK_TIMEOUT`); check the target with Status
   and redeploy. Locks are automatically released (TTL).

### 27. Restore PostgreSQL
Follow `docs/backup.md`. Short form: `scripts/restore.sh <backup dir>` (type `RESTORE`). The dump
contains encrypted credentials: the **same** `SCARLET_CREDENTIAL_ENCRYPTION_KEY` must be present
in `.env`, otherwise credentials/secrets cannot be decrypted (they must then be re-entered).
Run `flask db upgrade` (automatic on web start) and `flask scarlet check-config`.

### 28. Restore artifacts
`scripts/restore.sh` also restores `/data/scarlet/artifacts`. To restore only artifacts:
`tar -C /data/scarlet -xzf artifacts.tar.gz`. Verify integrity: Applications → version →
manifest icon shows *artifact checksum verified*; mismatches raise a CRITICAL security event.

### 29. Rotate credentials
- **SSH credentials**: Security → Credentials → host → Add / rotate with the new key; the old
  credential becomes INACTIVE (kept for audit). Remove the old public key from `authorized_keys` on
  the host. Test connection.
- **Application secrets**: Applications → application → Configuration → edit the SECRET entry with the
  new value; redeploy or restart to apply (a new configuration version is recorded).
- **Encryption key**: set `SCARLET_CREDENTIAL_ENCRYPTION_KEY` to the new key and
  `SCARLET_CREDENTIAL_ENCRYPTION_KEY_PREVIOUS` to the old one, restart, run
  `flask scarlet rotate-credentials`, then remove the previous key. Take a backup before and after.
- **Admin/user passwords**: Security → Users → key icon (reset; user must change at next login).
- **API tokens**: Security → tokens (user menu) → revoke and create a new one.

### 30. Handle compromised credentials
1. **Contain**: revoke the credential in SCARLET (Security → Credentials → revoke) so no further
   operations use it; on every affected host remove the public key from `authorized_keys` (or change
   the password) and review `journalctl -u sshd` for logins from unexpected sources.
2. **Rotate**: install a new key (§2) and add it in SCARLET; rotate application secrets (§29).
3. **Review**: Audit → Audit Log filtered by the host and time window; Security Events; hosts'
   `last_login` records. Check the applications for unexpected containers (`podman ps -a`).
4. If the SCARLET database or `.env` may have leaked: rotate `SCARLET_CREDENTIAL_ENCRYPTION_KEY`
   (§29) *after* rotating every stored secret, rotate `SCARLET_SECRET_KEY` (invalidates all sessions),
   force password resets.
5. Document the incident (audit export: Audit Log → CSV/JSON).

### 31. Handle an unexpected SSH fingerprint change
SCARLET blocks the connection, marks the host key **MISMATCH**, sets the host OFFLINE and records
a CRITICAL security event (`SSH_HOST_KEY_MISMATCH`).
1. Do **not** approve the new key yet. Determine whether the server was legitimately reinstalled or
   its SSH host keys regenerated (change records, sysadmin confirmation).
2. Obtain the real fingerprint from the server console (`ssh-keygen -lf /etc/ssh/ssh_host_*.pub`).
3. If it matches the pending fingerprint and the change is legitimate: Hosts → host → **Approve
   fingerprint** (type it). Acknowledge the security event (Audit → Security Events).
4. If it does **not** match or the change is unexplained: treat as a potential man-in-the-middle;
   keep the host blocked, involve security, check network path/DNS, and follow §30 for any
   credential that may have been exposed during the incident.

---

## Quick reference: statuses

| Host | ONLINE / OFFLINE / UNKNOWN / DISABLED |
|---|---|
| Application instance | RUNNING / STOPPED / STARTING / STOPPING / FAILED / UNKNOWN / NOT_INSTALLED |
| Deployment | QUEUED → VALIDATING → PREFLIGHT → TRANSFERRING → INSTALLING → STARTING → HEALTH_CHECKING → SUCCESS; failures: *_FAILED, ROLLBACK_REQUIRED, ROLLED_BACK, CANCELLED |
| Operation | QUEUED / RUNNING / SUCCESS / FAILED / TIMEOUT / CANCELLED |
| Health | HEALTHY / UNHEALTHY / UNKNOWN |
| Host key | UNKNOWN / PENDING_APPROVAL / APPROVED / MISMATCH / REVOKED |
