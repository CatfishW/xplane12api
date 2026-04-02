#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${XPLANE_ENV_FILE:-/home/your-user/xplane12.env}"
if [[ -f "${ENV_FILE}" ]]; then
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
fi

XPLANE_HOME="${XPLANE_HOME:-/home/your-user/X-Plane 12}"
XPLANE_BIN="${XPLANE_BIN:-${XPLANE_HOME}/X-Plane-x86_64}"
XPLANE_ARGS="${XPLANE_ARGS:-}"

if [[ ! -x "${XPLANE_BIN}" ]]; then
    echo "[xplane12_launch] missing executable: ${XPLANE_BIN}" >&2
    exit 1
fi

cd "${XPLANE_HOME}"
for name in DISPLAY WAYLAND_DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR; do
    if [[ -n "${!name:-}" ]]; then
        export "${name}"
    fi
done
read -r -a EXTRA_ARGS <<< "${XPLANE_ARGS}"
echo "[xplane12_launch] starting ${XPLANE_BIN} ${XPLANE_ARGS}" >&2

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

if [[ "${XPLANE_BIN}" == "/usr/games/steam" ]]; then
    XPLANE_PROCESS="${XPLANE_HOME}/X-Plane-x86_64"
    existing_pid="$(list_xplane_pids | head -n 1 || true)"
    if [[ -n "${existing_pid}" ]]; then
        echo "[xplane12_launch] reusing existing pid ${existing_pid}" >&2
        while kill -0 "${existing_pid}" >/dev/null 2>&1; do
            sleep 5
        done
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

exec "${XPLANE_BIN}" "${EXTRA_ARGS[@]}"
