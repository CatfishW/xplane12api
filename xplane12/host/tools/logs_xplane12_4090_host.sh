#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "Usage: $0 <ssh-target> <service> [--follow] [--lines N]" >&2
    echo "Example: $0 tang@your-4090-host xplane12-autoflight.service --lines 200" >&2
}

if [[ $# -lt 2 ]]; then
    usage
    exit 1
fi

SSH_TARGET="$1"
SERVICE_NAME="$2"
shift 2 || true

FOLLOW=0
LINES=100
while [[ $# -gt 0 ]]; do
    case "$1" in
        --follow|-f)
            FOLLOW=1
            ;;
        --lines|-n)
            shift
            if [[ $# -eq 0 ]]; then
                usage
                exit 1
            fi
            LINES="$1"
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage
            exit 1
            ;;
    esac
    shift
 done

cmd="journalctl -u $(printf '%q' "${SERVICE_NAME}") -n $(printf '%q' "${LINES}") --no-pager"
if [[ "${FOLLOW}" == "1" ]]; then
    cmd="journalctl -u $(printf '%q' "${SERVICE_NAME}") -n $(printf '%q' "${LINES}") -f"
fi

ssh -tt "${SSH_TARGET}" "sudo ${cmd}"
