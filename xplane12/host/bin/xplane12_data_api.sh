#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${XPLANE_ENV_FILE:-/home/tang/xplane12.env}"
if [[ -f "${ENV_FILE}" ]]; then
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
fi

REPO_ROOT="${REPO_ROOT:-/home/tang/Development}"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
API_BIND_HOST="${API_BIND_HOST:-127.0.0.1}"
API_BIND_PORT="${API_BIND_PORT:-12678}"
STREAM_HOST="${STREAM_HOST:-127.0.0.1}"
STREAM_PORT="${STREAM_PORT:-37212}"
API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8086/api/v3}"

SCRIPT_PATH="${REPO_ROOT}/xplane12/host/xplane12_data_api.py"
if [[ ! -f "${SCRIPT_PATH}" ]]; then
    echo "[xplane12_data_api] missing script: ${SCRIPT_PATH}" >&2
    exit 1
fi

export PYTHONUNBUFFERED=1
exec "${PYTHON_BIN}" "${SCRIPT_PATH}" \
    --bind-host "${API_BIND_HOST}" \
    --bind-port "${API_BIND_PORT}" \
    --stream-host "${STREAM_HOST}" \
    --stream-port "${STREAM_PORT}" \
    --xp-base-url "${API_BASE_URL}"
