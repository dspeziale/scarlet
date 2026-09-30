#!/usr/bin/env bash
# Login persistente al registry per l'utente deploy (una tantum per server).
#
#   sudo -u deploy ./registry-login.sh ghcr.io <utente-tecnico-github>
#
# Il token (PAT classic con SOLO scope read:packages, oppure token del machine user) viene letto
# da stdin o dal prompt: non passa mai come argomento (visibile in ps/history).
# Le credenziali finiscono in ~deploy/.docker/config.json (0600). Rotazione: docs/SECRETS.md.
set -euo pipefail
REGISTRY="${1:?registry (es. ghcr.io)}"
USER_NAME="${2:?utente tecnico}"
if [ -t 0 ]; then
  read -r -s -p "Token per ${USER_NAME}@${REGISTRY} (read:packages): " TOKEN; echo
else
  TOKEN="$(cat)"
fi
[ -n "$TOKEN" ] || { echo "token vuoto"; exit 1; }
umask 077
mkdir -p "$HOME/.docker"
printf '%s' "$TOKEN" | docker login "$REGISTRY" -u "$USER_NAME" --password-stdin
chmod 0600 "$HOME/.docker/config.json"
echo "Login salvato in $HOME/.docker/config.json (verifica: appctl doctor)"
