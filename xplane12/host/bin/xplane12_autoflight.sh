#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${XPLANE_ENV_FILE:-/home/your-user/xplane12.env}"
if [[ -f "${ENV_FILE}" ]]; then
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
fi

REPO_ROOT="${REPO_ROOT:-/home/your-user/Development}"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8086/api/v3}"
RELAY_MODE="${RELAY_MODE:-rref}"
LISTEN_HOST="${LISTEN_HOST:-127.0.0.1}"
LISTEN_PORT="${LISTEN_PORT:-37211}"
TARGET_ALTITUDE_FT="${TARGET_ALTITUDE_FT:-12000}"
TARGET_HEADING_DEG="${TARGET_HEADING_DEG:-90}"
TARGET_SPEED_KT="${TARGET_SPEED_KT:-240}"
RECOVERY_ALTITUDE_FT="${RECOVERY_ALTITUDE_FT:-8000}"
XPLANE_HOST="${XPLANE_HOST:-127.0.0.1}"
XPLANE_PORT="${XPLANE_PORT:-49009}"
XPLANE_UDP_PORT="${XPLANE_UDP_PORT:-49000}"
RREF_LISTEN_HOST="${RREF_LISTEN_HOST:-0.0.0.0}"
RREF_LISTEN_PORT="${RREF_LISTEN_PORT:-49004}"
RREF_FREQUENCY_HZ="${RREF_FREQUENCY_HZ:-10}"
RREF_SAMPLE_TIMEOUT_SECONDS="${RREF_SAMPLE_TIMEOUT_SECONDS:-1.25}"
TRAFFIC_SLOTS="${TRAFFIC_SLOTS:-5}"
XPLANE_AIRCRAFT_PATH="${XPLANE_AIRCRAFT_PATH:-}"
AUTOFLIGHT_EXTRA_ARGS="${AUTOFLIGHT_EXTRA_ARGS:-}"

SCRIPT_PATH="${REPO_ROOT}/xplane12/host/xplane12_web_autoflight.py"
if [[ ! -f "${SCRIPT_PATH}" ]]; then
    echo "[xplane12_autoflight] missing script: ${SCRIPT_PATH}" >&2
    exit 1
fi

read -r -a EXTRA_ARGS <<< "${AUTOFLIGHT_EXTRA_ARGS}"
AIRCRAFT_ARGS=()
if [[ -n "${XPLANE_AIRCRAFT_PATH}" ]]; then
    AIRCRAFT_ARGS=(--aircraft-path "${XPLANE_AIRCRAFT_PATH}")
fi
export PYTHONUNBUFFERED=1
exec "${PYTHON_BIN}" "${SCRIPT_PATH}" \
    --api-base-url "${API_BASE_URL}" \
    --mode "${RELAY_MODE}" \
    --listen-host "${LISTEN_HOST}" \
    --listen-port "${LISTEN_PORT}" \
    --target-altitude-ft "${TARGET_ALTITUDE_FT}" \
    --target-heading-deg "${TARGET_HEADING_DEG}" \
    --target-speed-kt "${TARGET_SPEED_KT}" \
    --recovery-altitude-ft "${RECOVERY_ALTITUDE_FT}" \
    --xplane-host "${XPLANE_HOST}" \
    --xplane-port "${XPLANE_PORT}" \
    --xplane-udp-port "${XPLANE_UDP_PORT}" \
    --rref-listen-host "${RREF_LISTEN_HOST}" \
    --rref-listen-port "${RREF_LISTEN_PORT}" \
    --rref-frequency-hz "${RREF_FREQUENCY_HZ}" \
    --rref-sample-timeout-seconds "${RREF_SAMPLE_TIMEOUT_SECONDS}" \
    --traffic-slots "${TRAFFIC_SLOTS}" \
    "${AIRCRAFT_ARGS[@]}" \
    "${EXTRA_ARGS[@]}"
