#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${XPLANE_ENV_FILE:-/home/your-user/xplane12.env}"
if [[ -f "${ENV_FILE}" ]]; then
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
fi

REPO_ROOT="${REPO_ROOT:-/home/your-user/Development}"
XPLANE_HOME="${XPLANE_HOME:-/home/your-user/X-Plane 12}"
XPLANE_BIN="${XPLANE_BIN:-${XPLANE_HOME}/X-Plane-x86_64}"
XPLANE_ARGS="${XPLANE_ARGS:-}"
STEAM_BIN="${STEAM_BIN:-${HOME}/.steam/debian-installation/steam.sh}"
STEAM_ARGS="${STEAM_ARGS:--silent}"
STEAM_BOOTSTRAP_TIMEOUT_SECONDS="${STEAM_BOOTSTRAP_TIMEOUT_SECONDS:-20}"

if [[ ! -x "${XPLANE_BIN}" ]]; then
    echo "[xplane12_launch] missing executable: ${XPLANE_BIN}" >&2
    exit 1
fi

PLUGIN_SYNC_SCRIPT="${REPO_ROOT}/xplane12/host/bin/xplane12_plugin_sync.sh"
if [[ -x "${PLUGIN_SYNC_SCRIPT}" ]]; then
    "${PLUGIN_SYNC_SCRIPT}"
fi

cd "${XPLANE_HOME}"
for name in \
    DISPLAY \
    WAYLAND_DISPLAY \
    XAUTHORITY \
    DBUS_SESSION_BUS_ADDRESS \
    XDG_RUNTIME_DIR \
    LANG \
    PATH \
    DESKTOP_SESSION \
    GDMSESSION \
    GNOME_SHELL_SESSION_MODE \
    XDG_SESSION_CLASS \
    XDG_SESSION_DESKTOP \
    XDG_SESSION_TYPE \
    XDG_CONFIG_DIRS \
    XDG_CURRENT_DESKTOP \
    XDG_DATA_DIRS \
    XDG_MENU_PREFIX \
    QT_IM_MODULE \
    XMODIFIERS \
    GTK_MODULES; do
    if [[ -n "${!name:-}" ]]; then
        export "${name}"
    fi
done
read -r -a EXTRA_ARGS <<< "${XPLANE_ARGS}"
echo "[xplane12_launch] starting ${XPLANE_BIN} ${XPLANE_ARGS}" >&2

steam_client_running() {
    pgrep -u "$(id -u)" -f "${HOME}/.steam/debian-installation/ubuntu12_32/steam" >/dev/null 2>&1 \
        || pgrep -u "$(id -u)" -f "${HOME}/.steam/debian-installation/steam.sh" >/dev/null 2>&1
}

maybe_start_steam_client() {
    if [[ "${XPLANE_BIN}" != *"/steamapps/common/"*"/X-Plane-x86_64" ]]; then
        return
    fi
    if steam_client_running; then
        echo "[xplane12_launch] steam client already running" >&2
        return
    fi
    if [[ ! -x "${STEAM_BIN}" ]]; then
        echo "[xplane12_launch] steam bootstrap skipped, missing client: ${STEAM_BIN}" >&2
        return
    fi

    local -a steam_extra_args=()
    read -r -a steam_extra_args <<< "${STEAM_ARGS}"
    echo "[xplane12_launch] bootstrapping steam client: ${STEAM_BIN} ${STEAM_ARGS}" >&2
    "${STEAM_BIN}" "${steam_extra_args[@]}" >/tmp/xplane12-steam-bootstrap.log 2>&1 &

    local elapsed=0
    while (( elapsed < STEAM_BOOTSTRAP_TIMEOUT_SECONDS )); do
        if steam_client_running; then
            echo "[xplane12_launch] steam client ready" >&2
            return
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    echo "[xplane12_launch] steam client did not appear within ${STEAM_BOOTSTRAP_TIMEOUT_SECONDS}s" >&2
}

maybe_start_steam_client

list_xplane_pids() {
    local pid=""
    local exe_path=""
    while IFS= read -r pid; do
        [[ -z "${pid}" ]] && continue
        exe_path="$(readlink -f "/proc/${pid}/exe" 2>/dev/null || true)"
        [[ "${exe_path}" == "${XPLANE_PROCESS}" ]] || continue
        printf '%s\n' "${pid}"
    done < <(pgrep -f "${XPLANE_PROCESS}" || true)
}

wait_for_existing_xplane() {
    local existing_pid=""
    existing_pid="$(list_xplane_pids | head -n 1 || true)"
    if [[ -z "${existing_pid}" ]]; then
        return 1
    fi

    echo "[xplane12_launch] reusing existing pid ${existing_pid}" >&2
    while kill -0 "${existing_pid}" >/dev/null 2>&1; do
        sleep 5
    done
    return 0
}

wait_for_webapi_port() {
    local port="${1:-8086}"
    local timeout="${2:-30}"
    local elapsed=0

    while (( elapsed < timeout )); do
        if ! ss -ltn "( sport = :${port} )" | grep -q ":${port}"; then
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    echo "[xplane12_launch] port ${port} still busy after ${timeout}s; proceeding anyway" >&2
    return 0
}

if [[ "${XPLANE_BIN}" == "/usr/games/steam" ]]; then
    XPLANE_PROCESS="${XPLANE_HOME}/X-Plane-x86_64"
    if wait_for_existing_xplane; then
        exit 0
    fi

    before_pids="$(list_xplane_pids)"
    launch_epoch="$(date +%s)"
    "${XPLANE_BIN}" "${EXTRA_ARGS[@]}" &
    launcher_pid=$!
    trap 'kill "${launcher_pid}" >/dev/null 2>&1 || true' EXIT

    xplane_pid=""
    best_etime=""
    for _ in $(seq 1 60); do
        elapsed_since_launch=$(( $(date +%s) - launch_epoch + 5 ))
        while IFS= read -r pid; do
            [[ -z "${pid}" ]] && continue
            if [[ " ${before_pids} " == *" ${pid} "* ]]; then
                continue
            fi
            etimes="$(ps -o etimes= -p "${pid}" 2>/dev/null | tr -d '[:space:]')"
            [[ -z "${etimes}" ]] && continue
            if (( etimes > elapsed_since_launch )); then
                continue
            fi
            if [[ -z "${xplane_pid}" || etimes -lt best_etime ]]; then
                xplane_pid="${pid}"
                best_etime="${etimes}"
            fi
        done < <(list_xplane_pids)
        [[ -n "${xplane_pid}" ]] && break
        if ! kill -0 "${launcher_pid}" >/dev/null 2>&1; then
            wait "${launcher_pid}"
            exit $?
        fi
        sleep 1
    done

    if [[ -z "${xplane_pid}" ]]; then
        echo "[xplane12_launch] X-Plane process did not appear" >&2
        wait "${launcher_pid}"
        exit $?
    fi

    echo "[xplane12_launch] tracking pid ${xplane_pid}" >&2
    while kill -0 "${xplane_pid}" >/dev/null 2>&1; do
        sleep 5
    done
    trap - EXIT
    wait "${launcher_pid}" || true
    exit 0
fi

XPLANE_PROCESS="${XPLANE_BIN}"
if wait_for_existing_xplane; then
    exit 0
fi
wait_for_webapi_port 8086 30
exec "${XPLANE_BIN}" "${EXTRA_ARGS[@]}"
