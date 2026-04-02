#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "Usage: $0 [--no-diag] <ssh-target> [diag-args...]" >&2
    echo "Example: $0 tang@your-4090-host --logs 200 xplane12-autoflight.service" >&2
}

RUN_DIAG=1
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-diag)
            RUN_DIAG=0
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            break
            ;;
    esac
done

if [[ $# -lt 1 ]]; then
    usage
    exit 1
fi

SSH_TARGET="$1"
shift || true

DIAG_ARGS=()
for arg in "$@"; do
    DIAG_ARGS+=("$(printf '%q' "${arg}")")
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
FEATURE_ROOT="$(cd "${HOST_ROOT}/.." && pwd)"
LOCAL_DEV_ROOT="$(cd "${FEATURE_ROOT}/.." && pwd)"
LOCAL_BIN_DIR="${HOST_ROOT}/bin"
LOCAL_SYSTEMD_DIR="${HOST_ROOT}/systemd"
LOCAL_ENV_DIR="${HOST_ROOT}/env"
REMOTE_HOME="${REMOTE_HOME:-/home/your-user}"
REMOTE_DEV_ROOT="${REMOTE_DEV_ROOT:-${REMOTE_HOME}/Development}"
REMOTE_XPLANE_DIR="${REMOTE_DEV_ROOT}/xplane12"
REMOTE_API_HEALTH_URL="${REMOTE_API_HEALTH_URL:-http://127.0.0.1:12678/health}"

SERVICE_NAMES=(
    xplane12-simulator.service
    xplane12-autoflight.service
    xplane12-data-api.service
    xplane12-tunnel.service
    xplane-49013-tunnel.service
)

HOME_SCRIPTS=(
    xplane12_launch.sh
    xplane12_autoflight.sh
    xplane12_data_api.sh
    xplane12_api_tunnel.sh
    xplane12_diag.sh
    tunnel_xplane_49013.sh
)

SYSTEMD_FILES=(
    xplane12-simulator.service
    xplane12-autoflight.service
    xplane12-data-api.service
    xplane12-tunnel.service
    xplane-49013-tunnel.service
)

mkdir_remote_dirs() {
    ssh "${SSH_TARGET}" "mkdir -p '${REMOTE_HOME}' '${REMOTE_DEV_ROOT}' '${REMOTE_XPLANE_DIR}'" </dev/null
}

copy_to_home() {
    local local_path="$1"
    local remote_name="$2"
    echo "[install_xplane12_4090_host] copying ${local_path} -> ${SSH_TARGET}:${REMOTE_HOME}/${remote_name}"
    scp "${local_path}" "${SSH_TARGET}:${REMOTE_HOME}/${remote_name}" </dev/null
}

copy_to_dev_root() {
    local local_path="$1"
    local remote_path="$2"
    local remote_dir
    remote_dir="$(dirname "${remote_path}")"
    ssh "${SSH_TARGET}" "mkdir -p '${remote_dir}'" </dev/null
    echo "[install_xplane12_4090_host] copying ${local_path} -> ${SSH_TARGET}:${remote_path}"
    scp "${local_path}" "${SSH_TARGET}:${remote_path}" </dev/null
}

install_remote() {
    local services_joined diag_args_joined remote_env_cmd
    services_joined="${SERVICE_NAMES[*]}"
    diag_args_joined="${DIAG_ARGS[*]}"
    remote_env_cmd="REMOTE_HOME=$(printf '%q' "${REMOTE_HOME}")"
    remote_env_cmd+=" REMOTE_API_HEALTH_URL=$(printf '%q' "${REMOTE_API_HEALTH_URL}")"
    remote_env_cmd+=" SERVICES_JOINED=$(printf '%q' "${services_joined}")"
    remote_env_cmd+=" RUN_DIAG=$(printf '%q' "${RUN_DIAG}")"
    remote_env_cmd+=" DIAG_ARGS_JOINED=$(printf '%q' "${diag_args_joined}")"
    ssh "${SSH_TARGET}" "${remote_env_cmd} bash -s" <<'EOF'
set -euo pipefail

chmod 755 \
    "${REMOTE_HOME}/xplane12_launch.sh" \
    "${REMOTE_HOME}/xplane12_autoflight.sh" \
    "${REMOTE_HOME}/xplane12_data_api.sh" \
    "${REMOTE_HOME}/xplane12_api_tunnel.sh" \
    "${REMOTE_HOME}/xplane12_diag.sh" \
    "${REMOTE_HOME}/tunnel_xplane_49013.sh"

if [[ ! -f "${REMOTE_HOME}/xplane12.env" ]]; then
    cp "${REMOTE_HOME}/xplane12.env.example" "${REMOTE_HOME}/xplane12.env"
fi

sudo install -m 644 "${REMOTE_HOME}/xplane12-simulator.service" /etc/systemd/system/xplane12-simulator.service
sudo install -m 644 "${REMOTE_HOME}/xplane12-autoflight.service" /etc/systemd/system/xplane12-autoflight.service
sudo install -m 644 "${REMOTE_HOME}/xplane12-data-api.service" /etc/systemd/system/xplane12-data-api.service
sudo install -m 644 "${REMOTE_HOME}/xplane12-tunnel.service" /etc/systemd/system/xplane12-tunnel.service
sudo install -m 644 "${REMOTE_HOME}/xplane-49013-tunnel.service" /etc/systemd/system/xplane-49013-tunnel.service

sudo systemctl daemon-reload
sudo systemctl enable ${SERVICES_JOINED}
sudo systemctl restart ${SERVICES_JOINED}
sudo systemctl --no-pager --full status ${SERVICES_JOINED}
for attempt in $(seq 1 30); do
    if curl -fsS "${REMOTE_API_HEALTH_URL}"; then
        break
    fi
    if [[ "$attempt" == "30" ]]; then
        exit 1
    fi
    sleep 2
done
if [[ "${RUN_DIAG}" == "1" ]]; then
    printf '\n'
    if [[ -n "${DIAG_ARGS_JOINED}" ]]; then
        # shellcheck disable=SC2086
        "${REMOTE_HOME}/xplane12_diag.sh" ${DIAG_ARGS_JOINED}
    else
        "${REMOTE_HOME}/xplane12_diag.sh"
    fi
fi
EOF
}

main() {
    mkdir_remote_dirs

    for name in "${HOME_SCRIPTS[@]}"; do
        copy_to_home "${LOCAL_BIN_DIR}/${name}" "${name}"
    done

    for name in "${SYSTEMD_FILES[@]}"; do
        copy_to_home "${LOCAL_SYSTEMD_DIR}/${name}" "${name}"
    done

    copy_to_home "${LOCAL_ENV_DIR}/xplane12.env.example" "xplane12.env.example"

    while IFS= read -r local_path; do
        remote_rel="${local_path#${LOCAL_DEV_ROOT}/}"
        remote_path="${REMOTE_DEV_ROOT}/${remote_rel}"
        copy_to_dev_root "${local_path}" "${remote_path}"
    done < <(python3 - "${LOCAL_DEV_ROOT}" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
for path in sorted((root / "xplane12").rglob("*.py")):
    print(path)
PY
)

    install_remote
}

main
