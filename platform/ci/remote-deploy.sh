#!/usr/bin/env bash
# Esegue "appctl deploy|rollback" su un server via SSH e verifica l'esito (smoke test).
#
# Variabili richieste: DEPLOY_HOST, DEPLOY_SSH_KEY (chiave privata PEM), DEPLOY_SSH_HOST_KEY
#                      (riga known_hosts del server), ACTION (deploy|rollback), IMAGE_TAG
# Opzionali: DEPLOY_USER (deploy), DEPLOY_PORT (22), APP_NAME (scarlet), ACTOR, EXPECTED_COMMIT,
#            SSH_CONNECT_TIMEOUT (15), ENVIRONMENT (solo per i messaggi)
#
# Exit code: quelli di appctl (0-9) per gli errori remoti; 20 = SSH non raggiungibile/rifiutato;
#            21 = configurazione mancante; 22 = smoke test fallito (commit diverso dall'atteso).
set -euo pipefail

: "${DEPLOY_HOST:?DEPLOY_HOST mancante}"
: "${DEPLOY_SSH_KEY:?DEPLOY_SSH_KEY mancante}"
: "${DEPLOY_SSH_HOST_KEY:?DEPLOY_SSH_HOST_KEY mancante}"
: "${ACTION:?ACTION mancante (deploy|rollback)}"
: "${IMAGE_TAG:?IMAGE_TAG mancante}"
DEPLOY_USER="${DEPLOY_USER:-deploy}"
DEPLOY_PORT="${DEPLOY_PORT:-22}"
APP_NAME="${APP_NAME:-scarlet}"
ACTOR="${ACTOR:-github-actions}"
EXPECTED_COMMIT="${EXPECTED_COMMIT:-}"
SSH_CONNECT_TIMEOUT="${SSH_CONNECT_TIMEOUT:-15}"
ENVIRONMENT="${ENVIRONMENT:-?}"

case "$ACTION" in
  deploy|rollback) ;;
  *) echo "::error::ACTION non valida: $ACTION"; exit 21 ;;
esac
if ! [[ "$IMAGE_TAG" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]]; then
  echo "::error::IMAGE_TAG non valido: $IMAGE_TAG"; exit 21
fi
if ! [[ "$ACTOR" =~ ^[A-Za-z0-9:_.@-]{1,128}$ ]]; then
  ACTOR="github-actions"
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
umask 077
printf '%s\n' "$DEPLOY_SSH_KEY" > "$WORK/key"
printf '%s\n' "$DEPLOY_SSH_HOST_KEY" > "$WORK/known_hosts"

SSH=(ssh -i "$WORK/key" -p "$DEPLOY_PORT"
     -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$WORK/known_hosts"
     -o ConnectTimeout="$SSH_CONNECT_TIMEOUT" -o ServerAliveInterval=30 -o ServerAliveCountMax=4
     -o IdentitiesOnly=yes -o LogLevel=ERROR
     "${DEPLOY_USER}@${DEPLOY_HOST}")

remote() {
  # Il server accetta solo sottocomandi appctl (platform/server/bin/appctl-ssh-gate).
  "${SSH[@]}" "appctl --app ${APP_NAME} --actor ${ACTOR} $*"
}

echo "== Connessione a ${DEPLOY_USER}@${DEPLOY_HOST}:${DEPLOY_PORT} (${ENVIRONMENT})"
if ! "${SSH[@]}" "appctl --app ${APP_NAME} --version" > "$WORK/probe.txt" 2>&1; then
  echo "::error::SSH verso ${DEPLOY_HOST} fallito o comando rifiutato dal server:"
  sed 's/^/  /' "$WORK/probe.txt"
  echo "Verificare: raggiungibilita' di rete dal runner, chiave DEPLOY_SSH_KEY in authorized_keys di ${DEPLOY_USER}, DEPLOY_SSH_HOST_KEY, servizio sshd (docs/TROUBLESHOOTING.md)"
  exit 20
fi
echo "   server ok: $(cat "$WORK/probe.txt")"

echo "== ${ACTION} ${IMAGE_TAG} su ${ENVIRONMENT}"
set +e
if [ "$ACTION" = "rollback" ] && [ "$IMAGE_TAG" = "previous" ]; then
  remote rollback
else
  remote "$ACTION" "$IMAGE_TAG"
fi
RC=$?
set -e

echo "== Stato dopo l'operazione"
remote status | tee /tmp/appctl-status.txt || true

case "$RC" in
  0) echo "   ${ACTION} riuscito" ;;
  4) echo "::error::${ACTION} FALLITO: il server ha ripristinato automaticamente la versione precedente (exit 4)"; exit 4 ;;
  7) echo "::error::${ACTION} FALLITO e rollback fallito: APPLICAZIONE NON DISPONIBILE su ${ENVIRONMENT} (exit 7). Intervenire subito: docs/RUNBOOK.md"; exit 7 ;;
  *) echo "::error::${ACTION} terminato con exit code ${RC} (vedi docs/OPERATIONS.md § exit code)"; exit "$RC" ;;
esac

echo "== Smoke test"
if ! remote health --wait 30 > "$WORK/health.txt" 2>&1; then
  cat "$WORK/health.txt"
  echo "::error::smoke test fallito: applicazione non sana dopo il ${ACTION}"
  exit 22
fi
cat "$WORK/health.txt"

remote --json version > "$WORK/version.json"
RUNNING_COMMIT=$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(((d.get("running") or {}).get("commit")) or ((d.get("current") or {}).get("commit")) or "")' < "$WORK/version.json")
RUNNING_VERSION=$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(((d.get("running") or {}).get("version")) or "?")' < "$WORK/version.json")
echo "   in esecuzione: versione ${RUNNING_VERSION}, commit ${RUNNING_COMMIT}"
if [ -n "$EXPECTED_COMMIT" ] && [ "$ACTION" = "deploy" ]; then
  if [ "${EXPECTED_COMMIT:0:12}" != "${RUNNING_COMMIT:0:12}" ]; then
    echo "::error::smoke test fallito: commit in esecuzione ${RUNNING_COMMIT} diverso dall'atteso ${EXPECTED_COMMIT:0:12}"
    exit 22
  fi
  echo "   commit verificato: ${EXPECTED_COMMIT:0:12}"
fi
echo "== Completato"
