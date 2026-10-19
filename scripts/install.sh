#!/usr/bin/env bash
# Podman Kubernetes Manager - installer for Oracle Linux 9 (x86_64, systemd).
#
#   sudo ./install.sh [options]
#
# Options:
#   --port N                 listening port (default 8443, or 8080 with --no-tls)
#   --bind ADDR              bind address (default 0.0.0.0)
#   --no-tls                 serve plain HTTP (only behind a TLS reverse proxy or for tests)
#   --kubeconfig PATH        kubeconfig to copy to /etc/pkm/kubeconfig (ServiceAccount "pkm" recommended)
#   --podman-socket URL      Podman API socket (default unix:///run/podman/podman.sock), or "none" to disable
#   --podman-access          give the pkm group access to the rootful Podman socket (root-equivalent!)
#   --no-firewall            do not open the port in firewalld
#   --non-interactive        never ask questions (defaults are used)
#   --force                  allow RHEL-9 compatible systems other than Oracle Linux
#   -h, --help               this help
#
# The installation is idempotent: running it again keeps the existing configuration and data.

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$DIR/lib/common.sh" 2>/dev/null || . "$DIR/scripts/lib/common.sh"

PORT=""
BIND="0.0.0.0"
TLS=yes
KUBECONFIG_SRC=""
PODMAN_URL="unix:///run/podman/podman.sock"
PODMAN_ACCESS=ask
FIREWALL=yes
INTERACTIVE=yes
FORCE=no

usage() { sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --bind) BIND="$2"; shift 2 ;;
    --no-tls) TLS=no; shift ;;
    --kubeconfig) KUBECONFIG_SRC="$2"; shift 2 ;;
    --podman-socket) PODMAN_URL="$2"; shift 2 ;;
    --podman-access) PODMAN_ACCESS=yes; shift ;;
    --no-podman-access) PODMAN_ACCESS=no; shift ;;
    --no-firewall) FIREWALL=no; shift ;;
    --non-interactive) INTERACTIVE=no; shift ;;
    --force) FORCE=yes; shift ;;
    -h|--help) usage ;;
    *) die "unknown option: $1 (see --help)" ;;
  esac
done
[[ -n "$PORT" ]] || { [[ "$TLS" == yes ]] && PORT=8443 || PORT=8080; }
[[ "$PORT" =~ ^[0-9]+$ && "$PORT" -ge 1 && "$PORT" -le 65535 ]] || die "invalid port: $PORT"
[[ "$PODMAN_URL" == none || "$PODMAN_URL" == unix://* || "$PODMAN_URL" == http://* || "$PODMAN_URL" == https://* ]] \
  || die "invalid --podman-socket: use unix:///path, http(s)://host:port or none"

ask_yes_no() {
  local question="$1" default="$2" answer
  [[ "$INTERACTIVE" == yes && -t 0 ]] || { [[ "$default" == yes ]]; return; }
  read -r -p "$question [$([[ $default == yes ]] && echo 'Y/n' || echo 'y/N')] " answer
  answer="${answer:-$default}"
  [[ "$answer" =~ ^[YySs] ]]
}

require_root
ROOT="$(cd "$DIR" && { [[ -f VERSION ]] && pwd || (cd .. && pwd); })"
VERSION="$(release_version "$ROOT")"
log "Podman Kubernetes Manager $VERSION - installation"

# ------------------------------------------------------------------ checks
check_os "$FORCE"
check_systemd
for cmd in tar curl openssl install runuser; do
  command -v "$cmd" >/dev/null || die "required command not found: $cmd (dnf install $cmd)"
done
ensure_python

if command -v podman >/dev/null 2>&1; then
  ok "podman: $(podman --version 2>/dev/null)"
  HAVE_PODMAN=yes
else
  warn "podman is not installed: the Container section will show 'Podman non raggiungibile' (optional component)"
  HAVE_PODMAN=no
fi

if [[ -n "$KUBECONFIG_SRC" ]]; then
  [[ -r "$KUBECONFIG_SRC" ]] || die "kubeconfig not readable: $KUBECONFIG_SRC"
  grep -q "apiVersion" "$KUBECONFIG_SRC" || die "$KUBECONFIG_SRC does not look like a kubeconfig file"
  ok "kubeconfig: $KUBECONFIG_SRC"
elif [[ -f "$PKM_ETC/kubeconfig" ]]; then
  ok "kubeconfig: existing $PKM_ETC/kubeconfig kept"
else
  warn "no --kubeconfig given: Kubernetes can be configured later in the setup wizard or Impostazioni → Kubernetes"
fi

# ------------------------------------------------------------------ install
ensure_user
ensure_dirs
install_release "$ROOT" "$VERSION" "$PKM_PY"
PREVIOUS="$(readlink -f "$PKM_CURRENT" 2>/dev/null || true)"
switch_current "$VERSION"
install_wrapper

if [[ -n "$KUBECONFIG_SRC" ]]; then
  install -m 0640 -o root -g "$PKM_GROUP" "$KUBECONFIG_SRC" "$PKM_ETC/kubeconfig"
fi

# ------------------------------------------------------------------ configuration
if [[ ! -f "$PKM_CONFIG_FILE" ]]; then
  log "creating $PKM_CONFIG_FILE"
  cfg="$(cat "$ROOT/config/config.example.yaml")"
  cfg="${cfg//host: 0.0.0.0 /host: $BIND }"
  cfg="$(sed -E "s|^(  port: )8443|\1$PORT|" <<<"$cfg")"
  if [[ "$TLS" == no ]]; then
    cfg="$(sed -E 's|^(  tls_cert: .*)|  tls_cert: null   # TLS disabled by install.sh --no-tls|; s|^(  tls_key: .*)|  tls_key: null|' <<<"$cfg")"
  fi
  if [[ "$PODMAN_URL" == none ]]; then
    cfg="$(sed -E '/^podman:/,/^[a-z]/ s|^(  enabled: )true|\1false|' <<<"$cfg")"
  else
    cfg="$(sed -E "s|^(  url: )unix:///run/podman/podman.sock|\1$PODMAN_URL|" <<<"$cfg")"
  fi
  if [[ ! -f "$PKM_ETC/kubeconfig" ]]; then
    cfg="$(sed -E 's|^(  kubeconfig: )/etc/pkm/kubeconfig|\1null|' <<<"$cfg")"
  fi
  printf '%s\n' "$cfg" > "$PKM_CONFIG_FILE"
  chown root:"$PKM_GROUP" "$PKM_CONFIG_FILE"
  chmod 0640 "$PKM_CONFIG_FILE"
else
  ok "existing configuration kept: $PKM_CONFIG_FILE"
fi
if [[ ! -f "$PKM_ENV_FILE" ]]; then
  install -m 0640 -o root -g "$PKM_GROUP" "$ROOT/.env.example" "$PKM_ENV_FILE"
fi

# ------------------------------------------------------------------ TLS
CERT="$(config_value server tls_cert)"
KEY="$(config_value server tls_key)"
if [[ -n "$CERT" && "$CERT" != null && ! -f "$CERT" ]]; then
  log "generating a self-signed certificate in $PKM_ETC/tls (replace it with a certificate of your CA)"
  FQDN="$(host_fqdn)"
  SAN="DNS:$FQDN,DNS:localhost,IP:127.0.0.1"
  [[ "${FQDN%%.*}" != "$FQDN" ]] && SAN="$SAN,DNS:${FQDN%%.*}"
  for ip in $(host_ipv4s); do SAN="$SAN,IP:$ip"; done
  openssl req -x509 -newkey rsa:3072 -sha256 -days 825 -nodes -keyout "$KEY" -out "$CERT" \
    -subj "/CN=$FQDN/O=Podman Kubernetes Manager" -addext "subjectAltName=$SAN" \
    -addext "extendedKeyUsage=serverAuth" >/dev/null 2>&1 || die "certificate generation failed"
  chown root:"$PKM_GROUP" "$KEY" "$CERT"
  chmod 0640 "$KEY"
  chmod 0644 "$CERT"
  ok "self-signed certificate created for $FQDN"
fi

# ------------------------------------------------------------------ Podman socket access
if [[ "$HAVE_PODMAN" == yes && "$PODMAN_URL" == unix:///run/podman/podman.sock ]]; then
  if [[ "$PODMAN_ACCESS" == ask ]]; then
    warn "Access to the ROOTFUL Podman socket is equivalent to root access on this host (see SECURITY.md)."
    if ask_yes_no "Grant the pkm service access to the rootful Podman socket?" no; then PODMAN_ACCESS=yes; else PODMAN_ACCESS=no; fi
  fi
  if [[ "$PODMAN_ACCESS" == yes ]]; then
    install -d -m 0755 /etc/systemd/system/podman.socket.d
    install -m 0644 "$ROOT/deploy/systemd/podman.socket.d-pkm.conf" /etc/systemd/system/podman.socket.d/10-pkm.conf
    systemctl daemon-reload
    systemctl enable --now podman.socket >/dev/null 2>&1 || warn "cannot enable podman.socket"
    systemctl restart podman.socket >/dev/null 2>&1 || true
    ok "podman.socket enabled with access for group $PKM_GROUP"
  else
    warn "Podman socket access not granted: enable it later with install.sh --podman-access or configure a rootless socket"
  fi
fi

# ------------------------------------------------------------------ database & services
log "preparing the database"
runuser -u "$PKM_USER" -- env PKM_CONFIG="$PKM_CONFIG_FILE" "$PKM_CURRENT/venv/bin/pkm-admin" migrate >/dev/null \
  || die "database initialisation failed (see the error above)"
install_units "$ROOT"
systemctl enable pkm.service pkm-backup.timer >/dev/null 2>&1
systemctl restart pkm.service
systemctl start pkm-backup.timer

if [[ "$FIREWALL" == yes ]] && systemctl is-active --quiet firewalld 2>/dev/null; then
  firewall-cmd --quiet --permanent --add-port="$PORT/tcp" && firewall-cmd --quiet --reload \
    && ok "firewalld: port $PORT/tcp opened" || warn "could not open port $PORT/tcp in firewalld"
fi

log "waiting for the service to become ready"
if ! wait_ready 90; then
  show_failure_hint
  if [[ -n "$PREVIOUS" && -d "$PREVIOUS" && "$PREVIOUS" != "$PKM_RELEASES/$VERSION" ]]; then
    warn "restoring the previous release $(basename "$PREVIOUS")"
    ln -sfn "$PREVIOUS" "$PKM_CURRENT"
    systemctl restart pkm.service || true
  fi
  die "installation completed with errors: the service is not ready"
fi

# ------------------------------------------------------------------ first-run token
SETUP_TOKEN=""
if [[ "$(runuser -u "$PKM_USER" -- env PKM_CONFIG="$PKM_CONFIG_FILE" "$PKM_CURRENT/venv/bin/pkm-admin" list-users 2>/dev/null | wc -l)" -eq 0 ]]; then
  SETUP_TOKEN="$(runuser -u "$PKM_USER" -- env PKM_CONFIG="$PKM_CONFIG_FILE" "$PKM_CURRENT/venv/bin/pkm-admin" setup-token)"
fi

URL="$(service_url)"
STATUS="$(systemctl is-active pkm.service)"
cat <<EOF

${C_BLD}Installation completed.${C_OFF}

Application:
  Podman Kubernetes Manager $VERSION

URL:
  $URL

Service:
  pkm.service (systemctl status pkm) · backups: pkm-backup.timer · logs: journalctl -u pkm

Status:
  $STATUS

Next step:
  Open the dashboard.
EOF
if [[ -n "$SETUP_TOKEN" ]]; then
  cat <<EOF
  The first access opens the setup wizard. One-time setup token:

      ${C_BLD}$SETUP_TOKEN${C_OFF}

  (regenerate it with: sudo pkm-admin setup-token)
EOF
fi
if [[ "$TLS" == yes ]] && openssl x509 -in "$CERT" -noout -issuer 2>/dev/null | grep -q "Podman Kubernetes Manager"; then
  echo
  warn "the certificate is self-signed: the browser will show a warning. Replace $CERT and $KEY with a certificate of your CA and run: systemctl restart pkm"
fi
