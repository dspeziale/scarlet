#!/usr/bin/env bash
# Installa la struttura di un'applicazione sul server (eseguire come root):
#
#   sudo ./install-app.sh <nome> <development|production> <image-repository> [porta]
#   es.: sudo ./install-app.sh scarlet production ghcr.io/dspeziale/scarlet 8080
#
# Crea /opt/apps/<nome>/ con app.conf (da template), config/, secrets/, data/, state/, logs/,
# l'audit log append-only in /var/log/apps/<nome>/ e abilita il timer di backup.
# Idempotente: non sovrascrive file esistenti (app.conf, app.env, secrets).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME="${1:?nome applicazione}"
ENVIRONMENT="${2:?development|production}"
IMAGE_REPO="${3:?image repository (es. ghcr.io/org/app)}"
PORT="${4:-8080}"
DEPLOY_USER="${DEPLOY_USER:-deploy}"
OPS_GROUP="${OPS_GROUP:-appops}"
APP_DIR="/opt/apps/${NAME}"
AUDIT_DIR="/var/log/apps/${NAME}"

[ "$(id -u)" -eq 0 ] || { echo "eseguire come root (sudo)"; exit 1; }
[[ "$NAME" =~ ^[a-z][a-z0-9-]{1,31}$ ]] || { echo "nome non valido: $NAME (minuscole, cifre, '-')"; exit 1; }
case "$ENVIRONMENT" in development|production) ;; *) echo "ambiente non valido: $ENVIRONMENT"; exit 1 ;; esac
id "$DEPLOY_USER" > /dev/null 2>&1 || { echo "utente $DEPLOY_USER assente: eseguire prima install-server.sh"; exit 1; }

echo "==> Struttura ${APP_DIR}"
install -d -m 0750 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$APP_DIR"
for d in config releases state logs data; do
  install -d -m 0750 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$APP_DIR/$d"
done
install -d -m 0700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$APP_DIR/secrets" "$APP_DIR/backups"
# PostgreSQL containerizzato (uid 999): directory dati dedicata
install -d -m 0700 -o 999 -g 999 "$APP_DIR/data/postgres"

if [ ! -f "$APP_DIR/app.conf" ]; then
  echo "==> app.conf da template (${ENVIRONMENT})"
  sed -e "s|@APP_NAME@|${NAME}|g" -e "s|@IMAGE_REPOSITORY@|${IMAGE_REPO}|g" -e "s|@APP_PORT@|${PORT}|g" \
    "$HERE/templates/app.conf.${ENVIRONMENT}" > "$APP_DIR/app.conf"
  chown "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR/app.conf"; chmod 0640 "$APP_DIR/app.conf"
else
  echo "==> app.conf esistente: non modificato"
fi

if [ ! -f "$APP_DIR/config/app.env" ]; then
  echo "==> config/app.env: creare dal file deploy/env/${ENVIRONMENT}.env del repository dell'applicazione"
  printf '# Configurazione non sensibile: copiare qui deploy/env/%s.env dal repository\n' "$ENVIRONMENT" > "$APP_DIR/config/app.env"
  chown "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR/config/app.env"; chmod 0640 "$APP_DIR/config/app.env"
fi

if [ ! -f "$APP_DIR/secrets/app.secrets.env" ]; then
  echo "==> secrets/app.secrets.env: generato con valori casuali (rivedere SCARLET_DATABASE_URL se DB esterno)"
  PW="$(openssl rand -hex 24 2>/dev/null || python3 -c 'import secrets; print(secrets.token_hex(24))')"
  TOKEN="$(openssl rand -hex 32 2>/dev/null || python3 -c 'import secrets; print(secrets.token_hex(32))')"
  umask 077
  cat > "$APP_DIR/secrets/app.secrets.env" <<EOF
# Secrets di ${NAME} (${ENVIRONMENT}). Mai versionare, mai copiare in chat/ticket. Permessi 0600.
POSTGRES_USER=${NAME//-/_}
POSTGRES_PASSWORD=${PW}
POSTGRES_DB=${NAME//-/_}
SCARLET_DATABASE_URL=postgresql+psycopg://${NAME//-/_}:${PW}@db:5432/${NAME//-/_}
SCARLET_API_TOKEN=${TOKEN}
EOF
  chown "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR/secrets/app.secrets.env"; chmod 0600 "$APP_DIR/secrets/app.secrets.env"
fi

echo "==> Audit log append-only ${AUDIT_DIR}/audit.log"
install -d -m 0750 -o root -g "$OPS_GROUP" "$AUDIT_DIR"
touch "$AUDIT_DIR/audit.log"
chown root:"$OPS_GROUP" "$AUDIT_DIR/audit.log"
# scrivibile da deploy (append) e leggibile dagli operatori
setfacl -m "u:${DEPLOY_USER}:rw" "$AUDIT_DIR/audit.log" 2>/dev/null || chown "$DEPLOY_USER":"$OPS_GROUP" "$AUDIT_DIR/audit.log"
chmod 0640 "$AUDIT_DIR/audit.log"
chattr +a "$AUDIT_DIR/audit.log" 2>/dev/null || echo "   (chattr +a non supportato su questo filesystem: audit log non append-only)"

echo "==> Timer di backup giornaliero"
systemctl enable --now "app-backup@${NAME}.timer" 2>/dev/null || echo "   (timer non abilitato: eseguire install-server.sh)"

cat <<EOF

Applicazione ${NAME} (${ENVIRONMENT}) pronta in ${APP_DIR}.
Prossimi passi:
  1. compilare ${APP_DIR}/config/app.env (da deploy/env/${ENVIRONMENT}.env del repository)
  2. verificare ${APP_DIR}/secrets/app.secrets.env
  3. login registry (una tantum): sudo -u ${DEPLOY_USER} ${HERE}/registry-login.sh $(echo "$IMAGE_REPO" | cut -d/ -f1) <utente-tecnico>
  4. primo deploy: appctl --app ${NAME} deploy <tag>
  5. verifica:     appctl --app ${NAME} status && appctl --app ${NAME} doctor
EOF
