---
title: Connecting Scarlet to Podman
summary: Enable the Podman API socket (rootful or rootless) and configure it in Scarlet, aware of the security implications.
category: procedures
order: 30
keywords: podman, socket, podman.socket, rootful, rootless, libpod, api, security
related: cos-e-podman, container, proc-installare, proc-diagnosticare-pod, faq
---

## When you need it

When you want to manage the host's Podman containers from Scarlet (**Container** section: Container, Immagini, Registry), during the **Podman** step of the wizard, or if Podman is **Unhealthy** on the [Health](app:/monitoring/health) page.

## Prerequisites

- Scarlet installed.
- Podman installed on the host (`podman --version`).
- A decision on **which** Podman to manage:
  - **rootful**: containers started by root, socket `/run/podman/podman.sock`;
  - **rootless**: containers of a specific user, socket `/run/user/<uid>/podman/podman.sock`.

> **Security warning.** Anyone who can write to the rootful socket can start privileged containers and mount the host filesystem: that access is effectively **root on the machine**. Giving the `pkm` group access to the socket means a compromise of Scarlet is a compromise of the host. Protect Scarlet accordingly (TLS, strong passwords, least-privilege roles) or prefer rootless mode.

## Procedure

### Option A: rootful Podman

1. Enable the API socket:

   ```bash
   sudo systemctl enable --now podman.socket
   ```

2. Grant access to the `pkm` group by re-running the installer with the explicit option (it is never done without consent, because of the risk described above): `sudo ./install.sh --podman-access` (from the release tarball; installation is idempotent). The installer adds the drop-in `/etc/systemd/system/podman.socket.d/10-pkm.conf` (`SocketGroup=pkm`, `SocketMode=0660`) and enables `podman.socket`. Check that it is in effect:

   ```bash
   systemctl cat podman.socket
   ls -l /run/podman/podman.sock   # expected: srw-rw---- root pkm
   ```

   If you enabled the socket after installation, reload: `sudo systemctl daemon-reload && sudo systemctl restart podman.socket`.

3. In [Settings → Podman](app:/settings/podman) set the URL `unix:///run/podman/podman.sock` (the default), save and check the connection status.

### Option B: rootless Podman

1. For the user owning the containers (e.g. `appuser`) enable the user socket and "linger", so the socket stays up without an open session:

   ```bash
   sudo loginctl enable-linger appuser
   sudo -u appuser XDG_RUNTIME_DIR=/run/user/$(id -u appuser) \
     systemctl --user enable --now podman.socket
   ```

2. The socket will be `/run/user/<uid>/podman/podman.sock`. By default only that user can access it: the `pkm` user must be able to reach it (permissions on the directory and the socket). Think carefully: the access grants full control over that user's containers, not over the host.

3. In [Settings → Podman](app:/settings/podman) set the URL `unix:///run/user/<uid>/podman/podman.sock` and check the connection.

## Verification

- From the server, with Scarlet's identity:

  ```bash
  sudo -u pkm curl -s --unix-socket /run/podman/podman.sock http://d/v4.0.0/libpod/_ping
  # expected: OK
  ```

- On [Health](app:/monitoring/health) Podman is **Healthy**.
- [Container](app:/podman/containers) shows the same containers as `sudo podman ps -a` (rootful) or `podman ps -a` run by the user (rootless).

## If something goes wrong

- **`permission denied` on the socket**: the `pkm` user is not in the right group or the drop-in is not applied. Check `ls -l` of the socket and `id pkm`.
- **Socket does not exist**: the service is not active; `systemctl status podman.socket` (or `systemctl --user` for rootless).
- **The container list is empty but containers exist**: you are probably looking at the wrong instance. Rootful and rootless containers are completely separate.
- **The rootless socket disappears on logout**: `loginctl enable-linger` is missing.
- **You want to revoke access**: disable Podman in Settings → Podman, delete `/etc/systemd/system/podman.socket.d/10-pkm.conf`, then `systemctl daemon-reload && systemctl restart podman.socket`.
