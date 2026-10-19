#!/usr/bin/env bash
# Shared helpers for the PKM installation scripts (install, upgrade, uninstall, backup, restore).
# shellcheck disable=SC2034

set -o errexit -o nounset -o pipefail

PKM_USER=pkm
PKM_GROUP=pkm
PKM_HOME=/opt/pkm
PKM_RELEASES="$PKM_HOME/releases"
PKM_CURRENT="$PKM_HOME/current"
PKM_ETC=/etc/pkm
PKM_DATA=/var/lib/pkm
PKM_LOG=/var/log/pkm
PKM_CONFIG_FILE="$PKM_ETC/config.yaml"
PKM_ENV_FILE="$PKM_ETC/pkm.env"
PKM_UNIT_DIR=/etc/systemd/system
PKM_ADMIN_WRAPPER=/usr/local/bin/pkm-admin

if [[ -t 1 ]]; then
  C_RED=$'\e[31m'; C_GRN=$'\e[32m'; C_YLW=$'\e[33m'; C_BLU=$'\e[34m'; C_BLD=$'\e[1m'; C_OFF=$'\e[0m'
else
  C_RED=''; C_GRN=''; C_YLW=''; C_BLU=''; C_BLD=''; C_OFF=''
fi

log()  { printf '%s[pkm]%s %s\n' "$C_BLU" "$C_OFF" "$*"; }
ok()   { printf '%s[ ok ]%s %s\n' "$C_GRN" "$C_OFF" "$*"; }
warn() { printf '%s[warn]%s %s\n' "$C_YLW" "$C_OFF" "$*" >&2; }
die()  { printf '%s[fail]%s %s\n' "$C_RED" "$C_OFF" "$*" >&2; exit 1; }

require_root() {
  [[ ${EUID:-$(id -u)} -eq 0 ]] || die "this script must be run as root (use sudo)"
}

# Directory containing the extracted release (parent of scripts/ or the tarball root).
release_root() {
  local here
  here="$(cd "$(dirname "${BASH_SOURCE[1]}")" && pwd)"
  if [[ -f "$here/VERSION" ]]; then echo "$here"; elif [[ -f "$here/../VERSION" ]]; then (cd "$here/.." && pwd); else echo "$here"; fi
}

release_version() {
  local root="$1"
  [[ -f "$root/VERSION" ]] || die "VERSION file not found in $root: run the script from an extracted release"
  tr -d '[:space:]' < "$root/VERSION"
}

check_os() {
  local force="${1:-no}" arch os_id os_ver os_pretty os_like
  [[ -r /etc/os-release ]] || die "/etc/os-release not found: unsupported system"
  # Read os-release in a subshell: it defines VERSION, NAME... which must not leak into the scripts.
  os_id="$(. /etc/os-release && echo "${ID:-}")"
  os_ver="$(. /etc/os-release && echo "${VERSION_ID:-}")"
  os_pretty="$(. /etc/os-release && echo "${PRETTY_NAME:-unknown}")"
  os_like="$(. /etc/os-release && echo "${ID_LIKE:-}")"
  arch="$(uname -m)"
  [[ "$arch" == "x86_64" ]] || die "unsupported architecture: $arch (x86_64 required)"
  if [[ "$os_id" == "ol" && "$os_ver" == 9* ]]; then
    ok "operating system: $os_pretty ($arch)"
  elif [[ "$os_like" == *rhel* && "$os_ver" == 9* ]]; then
    [[ "$force" == yes ]] || die "$os_pretty is RHEL 9 compatible but not Oracle Linux 9: re-run with --force to continue"
    warn "$os_pretty is not Oracle Linux: continuing because of --force"
  else
    die "unsupported operating system: $os_pretty (Oracle Linux 9.x required)"
  fi
}

check_systemd() {
  command -v systemctl >/dev/null || die "systemd (systemctl) is required"
  [[ -d /run/systemd/system ]] || die "systemd is not running as init on this host"
}

# Find a Python >= 3.11 (python3.12 from AppStream on Oracle Linux 9).
find_python() {
  local p
  for p in "${PKM_PYTHON:-}" /usr/bin/python3.12 /usr/bin/python3.11 python3.12 python3.11; do
    [[ -n "$p" ]] || continue
    if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys,venv; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      command -v "$p"
      return 0
    fi
  done
  return 1
}

# Sets PKM_PY to a usable interpreter, installing python3.12 if needed.
ensure_python() {
  local py
  if py="$(find_python)"; then
    ok "python: $py ($("$py" -c 'import platform; print(platform.python_version())'))"
    PKM_PY="$py"
    return 0
  fi
  log "Python 3.12 not found: installing python3.12 from the AppStream repository"
  if ! dnf -y -q install python3.12 python3.12-pip >/dev/null; then
    die "cannot install python3.12 (no repository access?). Install it manually: dnf install python3.12"
  fi
  py="$(find_python)" || die "python3.12 installed but not usable"
  ok "python: $py"
  PKM_PY="$py"
}

ensure_user() {
  if ! getent group "$PKM_GROUP" >/dev/null; then
    groupadd --system "$PKM_GROUP"
  fi
  if ! id -u "$PKM_USER" >/dev/null 2>&1; then
    useradd --system --gid "$PKM_GROUP" --home-dir "$PKM_DATA" --no-create-home --shell /sbin/nologin \
      --comment "Podman Kubernetes Manager" "$PKM_USER"
    ok "system user '$PKM_USER' created"
  fi
}

ensure_dirs() {
  install -d -m 0755 -o root -g root "$PKM_HOME" "$PKM_RELEASES"
  install -d -m 0750 -o root -g "$PKM_GROUP" "$PKM_ETC" "$PKM_ETC/tls"
  install -d -m 0750 -o "$PKM_USER" -g "$PKM_GROUP" "$PKM_DATA" "$PKM_LOG"
  install -d -m 0700 -o "$PKM_USER" -g "$PKM_GROUP" "$PKM_DATA/backups"
  if command -v restorecon >/dev/null 2>&1; then
    restorecon -RF "$PKM_HOME" "$PKM_ETC" "$PKM_DATA" "$PKM_LOG" >/dev/null 2>&1 || true
  fi
}

# Create the virtualenv of a release and install the application wheels (offline when wheels/ is present).
install_release() {
  local root="$1" version="$2" py="$3"
  local dest="$PKM_RELEASES/$version"
  if [[ -d "$dest" ]]; then
    warn "release directory $dest already exists: it will be replaced"
    rm -rf "$dest"
  fi
  install -d -m 0755 "$dest"
  log "creating virtual environment in $dest/venv"
  "$py" -m venv "$dest/venv"
  "$dest/venv/bin/python" -m pip install -q --upgrade --no-index --find-links "$root/wheels" pip 2>/dev/null || true
  if [[ -d "$root/wheels" ]] && ls "$root"/wheels/pkm-*.whl >/dev/null 2>&1; then
    log "installing application (offline, bundled wheels)"
    "$dest/venv/bin/pip" install -q --no-index --find-links "$root/wheels" pkm || die "pip install failed (bundled wheels)"
  else
    die "no application wheel found in $root/wheels: use an official release tarball (scripts/build-release.sh)"
  fi
  # Scripts, docs and deployment files travel with the release (used by the UI restore instructions).
  cp -a "$root/scripts" "$dest/scripts"
  cp -a "$root/deploy" "$dest/deploy"
  [[ -d "$root/docs" ]] && cp -a "$root/docs" "$dest/docs"
  for f in README.md ARCHITECTURE.md INSTALL.md OPERATIONS.md SECURITY.md TROUBLESHOOTING.md DEVELOPMENT.md BACKUP.md CHANGELOG.md VERSION; do
    [[ -f "$root/$f" ]] && cp -a "$root/$f" "$dest/"
  done
  install -d -m 0755 "$dest/config"
  cp -a "$root/config/config.example.yaml" "$dest/config/"
  [[ -f "$root/.env.example" ]] && cp -a "$root/.env.example" "$dest/config/pkm.env.example"
  chown -R root:root "$dest"
  chmod -R go-w "$dest"
  if command -v restorecon >/dev/null 2>&1; then restorecon -RF "$dest" >/dev/null 2>&1 || true; fi
  ok "release $version installed in $dest"
}

switch_current() {
  local version="$1"
  ln -sfn "$PKM_RELEASES/$version" "$PKM_CURRENT.new"
  mv -Tf "$PKM_CURRENT.new" "$PKM_CURRENT"
  ok "$PKM_CURRENT -> $PKM_RELEASES/$version"
}

install_wrapper() {
  cat > "$PKM_ADMIN_WRAPPER" <<'EOF'
#!/usr/bin/env bash
# pkm-admin wrapper: runs the administration CLI as the pkm user with the service environment,
# so files in /var/lib/pkm keep the right ownership.
set -o errexit -o nounset -o pipefail
export PKM_CONFIG=/etc/pkm/config.yaml
if [[ -r /etc/pkm/pkm.env ]]; then set -a; . /etc/pkm/pkm.env; set +a; fi
BIN=/opt/pkm/current/venv/bin/pkm-admin
if [[ $(id -u) -eq 0 && "${1:-}" != "restore" ]]; then
  exec runuser -u pkm -- env PKM_CONFIG="$PKM_CONFIG" "$BIN" "$@"
fi
exec "$BIN" "$@"
EOF
  chmod 0755 "$PKM_ADMIN_WRAPPER"
}

install_units() {
  local root="$1"
  install -m 0644 "$root/deploy/systemd/pkm.service" "$PKM_UNIT_DIR/pkm.service"
  install -m 0644 "$root/deploy/systemd/pkm-backup.service" "$PKM_UNIT_DIR/pkm-backup.service"
  install -m 0644 "$root/deploy/systemd/pkm-backup.timer" "$PKM_UNIT_DIR/pkm-backup.timer"
  systemctl daemon-reload
}

# Read a value from config.yaml (simple "key: value" lines inside a section) - used only for messages.
config_value() {
  local section="$1" key="$2"
  awk -v s="$section" -v k="$key" '
    $0 ~ "^"s":" {ins=1; next}
    ins && /^[^[:space:]#]/ {ins=0}
    ins && $1 == k":" {sub(/^[^:]*:[[:space:]]*/, ""); sub(/[[:space:]]+#.*/, ""); gsub(/"/, ""); print; exit}
  ' "$PKM_CONFIG_FILE" 2>/dev/null
}

# Host name / addresses without requiring the "hostname" package (absent on minimal installs).
host_fqdn() {
  local h
  h="$(hostname -f 2>/dev/null || true)"
  [[ -n "$h" ]] || h="$(hostnamectl --static 2>/dev/null || true)"
  [[ -n "$h" ]] || h="$(uname -n)"
  echo "$h"
}

host_ipv4s() {
  if command -v hostname >/dev/null 2>&1 && hostname -I >/dev/null 2>&1; then
    hostname -I | tr ' ' '\n' | grep -v ':' | grep -v '^$' || true
  elif command -v ip >/dev/null 2>&1; then
    ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1
  fi
}

service_url() {
  local host port cert scheme
  host="$(config_value server host)"; port="$(config_value server port)"; cert="$(config_value server tls_cert)"
  [[ -n "$cert" && "$cert" != "null" ]] && scheme=https || scheme=http
  [[ -z "$host" || "$host" == "0.0.0.0" || "$host" == "::" ]] && host="$(host_fqdn)"
  echo "$scheme://$host:${port:-8443}"
}

local_probe_url() {
  local port cert scheme
  port="$(config_value server port)"; cert="$(config_value server tls_cert)"
  [[ -n "$cert" && "$cert" != "null" ]] && scheme=https || scheme=http
  echo "$scheme://127.0.0.1:${port:-8443}"
}

# Wait until /readyz answers (max $1 seconds).
wait_ready() {
  local timeout="${1:-60}" url i
  url="$(local_probe_url)/readyz"
  for ((i = 0; i < timeout; i++)); do
    if curl -fsk --max-time 3 "$url" >/dev/null 2>&1; then
      return 0
    fi
    if ! systemctl is-active --quiet pkm.service && [[ $i -gt 5 ]]; then
      return 1
    fi
    sleep 1
  done
  return 1
}

show_failure_hint() {
  warn "the service did not become ready. Last log lines:"
  journalctl -u pkm.service -n 30 --no-pager >&2 || true
  warn "check the configuration with: sudo pkm-admin check-config"
}
