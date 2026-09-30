#!/usr/bin/env bash
# Prepara un server Linux nuovo per la piattaforma (eseguire come root, una sola volta).
#
#   sudo ./install-server.sh
#
# Cosa fa (idempotente: si puo' rieseguire):
#   1. installa Docker Engine + Compose plugin dal repository ufficiale Docker;
#   2. crea utente di sistema "deploy" (gruppo docker) e gruppo "appops" per gli operatori;
#   3. crea /opt/apps, /opt/platform, /var/log/apps con permessi corretti;
#   4. installa appctl (/opt/appctl + /usr/local/bin/appctl) e il gate SSH;
#   5. configura sudoers per appops -> deploy appctl;
#   6. crea la rete docker "proxy" e installa il reverse proxy Caddy (opzionale, PROXY=1 default);
#   7. installa le unit systemd per il backup;
#   8. hardening base: limiti log Docker (daemon.json), sshd senza password, ufw se presente.
#
# Distribuzioni supportate: Ubuntu 22.04/24.04, Debian 12 (apt); RHEL 9 / Oracle Linux 9 (dnf).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "$HERE/.." && pwd)"
DEPLOY_USER="${DEPLOY_USER:-deploy}"
OPS_GROUP="${OPS_GROUP:-appops}"
PROXY="${PROXY:-1}"
# HARDEN_SSH=0 per NON disabilitare l'autenticazione con password (server condivisi con login di dominio)
HARDEN_SSH="${HARDEN_SSH:-1}"
# Disco dati separato (es. /data): Docker e applicazioni vengono messi li', con symlink da /opt/apps
DOCKER_DATA_ROOT="${DOCKER_DATA_ROOT:-}"
APPS_DATA_DIR="${APPS_DATA_DIR:-}"

log() { printf '\n==> %s\n' "$*"; }
[ "$(id -u)" -eq 0 ] || { echo "eseguire come root (sudo)"; exit 1; }

# ---------------------------------------------------------------- 1. Docker
if command -v docker > /dev/null 2>&1 && docker compose version > /dev/null 2>&1; then
  log "Docker gia' installato: $(docker --version)"
else
  log "Installazione Docker Engine"
  if command -v apt-get > /dev/null; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -q
    apt-get install -y -q ca-certificates curl gnupg python3 openssh-server
    install -m 0755 -d /etc/apt/keyrings
    # shellcheck disable=SC1091
    . /etc/os-release
    curl -fsSL "https://download.docker.com/linux/${ID}/gpg" | gpg --dearmor -o /etc/apt/keyrings/docker.gpg --yes
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/${ID} ${VERSION_CODENAME} stable" \
      > /etc/apt/sources.list.d/docker.list
    apt-get update -q
    apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-compose-plugin
  elif command -v dnf > /dev/null; then
    dnf -y -q install dnf-plugins-core python3 openssh-server
    # Oracle Linux / RHEL spesso hanno il comando "docker" fornito da Podman: si rimuove solo lo shim.
    if rpm -q podman-docker > /dev/null 2>&1; then
      echo "   rimuovo lo shim podman-docker (Podman resta installato)"
      dnf -y -q remove podman-docker
    fi
    dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo
    dnf -y -q install docker-ce docker-ce-cli containerd.io docker-compose-plugin
  else
    echo "gestore pacchetti non supportato: installare Docker manualmente (https://docs.docker.com/engine/install/)"; exit 1
  fi
fi

log "Configurazione daemon Docker (log rotation di default, live-restore)"
install -d -m 0755 /etc/docker
if [ ! -f /etc/docker/daemon.json ]; then
  DATA_ROOT_LINE=""
  if [ -n "$DOCKER_DATA_ROOT" ]; then
    install -d -m 0710 "$DOCKER_DATA_ROOT"
    DATA_ROOT_LINE="  \"data-root\": \"${DOCKER_DATA_ROOT}\","
    echo "   data-root Docker: ${DOCKER_DATA_ROOT}"
  fi
  cat > /etc/docker/daemon.json <<EOF
{
${DATA_ROOT_LINE}
  "log-driver": "json-file",
  "log-opts": { "max-size": "20m", "max-file": "5" },
  "live-restore": true,
  "no-new-privileges": true
}
EOF
  python3 -c "import json; json.load(open('/etc/docker/daemon.json'))"
else
  echo "   /etc/docker/daemon.json esistente: non modificato (verificare log-opts e live-restore)"
fi
systemctl enable --now docker
systemctl restart docker

# ---------------------------------------------------------------- 2. utenti e gruppi
log "Utente ${DEPLOY_USER} e gruppo ${OPS_GROUP}"
getent group "$OPS_GROUP" > /dev/null || groupadd --system "$OPS_GROUP"
if ! id "$DEPLOY_USER" > /dev/null 2>&1; then
  useradd --system --create-home --home-dir "/home/${DEPLOY_USER}" --shell /bin/bash "$DEPLOY_USER"
fi
usermod -aG docker "$DEPLOY_USER"
passwd -l "$DEPLOY_USER" > /dev/null 2>&1 || true
install -d -m 0700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/${DEPLOY_USER}/.ssh"
touch "/home/${DEPLOY_USER}/.ssh/authorized_keys"
chown "$DEPLOY_USER:$DEPLOY_USER" "/home/${DEPLOY_USER}/.ssh/authorized_keys"
chmod 0600 "/home/${DEPLOY_USER}/.ssh/authorized_keys"

# ---------------------------------------------------------------- 3. directory
log "Directory di piattaforma"
install -d -m 0755 /opt/platform /var/log/apps
if [ -n "$APPS_DATA_DIR" ]; then
  install -d -m 0755 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$APPS_DATA_DIR"
  if [ -d /opt/apps ] && [ ! -L /opt/apps ]; then
    rmdir /opt/apps 2>/dev/null || { echo "/opt/apps esiste e non e' vuota: spostarla in $APPS_DATA_DIR manualmente"; exit 1; }
  fi
  [ -L /opt/apps ] || ln -s "$APPS_DATA_DIR" /opt/apps
  echo "   /opt/apps -> ${APPS_DATA_DIR}"
else
  install -d -m 0755 -o "$DEPLOY_USER" -g "$DEPLOY_USER" /opt/apps
fi

# ---------------------------------------------------------------- 4. appctl
log "Installazione appctl"
"$HERE/install-appctl.sh"

# ---------------------------------------------------------------- 5. sudoers
log "Regola sudoers per il gruppo ${OPS_GROUP}"
sed "s/%appops/%${OPS_GROUP}/; s/(deploy)/(${DEPLOY_USER})/" "$HERE/sudoers.d/appctl" > /etc/sudoers.d/appctl
chmod 0440 /etc/sudoers.d/appctl
visudo -cf /etc/sudoers.d/appctl > /dev/null

# ---------------------------------------------------------------- 6. rete proxy + Caddy
log "Rete docker 'proxy'"
docker network inspect proxy > /dev/null 2>&1 || docker network create proxy
if [ "$PROXY" = "1" ]; then
  log "Reverse proxy Caddy in /opt/platform/proxy"
  install -d -m 0755 /opt/platform/proxy /opt/platform/proxy/sites /opt/platform/proxy/certs /opt/platform/proxy/logs
  cp -n "$PLATFORM_DIR/proxy/compose.yaml" /opt/platform/proxy/compose.yaml || true
  cp -n "$PLATFORM_DIR/proxy/Caddyfile" /opt/platform/proxy/Caddyfile || true
  cp "$PLATFORM_DIR/proxy/sites/"*.example /opt/platform/proxy/sites/
  chown -R "$DEPLOY_USER:$DEPLOY_USER" /opt/platform/proxy
  echo "   configurare /opt/platform/proxy/sites/<app>.caddy e avviare: cd /opt/platform/proxy && docker compose up -d"
fi

# ---------------------------------------------------------------- 7. systemd (backup)
log "Unit systemd per il backup"
sed "s/User=deploy/User=${DEPLOY_USER}/" "$HERE/systemd/app-backup@.service" > /etc/systemd/system/app-backup@.service
cp "$HERE/systemd/app-backup@.timer" /etc/systemd/system/app-backup@.timer
systemctl daemon-reload

# ---------------------------------------------------------------- 8. hardening
if [ "$HARDEN_SSH" = "1" ]; then
log "Hardening SSH"
install -d -m 0755 /etc/ssh/sshd_config.d
cat > /etc/ssh/sshd_config.d/90-platform.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
X11Forwarding no
AllowAgentForwarding no
AllowTcpForwarding no
ClientAliveInterval 300
ClientAliveCountMax 2
EOF
if sshd -t 2> /dev/null; then systemctl reload ssh 2> /dev/null || systemctl reload sshd 2> /dev/null || true; fi
echo "   ATTENZIONE: l'autenticazione con password SSH e' disabilitata: assicurarsi di avere una chiave valida"
else
  log "Hardening SSH saltato (HARDEN_SSH=0): valutare con il sistemista di disabilitare le password (docs/SECURITY.md)"
fi

if command -v ufw > /dev/null 2>&1; then
  log "Firewall ufw: consentiti solo 22, 80, 443"
  ufw --force reset > /dev/null
  ufw default deny incoming > /dev/null
  ufw default allow outgoing > /dev/null
  ufw allow 22/tcp > /dev/null
  ufw allow 80/tcp > /dev/null
  ufw allow 443/tcp > /dev/null
  ufw --force enable > /dev/null
  ufw status | sed 's/^/   /'
elif command -v firewall-cmd > /dev/null 2>&1; then
  log "Firewall firewalld: consentiti ssh, http, https"
  firewall-cmd --permanent --add-service=ssh --add-service=http --add-service=https > /dev/null
  firewall-cmd --reload > /dev/null
else
  echo "   nessun firewall gestito trovato: configurare manualmente (docs/SECURITY.md)"
fi

log "Server pronto. Prossimi passi:"
cat <<EOF
   1. aggiungere gli operatori al gruppo ${OPS_GROUP}:   usermod -aG ${OPS_GROUP} <utente>
   2. installare l'applicazione:                     sudo $HERE/install-app.sh <nome> <development|production> <immagine>
   3. registrare la chiave SSH della pipeline:       $HERE/add-deploy-key.sh "<chiave pubblica>"
   4. login al registry come ${DEPLOY_USER}:                sudo -u ${DEPLOY_USER} $HERE/registry-login.sh ghcr.io <utente-tecnico>
   Guida completa: docs/INSTALLATION.md
EOF
