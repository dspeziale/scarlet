#!/usr/bin/env bash
# Podman Kubernetes Manager - upgrade to the release this script belongs to.
#
#   sudo ./upgrade.sh [--yes] [--keep N]
#
# Steps: pre-upgrade backup -> install the new release next to the current one -> switch
# /opt/pkm/current -> restart (database migrations run at startup) -> health check.
# If the new version does not become ready, the previous release AND the pre-upgrade
# database are restored automatically (migrations are forward-only).
# --keep N   number of old releases kept in /opt/pkm/releases (default 2)

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$DIR/lib/common.sh" 2>/dev/null || . "$DIR/scripts/lib/common.sh"

YES=no
KEEP=2
while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y) YES=yes; shift ;;
    --keep) KEEP="$2"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done
require_root
ROOT="$(cd "$DIR" && { [[ -f VERSION ]] && pwd || (cd .. && pwd); })"
NEW="$(release_version "$ROOT")"
[[ -L "$PKM_CURRENT" ]] || die "PKM is not installed (no $PKM_CURRENT): use install.sh"
OLD_DIR="$(readlink -f "$PKM_CURRENT")"
OLD="$(basename "$OLD_DIR")"
[[ "$OLD" != "$NEW" ]] || die "version $NEW is already installed"
log "upgrade $OLD -> $NEW"
if [[ "$YES" != yes && -t 0 ]]; then
  read -r -p "The service will be restarted (short interruption). Continue? [y/N] " a; [[ "$a" =~ ^[YySs] ]] || die "aborted"
fi

check_os yes
ensure_python

log "pre-upgrade backup"
BACKUP_JSON="$(runuser -u "$PKM_USER" -- env PKM_CONFIG="$PKM_CONFIG_FILE" "$OLD_DIR/venv/bin/pkm-admin" backup)" \
  || die "pre-upgrade backup failed: upgrade aborted, nothing was changed"
BACKUP_FILE="$(sed -n 's/.*"file": "\(.*\)".*/\1/p' <<<"$BACKUP_JSON")"
ok "backup: $BACKUP_FILE"

install_release "$ROOT" "$NEW" "$PKM_PY"
install_units "$ROOT"
install_wrapper
switch_current "$NEW"
systemctl restart pkm.service

log "health check"
if wait_ready 120; then
  ok "version $NEW is running"
else
  show_failure_hint
  warn "rolling back to $OLD"
  systemctl stop pkm.service || true
  ln -sfn "$OLD_DIR" "$PKM_CURRENT"
  rm -rf "${PKM_RELEASES:?}/$NEW"
  "$OLD_DIR/venv/bin/pkm-admin" --config "$PKM_CONFIG_FILE" restore "$BACKUP_FILE" --yes \
    || warn "database restore failed: restore it manually with restore.sh $BACKUP_FILE"
  chown "$PKM_USER:$PKM_GROUP" "$PKM_DATA"/pkm.db* 2>/dev/null || true
  install_units "$OLD_DIR"
  systemctl restart pkm.service
  if wait_ready 90; then
    die "upgrade failed: version $OLD restored and running (backup used: $BACKUP_FILE)"
  fi
  die "upgrade failed and the previous version does not start either: see journalctl -u pkm and TROUBLESHOOTING.md"
fi

# Keep only the most recent releases; the current one and the one we upgraded from (rollback target)
# are always kept.
mapfile -t OLD_RELEASES < <(ls -1dt "$PKM_RELEASES"/*/ 2>/dev/null | tail -n +"$((KEEP + 1))")
for r in "${OLD_RELEASES[@]}"; do
  r="$(readlink -f "$r")"
  [[ "$r" == "$(readlink -f "$PKM_CURRENT")" || "$r" == "$OLD_DIR" ]] && continue
  rm -rf "$r"
  log "removed old release $(basename "$r")"
done

cat <<EOF

${C_BLD}Upgrade completed.${C_OFF}

Application:  Podman Kubernetes Manager $NEW (previous: $OLD, kept in $PKM_RELEASES)
URL:          $(service_url)
Service:      pkm.service
Status:       $(systemctl is-active pkm.service)
Backup:       $BACKUP_FILE
EOF
