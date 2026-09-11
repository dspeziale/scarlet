# Disaster recovery

## Recovery objectives

SCARLET is a control plane: if it is down, **applications on the target hosts keep running**
(containers restart according to their runtime policy). Losing SCARLET means losing the ability to
deploy/roll back centrally and the audit history — not the applications. Typical objectives:
RPO = last nightly backup (24 h), RTO = 1–2 hours with the procedure below.

## Scenarios

### A. SCARLET server lost (hardware/VM failure)

1. Provision a new Oracle Linux server following `installation.md` §1–§9 (same FQDN or update DNS;
   operators' browsers must trust the TLS certificate).
2. Restore `.env` **from the vault** — the `SCARLET_CREDENTIAL_ENCRYPTION_KEY` must be identical to
   the one used when the backup was taken.
3. Start the stack (`systemctl start scarlet`), wait for `/api/ready`.
4. Run `scripts/restore.sh <latest backup dir>` (database + artifacts). Migrations run on restart.
5. Validate: log in, Hosts → any host → **Test connection** (proves credentials decrypt), open a
   recent deployment, check Monitoring → Health after one reconciliation cycle.
6. Target hosts need **no change**: their approved host keys and SSH users are in the database; the
   new server's outbound IP may need to be allowed in target firewalls / `from=` restrictions.

### B. Database corruption or accidental deletion

1. Stop web/worker/beat (`podman compose stop scarlet-web scarlet-worker scarlet-beat`).
2. `scripts/restore.sh <backup>` restores database and artifacts (type `RESTORE`).
3. Deployments performed between the backup and the failure are unknown to SCARLET: the next
   reconciliation reports **VERSION drift** for instances where the host runs a newer version than
   recorded. Resolve by redeploying the correct version (or uploading the newer package again and
   redeploying it).

### C. Artifact storage lost, database intact

1. Restore `artifacts.tar.gz` (`tar -C /data/scarlet -xzf`).
2. Versions whose artifact is missing fail *Validate package* and pre-flight (*Artifact not found*).
   Re-upload the original package from the team's release archive: the checksum must match the
   immutable version record; otherwise publish a new version.

### D. Encryption key lost

Credentials, kubeconfigs and configuration secrets cannot be decrypted. Generate a new key, set it
in `.env`, restart, then re-enter every SSH credential (RUNBOOK §2) and every SECRET configuration
entry. Host records, applications, versions, deployment history and audit remain intact. This is
why the key must be in the vault with tested access.

### E. Encryption key compromised

Rotate immediately: set the new key as `SCARLET_CREDENTIAL_ENCRYPTION_KEY`, the old as
`SCARLET_CREDENTIAL_ENCRYPTION_KEY_PREVIOUS`, restart, `flask scarlet rotate-credentials`, remove
the previous key, then rotate the underlying SSH keys and secrets themselves (RUNBOOK §29–§30):
re-encrypting does not undo exposure of the old plaintexts.

### F. Redis lost

Redis holds the Celery queue and locks only. Queued jobs are lost: deployments left QUEUED/RUNNING
should be cancelled or will time out; re-run them. Locks expire by TTL. No data loss.

### G. Target host rebuilt

The host's SSH key changes → **MISMATCH** (RUNBOOK §31). After verification approve the new key,
re-run Discover, and redeploy the desired versions (the reconciler shows MISSING drift for every
application that used to run there).

## Exercise

Run a DR test twice a year on a staging server: restore last night's backup, perform a DEV
deployment against a mock host, verify audit continuity. Record RTO/RPO achieved.

## Contacts and inventory

Keep with the DR plan: location of backups, vault entries (`SCARLET_SECRET_KEY`,
`SCARLET_CREDENTIAL_ENCRYPTION_KEY`, `POSTGRES_PASSWORD`, TLS key), list of target hosts with
approved fingerprints (export Hosts from the API), owners of each application.
