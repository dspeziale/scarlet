#!/bin/bash
set -e

echo "[entrypoint] Starting SOC Seattle Probe Agent"
echo "[entrypoint] Hostname: $(hostname)"
echo "[entrypoint] Machine ID: $(cat /etc/machine-id 2>/dev/null || hostname)"

# Ensure Suricata runtime dirs are writable
mkdir -p /var/log/suricata /var/run/suricata /opt/pcap /opt/agent/data

# Validate required environment variables
REQUIRED_VARS=(SERVER_URL REGISTRATION_TOKEN)
for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        echo "[entrypoint] ERROR: Required env var $var is not set"
        exit 1
    fi
done

echo "[entrypoint] Server URL: $SERVER_URL"
echo "[entrypoint] Agent Version: ${AGENT_VERSION:-1.0.0}"

exec "$@"
