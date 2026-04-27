#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <ssh-target> [diag-args...]" >&2
    echo "Example: $0 user@your-host" >&2
    exit 1
fi

SSH_TARGET="$1"
REMOTE_HOME="${REMOTE_HOME:-/home/your-user}"
shift || true

SERVICE_NAMES=(
    xplane12-simulator.service
    xplane12-autoflight.service
    xplane12-data-api.service
    xplane12-tunnel.service
    xplane-49013-tunnel.service
)

TIMER_NAMES=(
    xplane12-restart.timer
)

remote_args=()
for arg in "$@"; do
    remote_args+=("$(printf '%q' "${arg}")")
done

services_joined="${SERVICE_NAMES[*]}"
timers_joined="${TIMER_NAMES[*]}"
remote_cmd="sudo systemctl enable --now ${timers_joined} && sudo systemctl restart ${services_joined} && sudo systemctl --no-pager --full status ${services_joined} && ${REMOTE_HOME}/xplane12_diag.sh"
if [[ ${#remote_args[@]} -gt 0 ]]; then
    remote_cmd+=" ${remote_args[*]}"
fi

ssh -tt "${SSH_TARGET}" "${remote_cmd}"
