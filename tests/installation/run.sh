#!/usr/bin/env bash
# Installation test on Oracle Linux 9 with systemd (runs on any Docker or Podman host).
#
#   tests/installation/run.sh release/pkm-1.0.0-linux-x86_64.tar.gz
#
# Scenario: install -> service/timer/health/setup token -> idempotent re-install -> backup.sh ->
# restore.sh -> upgrade.sh to a re-versioned copy (+ automatic rollback test with a broken release)
# -> uninstall (data kept) -> install again (data reused) -> uninstall --purge.
set -o errexit -o nounset -o pipefail

TARBALL="${1:?usage: run.sh <release tarball>}"
ENGINE="${ENGINE:-$(command -v podman >/dev/null && echo podman || echo docker)}"
NAME=pkm-install-test
IMAGE=localhost/pkm-ol9-systemd:test
# pwd -W gives a native path on Git Bash for Windows (Docker Desktop needs it); plain pwd elsewhere.
HERE="$(cd "$(dirname "$0")" && (pwd -W 2>/dev/null || pwd))"
TARBALL="$(cd "$(dirname "$TARBALL")" && (pwd -W 2>/dev/null || pwd))/$(basename "$TARBALL")"
PASS=0
FAIL=0

say() { printf '\n\033[1;34m== %s\033[0m\n' "$*"; }
check() {
  local desc="$1"; shift
  if "$@" >/tmp/pkm-check.out 2>&1; then
    printf '  \033[32mPASS\033[0m %s\n' "$desc"; PASS=$((PASS + 1))
  else
    printf '  \033[31mFAIL\033[0m %s\n' "$desc"; sed 's/^/       /' /tmp/pkm-check.out | tail -25; FAIL=$((FAIL + 1))
  fi
}
x() { "$ENGINE" exec "$NAME" bash -lc "set -o pipefail; $*"; }

cleanup() { "$ENGINE" rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

say "building the Oracle Linux 9 + systemd test image"
"$ENGINE" build -q -t "$IMAGE" -f "$HERE/Containerfile.ol9" "$HERE" >/dev/null

say "starting the test host"
cleanup
"$ENGINE" run -d --name "$NAME" --privileged --cgroupns=host -v /sys/fs/cgroup:/sys/fs/cgroup:rw \
  --tmpfs /run --tmpfs /run/lock -h ol9-pkm.example.test "$IMAGE" >/dev/null
for _ in $(seq 1 30); do x "systemctl is-system-running 2>/dev/null | grep -Eq 'running|degraded'" && break; sleep 1; done
x "cat /etc/oracle-release; uname -m; python3.12 --version; podman --version"

"$ENGINE" cp "$TARBALL" "$NAME:/root/"
BASE="$(basename "$TARBALL" .tar.gz)"
x "cd /root && tar xzf $BASE.tar.gz"

say "1. install"
check "install.sh completes" x "cd /root/$BASE && ./install.sh --non-interactive --podman-access 2>&1 | tee /root/install.log"
check "summary printed" x "grep -q 'Installation completed.' /root/install.log && grep -q 'URL:' /root/install.log"
check "pkm.service active" x "systemctl is-active pkm.service"
check "pkm.service enabled" x "systemctl is-enabled pkm.service"
check "pkm-backup.timer active" x "systemctl is-active pkm-backup.timer"
check "readyz over HTTPS (self-signed)" x "curl -fsk https://127.0.0.1:8443/readyz"
check "UI served" x "curl -fsk https://127.0.0.1:8443/ | grep -q '<div id=\"root\">'"
check "setup token printed" x "grep -A2 'One-time setup token' /root/install.log | grep -Eq '[A-Za-z0-9_-]{20,}'"
check "setup required before wizard" x "curl -fsk https://127.0.0.1:8443/api/v1/system/info | grep -q '\"setupRequired\":true'"
check "permissions /etc/pkm 0750 root:pkm" x "[ \"\$(stat -c '%a %U:%G' /etc/pkm)\" = '750 root:pkm' ]"
check "permissions config 0640 root:pkm" x "[ \"\$(stat -c '%a %U:%G' /etc/pkm/config.yaml)\" = '640 root:pkm' ]"
check "TLS key not world readable" x "[ \"\$(stat -c '%a' /etc/pkm/tls/pkm.key)\" = '640' ]"
check "data dir owned by pkm" x "[ \"\$(stat -c '%U' /var/lib/pkm/pkm.db)\" = 'pkm' ]"
check "service runs as pkm" x "ps -o user= -p \$(systemctl show -p MainPID --value pkm.service) | grep -qx pkm"
check "podman socket drop-in installed" x "test -f /etc/systemd/system/podman.socket.d/10-pkm.conf"
check "journald logs present" x "journalctl -u pkm --no-pager | grep -q 'Scarlet started'"
check "file log present" x "test -s /var/log/pkm/pkm.log"
check "systemd hardening applied" x "systemctl show pkm.service -p NoNewPrivileges -p ProtectSystem | grep -q 'ProtectSystem=strict'"

say "2. first-run wizard via API, then admin login"
TOKEN="$(x "grep -A2 'One-time setup token' /root/install.log | grep -Eo '[A-Za-z0-9_-]{20,}' | head -1")"
check "setup/complete" x "curl -fsk -X POST https://127.0.0.1:8443/api/v1/setup/complete -H 'X-Setup-Token: $TOKEN' -H 'Content-Type: application/json' -d '{\"admin\":{\"username\":\"opsadmin\",\"password\":\"Install-Test-2026!\"}}'"
check "pkm-admin list-users" x "pkm-admin list-users | grep -q opsadmin"
check "login works" x "curl -fsk -c /root/c -X POST https://127.0.0.1:8443/api/v1/auth/login -H 'Content-Type: application/json' -d '{\"username\":\"opsadmin\",\"password\":\"Install-Test-2026!\"}'"
check "health endpoint (no Kubernetes configured -> reported, app still up)" x "curl -fsk -b /root/c https://127.0.0.1:8443/api/v1/health | grep -q '\"id\":\"kubernetes\"'"
check "podman integration connected" x "curl -fsk -b /root/c https://127.0.0.1:8443/api/v1/podman/info | grep -q '\"connected\":true'"

say "3. idempotent re-install"
check "install.sh again keeps config and data" x "cd /root/$BASE && ./install.sh --non-interactive --no-podman-access >/root/install2.log 2>&1 && pkm-admin list-users | grep -q opsadmin"

say "4. backup.sh / restore.sh"
check "backup.sh" x "/opt/pkm/current/scripts/backup.sh --copy-to /root/offsite | tee /root/backup.log"
BK="$(x "ls -1t /var/lib/pkm/backups/pkm-backup-*.tar.gz | head -1")"
check "backup verified" x "pkm-admin verify-backup $BK"
check "change after backup (user created)" x "printf 'Another-Pass-2026!\n' | pkm-admin create-admin --username lateuser --password-stdin"
check "restore.sh" x "/opt/pkm/current/scripts/restore.sh $BK --yes"
check "restored state (user created after backup is gone)" x "! pkm-admin list-users | grep -q lateuser"
check "service active after restore" x "systemctl is-active pkm.service"
check "scheduled backup unit works" x "systemctl start pkm-backup.service && journalctl -u pkm-backup --no-pager | grep -q sha256"

say "5. upgrade with automatic rollback (broken release)"
x "rm -rf /root/broken && cp -a /root/$BASE /root/broken && echo 9.9.9-broken > /root/broken/VERSION && sed -i 's#ExecStart=.*#ExecStart=/bin/false#' /root/broken/deploy/systemd/pkm.service"
check "upgrade.sh fails and rolls back" x "! /root/broken/upgrade.sh --yes > /root/upgrade-broken.log 2>&1 && grep -q 'restored and running' /root/upgrade-broken.log"
check "still on the original version" x "readlink /opt/pkm/current | grep -q \"\$(cat /root/$BASE/VERSION)\" && systemctl is-active pkm.service"

say "6. upgrade (re-versioned release)"
x "rm -rf /root/next && cp -a /root/$BASE /root/next && echo 1.0.1-test > /root/next/VERSION"
check "upgrade.sh" x "/root/next/upgrade.sh --yes 2>&1 | tee /root/upgrade.log | grep -q 'Upgrade completed.'"
check "current -> 1.0.1-test" x "readlink /opt/pkm/current | grep -q 1.0.1-test"
check "data preserved after upgrade" x "pkm-admin list-users | grep -q opsadmin"
check "previous release kept" x "test -d /opt/pkm/releases/\$(cat /root/$BASE/VERSION)"

say "7. uninstall (keep data) and reinstall"
check "uninstall.sh --yes" x "/opt/pkm/current/scripts/uninstall.sh --yes"
check "service removed" x "! systemctl cat pkm.service >/dev/null 2>&1"
check "data kept" x "test -f /var/lib/pkm/pkm.db && test -f /etc/pkm/config.yaml"
check "reinstall reuses data" x "cd /root/$BASE && ./install.sh --non-interactive --no-podman-access >/root/install3.log 2>&1 && pkm-admin list-users | grep -q opsadmin && ! grep -q 'One-time setup token' /root/install3.log"

say "8. uninstall --purge"
check "uninstall.sh --purge --yes" x "/opt/pkm/current/scripts/uninstall.sh --purge --yes"
check "everything removed" x "! test -e /opt/pkm && ! test -e /etc/pkm && ! test -e /var/lib/pkm && ! id pkm"

printf '\n\033[1mResult: %d passed, %d failed\033[0m\n' "$PASS" "$FAIL"
[[ $FAIL -eq 0 ]]
