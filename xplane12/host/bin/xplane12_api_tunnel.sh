#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${XPLANE_ENV_FILE:-/home/tang/xplane12.env}"
if [[ -f "${ENV_FILE}" ]]; then
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
fi

REMOTE_USER="${TUNNEL_REMOTE_USER:-luobin}"
REMOTE_HOST="${TUNNEL_REMOTE_HOST:-public-server}"
REMOTE_PORT="${API_TUNNEL_REMOTE_PORT:-12678}"
LOCAL_PORT="${API_BIND_PORT:-12678}"
RECONNECT_DELAY="${TUNNEL_RECONNECT_DELAY:-5}"

echo "=== X-Plane 12 API Reverse SSH Tunnel ==="
echo "Forwarding: ${REMOTE_HOST}:${REMOTE_PORT} -> 127.0.0.1:${LOCAL_PORT}"

if ! curl -fsS --max-time 2 "http://127.0.0.1:${LOCAL_PORT}/health" >/dev/null 2>&1; then
    echo "[WARN] Local API health check failed at http://127.0.0.1:${LOCAL_PORT}/health"
fi

ATTEMPT=0
while true; do
    ((ATTEMPT+=1))
    echo "[$(date +%Y-%m-%dT%H:%M:%S%z)] Starting tunnel (attempt #${ATTEMPT})..."

    ssh -NT \
        -R "${REMOTE_PORT}:127.0.0.1:${LOCAL_PORT}" \
        -o ServerAliveInterval=30 \
        -o ServerAliveCountMax=3 \
        -o ExitOnForwardFailure=yes \
        -o StrictHostKeyChecking=accept-new \
        "${REMOTE_USER}@${REMOTE_HOST}"

    echo "[WARN] Tunnel disconnected. Reconnecting in ${RECONNECT_DELAY}s..."
    sleep "${RECONNECT_DELAY}"
done
