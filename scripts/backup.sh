#!/usr/bin/env bash
# Podman Kubernetes Manager - create a backup now.
#
#   sudo ./backup.sh [--include-manifests] [--copy-to DIR]
#
# Creates /var/lib/pkm/backups/pkm-backup-<UTC>.tar.gz (+ .sha256) with the PKM database and
# configuration (and, with --include-manifests, a YAML export of the application resources:
# no Secrets, no volume data). This is NOT a Kubernetes cluster backup (see BACKUP.md).
# --copy-to DIR also copies the archive and its checksum to DIR (e.g. an NFS mount) and verifies the copy.

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$DIR/lib/common.sh" 2>/dev/null || . "$DIR/scripts/lib/common.sh"

ARGS=()
COPY_TO=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --include-manifests) ARGS+=(--include-manifests); shift ;;
    --copy-to) COPY_TO="$2"; shift 2 ;;
    -h|--help) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done
require_root
[[ -x "$PKM_CURRENT/venv/bin/pkm-admin" ]] || die "PKM is not installed"

OUT="$(runuser -u "$PKM_USER" -- env PKM_CONFIG="$PKM_CONFIG_FILE" "$PKM_CURRENT/venv/bin/pkm-admin" backup "${ARGS[@]}")" \
  || die "backup failed"
echo "$OUT"
FILE="$(sed -n 's/.*"file": "\(.*\)".*/\1/p' <<<"$OUT")"
ok "backup created: $FILE"

if [[ -n "$COPY_TO" ]]; then
  install -d -m 0700 "$COPY_TO"
  cp -p "$FILE" "$FILE.sha256" "$COPY_TO/"
  (cd "$COPY_TO" && sha256sum -c "$(basename "$FILE").sha256" >/dev/null) || die "the copy in $COPY_TO is corrupted"
  ok "copied and verified in $COPY_TO"
fi
