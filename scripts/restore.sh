#!/usr/bin/env bash
# Scarlet - restore a backup archive.
#
#   sudo ./restore.sh /var/lib/pkm/backups/pkm-backup-<UTC>.tar.gz [--with-config] [--yes]
#
# 1. verifies the archive (SHA-256, file checksums, SQLite integrity) - aborts if anything is wrong
# 2. stops pkm.service
# 3. keeps the current database as pkm.db.pre-restore-<UTC> and restores the one in the archive
#    (--with-config also restores config.yaml, pkm.env, kubeconfig and tls/, keeping .pre-restore copies)
# 4. starts the service and waits until it is ready
# Kubernetes and Podman are not touched: the archive only contains Scarlet's own state.

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$DIR/lib/common.sh" 2>/dev/null || . "$DIR/scripts/lib/common.sh"

FILE=""
ARGS=()
YES=no
while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-config) ARGS+=(--with-config); shift ;;
    --yes|-y) YES=yes; shift ;;
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) die "unknown option: $1" ;;
    *) FILE="$1"; shift ;;
  esac
done
require_root
[[ -n "$FILE" ]] || die "usage: restore.sh <backup.tar.gz> [--with-config] [--yes]"
[[ -r "$FILE" ]] || die "file not readable: $FILE"
BIN="$PKM_CURRENT/venv/bin/pkm-admin"
[[ -x "$BIN" ]] || die "Scarlet is not installed"

log "verifying $FILE"
PKM_CONFIG="$PKM_CONFIG_FILE" "$BIN" verify-backup "$FILE" || die "verification failed: nothing was changed"
ok "archive verified"

if [[ "$YES" != yes ]]; then
  read -r -p "The service will be stopped and the current database replaced. Continue? [y/N] " a
  [[ "$a" =~ ^[YySs] ]] || die "aborted"
fi

log "stopping pkm.service"
systemctl stop pkm.service
trap 'warn "restore interrupted: starting the service again"; systemctl start pkm.service || true' ERR

PKM_CONFIG="$PKM_CONFIG_FILE" "$BIN" restore "$FILE" --yes "${ARGS[@]}"
chown "$PKM_USER:$PKM_GROUP" "$PKM_DATA"/pkm.db* 2>/dev/null || true
chmod 0640 "$PKM_DATA"/pkm.db 2>/dev/null || true
chown root:"$PKM_GROUP" "$PKM_ETC"/config.yaml "$PKM_ETC"/pkm.env "$PKM_ETC"/kubeconfig "$PKM_ETC"/tls/pkm.key "$PKM_ETC"/tls/pkm.crt 2>/dev/null || true
chmod 0640 "$PKM_ETC"/config.yaml "$PKM_ETC"/pkm.env "$PKM_ETC"/kubeconfig "$PKM_ETC"/tls/pkm.key 2>/dev/null || true
chmod 0644 "$PKM_ETC"/tls/pkm.crt 2>/dev/null || true
if command -v restorecon >/dev/null 2>&1; then restorecon -RF "$PKM_DATA" "$PKM_ETC" >/dev/null 2>&1 || true; fi
trap - ERR

log "starting pkm.service"
systemctl start pkm.service
if wait_ready 90; then
  ok "restore completed: the service is running ($(service_url))"
else
  show_failure_hint
  die "the service does not start after the restore: the previous database is in $PKM_DATA/pkm.db.pre-restore-*"
fi
