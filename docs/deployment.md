# Deployment pipeline

## States

```
CREATED ─▶ (PENDING_APPROVAL ─▶ APPROVED) ─▶ QUEUED ─▶ VALIDATING ─▶ VALIDATED ─▶ PREFLIGHT
  ─▶ TRANSFERRING ─▶ TRANSFERRED ─▶ INSTALLING ─▶ INSTALLED ─▶ STARTING ─▶ STARTED
  ─▶ HEALTH_CHECKING ─▶ SUCCESS

failures: VALIDATION_FAILED · PREFLIGHT_FAILED · TRANSFER_FAILED · INSTALL_FAILED · START_FAILED
          · HEALTH_CHECK_FAILED · ROLLBACK_REQUIRED ─▶ ROLLING_BACK ─▶ ROLLED_BACK · FAILED
other:    CANCELLED · REJECTED
```

Transitions are enforced by `app/deployment/state_machine.py`; the coarse `status_summary`
(QUEUED/RUNNING/SUCCESS/FAILED/ROLLED_BACK/CANCELLED/PENDING_APPROVAL) is used by lists.

## Steps executed by the engine

| Step | Kind | What happens on the target | Failure state |
|---|---|---|---|
| Validate package | validate | local: artifact exists, SHA-256 equals the immutable version checksum (Kubernetes API mode also extracts locally) | VALIDATION_FAILED |
| Check target | preflight | runtime `detect()`, static checks (compatibility, host key, credential, secrets, package) | PREFLIGHT_FAILED |
| Prepare remote layout | prepare | `mkdir -p` of `applications/<app>/{releases,shared/{config,data,logs},staging,backups}` and volume dirs | FAILED |
| Transfer package | transfer | SFTP to `staging/<version>.<token>.scarlet.tar.gz` (`.part` + rename) | TRANSFER_FAILED |
| Verify checksum | verify_checksum | remote `sha256sum` equals local | TRANSFER_FAILED |
| Extract release | extract | `tar --no-same-owner -xzf` into `staging/<version>.<token>.extract`, manifest version check, `mv -T` to `releases/<version>` (an existing dir is moved to `backups/`) | INSTALL_FAILED |
| Render configuration | configure | env file `shared/config/scarlet.env` (manifest env + env files + SCARLET configuration + secrets + `SCARLET_*`) uploaded via SFTP | INSTALL_FAILED |
| pre-deploy / migrate hooks | hook | `timeout N sh -e releases/<v>/scripts/x.sh` | INSTALL_FAILED |
| Install release | install | adapter: `podman load`/`pull` (or `compose pull`), Kubernetes `apply` | INSTALL_FAILED |
| Activate release | activate | `ln -sfn … current.tmp && mv -T current.tmp current` (atomic) | INSTALL_FAILED → rollback candidate |
| Start application | start | adapter `start()` (recreate container with labels/env/ports/volumes; compose up; k8s scale + rollout) | START_FAILED |
| Health check | health | adapter probe with retries/interval from the manifest | HEALTH_CHECK_FAILED |
| post-deploy hooks | hook (non-critical) | logged, does not fail the deployment | — |
| Finalize | finalize | instance current/previous version, actual state, drift reset, audit | — |
| Clean staging | cleanup (non-critical) | remove staged archive | — |

Rollback deployments (`kind=ROLLBACK`, `RBK-…`) reuse the release directory already on the host
(transfer/verify/extract are skipped) and run `pre_rollback`/`post_rollback` hooks.

## Remote layout

```
/opt/scarlet/applications/<app>/
  releases/<version>/      immutable extracted package
  current -> releases/<v>  active release
  shared/config/scarlet.env, shared/data/<volume>, shared/logs/<volume>
  staging/                 uploads + temporary extraction
  backups/                 replaced release directories
```

## Multi-host

`DeploymentBatch` groups the per-host deployments. `SEQUENTIAL`: one after the other, stop on
failure (remaining CANCELLED). `PARALLEL`: up to `max_parallel` (bounded by the environment and
`SCARLET_[PROD_]MAX_PARALLEL_DEPLOYMENTS`). `CANARY` is reserved.

## Rollback

Manual: instance → Rollback (target = previous version or an explicit version). Automatic:
`SCARLET_AUTO_ROLLBACK=true` and failure after activation → engine re-activates the previous
release, restarts, health-checks and marks `ROLLED_BACK`. Previous releases are never deleted
automatically; retention keeps current + previous + the newest N.

## Idempotency

Redeploying the currently running version recreates the container (warning in pre-flight).
START/STOP are idempotent. A release directory left by a failed attempt is moved aside, never
overwritten in place.

## Timeouts

SSH connect (`SCARLET_SSH_TIMEOUT`), per command (`SCARLET_SSH_COMMAND_TIMEOUT`, pull/load up to
900 s), whole deployment (`SCARLET_DEPLOYMENT_TIMEOUT`), health probe (manifest), Celery task
(`SCARLET_JOB_TIMEOUT`), lock TTL (`SCARLET_LOCK_TIMEOUT`).
