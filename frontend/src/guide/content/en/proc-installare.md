---
title: Installing PKM on Oracle Linux 9.7
summary: Install Podman Kubernetes Manager on an Oracle Linux 9.7 x86_64 server and complete the first-run setup wizard.
category: procedures
order: 10
keywords: installation, install.sh, oracle linux, setup, token, systemd, tls, pkm-admin
related: introduzione, proc-collegare-kubernetes, proc-collegare-podman, proc-backup, faq
---

## When you need it

When you are putting PKM into service for the first time on a server, or reinstalling it on a new machine. To move to a newer version on a server where PKM is already installed you do not reinstall: use `upgrade.sh` (see the last section).

## Prerequisites

- An **Oracle Linux 9.7 x86_64** server with `sudo` access.
- Access to the AppStream repositories: the installer installs `python3.12` if missing.
- The release tarball `pkm-<version>-linux-x86_64.tar.gz`.
- The port you will use (default **8443/tcp**) reachable from the operators' browsers. If `firewalld` is active the installer opens it automatically (unless `--no-firewall`).
- Optional but recommended: a dedicated kubeconfig (see [Connecting Kubernetes](guide:proc-collegare-kubernetes)) and/or an active Podman socket (see [Connecting Podman](guide:proc-collegare-podman)). You can also configure them later, from the wizard or from [Settings](app:/settings/system).

## Procedure

1. Copy the tarball to the server and extract it:

   ```bash
   tar -xzf pkm-<version>-linux-x86_64.tar.gz
   cd pkm-<version>-linux-x86_64
   ```

2. Run the installer. In interactive mode it asks a few questions:

   ```bash
   sudo ./install.sh
   ```

   Useful options:

   | Option | Effect |
   |---|---|
   | `--port N` | listening port (default 8443; 8080 with `--no-tls`) |
   | `--bind ADDR` | listening address (default `0.0.0.0`) |
   | `--no-tls` | disables HTTPS (only behind a TLS reverse proxy) |
   | `--kubeconfig PATH` | kubeconfig copied to `/etc/pkm/kubeconfig` |
   | `--podman-socket URL` | Podman API socket (default `unix:///run/podman/podman.sock`, `none` to disable) |
   | `--podman-access` | gives the `pkm` group access to the **rootful** Podman socket (root-equivalent: see [Connecting Podman](guide:proc-collegare-podman)) |
   | `--no-firewall` | does not open the port in firewalld |
   | `--non-interactive` | no questions, uses defaults and the options passed |
   | `--force` | allows RHEL 9 compatible systems other than Oracle Linux |

3. The installer performs these steps:
   - creates the system user `pkm`;
   - installs the software into `/opt/pkm/releases/<version>` with the symlink `/opt/pkm/current`;
   - writes the configuration to `/etc/pkm/config.yaml` and secret variables to `/etc/pkm/pkm.env` (mode `0640 root:pkm`);
   - creates the data directory `/var/lib/pkm` (database `/var/lib/pkm/pkm.db`, backups in `/var/lib/pkm/backups`);
   - generates a self-signed certificate in `/etc/pkm/tls/` (if none exists yet);
   - installs and starts `pkm.service` and the backup timer `pkm-backup.timer`;
   - installs the admin command `pkm-admin`;
   - opens the port in firewalld if it is active;
   - waits until the service is ready and prints the summary (`Installation completed.`, URL, service, status, next step).

4. At the end, **write down the setup token** printed on screen. It is single-use. If you lose it, regenerate it with:

   ```bash
   sudo pkm-admin setup-token
   ```

5. If you used `--no-firewall` or use a firewall other than firewalld, open the port manually, for example:

   ```bash
   sudo firewall-cmd --permanent --add-port=8443/tcp
   sudo firewall-cmd --reload
   ```

6. Open a browser at `https://<host>:8443`. The certificate is self-signed, so the browser shows a warning: accept it only for the first access and replace the certificate as soon as possible.

7. Complete the setup wizard: **Benvenuto → Verifica sistema → Kubernetes → Podman → Autenticazione → Monitoraggio → Backup → TLS → Riepilogo → Test connessione → Completato**. In the Verifica sistema step enter the token; in the Autenticazione step you create the first **Administrator** user. Optional components (Podman, Prometheus) do not block completion.

8. Replace the self-signed certificate with one issued by your CA: copy certificate and key to `/etc/pkm/tls/pkm.crt` and `/etc/pkm/tls/pkm.key` (`0640 root:pkm` for the key), then restart: `sudo systemctl restart pkm`. The TLS step of the wizard shows the current state and these instructions.

## Verification

- Service running:

  ```bash
  systemctl status pkm
  systemctl list-timers pkm-backup.timer
  sudo pkm-admin check-config
  ```

- Logs without errors: `journalctl -u pkm -n 100` or `/var/log/pkm/pkm.log`.
- In the app, the [Health](app:/monitoring/health) page shows backend and database as **Healthy**; Kubernetes and Podman are Healthy if you configured them.
- The green **LIVE** badge with the cluster context appears at the top. The striped **DEMO** banner cannot appear in production: with `environment: production` the service refuses `mode: demo` at startup.

## If something goes wrong

- **The installer cannot find python3.12**: check that the AppStream repository is enabled (`dnf repolist`).
- **The service does not start**: read `journalctl -u pkm -e` and run `sudo pkm-admin check-config`; often it is a syntax error in `config.yaml` or wrong permissions on the kubeconfig or `pkm.env`.
- **The browser cannot reach the page**: check port and bind address (`ss -tlnp | grep 8443`) and the firewall.
- **Token lost or invalid**: `sudo pkm-admin setup-token` (works as long as no user exists).
- **Administrator password forgotten**: `sudo pkm-admin reset-password <user>`, or create a new administrator with `sudo pkm-admin create-admin`.
- **Future upgrades**: extract the new tarball and run `sudo ./upgrade.sh`. The script takes a backup, installs the new release, restarts (the database is migrated at startup), runs a health check and, on failure, automatically rolls back to the previous release restoring the database from the backup.
- **Uninstalling**: `sudo /opt/pkm/current/scripts/uninstall.sh` removes the software but keeps configuration, data and backups; with `--purge` it also deletes data and configuration. Take a [backup](guide:proc-backup) first.
