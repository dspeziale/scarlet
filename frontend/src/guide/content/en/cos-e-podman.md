---
title: What Podman is
summary: Oracle Linux's daemonless container engine, different from Kubernetes, with rootful and rootless modes and an API socket.
category: intro
order: 30
keywords: podman, container, rootless, rootful, socket, libpod, api, systemd
related: container, cos-e-kubernetes, proc-collegare-podman, introduzione
---

## In simple terms

Podman is a program that **runs containers on a single machine**. It is the standard container tool on Oracle Linux and RHEL, compatible with Docker commands (`podman run`, `podman ps`, `podman images`...).

The difference from Kubernetes is one of scale and responsibility:

| | Podman | Kubernetes |
|---|---|---|
| Scope | One host | A cluster of many nodes |
| Who decides where the container runs | You, on the chosen host | The scheduler |
| Automatic restart | With `--restart` or a systemd unit | Always, through controllers |
| Replicas, rolling updates, Services | No (not natively) | Yes |

In Scarlet the **Container** section (Container, Immagini, Registry) is about Podman; every other section is about Kubernetes.

## Technical details

**Daemonless.** Podman has no central always-on daemon like Docker: each command starts the container directly through `conmon` and an OCI runtime (`crun` or `runc`). To let external programs such as Scarlet talk to Podman, there is an optional **API service**, activated via systemd.

**Rootful and rootless.**

- **Rootful**: containers are managed by root. Storage lives in `/var/lib/containers/storage`, the API socket is `/run/podman/podman.sock`, activated by the system `podman.socket`.
- **Rootless**: containers belong to a regular user, isolated through user namespaces. Storage in `~/.local/share/containers/storage`, socket at `/run/user/<uid>/podman/podman.sock`, activated with `systemctl --user enable --now podman.socket` (you need `loginctl enable-linger <user>` for it to stay active without an open session). Each user sees only their own containers.

**The API socket.** Scarlet uses the **libpod REST API** exposed on the socket. The socket is activated by systemd (`podman.socket`), which starts `podman.service` on the first request.

> **Security warning:** anyone who can write to the rootful socket can start privileged containers and therefore effectively gain root privileges on the host. The Scarlet installer adds a drop-in with `SocketGroup=pkm` and `SocketMode=0660` to give the `pkm` group access: this gives Scarlet **root-equivalent** access. Protect the host, access to Scarlet and the Administrator role accordingly. If managing a single user's containers is enough, prefer the rootless socket.

## Example

Enable the rootful socket and check it (from a shell, as root):

```bash
systemctl enable --now podman.socket
ls -l /run/podman/podman.sock
curl --unix-socket /run/podman/podman.sock http://d/v4.0.0/libpod/_ping
```

Commands equivalent to the Scarlet pages:

```bash
podman ps -a                 # Container
podman images                # Immagini
podman logs --tail 100 web   # container logs
podman restart web
```

## What can go wrong

- **Socket inactive or missing**: Scarlet shows Podman as Unhealthy on the [Health](app:/monitoring/health) page.
- **Permission denied on the socket**: the `pkm` user is not in the right group or the drop-in was not applied (missing `systemctl daemon-reload`).
- **Rootless socket gone**: the user does not have linger enabled and has logged out.
- **Rootful and rootless containers mixed up**: a container created by a user does not appear on root's socket, and vice versa.

## How to verify

- [Impostazioni → Podman](app:/settings/podman): configured socket path and connection test.
- [Container](app:/podman/containers): you should see the host's container list.
- From a shell:

```bash
systemctl status podman.socket
systemctl cat podman.socket      # also shows the drop-in
sudo -u pkm curl --unix-socket /run/podman/podman.sock http://d/v4.0.0/libpod/_ping
```

## How to fix

- Inactive socket: `systemctl enable --now podman.socket` (rootful) or `systemctl --user enable --now podman.socket` for the rootless user.
- Permissions: after changing the drop-in run `systemctl daemon-reload` and `systemctl restart podman.socket`.
- Wrong path: fix it in [Impostazioni → Podman](app:/settings/podman).
- Full procedure: [Connecting Podman](guide:proc-collegare-podman).
