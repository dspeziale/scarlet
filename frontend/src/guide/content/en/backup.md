---
title: Backup
summary: What the Scarlet backup saves, what the manifests export contains, and why neither replaces a real cluster backup.
category: reliability
order: 90
keywords: backup, restore, etcd, velero, manifests export, sqlite, pkm-admin
related: proc-backup, proc-restore, persistent-volume, cluster, alta-disponibilita
---

## In simple terms

When we talk about "backup" in this application there are **three different things**, and it is important not to confuse them:

| Type | What it contains | Who does it |
|---|---|---|
| **Scarlet backup** | The console database and configuration (users, roles, audit, settings) | Scarlet |
| **Kubernetes manifests export** | The YAML of resources (Deployments, Services, ConfigMaps...) | Scarlet, on request |
| **Cluster backup** | The full cluster state (etcd) and volume data | Dedicated tools (etcd snapshot, Velero), **not** Scarlet |

The Scarlet backup protects the console, not your applications. The manifests export helps recreate resources, but **does not contain data**. To truly protect the cluster you need a dedicated solution.

## Technical details

**1. Scarlet application backup**
- It contains the SQLite database `/var/lib/pkm/pkm.db` and the configuration files found in `/etc/pkm`: `config.yaml`, `pkm.env`, `kubeconfig` and the TLS certificate/key (`tls/`). It is written to `/var/lib/pkm/backups` (mode 0600, it contains secrets) with a SHA-256 checksum for integrity checks.
- It runs periodically through the systemd timer `pkm-backup.timer`, or manually with `pkm-admin backup` or `backup.sh`, or from [Operazioni → Backup](app:/operations/backup). The timer runs a backup every day at 02:30 (with a random delay of up to 15 minutes); [Impostazioni → Backup](app:/settings/backup) sets how many backups are kept and the manifest export.
- It is restored with `sudo /opt/pkm/current/scripts/restore.sh <file>`: the archive is verified, the service stopped, the database (and with `--with-config` the configuration) restored and the service started again.
- The file contains sensitive configuration: store it with restrictive permissions and also copy it off the server.

**2. Kubernetes manifests export**
- It is an archive of YAML files for the selected resources, read from the API server.
- It does **not** contain Persistent Volume data (files, application databases), it is **not** an etcd snapshot, and it does **not** include runtime state (Pods, events) in a re-applicable form.
- Secrets are **never** exported; system namespaces (`kube-system`, `kube-public`, `kube-node-lease`) are excluded too.
- Useful for audit, comparing environments, recreating resources deleted by mistake. Generated fields (`status`, `metadata.uid`, `resourceVersion`, `managedFields`, the `clusterIP` of Services) are already removed by the export.

**3. Real cluster backup (not done by Scarlet)**
- **etcd snapshot** (`etcdctl snapshot save`): saves all cluster objects; it runs on control plane nodes and is the responsibility of whoever administers the cluster.
- **Velero** or similar tools: save resources per namespace and volume data (CSI snapshots or file copy) to external storage.
- Application databases: also use their native tools (dump, replication).

## Example

```bash
# Manual Scarlet backup and verification
sudo pkm-admin backup
sudo pkm-admin verify-backup /var/lib/pkm/backups/<file>
systemctl list-timers pkm-backup.timer

# Example of a cluster backup (outside Scarlet, on the control plane)
sudo ETCDCTL_API=3 etcdctl snapshot save /backup/etcd-$(date +%F).db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key
```

etcd certificate paths depend on the Kubernetes distribution in use.

## What can go wrong

- **Believing you have a cluster backup** while having only the Scarlet backup or the manifests export.
- **Local-only backups**: if the Scarlet server disk fails, the backups in `/var/lib/pkm/backups` are lost too.
- **Full disk**: backups fail; the Health page reports free space of the data directory.
- **Never-tested backups**: a restore that was never tested is not a reliable backup.
- **Export re-applied without cleanup**: conflict errors or immutable field errors.

## How to verify

- [Operazioni → Backup](app:/operations/backup) shows the latest backups and their outcome.
- [Monitoraggio → Health](app:/monitoring/health) reports storage and database problems.
- `pkm-admin verify-backup <file>` checks the integrity of an archive.
- Periodically run a test restore on a test server.

## How to fix

1. Check retention in [Impostazioni → Backup](app:/settings/backup) and copy the files to external storage (`backup.sh --copy-to`).
2. Follow [Run a backup](guide:proc-backup) and [Restore a backup](guide:proc-restore).
3. Agree with the cluster owners on etcd snapshots and a volume backup (e.g. Velero).
4. Free space or move old backups if the disk fills up.
