#!/usr/bin/env bash
# SCARLET restore from a backup directory produced by scripts/backup.sh.
# Usage: scripts/restore.sh /var/backups/scarlet/20260911-020000
# Prerequisites: the stack is running (postgres + scarlet-web), .env contains the SAME
# SCARLET_CREDENTIAL_ENCRYPTION_KEY that was active when the backup was taken.
set -euo pipefail

SRC="${1:?backup directory required}"
COMPOSE="${COMPOSE:-docker compose}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
ENV_FILE="${ENV_FILE:-.env}"

[ -f "$SRC/scarlet.pgdump" ] || { echo "missing $SRC/scarlet.pgdump"; exit 1; }
[ -f "$SRC/artifacts.tar.gz" ] || { echo "missing $SRC/artifacts.tar.gz"; exit 1; }
( cd "$SRC" && sha256sum -c SHA256SUMS ) || { echo "checksum verification failed"; exit 1; }

read -r -p "This will REPLACE the SCARLET database and artifacts. Type RESTORE to continue: " answer
[ "$answer" = "RESTORE" ] || { echo "aborted"; exit 1; }

echo "[restore] stopping web/worker/beat"
$COMPOSE -f "$COMPOSE_FILE" --env-file "$ENV_FILE" stop scarlet-web scarlet-worker scarlet-beat

echo "[restore] database"
$COMPOSE -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T postgres psql -U scarlet -d postgres -c "DROP DATABASE IF EXISTS scarlet;" -c "CREATE DATABASE scarlet OWNER scarlet;"
$COMPOSE -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T postgres pg_restore -U scarlet -d scarlet --no-owner --role=scarlet < "$SRC/scarlet.pgdump"

echo "[restore] artifacts"
$COMPOSE -f "$COMPOSE_FILE" --env-file "$ENV_FILE" run --rm --no-deps --entrypoint sh scarlet-web -c "rm -rf /data/scarlet/artifacts && tar -C /data/scarlet -xzf -" < "$SRC/artifacts.tar.gz"

echo "[restore] starting services (migrations run automatically)"
$COMPOSE -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d scarlet-web scarlet-worker scarlet-beat
echo "[restore] done. Verify with: flask scarlet check-config and a TEST CONNECTION on one host."
