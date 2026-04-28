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
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
STEAM_BIN="${STEAM_BIN:-${HOME}/.steam/debian-installation/steam.sh}"
STEAM_ARGS="${STEAM_ARGS:--silent}"
STEAM_BOOTSTRAP_TIMEOUT_SECONDS="${STEAM_BOOTSTRAP_TIMEOUT_SECONDS:-20}"
XPLANE_PROCESS_EXIT_TIMEOUT_SECONDS="${XPLANE_PROCESS_EXIT_TIMEOUT_SECONDS:-180}"
WEBAPI_PORT="${WEBAPI_PORT:-8086}"
WEBAPI_PORT_WAIT_TIMEOUT_SECONDS="${WEBAPI_PORT_WAIT_TIMEOUT_SECONDS:-180}"
WEBAPI_STARTUP_TIMEOUT_SECONDS="${WEBAPI_STARTUP_TIMEOUT_SECONDS:-240}"

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

maybe_start_safe_mode_watchdog() {
    local watchdog_script="${REPO_ROOT}/xplane12/host/bin/xplane12_safe_mode_watchdog.py"
    if [[ -z "${DISPLAY:-}" || -z "${XAUTHORITY:-}" ]]; then
        return
    fi
    if [[ ! -x "${PYTHON_BIN}" || ! -f "${watchdog_script}" ]]; then
        return
    fi
    "${PYTHON_BIN}" "${watchdog_script}" >/tmp/xplane12-safe-mode-watchdog.log 2>&1 &
}

maybe_start_webapi_watchdog() {
    local xplane_pid="${1:-}"
    local watchdog_script="${REPO_ROOT}/xplane12/host/bin/xplane12_webapi_watchdog.py"
    local log_path="${XPLANE_HOME}/Log.txt"
    if [[ -z "${xplane_pid}" ]]; then
        return
    fi
    if [[ ! -x "${PYTHON_BIN}" || ! -f "${watchdog_script}" ]]; then
        return
    fi
    "${PYTHON_BIN}" "${watchdog_script}" \
        --pid "${xplane_pid}" \
        --port "${WEBAPI_PORT}" \
        --timeout-seconds "${WEBAPI_STARTUP_TIMEOUT_SECONDS}" \
        --log-path "${log_path}" \
        >/tmp/xplane12-webapi-watchdog.log 2>&1 &
}

log_process_snapshot() {
    local pid=""
    for pid in "$@"; do
        [[ -n "${pid}" ]] || continue
        ps -o pid=,ppid=,etimes=,cmd= -p "${pid}" 2>/dev/null || true
    done
}

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
    local timeout="${1:-180}"
    local elapsed=0
    local saw_existing=0
    local -a existing_pids=()

    while true; do
        mapfile -t existing_pids < <(list_xplane_pids)
        if (( ${#existing_pids[@]} == 0 )); then
            if (( saw_existing )); then
                echo "[xplane12_launch] previous X-Plane process exited; continuing startup" >&2
                return 0
            fi
            return 1
        fi

        saw_existing=1
        if (( elapsed == 0 || elapsed % 5 == 0 )); then
            echo "[xplane12_launch] waiting for existing X-Plane pid(s): ${existing_pids[*]}" >&2
            log_process_snapshot "${existing_pids[@]}" >&2
        fi
        if (( elapsed >= timeout )); then
            echo "[xplane12_launch] existing X-Plane pid(s) still alive after ${timeout}s" >&2
            log_process_snapshot "${existing_pids[@]}" >&2
            return 2
        fi

        sleep 1
        elapsed=$((elapsed + 1))
    done
}

port_listener_snapshot() {
    local port="${1:-8086}"
    ss -H -ltnp "( sport = :${port} )" 2>/dev/null || true
}

wait_for_webapi_port() {
    local port="${1:-8086}"
    local timeout="${2:-180}"
    local elapsed=0
    local listeners=""

    while (( elapsed < timeout )); do
        listeners="$(port_listener_snapshot "${port}")"
        if [[ -z "${listeners}" ]]; then
            return 0
        fi
        if (( elapsed == 0 || elapsed % 5 == 0 )); then
            echo "[xplane12_launch] waiting for port ${port} to clear" >&2
            printf '%s\n' "${listeners}" >&2
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    listeners="$(port_listener_snapshot "${port}")"
    echo "[xplane12_launch] port ${port} still busy after ${timeout}s; aborting startup" >&2
    if [[ -n "${listeners}" ]]; then
        printf '%s\n' "${listeners}" >&2
    fi
    return 1
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

    maybe_start_safe_mode_watchdog
    maybe_start_webapi_watchdog "${xplane_pid}"
    echo "[xplane12_launch] tracking pid ${xplane_pid}" >&2
    while kill -0 "${xplane_pid}" >/dev/null 2>&1; do
        sleep 5
    done
    trap - EXIT
    wait "${launcher_pid}" || true
    exit 0
fi

XPLANE_PROCESS="${XPLANE_BIN}"
if wait_for_existing_xplane "${XPLANE_PROCESS_EXIT_TIMEOUT_SECONDS}"; then
    :
else
    wait_status=$?
    if (( wait_status > 1 )); then
        exit 1
    fi
fi
wait_for_webapi_port "${WEBAPI_PORT}" "${WEBAPI_PORT_WAIT_TIMEOUT_SECONDS}"
maybe_start_safe_mode_watchdog
maybe_start_webapi_watchdog "$$"
exec "${XPLANE_BIN}" "${EXTRA_ARGS[@]}"
