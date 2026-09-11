# Runtime: Docker

## Host prerequisites

- Docker Engine 24+ (`dnf install docker-ce` from the Docker repository, or Oracle's `docker-engine`).
- The SCARLET SSH user must be able to run `docker` without sudo: `usermod -aG docker scarlet`
  (rootful daemon) **or** rootless Docker (`dockerd-rootless-setuptool.sh install`, then
  `loginctl enable-linger scarlet`). Rootful membership of the `docker` group is equivalent to root
  on the host — prefer rootless or Podman.
- Registry access from the host for `image.pull_policy` `always`/`if-not-present`; `docker login`
  as the SSH user when authentication is required. Air-gapped hosts: ship `image.archive`.
- `docker compose` v2 plugin for compose-mode packages.

## How the adapter works (`DockerRuntimeAdapter`)

| Operation | Commands |
|---|---|
| detect | `command -v docker`, `docker version --format {{.Client.Version}}`, `id -u` |
| install | `docker load -i <release>/<archive>` or `docker image exists`/`docker pull image:tag`; compose: `docker compose … pull` |
| start | `docker run -d --name <app> --label scarlet.application=<app> --label scarlet.version=<v> --label scarlet.managed=true --env-file <shared>/config/scarlet.env --restart <policy> -p … -v … [--memory --cpus --user --read-only --stop-timeout] image:tag`; existing stopped container of the same version → `docker start`; different version → remove and recreate |
| stop | `docker stop <app>` (`ALREADY_STOPPED` if not running) |
| restart | `docker restart <app>` (same version) or recreate |
| status | `docker inspect --type container --format {{json .}} <app>` → state, labels, image, health |
| logs | `docker logs --timestamps --tail N [--since 10m] <app>` |
| health | http/https via `curl` on 127.0.0.1:<host port>, tcp via `nc -z`, command via `docker exec`, container_status via inspect |
| remove | `docker rm -f <app>` / `docker compose down --remove-orphans` |
| rollback | stop → install(previous) → start(previous) |

Containers are identified by name = application code; SCARLET labels carry the version used
for status/drift. Environment values pass only through the env file (never on the command line).

## Compose mode

`compose.file` in the manifest → `docker compose --project-name <app> --file <release>/docker-compose.yml
--env-file <shared>/config/scarlet.env up -d --remove-orphans`. The main service should use
`container_name: <application code>` so status/logs/health address it. `${SCARLET_VERSION}` and
other `SCARLET_*` variables are available in the compose file.

## Restart policies

`deployment.restart_policy` → `--restart always|unless-stopped|on-failure|no`. With the Docker
daemon enabled in systemd, containers restart after reboot according to the policy; SCARLET's
reconciler reports UNEXPECTED_STOP when a container is down while desired RUNNING.

## Known limitations

- Rootless Docker cannot bind ports < 1024 without `net.ipv4.ip_unprivileged_port_start`.
- SELinux volume relabelling (`:Z`) is not applied for Docker (Docker's SELinux support is
  optional); ensure the shared directories are readable by the container user or enable
  `--selinux-enabled` on the daemon and add `:Z` in a compose file.
