# SCARLET

**System Container Application Release, Lifecycle & Environment Tool**

SCARLET is an internal enterprise control plane for the lifecycle of applications running on
remote Oracle Linux servers with **Docker**, **Podman** or **Kubernetes**. Operators register
target hosts, upload standardised release packages, and deploy / start / stop / restart /
inspect / roll back applications from a single AdminLTE web console, without ever opening an
SSH session by hand. Every action is authorised, audited and executed through a controlled,
allow-listed command layer.

```
 Browser ──HTTPS──▶ Nginx ──▶ SCARLET web (Flask/Gunicorn) ──▶ PostgreSQL
                                   │                          ▶ Redis ──▶ Celery workers
                                   │                                           │ SSH/SFTP
                                   ▼                                           ▼
                             Artifact storage                        Oracle Linux hosts
                                                                     (Docker/Podman/Kubernetes)
```

## Key concepts

| Concept | Meaning |
|---|---|
| **Target host** | Remote Oracle Linux machine reached over SSH (strict host-key verification, encrypted credentials). |
| **Environment** | `DEV` or `PROD`. PROD operations need `prod.*` permissions, a reason and a typed confirmation (`DEPLOY TO PROD`), optionally a second-person approval. |
| **Application / Version** | A deployable business application and its immutable released versions (SHA-256 pinned). |
| **Package** | `name-version.scarlet.tar.gz` with a versioned `manifest.yaml` — see [docs/APPLICATION_RELEASE_CONTRACT.md](docs/APPLICATION_RELEASE_CONTRACT.md). |
| **Desired vs actual state** | SCARLET is a control plane: each application/host instance records what operators want (version, RUNNING/STOPPED) and what the reconciler observes; differences surface as **DRIFT**. |
| **Runtime adapter** | Docker, Podman and Kubernetes implementations of one interface. Business logic never branches on the runtime. |
| **Deployment plan** | Ordered, auditable steps (validate → pre-flight → transfer → verify → extract → configure → hooks → install → activate → start → health → finalize) with automatic or manual rollback. |

## Quick start (development)

```bash
cp .env.example .env                     # set SCARLET_INITIAL_ADMIN_PASSWORD
docker compose --profile dev up -d --build   # or: podman compose --profile dev up -d --build
docker compose exec scarlet-web flask scarlet seed --with-demo
open http://localhost:8080                # admin / SCARLET_INITIAL_ADMIN_PASSWORD (forced change at first login)
```

The `dev` profile starts a simulated Oracle Linux host (`mockhost`, SSH on port 2222, user
`scarlet`, password `scarlet-dev`, rootless Podman). Register it as a DEV host, add the password
credential, approve its host key, run **Discover**, then build and upload the example package:

```bash
python scripts/build-scarlet-package.py --source examples/podman-app --version 1.0.0 --output dist/
```

Local (no containers) development: `make install && make run` (SQLite + eager Celery) — see
[docs/development.md](docs/development.md).

## Production

Follow [docs/installation.md](docs/installation.md) (Oracle Linux, Podman, PostgreSQL, Redis,
SELinux, firewall, systemd, TLS) and [docs/security.md](docs/security.md). Production refuses to
start without `SCARLET_SECRET_KEY`, `SCARLET_CREDENTIAL_ENCRYPTION_KEY`, PostgreSQL and secure
cookies (`flask scarlet check-config`).

## Documentation

| Document | Audience |
|---|---|
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | Operators: step-by-step procedures (add host, deploy, rollback, diagnose, recover) |
| [docs/APPLICATION_RELEASE_CONTRACT.md](docs/APPLICATION_RELEASE_CONTRACT.md) | Application teams: package & manifest contract |
| [docs/architecture.md](docs/architecture.md) | Engineers: control plane, layers, domain model |
| [docs/security.md](docs/security.md) | Security: threat model, controls, defaults |
| [docs/installation.md](docs/installation.md) | Administrators: Oracle Linux installation |
| [docs/operations.md](docs/operations.md), [docs/deployment.md](docs/deployment.md) | Day-2 operations, deployment pipeline |
| [docs/ssh.md](docs/ssh.md), [docs/runtime-docker.md](docs/runtime-docker.md), [docs/runtime-podman.md](docs/runtime-podman.md), [docs/runtime-kubernetes.md](docs/runtime-kubernetes.md) | Remote access & runtimes |
| [docs/package-format.md](docs/package-format.md) | Package validation rules |
| [docs/troubleshooting.md](docs/troubleshooting.md), [docs/backup.md](docs/backup.md), [docs/disaster-recovery.md](docs/disaster-recovery.md) | Support & continuity |
| [docs/development.md](docs/development.md) | Contributors |

API: `GET /api/docs` (Swagger UI, enabled in development; `SCARLET_API_DOCS_ENABLED` in production).

## Repository layout

```
app/            Flask application (config, models, repositories, services, ssh, runtimes,
                deployment engine, lifecycle, security, audit, tasks, api, web, templates, static)
migrations/     Alembic migrations (flask db upgrade)
tests/          unit · integration · security · e2e (149 tests, fake SSH host, eager Celery)
docker/         Dockerfile, nginx configs, entrypoint, mock Oracle Linux host
deployment/     production compose, Kubernetes manifests, Helm chart, systemd unit
examples/       podman-app · docker-app · kubernetes-app packages
scripts/        build-scarlet-package.py, backup.sh, restore.sh, fetch-vendor-assets.sh
docs/           documentation
```

## Commands

```
make dev / down / logs      compose stack            make test / lint / format / typecheck
make migrate / seed         database                 make package   build example packages
flask scarlet gen-key | create-admin | seed | sync-rbac | rotate-credentials | reconcile | cleanup | check-config | validate-package
```

## Licence

Internal / proprietary. Third-party components: Flask, SQLAlchemy, Celery, Paramiko, Pydantic,
AdminLTE 4.3.1, Bootstrap 5, Font Awesome Free, Chart.js (see their licences).
