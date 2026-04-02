#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${XPLANE_ENV_FILE:-/home/tang/xplane12.env}"
if [[ -f "${ENV_FILE}" ]]; then
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
fi

REMOTE_USER="${TUNNEL_REMOTE_USER:-your-user}"
REMOTE_HOST="${TUNNEL_REMOTE_HOST:-your-public-host}"
XPLANE_PORT="${XPLANE_TUNNEL_PORT:-49013}"
XPLANE_UDP_TARGET_PORT="${XPLANE_UDP_TUNNEL_TARGET_PORT:-${XPLANE_PORT}}"
RECONNECT_DELAY="${TUNNEL_RECONNECT_DELAY:-5}"

echo "=== X-Plane TCP/UDP reverse tunnel ==="
echo "Reverse SSH: ${REMOTE_HOST}:${XPLANE_PORT} -> 127.0.0.1:${XPLANE_PORT} (TCP)"
echo "Local bridge: TCP ${XPLANE_PORT} -> UDP 127.0.0.1:${XPLANE_UDP_TARGET_PORT}"

ATTEMPT=0
while true; do
    ATTEMPT=$((ATTEMPT+1))
    echo "[$(date +%Y-%m-%dT%H:%M:%S%z)] Starting local TCP->UDP bridge (attempt #${ATTEMPT})..."
    socat TCP-LISTEN:${XPLANE_PORT},bind=127.0.0.1,reuseaddr,fork UDP:127.0.0.1:${XPLANE_UDP_TARGET_PORT} &
    SOCAT_PID=$!
    cleanup() {
        kill "${SOCAT_PID}" >/dev/null 2>&1 || true
    }
    trap cleanup EXIT

    echo "[$(date +%Y-%m-%dT%H:%M:%S%z)] Starting reverse SSH tunnel..."
    if ssh -NT \
        -R "${XPLANE_PORT}:127.0.0.1:${XPLANE_PORT}" \
        -o ServerAliveInterval=30 \
        -o ServerAliveCountMax=3 \
        -o ExitOnForwardFailure=yes \
        -o StrictHostKeyChecking=accept-new \
        "${REMOTE_USER}@${REMOTE_HOST}"; then
        echo "[WARN] Tunnel exited cleanly; restarting in ${RECONNECT_DELAY}s..."
    else
        echo "[WARN] Tunnel failed; restarting in ${RECONNECT_DELAY}s..."
    fi

    cleanup
    trap - EXIT
    sleep "${RECONNECT_DELAY}"
done
