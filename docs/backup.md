# Backup

## What to back up

| Item | Contains | How |
|---|---|---|
| PostgreSQL database | hosts, encrypted credentials, applications, versions metadata, deployments, audit, configuration | `pg_dump --format=custom` (`scripts/backup.sh`) |
| Artifacts | release packages (`SCARLET_ARTIFACT_PATH`) | filesystem archive (`scripts/backup.sh`) |
| Configuration | `.env`, `nginx-tls.conf`, compose files, TLS material | copy to the vault / configuration management |
| **Encryption key** | `SCARLET_CREDENTIAL_ENCRYPTION_KEY` (and `SCARLET_SECRET_KEY`) | **separately**, in the company password vault / HSM — never next to the database dump |

Credentials and secrets in the database are useless without the encryption key, and the key alone
is useless without the database: store them in different places with different access controls.

## Schedule

Nightly full backup + before every SCARLET upgrade. Example systemd timer:

```ini
# /etc/systemd/system/scarlet-backup.service
[Service]
Type=oneshot
WorkingDirectory=/opt/scarlet-server
Environment=COMPOSE_FILE=deployment/docker-compose.yml
ExecStart=/opt/scarlet-server/scripts/backup.sh /var/backups/scarlet

# /etc/systemd/system/scarlet-backup.timer
[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true
[Install]
WantedBy=timers.target
```

`scripts/backup.sh` writes `<target>/<timestamp>/{scarlet.pgdump, artifacts.tar.gz, env.redacted,
compose file, nginx conf, SHA256SUMS}` and keeps the last `BACKUP_KEEP` (14) sets. Copy the
directory off-host (object storage, backup server) with encryption at rest.

## Consistency

`pg_dump` produces a consistent snapshot. Artifacts are immutable once released, so a filesystem
copy taken after the dump is consistent for every version referenced by the dump (versions released
in between are simply extra files). Avoid running the backup while a large upload is being promoted.

## Verification

Monthly: restore into a staging stack (`scripts/restore.sh`), log in, open a deployment detail,
run **Test connection** on one host (proves the encryption key matches), verify an artifact
checksum from the UI.

## Retention

Backups contain audit data: align retention with the audit policy (`SCARLET_AUDIT_RETENTION_DAYS`
defaults to never purge). Protect backup storage like production data (contains encrypted
credentials).

## Related

`disaster-recovery.md` for full restore procedures; RUNBOOK §27–§29.
