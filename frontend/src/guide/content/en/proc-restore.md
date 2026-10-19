---
title: Restore from a backup
summary: How to bring PKM back to a previously saved state with restore.sh (verify, stop the service, restore, restart).
category: procedures
order: 130
keywords: restore, restore.sh, pkm-admin restore, verify-backup, checksum, disaster recovery
related: backup, proc-backup, proc-installare, faq
---

## When you need it

- The PKM database is corrupted or PKM no longer starts after an error.
- A wrong change (deleted users, bad settings) must be undone.
- You have to rebuild PKM on a new server after losing the original one.

> Restore covers **PKM only** (database and configuration). It does not restore Kubernetes resources, Persistent Volume data or etcd. Those require the cluster backup tools: see [Backup](guide:backup).

## Prerequisites

- `sudo` access to the PKM server.
- The backup file to restore, already verified or verifiable.
- The `restore.sh` script, installed as `/opt/pkm/current/scripts/restore.sh` (it is also in the release tarball).
- A maintenance window: PKM is unavailable during the restore. Workloads in the cluster are **not** affected.
- If you restore on a new server: PKM already installed with `install.sh`, preferably the **same version** as the backup or a newer one.

## Procedure

1. **Notify users** that PKM will be unavailable for a few minutes.
2. **Back up the current state**, even if it is broken: it lets you go back if the restore turns out to be the wrong one.

   ```bash
   sudo pkm-admin backup
   ```

3. **Verify the file to restore.** If it comes from another system, copy it into `/var/lib/pkm/backups/` first.

   ```bash
   sudo pkm-admin verify-backup /var/lib/pkm/backups/<file>
   ```

4. **Run the restore**:

   ```bash
   sudo /opt/pkm/current/scripts/restore.sh /var/lib/pkm/backups/<file>                # database only
   sudo /opt/pkm/current/scripts/restore.sh /var/lib/pkm/backups/<file> --with-config  # also config.yaml and pkm.env
   ```

   The script verifies the archive (if verification fails it stops without changing anything), asks for confirmation (unless `--yes`), stops `pkm.service`, keeps the current database as `pkm.db.pre-restore-<date>` (and with `--with-config` `.pre-restore` copies of the configuration files), restores, fixes ownership and SELinux contexts and starts the service, waiting until it is ready. `pkm-admin restore` only performs the core step and requires the service to be already stopped: always use `restore.sh`.
5. **Check the restored configuration**:

   ```bash
   sudo pkm-admin check-config
   systemctl status pkm
   ```

6. **Recheck external references.** With `--with-config` the backup also restores the `kubeconfig` and TLS files found in `/etc/pkm`; files referenced with paths outside `/etc/pkm` and the Podman socket access must instead exist and be readable by the `pkm` user on the server.
7. **Log in to the UI** and open [Monitoring → Health](app:/monitoring/health).

## Verification

- `systemctl status pkm` shows the service `active (running)`.
- The [Health](app:/monitoring/health) page shows backend, database, Kubernetes and Podman as Healthy.
- Users can log in with the credentials valid at the time of the backup.
- Settings in [Settings](app:/settings/system) match the expected ones.
- The [Audit Log](app:/security/audit) can be consulted (it contains events up to the backup date).

## If something goes wrong

- **Invalid checksum**: `restore.sh` stops without changing anything. Use another backup, for example the copy kept off the server.
- **The service does not start**: read `journalctl -u pkm -n 200` and `/var/log/pkm/pkm.log`. If the error concerns the database version, install the same PKM version that produced the backup or a newer one (upgrading migrates the database).
- **Kubernetes Unhealthy after the restore**: the kubeconfig referenced in the configuration does not exist on the server or is not readable by the `pkm` user (recommended permissions 0640 root:pkm).
- **Forgotten password after the restore**: `sudo pkm-admin reset-password <user>`.
- **You want to go back to the previous state**: restore the backup taken in step 2, or (with the service stopped) put back `/var/lib/pkm/pkm.db.pre-restore-<date>` owned by `pkm:pkm`.
