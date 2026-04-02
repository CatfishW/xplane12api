#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <ssh-target> [diag-args...]" >&2
    echo "Example: $0 tang@your-4090-host" >&2
    exit 1
fi

SSH_TARGET="$1"
REMOTE_HOME="${REMOTE_HOME:-/home/your-user}"
shift || true

remote_args=()
for arg in "$@"; do
    remote_args+=("$(printf '%q' "${arg}")")
done

remote_cmd="${REMOTE_HOME}/xplane12_diag.sh"
if [[ ${#remote_args[@]} -gt 0 ]]; then
    remote_cmd+=" ${remote_args[*]}"
fi

ssh -tt "${SSH_TARGET}" "${remote_cmd}"
