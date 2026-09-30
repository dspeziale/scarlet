#!/usr/bin/env bash
# Installa (o aggiorna) appctl in /opt/appctl e i comandi in /usr/local/bin. Eseguire come root.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$(cd "$HERE/../appctl" && pwd)"
DEST="${APPCTL_DEST:-/opt/appctl}"

[ "$(id -u)" -eq 0 ] || { echo "eseguire come root (sudo)"; exit 1; }
command -v python3 > /dev/null || { echo "python3 richiesto (apt install python3 / dnf install python3)"; exit 1; }
PYV="$(python3 -c 'import sys; print(sys.version_info >= (3, 10))')"
[ "$PYV" = "True" ] || { echo "python3 >= 3.10 richiesto"; exit 1; }

install -d -m 0755 "$DEST"
rm -rf "$DEST/appctl"
cp -r "$SRC/appctl" "$DEST/appctl"
find "$DEST" -name '__pycache__' -type d -prune -exec rm -rf {} +
chown -R root:root "$DEST"
chmod -R a+rX "$DEST"

install -m 0755 "$HERE/bin/appctl" /usr/local/bin/appctl
install -m 0755 "$HERE/bin/appctl-ssh-gate" /usr/local/bin/appctl-ssh-gate
sed -i "s|^APPCTL_HOME=.*|APPCTL_HOME=\"$DEST\"|" /usr/local/bin/appctl

echo "appctl installato: $(PYTHONPATH="$DEST" python3 -m appctl --version)"
