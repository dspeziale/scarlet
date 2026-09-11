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
mkdir -p "/home/${USER_NAME}/.local/share/containers" && chown -R "${USER_NAME}:${USER_NAME}" "/home/${USER_NAME}/.local"
mkdir -p /run/sshd
echo "[mockhost] ssh user=${USER_NAME} podman=$(podman --version 2>/dev/null || echo n/a)"
exec /usr/sbin/sshd -D -e
