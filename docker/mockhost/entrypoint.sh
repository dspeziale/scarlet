#!/bin/sh
# Create the SCARLET operator user, prepare /opt/scarlet and start sshd (foreground).
set -eu
USER_NAME="${MOCKHOST_USER:-scarlet}"
USER_PASSWORD="${MOCKHOST_PASSWORD:-scarlet-dev}"

if ! id "$USER_NAME" >/dev/null 2>&1; then
    useradd -m -s /bin/bash "$USER_NAME"
    echo "${USER_NAME}:${USER_PASSWORD}" | chpasswd
    # subuid/subgid ranges required by rootless podman
    grep -q "^${USER_NAME}:" /etc/subuid || echo "${USER_NAME}:100000:65536" >> /etc/subuid
    grep -q "^${USER_NAME}:" /etc/subgid || echo "${USER_NAME}:100000:65536" >> /etc/subgid
fi
if [ -n "${MOCKHOST_AUTHORIZED_KEY:-}" ]; then
    mkdir -p "/home/${USER_NAME}/.ssh"
    echo "$MOCKHOST_AUTHORIZED_KEY" >> "/home/${USER_NAME}/.ssh/authorized_keys"
    chmod 700 "/home/${USER_NAME}/.ssh" && chmod 600 "/home/${USER_NAME}/.ssh/authorized_keys"
    chown -R "${USER_NAME}:${USER_NAME}" "/home/${USER_NAME}/.ssh"
fi
mkdir -p /opt/scarlet && chown "${USER_NAME}:${USER_NAME}" /opt/scarlet
# rootless podman needs XDG dirs: config, storage and a runtime dir (no systemd-logind in a container)
USER_UID="$(id -u "$USER_NAME")"
mkdir -p "/home/${USER_NAME}/.config/containers" "/home/${USER_NAME}/.local/share/containers" "/run/user/${USER_UID}"
chown -R "${USER_NAME}:${USER_NAME}" "/home/${USER_NAME}/.config" "/home/${USER_NAME}/.local" "/run/user/${USER_UID}"
chmod 700 "/run/user/${USER_UID}"
grep -q "^SetEnv XDG_RUNTIME_DIR" /etc/ssh/sshd_config || echo "SetEnv XDG_RUNTIME_DIR=/run/user/${USER_UID}" >> /etc/ssh/sshd_config
# Rootless user namespaces are not available inside every container engine (e.g. Docker Desktop):
# expose Podman to the SCARLET user through a sudo wrapper (rootful mode). DEV SIMULATOR ONLY.
if [ "${MOCKHOST_PODMAN_MODE:-sudo}" = "sudo" ]; then
    echo "${USER_NAME} ALL=(root) NOPASSWD: /usr/bin/podman" > /etc/sudoers.d/scarlet-podman
    chmod 440 /etc/sudoers.d/scarlet-podman
    printf '#!/bin/sh\nexec /usr/bin/sudo -n /usr/bin/podman "$@"\n' > /usr/local/bin/podman
    chmod 755 /usr/local/bin/podman
fi
mkdir -p /run/sshd
echo "[mockhost] ssh user=${USER_NAME} podman=$(podman --version 2>/dev/null || echo n/a)"
exec /usr/sbin/sshd -D -e
