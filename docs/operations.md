# Operations guide

Day-2 operation of SCARLET itself and of the applications it manages. Step-by-step procedures are
in `RUNBOOK.md`; this guide explains the concepts behind them.

## Environments and production safety

`DEV` and `PROD` are seeded; more can be added as rows in `environments`. Per environment you can
set `require_confirmation`, `require_approval`, `allow_rollback`, `max_parallel_deployments`
(**Infrastructure → Environments**). Global settings (`System → Settings`) act as a floor: the
stricter value wins. PROD operations require the `prod.*` permission variant, a reason and typed
confirmation (`DEPLOY TO PROD`, `STOP PROD`, `ROLLBACK PROD`, `RESTART PROD`, `DELETE PROD`).

## Hosts

Lifecycle: create → credential → host-key approval → test → discover → set runtime → deploy.
Host status: ONLINE/OFFLINE (last connection attempt), UNKNOWN (never tested), DISABLED (excluded
from everything). Disabled hosts and hosts with deployment history cannot be deleted (audit trail).
Host groups (`DEV-API`, `PROD-API`) allow one-click multi-host selection in the wizard and target
rules on applications.

## Applications and versions

The application record is the policy: runtime, allowed environments/runtimes/host groups, health
check defaults, `allow_hooks`. Versions are created only by uploading a valid package; they are
immutable and can be *deactivated* (no new deployments, kept for history). Rollback candidates are
never deactivated automatically.

## Deployments

- Single or multi-host (`SEQUENTIAL` stops on first failure; `PARALLEL` up to the environment limit,
  PROD default 1).
- Steps and their command output are stored per deployment; download the full log from the
  deployment page.
- Failure handling: failures before *activate* leave the previous release running; failures after
  activation set `ROLLBACK_REQUIRED` (manual rollback button) unless `SCARLET_AUTO_ROLLBACK` is on
  (then `ROLLED_BACK`).
- Cancel is possible while QUEUED/PENDING_APPROVAL/APPROVED.
- Pre-flight (`POST /api/deployments/preflight`) can be run at any time from the wizard.

## Lifecycle operations

START/STOP/RESTART/SCALE change the desired state and act through the runtime adapter under a lock
(`runtime:{host}:{app}`); STATUS/HEALTH/LOGS/VERSION are read-only. Operations are asynchronous
(202 + poll) with live modals in the UI; the **Operations** and **Jobs** pages list history and
active jobs. Idempotency: START on a running app returns `ALREADY_RUNNING`, STOP on a stopped app
`ALREADY_STOPPED`.

## Reconciliation and drift

Celery beat runs `reconcile` every `SCARLET_RECONCILE_INTERVAL` seconds (300): for each enabled
host and deployed instance it observes the actual state and computes drift:

| Drift | Meaning |
|---|---|
| VERSION | running version label ≠ desired version |
| UNEXPECTED_STOP | desired RUNNING but container exited/failed |
| STATE | desired STOPPED but running, or replica mismatch |
| MISSING | no container and no `current` release |
| RUNTIME | host runtime differs from the one recorded |

Drift raises a notification and audit event (`DRIFT_DETECTED`) once, and is shown on the dashboard,
Monitoring → Health and the application page. `SCARLET_RECONCILE_AUTO_REMEDIATE=true` lets the
reconciler start/stop containers to match the desired state — **never on PROD** (enforced) and only
for UNEXPECTED_STOP/STATE drift. `Hosts → host → Reconcile` runs it on demand.

## Health

Health checks run at the end of every deployment, on demand, and every 10 minutes for running
instances (`health_sweep`). The first transition to UNHEALTHY notifies operators (e-mail if
configured) and writes `HEALTH_CHECK_FAILED` to the audit log.

## Notifications

In-app (bell icon) for deployment success/failure, rollback, health failure, host unreachable,
drift, approval requests. E-mail requires `SCARLET_MAIL_*`; it is disabled otherwise.

## Retention and cleanup

`cleanup` runs every 6 hours: stale incoming uploads (>24 h), INVALID packages (>7 days), health
checks (`SCARLET_LOG_RETENTION_DAYS`), operation logs (`SCARLET_OPERATION_LOG_RETENTION_DAYS`),
artifacts beyond `SCARLET_ARTIFACT_RETENTION_COUNT` per application (never current/previous/desired
versions), audit only if `SCARLET_AUDIT_RETENTION_DAYS` > 0. Remote releases on a host are pruned
with the `cleanup_remote_releases` task / `flask scarlet cleanup` keeping current, previous and the
newest N.

## Users, roles, tokens

Security → Users/Roles. Admins reset passwords (forced change), lock/unlock, deactivate. Personal
API tokens (user menu → API tokens) for CI integrations, e.g. uploading a package:

```bash
curl -H "Authorization: Bearer scl_…" -F file=@dist/customer-api-2.5.0.scarlet.tar.gz \
     https://scarlet.example.internal/api/packages/upload
```

## Monitoring SCARLET

- `/api/health` (liveness: DB), `/api/ready` (DB + Redis + workers), `/api/metrics` (Prometheus:
  `scarlet_hosts`, `scarlet_application_instances`, `scarlet_instances_drift`,
  `scarlet_deployments_running`, counters).
- JSON logs on stdout of each container with `request_id`, `deployment_id`, `operation_id`.
- **Jobs** page: active operations and deployments; `GET /api/jobs/<id>` for Celery state.

## System settings

`System → Settings` overrides environment values at runtime (timeouts, retention, PROD controls,
parallelism, reconciliation). Changes are audited (`SETTING_UPDATED`). Secrets are never settings.
