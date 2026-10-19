#!/usr/bin/env bash
# Podman Kubernetes Manager - uninstall.
#
#   sudo ./uninstall.sh            remove the application, KEEP configuration, data, backups and logs
#   sudo ./uninstall.sh --purge    also delete /etc/pkm, /var/lib/pkm (database AND backups), /var/log/pkm and the pkm user
#   options: --yes (no confirmation), --keep-firewall
#
# Nothing is ever removed from the Kubernetes cluster or from Podman.

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$DIR/lib/common.sh" 2>/dev/null || . "$DIR/scripts/lib/common.sh"

PURGE=no
YES=no
FIREWALL=yes
while [[ $# -gt 0 ]]; do
  case "$1" in
    --purge) PURGE=yes; shift ;;
    --yes|-y) YES=yes; shift ;;
    --keep-firewall) FIREWALL=no; shift ;;
    -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done
require_root

if [[ "$YES" != yes ]]; then
  if [[ "$PURGE" == yes ]]; then
    warn "--purge deletes the PKM database, ALL backups in $PKM_DATA/backups, the configuration and the logs."
    read -r -p "Type 'purge' to confirm: " a; [[ "$a" == purge ]] || die "aborted"
  else
    read -r -p "Remove Podman Kubernetes Manager (configuration and data are kept)? [y/N] " a; [[ "$a" =~ ^[YySs] ]] || die "aborted"
  fi
fi

PORT="$(config_value server port || true)"
log "stopping services"
systemctl disable --now pkm-backup.timer pkm.service >/dev/null 2>&1 || true
rm -f "$PKM_UNIT_DIR/pkm.service" "$PKM_UNIT_DIR/pkm-backup.service" "$PKM_UNIT_DIR/pkm-backup.timer"
if [[ -f /etc/systemd/system/podman.socket.d/10-pkm.conf ]]; then
  rm -f /etc/systemd/system/podman.socket.d/10-pkm.conf
  rmdir /etc/systemd/system/podman.socket.d 2>/dev/null || true
  systemctl daemon-reload
  systemctl restart podman.socket >/dev/null 2>&1 || true
  ok "Podman socket access for group pkm removed"
fi
systemctl daemon-reload
rm -f "$PKM_ADMIN_WRAPPER"
rm -rf "$PKM_HOME"
ok "application removed ($PKM_HOME)"

if [[ "$FIREWALL" == yes && -n "$PORT" ]] && systemctl is-active --quiet firewalld 2>/dev/null; then
  firewall-cmd --quiet --permanent --remove-port="$PORT/tcp" 2>/dev/null && firewall-cmd --quiet --reload && ok "firewalld: port $PORT/tcp closed" || true
fi

if [[ "$PURGE" == yes ]]; then
  rm -rf "$PKM_ETC" "$PKM_DATA" "$PKM_LOG"
  userdel "$PKM_USER" 2>/dev/null || true
  groupdel "$PKM_GROUP" 2>/dev/null || true
  ok "configuration, data, backups, logs and user removed"
else
  log "kept: $PKM_ETC (configuration), $PKM_DATA (database and backups), $PKM_LOG (logs), user $PKM_USER"
  log "a later ./install.sh reuses them; use --purge to delete them"
fi
ok "uninstall completed"
