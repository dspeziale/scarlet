# Runtime: Podman (recommended on Oracle Linux)

## Host prerequisites

```bash
sudo dnf install -y podman podman-plugins fuse-overlayfs slirp4netns nmap-ncat curl tar gzip
sudo useradd -m scarlet
sudo loginctl enable-linger scarlet                 # keep user services/containers after logout
sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 scarlet   # if not set by useradd
```

Podman 4.x+ (Oracle Linux 9 ships 4.9/5.x; 8 ships 4.x). Rootless is the default and recommended
mode; SCARLET detects `rootless` via `podman info --format {{.Host.Security.Rootless}}` and shows
it on the host page.

### Rootless vs rootful

| | Rootless (recommended) | Rootful |
|---|---|---|
| Privileges | SSH user only, no sudo | daemon-less but containers run as root |
| Ports < 1024 | need `sysctl net.ipv4.ip_unprivileged_port_start=80` | allowed |
| Storage | `~/.local/share/containers` (watch disk usage) | `/var/lib/containers` |
| Restart after reboot | `loginctl enable-linger` + `--restart` policy; consider `podman generate systemd`/Quadlet | systemd units |
| SELinux | volumes relabelled with `:Z` by SCARLET | same |

SCARLET requires no `sudo`; if rootful Podman is chosen, run SSH as root **is not supported** —
use a user with membership that can reach the rootful socket only if your policy allows it.

## How the adapter works (`PodmanRuntimeAdapter`)

Identical command surface to Docker (see `runtime-docker.md`) with `podman` as binary and:
- volumes mounted with `:Z` (SELinux relabel) unless read-only;
- `podman image exists` for `pull_policy: if-not-present`;
- `podman load -i` for `image.archive` (air-gapped);
- compose mode uses `podman compose` (Podman 4.1+, needs `podman-compose` or docker-compose).

## Restart behaviour

`--restart unless-stopped|always` is honoured while the user session/linger is active. For
guaranteed restart after reboot generate a unit for the container
(`podman generate systemd --new --name customer-api`) or rely on SCARLET's reconciler with
auto-remediation on DEV. On PROD, prefer Quadlet units created by the platform team.

## Storage and cleanup

Images accumulate in the user's storage. `cleanup_remote_releases` prunes release directories but
not images; schedule `podman image prune -a --filter until=168h` on the host or run it after
rollbacks are no longer needed. Check `podman system df`.

## Logging

`podman logs --timestamps --tail N` (journald or file driver). SCARLET's mock host uses the
`file` events logger; production hosts can keep journald — `podman logs` works with both.

## Troubleshooting (see RUNBOOK §19)

`newuidmap` errors → subuid/subgid; containers vanish at logout → linger; `permission denied` on
volumes → ownership + `:Z`; `no space left` → prune; low ports → sysctl or ports ≥ 1024.
