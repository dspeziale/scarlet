#!/usr/bin/env bash
# Registra la chiave pubblica della pipeline GitHub per l'utente deploy con forced command.
#
#   sudo ./add-deploy-key.sh "ssh-ed25519 AAAA... github-actions-scarlet"
#
# La chiave potra' eseguire SOLO i sottocomandi appctl ammessi da appctl-ssh-gate: niente shell,
# niente port forwarding, niente agent forwarding ("restrict").
set -euo pipefail
PUBKEY="${1:?chiave pubblica (ssh-ed25519 AAAA... commento)}"
DEPLOY_USER="${DEPLOY_USER:-deploy}"
AUTH="/home/${DEPLOY_USER}/.ssh/authorized_keys"

[ "$(id -u)" -eq 0 ] || { echo "eseguire come root (sudo)"; exit 1; }
[[ "$PUBKEY" =~ ^(ssh-ed25519|ecdsa-sha2-nistp256|ssh-rsa)\ [A-Za-z0-9+/=]+(\ .*)?$ ]] || { echo "chiave pubblica non valida"; exit 1; }
KEY_PART="$(echo "$PUBKEY" | awk '{print $1" "$2}')"
if grep -qF "$KEY_PART" "$AUTH" 2>/dev/null; then
  echo "chiave gia' presente in $AUTH"; exit 0
fi
echo "restrict,command=\"/usr/local/bin/appctl-ssh-gate\" ${PUBKEY}" >> "$AUTH"
chown "$DEPLOY_USER:$DEPLOY_USER" "$AUTH"; chmod 0600 "$AUTH"
echo "chiave registrata in $AUTH con forced command appctl-ssh-gate"
echo "Host key da inserire nel secret DEPLOY_SSH_HOST_KEY dell'environment GitHub:"
ssh-keyscan -t ed25519 -H localhost 2>/dev/null | sed 's/^/   /' || true
echo "   (sostituire 'localhost' con l'hostname/IP usato in DEPLOY_HOST: ssh-keyscan -t ed25519 <host>)"
