# Architecture

## 1. SCARLET is a control plane

Remote Oracle Linux servers are the **data/execution plane**. SCARLET never "just runs SSH
commands"; it keeps, for every application × target pair (`ApplicationInstance`):

| | Fields | Set by |
|---|---|---|
| **Desired state** | `desired_version`, `desired_state` (RUNNING/STOPPED/ABSENT), `desired_replicas` | operators through deployments and lifecycle operations |
| **Actual state** | `actual_version`, `actual_state`, `actual_replicas`, `actual_runtime`, `health_status`, `actual_observed_at` | deployment engine, lifecycle operations, reconciler |
| **Drift** | `drift_detected`, `drift_type` (VERSION, STATE, UNEXPECTED_STOP, MISSING, RUNTIME), `drift_details` | `compute_drift(desired, actual)` |

The deployment engine moves actual toward desired; the reconciler (Celery beat, default every 5
minutes) observes and reports drift, and may remediate (DEV only, opt-in).

## 2. Layers

```
Flask routes (app/api, app/web)      ─ HTTP, auth, validation of shape; no business logic
        │
Services (app/services)              ─ DeploymentService, LifecycleService, HostService, PackageService,
        │                              PreflightService, ReconciliationService … (authorization + PROD guard)
        │
Deployment engine (app/deployment)   ─ domain objects, planner, engine (state machine, steps, rollback),
        │                              manifest contract, package validator, artifact storage, remote layout
        │
Runtime adapters (app/runtimes)      ─ RuntimeAdapter interface; Docker, Podman, Kubernetes implementations
        │
SSH layer (app/ssh)                  ─ RemoteCommand (argv + allowlist), SSHClient (Paramiko, strict host keys),
        │                              SFTP transfer, FakeSSHClient for tests
        ▼
Target host                          ─ /opt/scarlet layout, container runtime
```

Cross-cutting: `app/security` (crypto, RBAC, validators, ProductionGuard, headers),
`app/audit` (append-only recorder + security events), `app/lifecycle` (locks, health checker),
`app/tasks` (Celery), `app/repositories` (queries/pagination), `app/models`.

### Domain objects (`app/deployment/domain.py`)

- `DesiredApplicationState` — application, version, state, replicas, image, manifest, env, ports,
  volumes, health spec, namespace.
- `ActualApplicationState` — observed version/state/replicas/health/details.
- `DriftReport` = `compute_drift(desired, actual)`.
- `PlanStep` / `DeploymentPlan` — ordered, runtime-agnostic steps (`validate`, `preflight`,
  `prepare`, `transfer`, `verify_checksum`, `extract`, `configure`, `hook`, `install`, `activate`,
  `start`, `health`, `finalize`, `cleanup`) with `critical` and `rollback_trigger` flags.
- `StepExecution` / `DeploymentExecution` — runtime record, persisted into `Deployment`/`DeploymentStep`.

### Deployment flow

```
DeploymentService.create()
  ├─ resolve app/version/hosts, authorize (prod.* on PROD), ProductionGuard.check_operation
  ├─ compatibility rules, conflict check, static pre-flight
  ├─ DeploymentBatch + Deployment rows (CREATED → QUEUED | PENDING_APPROVAL)
  └─ Celery: run_deployment_batch → deploy_application(id)
        DeploymentEngine.execute()
          ├─ lock runtime:{target}:{application}
          ├─ build DesiredApplicationState (manifest + configuration + secrets)
          ├─ DeploymentPlanner.plan() → DeploymentPlan (persisted as JSON)
          ├─ for each step: state machine transition, DeploymentStep row, adapter call
          └─ failure: fail-state, notification; auto-rollback if enabled and after activation
```

### Runtime adapter interface

`detect · status · version · inspect · logs · health · install · start · stop · restart · remove ·
rollback · scale · apply`. `RuntimeFactory.get(runtime_type)` returns the adapter; adding a runtime
= one class + `RuntimeFactory.register`. Adapters receive a `RuntimeContext` (executor, host info,
layout, logger) and never see Flask.

### Remote command safety

`RemoteCommand(argv, command_type, …)` — argv[0] must be in `ALLOWED_BINARIES`; `sh`,
`timeout`, `find` only through trusted builders; arguments quoted with `shlex.quote`; remote paths
validated under the base path; hooks limited to `release/scripts/*.sh`.

## 3. Data model (PostgreSQL)

Users/RBAC: `users, roles, permissions, role_permissions, user_roles, api_tokens`.
Infrastructure: `environments, target_hosts, target_credentials (encrypted), ssh_keys, host_groups,
host_group_members, runtime_capabilities`. Applications: `applications, application_versions
(immutable), packages, application_instances (desired/actual)`. Operations: `deployment_batches,
deployments, deployment_steps, deployment_approvals, lifecycle_operations, operation_logs,
health_checks, distributed_locks`. Governance: `audit_logs (append-only), security_events,
configurations, configuration_entries, configuration_versions, notifications, system_settings`.

Indexes exist on deployment target/application/created_at/status, audit timestamp/user/action,
operation status/created_at, versions per application, instances per host/app.

## 4. Jobs

Celery + Redis. Queues: `scarlet` (lifecycle/host ops), `scarlet-deploy`, `scarlet-maintenance`.
Tasks: `deploy_application`, `run_deployment_batch`, `run_lifecycle_operation`,
`test_ssh_connection`, `discover_host`, `reconcile`, `reconcile_host`, `cleanup`,
`cleanup_remote_releases`, `health_sweep`. Retries with exponential backoff only for
`retryable` errors (SSH connection/timeout, transfer) and only before remote state changed.
Locks: Redis `SET NX PX` + Lua release (DB fallback), key `runtime:{target}:{application}`, TTL.

## 5. Observability

Request id (ULID) per request → `X-Request-ID` header, JSON logs, audit rows, worker context.
Human references: `DEP-YYYYMMDD-nnnnnn`, `RBK-…`, `OP-…`, `BATCH-…`. `/api/health`, `/api/ready`,
`/api/metrics` (Prometheus).

## 6. Extension points

- New runtime: implement `RuntimeAdapter`, register in `RuntimeFactory`.
- New artifact backend: implement `ArtifactStorage` (S3/MinIO).
- New secret backend: implement `SecretProvider` (Vault, AWS SM, Kubernetes Secrets).
- New environment: insert an `environments` row (seed) — the model is not limited to DEV/PROD.
- Approval workflow: `DeploymentApproval` rows and `PENDING_APPROVAL` state already exist;
  multi-approver policies extend `ProductionGuard.check_approval`.
- Deployment strategies: `DeploymentStrategy.CANARY` reserved; batch runner handles SEQUENTIAL/PARALLEL.
- Live updates: the UI polls `/api/deployments/<id>/steps` and `/api/operations/<id>`; a
  WebSocket/SSE publisher can be added without changing the engine (steps are persisted per change).
