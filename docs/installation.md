# Installation on Oracle Linux (production)

Target: one central SCARLET server (Oracle Linux 8.8+/9.x, x86_64) running the stack with
**Podman** (rootful or rootless) via `podman compose`. Docker is equally supported; the commands
below use Podman.

## 1. System requirements

| Component | Minimum | Recommended |
|---|---|---|
| CPU / RAM | 2 vCPU / 4 GB | 4 vCPU / 8 GB |
| Disk | 40 GB | 100 GB+ (artifacts: several releases × package size), separate volume for `/var/lib/scarlet` |
| OS | Oracle Linux 8.8 or 9.x, SELinux enforcing | 9.x |
| Network | outbound SSH (22/tcp) to every target host; inbound 443/tcp from operators | |
| Optional | outbound SMTP for e-mail notifications; access to container registries for the **targets** (not SCARLET) | |

## 2. Install Podman and compose

```bash
sudo dnf -y install podman podman-compose git tar policycoreutils-python-utils firewalld
podman --version            # 4.x+
podman compose version      # uses podman-compose (or docker-compose if installed)
```

Rootless operation is possible (run the stack as a dedicated user with lingering enabled); the
examples below use a system user with rootful Podman for simplicity of systemd integration.

## 3. Create directories and user

```bash
sudo useradd -r -m -d /opt/scarlet-server -s /bin/bash scarlet
sudo mkdir -p /var/lib/scarlet/{postgres,redis,data,nginx-logs} /opt/scarlet-server/tls
sudo chown -R scarlet:scarlet /opt/scarlet-server /var/lib/scarlet
```

Copy the repository (or the release tarball) into `/opt/scarlet-server`.

## 4. Configuration

```bash
cd /opt/scarlet-server
cp .env.example .env && chmod 600 .env
# generate secrets (two DIFFERENT keys)
podman run --rm scarlet:1.0.0 flask scarlet gen-key   # -> SCARLET_SECRET_KEY
podman run --rm scarlet:1.0.0 flask scarlet gen-key   # -> SCARLET_CREDENTIAL_ENCRYPTION_KEY
```

Mandatory in `.env`: `SCARLET_ENV=production`, `SCARLET_SECRET_KEY`,
`SCARLET_CREDENTIAL_ENCRYPTION_KEY`, `POSTGRES_PASSWORD`, `SCARLET_INITIAL_ADMIN_PASSWORD`
(remove it after the first start), `SESSION_COOKIE_SECURE=true`. **Store the two keys in the
company vault**: without `SCARLET_CREDENTIAL_ENCRYPTION_KEY` a database backup cannot decrypt
SSH credentials or secrets.

## 5. Build or pull the image

```bash
podman build -f docker/Dockerfile -t scarlet:1.0.0 .      # or pull from your internal registry
```

## 6. Database and Redis

Provided by the compose stack (PostgreSQL 16, Redis 7, persistent volumes). To use an external
PostgreSQL set `DATABASE_URL=postgresql://user:pass@dbhost:5432/scarlet` and remove the
`postgres` service. Requirements: PostgreSQL 13+, database owner role, `md5`/`scram` auth, TLS
recommended (`?sslmode=require`). Redis 6+ with persistence (`appendonly yes`) and no eviction
(`maxmemory-policy noeviction`) — it is the Celery broker.

## 7. Filesystem permissions and SELinux

Use bind mounts for persistent data with the `:Z` label so Podman relabels them for the containers,
or keep named volumes (default compose files). Example bind-mount override
(`deployment/docker-compose.override.yml`):

```yaml
services:
  postgres:   { volumes: ["/var/lib/scarlet/postgres:/var/lib/postgresql/data:Z"] }
  scarlet-web: { volumes: ["/var/lib/scarlet/data:/data/scarlet:Z"] }
  scarlet-worker: { volumes: ["/var/lib/scarlet/data:/data/scarlet:Z"] }
```

Do **not** set SELinux to permissive. If a denial appears (`ausearch -m avc -ts recent`), fix the
label (`semanage fcontext -a -t container_file_t '/var/lib/scarlet(/.*)?' && restorecon -Rv
/var/lib/scarlet`) or use `:Z`. The SCARLET container runs as UID 10001 with a read-only root
filesystem; `/tmp` is a tmpfs volume.

## 8. Firewall

```bash
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --permanent --add-service=http      # only for the HTTPS redirect
sudo firewall-cmd --reload
```
Outbound: 22/tcp (or the configured SSH port) to targets; 587/tcp to SMTP if enabled. Targets must
allow inbound SSH from the SCARLET server only.

## 9. TLS

Place the certificate chain and key in `/opt/scarlet-server/tls/scarlet.crt|scarlet.key`
(0600, owned by the compose user). Copy `docker/nginx-tls.conf.example` to
`/opt/scarlet-server/nginx-tls.conf` and set `server_name`.

- **Internal CA**: issue a server certificate for the SCARLET FQDN; distribute the CA to operator
  browsers. Include intermediates in `scarlet.crt`.
- **Let's Encrypt** (if the host is reachable): use certbot in standalone mode on 80/tcp before
  starting nginx, then mount `/etc/letsencrypt/live/<fqdn>/fullchain.pem` and `privkey.pem`;
  reload nginx after renewal (`podman compose exec nginx nginx -s reload`).

SCARLET never serves plain HTTP in production: nginx redirects 80 → 443 and `SESSION_COOKIE_SECURE`
is enforced.

## 10. Start with systemd

```bash
sudo cp deployment/systemd/scarlet.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now scarlet
sudo systemctl status scarlet
podman compose -f deployment/docker-compose.yml --env-file .env ps
```

The web container applies migrations and creates the `admin` user (password from
`SCARLET_INITIAL_ADMIN_PASSWORD`, forced change at first login). Verify:

```bash
curl -k https://scarlet.example.internal/api/ready
podman compose -f deployment/docker-compose.yml --env-file .env exec scarlet-web flask scarlet check-config
```

## 11. Reverse proxy notes

Gunicorn trusts one proxy (`SCARLET_TRUSTED_PROXIES=1`) for `X-Forwarded-*`. If another load
balancer sits in front of nginx, raise the value. `client_max_body_size` in nginx must be ≥
`SCARLET_MAX_UPLOAD_MB`.

## 12. Log rotation

Container logs use the json-file driver with rotation (`max-size 50m`, `max-file 5`) in the
production compose file. Nginx logs live in the `nginx-logs` volume; rotate with `logrotate`
(`copytruncate`). Application data retention (operation logs, health checks) is configured in
**System → Settings**.

## 13. Backup

See `docs/backup.md`; schedule `scripts/backup.sh` via cron/systemd timer nightly.

## 14. Offline / air-gapped installations

Run `scripts/fetch-vendor-assets.sh` on a connected machine, commit/ship `app/static/vendor`,
set `SCARLET_ASSET_MODE=local`. Pre-pull `postgres:16-alpine`, `redis:7-alpine`, `nginx:1.27-alpine`
and the SCARLET image into the internal registry.

## 15. Upgrade procedure

1. Backup (`scripts/backup.sh`).
2. Pull/build the new image, update `SCARLET_IMAGE` in `.env`.
3. `systemctl restart scarlet` — migrations run automatically (`flask db upgrade`); never drop
   the database.
4. Verify `/api/ready`, log in, run a Test connection on one host.
