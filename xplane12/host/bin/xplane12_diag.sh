#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${XPLANE_ENV_FILE:-/home/tang/xplane12.env}"
if [[ -f "${ENV_FILE}" ]]; then
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
fi

API_BIND_HOST="${API_BIND_HOST:-127.0.0.1}"
API_BIND_PORT="${API_BIND_PORT:-12678}"
STREAM_HOST="${STREAM_HOST:-127.0.0.1}"
STREAM_PORT="${STREAM_PORT:-37212}"
API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8086/api/v3}"
XPLANE_BIN="${XPLANE_BIN:-/home/tang/X-Plane 12/X-Plane-x86_64}"
XPLANE_HOME="${XPLANE_HOME:-/home/tang/X-Plane 12}"
LOG_LINES="${XPLANE_DIAG_LOG_LINES:-80}"

DEFAULT_SERVICES=(
    xplane12-simulator.service
    xplane12-autoflight.service
    xplane12-data-api.service
    xplane12-tunnel.service
    xplane-49013-tunnel.service
)
SERVICES=("${DEFAULT_SERVICES[@]}")

usage() {
    echo "Usage: $0 [--logs N] [service ...]" >&2
    echo "Example: $0 --logs 200 xplane12-autoflight.service" >&2
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --logs)
            shift
            if [[ $# -eq 0 ]]; then
                usage
                exit 1
            fi
            LOG_LINES="$1"
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            SERVICES=("$@")
            break
            ;;
    esac
    shift
 done

section() {
    printf '\n===== %s =====\n' "$1"
}

section "Environment"
printf 'ENV_FILE=%s\n' "${ENV_FILE}"
printf 'XPLANE_HOME=%s\n' "${XPLANE_HOME}"
printf 'XPLANE_BIN=%s\n' "${XPLANE_BIN}"
printf 'API_BASE_URL=%s\n' "${API_BASE_URL}"
printf 'LOCAL_API=http://%s:%s/health\n' "${API_BIND_HOST}" "${API_BIND_PORT}"
printf 'LOCAL_STREAM=%s:%s\n' "${STREAM_HOST}" "${STREAM_PORT}"
printf 'LOG_LINES=%s\n' "${LOG_LINES}"
printf 'SERVICES=%s\n' "${SERVICES[*]}"

section "Filesystem"
ls -ld "${XPLANE_HOME}" || true
ls -l "${XPLANE_BIN}" || true
ls -l /home/tang/xplane12*.sh /home/tang/tunnel_xplane_49013.sh 2>/dev/null || true
ls -l /home/tang/xplane12*.env* 2>/dev/null || true

section "systemctl status"
sudo systemctl --no-pager --full status "${SERVICES[@]}" || true

section "service enabled state"
for service in "${SERVICES[@]}"; do
    printf '%s: ' "${service}"
    sudo systemctl is-enabled "${service}" 2>/dev/null || true
    printf '%s active=' "${service}"
    sudo systemctl is-active "${service}" 2>/dev/null || true
done

section "health checks"
curl -fsS --max-time 5 "http://${API_BIND_HOST}:${API_BIND_PORT}/health" || true
printf '\n'
curl -fsS --max-time 5 "http://${API_BIND_HOST}:${API_BIND_PORT}/v1/snapshot" || true
printf '\n'
curl -fsS --max-time 5 "${API_BASE_URL}/datarefs/count" || true
printf '\n'

section "listeners"
lsof -nP -iTCP:"${API_BIND_PORT}" -sTCP:LISTEN || true
lsof -nP -iTCP:"${STREAM_PORT}" -sTCP:LISTEN || true

section "processes"
ps aux | grep -E 'X-Plane-x86_64|xplane12_web_autoflight|xplane12_data_api|tunnel_xplane_49013|xplane12_api_tunnel' | grep -v grep || true

section "recent logs"
for service in "${SERVICES[@]}"; do
    printf '\n--- %s ---\n' "${service}"
    journalctl -u "${service}" -n "${LOG_LINES}" --no-pager || true
done
