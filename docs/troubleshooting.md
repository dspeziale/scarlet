# Troubleshooting

Always start from the **request id** shown in the error message / footer: search it in the
container logs (`docker compose logs scarlet-web scarlet-worker | grep <request_id>`) and in
Audit → Audit Log.

## SCARLET does not start

| Symptom | Cause / fix |
|---|---|
| `Invalid SCARLET configuration: …` | fix the listed variables in `.env` (secrets, PostgreSQL URL, secure cookies); `flask scarlet check-config` |
| `database not reachable after 60 attempts` | PostgreSQL not ready / wrong `DATABASE_URL` / firewall |
| `alembic … Can't locate revision` | database created by a newer version; restore from backup or upgrade the image |
| nginx 502 | web container unhealthy; `curl http://scarlet-web:8000/api/health` inside the network |
| `/api/ready` → `workers: 0 worker(s)` | worker container down or wrong `REDIS_URL`; `docker compose logs scarlet-worker` |

## Login problems

- *Account temporarily locked*: wait `SCARLET_LOCKOUT_MINUTES` or Security → Users → unlock.
- *429 Too many requests*: login rate limit (`SCARLET_LOGIN_RATE_LIMIT`) — per IP; behind a proxy
  ensure `SCARLET_TRUSTED_PROXIES` is correct, otherwise all users share one IP.
- CSRF errors on forms: cookies blocked or page open too long; reload. Behind HTTPS proxy check
  `X-Forwarded-Proto` so secure cookies are accepted.
- Session expires quickly: `SCARLET_SESSION_LIFETIME_SECONDS`.

## Hosts

| Error | Fix |
|---|---|
| `SSH_CONNECTION_ERROR` | reachability/port/firewall; `nc -vz host 22` from the SCARLET server |
| `SSH_AUTHENTICATION_ERROR` | credential wrong/expired; `authorized_keys` permissions; SELinux context |
| `SSH_HOST_KEY_ERROR` | approve pending fingerprint (RUNBOOK §3) or investigate mismatch (§31) |
| `Host … has no active SSH credential` | add a credential |
| Discover shows runtime `available: false` | install runtime; check `command -v podman` as the SSH user (PATH in non-login shells: `/usr/bin` is required) |
| Status stuck UNKNOWN | never tested; run Test connection |

## Packages

| Error | Fix |
|---|---|
| `Unsafe path in archive` / `Links are not allowed` | rebuild with `scripts/build-scarlet-package.py` (never hand-craft tars with symlinks) |
| `manifest.yaml failed validation: …` | follow the listed field errors; unknown keys are rejected |
| `Application '…' is not registered` | create the application with the same code |
| `Version … already exists` | releases are immutable: bump the version |
| `413` | `SCARLET_MAX_UPLOAD_MB` and nginx `client_max_body_size` |
| `Malware scanner rejected the package` | scanner returned non-zero; inspect the file offline |

## Deployments

| Failed step | Typical cause |
|---|---|
| Validate package | artifact missing on disk (storage volume lost) or checksum mismatch → restore artifacts |
| Check target | runtime unavailable, disk/memory, ports busy, secrets missing (see pre-flight details) |
| Transfer / Verify checksum | network interruption; retried automatically for transient errors |
| Extract release | disk full, `tar` missing, base path not writable |
| Install release | image pull denied/not found; registry auth on the host; archive missing |
| Start application | port conflict, invalid env, container exits immediately → Logs |
| Health check | see RUNBOOK §24 |
| auto_rollback FAILED | previous release directory removed on the host; redeploy the wanted version |

Deployment stuck in RUNNING: worker crashed — the lock expires after `SCARLET_LOCK_TIMEOUT`; the
task is marked FAILED on the next worker attempt or manually via the database only if truly
orphaned. Check **Jobs** and `GET /api/jobs/<job_id>`.

## Operations

- `CONCURRENT_OPERATION`: wait for the running operation (Jobs page) or for the lock to expire.
- `RUNTIME_ERROR: no container`: application never started on this host → deploy.
- LOGS returns nothing: container just recreated; increase lines or remove `since`.

## Reconciliation / drift

Unexpected DRIFT after a manual change on the host: redeploy or START/STOP to realign, or enable
auto-remediation on DEV. RUNTIME drift: host runtime changed — update the host record and redeploy.

## Kubernetes

`kubectl: command not found` (kubectl mode) / kubeconfig invalid (API mode) / RBAC forbidden /
rollout timeout (`deployment.start_timeout`). `kubectl -n <ns> describe deployment <app>` and
`get events` explain most failures.

## Performance

- Large uploads: gunicorn `timeout` 300 s and nginx `proxy_read_timeout 600` are set; raise for
  very slow links. Uploads stream to disk (`SCARLET_UPLOAD_TMP_PATH`).
- Many hosts: increase `CELERY_CONCURRENCY`, run more worker containers; reconciliation interval
  `SCARLET_RECONCILE_INTERVAL`.
- Dashboard slow: check PostgreSQL indexes exist (`flask db upgrade`), vacuum.

## Collecting diagnostics for support

```
docker compose ps
docker compose logs --since 1h scarlet-web scarlet-worker scarlet-beat > scarlet-logs.txt
curl -s https://scarlet/api/ready
Audit → export CSV for the time window; Deployments → deployment → Download log
```
Never share `.env`, backups or credential material.
