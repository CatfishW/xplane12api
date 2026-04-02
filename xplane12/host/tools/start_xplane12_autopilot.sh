#!/usr/bin/env bash
set -euo pipefail


if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <ssh-target> [diag-args...]" >&2
    echo "Example: $0 4090 --logs 120 xplane12-autoflight.service" >&2
    exit 1
fi

SSH_TARGET="$1"
shift || true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"${SCRIPT_DIR}/install_xplane12_4090_host.sh" "${SSH_TARGET}" "$@"
