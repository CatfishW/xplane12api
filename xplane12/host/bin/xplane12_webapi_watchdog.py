#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import signal
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path


BIND_FAILURE_MARKER = "LINUX: NET: I could not even bind the socket! Uh-oh!"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Terminate a broken X-Plane startup when the Web API never becomes ready."
    )
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--port", type=int, default=8086)
    parser.add_argument("--timeout-seconds", type=float, default=240.0)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--terminate-grace-seconds", type=float, default=10.0)
    parser.add_argument("--log-path", type=Path, required=True)
    parser.add_argument(
        "--ready-url",
        default=None,
        help="Optional HTTP endpoint to probe. Defaults to http://127.0.0.1:<port>/api/v3/datarefs/count",
    )
    return parser


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def api_ready(url: str, timeout_seconds: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError, urllib.error.HTTPError):
        return False


def log_contains_bind_failure(log_path: Path) -> bool:
    try:
        return BIND_FAILURE_MARKER in log_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False


def terminate_process(pid: int, grace_seconds: float) -> None:
    if not process_alive(pid):
        return

    print(
        f"[xplane12_webapi_watchdog] terminating pid={pid} after Web API startup failure",
        flush=True,
    )
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return

    deadline = time.monotonic() + max(1.0, grace_seconds)
    while time.monotonic() < deadline:
        if not process_alive(pid):
            return
        time.sleep(0.25)

    if process_alive(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return


def wait_for_api(
    pid: int,
    ready_url: str,
    timeout_seconds: float,
    poll_seconds: float,
    log_path: Path,
    terminate_grace_seconds: float,
) -> int:
    deadline = time.monotonic() + max(1.0, timeout_seconds)
    while time.monotonic() < deadline:
        if not process_alive(pid):
            print("[xplane12_webapi_watchdog] X-Plane exited before Web API became ready", flush=True)
            return 0

        if api_ready(ready_url):
            print(f"[xplane12_webapi_watchdog] Web API ready at {ready_url}", flush=True)
            return 0

        if log_contains_bind_failure(log_path):
            print("[xplane12_webapi_watchdog] detected Web API bind failure in Log.txt", flush=True)
            terminate_process(pid, terminate_grace_seconds)
            return 0

        time.sleep(max(0.2, poll_seconds))

    if process_alive(pid) and not api_ready(ready_url):
        print(
            f"[xplane12_webapi_watchdog] timeout waiting for Web API at {ready_url}",
            flush=True,
        )
        terminate_process(pid, terminate_grace_seconds)
    return 0


def main() -> int:
    args = build_arg_parser().parse_args()
    ready_url = args.ready_url or f"http://127.0.0.1:{args.port}/api/v3/datarefs/count"
    return wait_for_api(
        pid=args.pid,
        ready_url=ready_url,
        timeout_seconds=args.timeout_seconds,
        poll_seconds=args.poll_seconds,
        log_path=args.log_path,
        terminate_grace_seconds=args.terminate_grace_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
