#!/usr/bin/env bash
# SCARLET backup: PostgreSQL dump + artifact archive + configuration copy.
# Usage: scripts/backup.sh [/backup/target/dir]   (run from the stack directory containing .env)
# The encryption key (SCARLET_CREDENTIAL_ENCRYPTION_KEY) is NOT included: back it up separately in a vault.
set -euo pipefail

TARGET="${1:-/var/backups/scarlet}"
STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="${TARGET}/${STAMP}"
COMPOSE="${COMPOSE:-docker compose}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
ENV_FILE="${ENV_FILE:-.env}"

mkdir -p "$DEST"
chmod 700 "$DEST"
echo "[backup] destination: $DEST"

echo "[backup] postgres dump"
$COMPOSE -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T postgres pg_dump -U scarlet -d scarlet --format=custom --compress=6 > "$DEST/scarlet.pgdump"

echo "[backup] artifacts"
$COMPOSE -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T scarlet-web tar -C /data/scarlet -czf - artifacts > "$DEST/artifacts.tar.gz"

echo "[backup] configuration (secrets are redacted: keep the real .env in your vault)"
sed -E 's/^(SCARLET_SECRET_KEY|SCARLET_CREDENTIAL_ENCRYPTION_KEY[A-Z_]*|POSTGRES_PASSWORD|SCARLET_MAIL_PASSWORD|SCARLET_INITIAL_ADMIN_PASSWORD)=.*/\1=<redacted>/' "$ENV_FILE" > "$DEST/env.redacted"
cp "$COMPOSE_FILE" "$DEST/"
[ -f nginx-tls.conf ] && cp nginx-tls.conf "$DEST/"

( cd "$DEST" && sha256sum ./* > SHA256SUMS )
echo "[backup] done: $(du -sh "$DEST" | cut -f1)"

# retention: keep the last N backups (default 14)
KEEP="${BACKUP_KEEP:-14}"
ls -1d "${TARGET}"/*/ 2>/dev/null | sort | head -n -"$KEEP" | xargs -r rm -rf
