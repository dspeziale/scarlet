---
title: Take a backup
summary: How to save the Scarlet database and configuration, verify the backup and keep it safely.
category: procedures
order: 120
keywords: backup, pkm-admin, backup.sh, pkm-backup.timer, sqlite, manifest export, verify-backup
related: backup, proc-restore, proc-installare, faq
---

## When you need it

- Before upgrading Scarlet (`upgrade.sh` takes one anyway, but it is wise to have your own verified one).
- Before major changes to users, roles or settings.
- To check that the automatic nightly backup works.

First, be clear about **what** you are saving (details in [Backup](guide:backup)):

| Type | What it contains | Who does it |
|---|---|---|
| Scarlet application backup | SQLite DB `/var/lib/pkm/pkm.db` + Scarlet configuration | Scarlet |
| Kubernetes manifests export | YAML of resources; **not** PV data, **not** etcd | Scarlet |
| Cluster backup | etcd snapshot, Velero, volume backups | **not** Scarlet: cluster tools |

This procedure is about the **Scarlet application backup**.

## Prerequisites

- **Administrator** role in Scarlet, or `sudo` access to the server where Scarlet is installed.
- Enough free space in the data directory `/var/lib/pkm` (check the storage item in [Monitoring → Health](app:/monitoring/health)).
- A destination outside the server to copy backups to (a backup that lives only on the same disk does not protect against a disk failure).

## Procedure

1. **Check the configuration** in [Settings → Backup](app:/settings/backup): number of backups kept and manifest export. The automatic backup is run by the systemd timer `pkm-backup.timer` every day at 02:30 (random delay up to 15 minutes).
2. **Start a manual backup from the UI**: in [Operations → Backup](app:/operations/backup) start a new backup and wait for it to appear in the list with a successful result.
3. **Alternatively, from the shell** on the server:

   ```bash
   sudo pkm-admin backup
   ls -lh /var/lib/pkm/backups/
   ```

   Alternatively `sudo /opt/pkm/current/scripts/backup.sh [--include-manifests] [--copy-to DIR]`: with `--copy-to` it copies the archive and its `.sha256` to `DIR` (for example an NFS mount) and verifies the copy.
4. **Verify the backup** you just created (integrity and checksum check):

   ```bash
   sudo pkm-admin verify-backup /var/lib/pkm/backups/<file>
   ```

5. **Copy the backup off the server**, with `backup.sh --copy-to` or with `scp` or `rsync` to dedicated storage, keeping permissions restricted: the backup contains sensitive data (users, password hashes, configuration).
6. **(Optional) Include the Kubernetes manifests**: select the export option when starting the backup in [Operations → Backup](app:/operations/backup) (or use `--include-manifests`) to get a YAML copy of the application resources. It includes no Secrets, no volume data and no etcd state.
7. **Check the automatic timer**:

   ```bash
   systemctl list-timers pkm-backup.timer
   systemctl status pkm-backup.timer
   journalctl -u pkm-backup --since today
   ```

## Verification

- The backup appears in [Operations → Backup](app:/operations/backup) and in `/var/lib/pkm/backups`.
- `pkm-admin verify-backup` completes without errors.
- A copy exists on a system other than the Scarlet server.
- `systemctl list-timers` shows the next run of `pkm-backup.timer`.
- Periodically (for example every quarter) test a [restore](guide:proc-restore) in a test environment: a backup that has never been tested is not a reliable backup.

## If something goes wrong

- **Not enough disk space**: free space or reduce retention in [Settings → Backup](app:/settings/backup). The Health page reports Degraded when space runs low.
- **Permission denied**: run the commands with `sudo`; files are owned by the `pkm` system user.
- **`verify-backup` fails**: the file is incomplete or altered. Do not use it; create a new backup and check the logs in `/var/log/pkm/pkm.log` or with `journalctl -u pkm`.
- **The timer does not run**: enable it with `sudo systemctl enable --now pkm-backup.timer`.
- **You need a cluster backup**: Scarlet does not do that. Use etcd snapshots or a tool such as Velero, managed by the cluster administrator.
