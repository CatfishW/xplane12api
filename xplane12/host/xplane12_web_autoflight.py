#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from xplane12.autopilot import request_json, start_air_session_once
from xplane12.host import xplane_remote_relay

API_READY_POLL_SECONDS = 5.0
API_READY_TIMEOUT_SECONDS = 600.0


def api_is_ready(base_url: str) -> bool:
    try:
        request_json("GET", "/datarefs/count", base_url=base_url)
        return True
    except Exception:
        return False


def wait_for_api_ready(
    *,
    base_url: str,
    poll_seconds: float,
    timeout_seconds: float,
    process: subprocess.Popen[bytes] | None = None,
) -> None:
    deadline = time.monotonic() + timeout_seconds if timeout_seconds > 0 else None
    while True:
        if api_is_ready(base_url):
            print("[xplane12_web_autoflight] api_ready", flush=True)
            return
        if process is not None:
            returncode = process.poll()
            if returncode is not None:
                raise RuntimeError(
                    f"X-Plane process exited before API became ready (code {returncode})"
                )
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("Timed out waiting for X-Plane Web API readiness")
        print("[xplane12_web_autoflight] waiting_for_api_ready", flush=True)
        time.sleep(poll_seconds)


def launch_xplane_process(command: str, working_directory: str | None) -> subprocess.Popen[bytes]:
    argv = shlex.split(command)
    if not argv:
        raise ValueError("xplane command is empty")
    cwd = str(Path(working_directory).expanduser()) if working_directory else None
    print(f"[xplane12_web_autoflight] launching_xplane command={argv[0]}", flush=True)
    return subprocess.Popen(argv, cwd=cwd)


def stop_process(process: subprocess.Popen[bytes], grace_seconds: float = 10.0) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=grace_seconds)


def build_relay_args(args: argparse.Namespace) -> argparse.Namespace:
    relay_args = xplane_remote_relay.build_arg_parser().parse_args([])
    for name in (
        "mode",
        "listen_host",
        "listen_port",
        "broadcast_hz",
        "duration_seconds",
        "target_altitude_ft",
        "target_heading_deg",
        "target_speed_kt",
        "recovery_altitude_ft",
        "xplane_host",
        "xplane_port",
        "xplane_udp_port",
        "rref_listen_host",
        "rref_listen_port",
        "rref_frequency_hz",
        "rref_sample_timeout_seconds",
        "traffic_slots",
        "restart_on_crash",
        "restart_confirm_seconds",
        "restart_min_interval_seconds",
        "restart_grace_seconds",
    ):
        setattr(relay_args, name, getattr(args, name))
    relay_args.webapi_base_url = args.api_base_url
    relay_args.aircraft_path = args.aircraft_path
    return relay_args


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch X-Plane 12, wait for Web API readiness, air-start once, and hand off to the endless-flight relay"
    )
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8086/api/v3")
    parser.add_argument("--api-ready-poll-seconds", type=float, default=API_READY_POLL_SECONDS)
    parser.add_argument("--api-ready-timeout-seconds", type=float, default=API_READY_TIMEOUT_SECONDS)
    parser.add_argument("--xplane-command")
    parser.add_argument("--xplane-working-directory")
    parser.add_argument("--aircraft-path")
    parser.add_argument("--skip-air-start", action="store_true")
    parser.add_argument("--restart-on-crash", action="store_true", default=True)
    parser.add_argument("--no-restart-on-crash", dest="restart_on_crash", action="store_false")
    parser.add_argument("--restart-confirm-seconds", type=float, default=8.0)
    parser.add_argument("--restart-min-interval-seconds", type=float, default=45.0)
    parser.add_argument("--restart-grace-seconds", type=float, default=25.0)
    parser.add_argument("--mode", choices=("mock", "xpc", "rref", "auto"), default="rref")
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=37211)
    parser.add_argument("--broadcast-hz", type=float, default=5.0)
    parser.add_argument("--duration-seconds", type=float, default=0.0)
    parser.add_argument("--target-altitude-ft", type=float, default=8500.0)
    parser.add_argument("--target-heading-deg", type=float, default=90.0)
    parser.add_argument("--target-speed-kt", type=float, default=160.0)
    parser.add_argument("--recovery-altitude-ft", type=float, default=4500.0)
    parser.add_argument("--xplane-host", default="127.0.0.1")
    parser.add_argument("--xplane-port", type=int, default=49009)
    parser.add_argument("--xplane-udp-port", type=int, default=49000)
    parser.add_argument("--rref-listen-host", default="0.0.0.0")
    parser.add_argument("--rref-listen-port", type=int, default=49004)
    parser.add_argument("--rref-frequency-hz", type=float, default=10.0)
    parser.add_argument("--rref-sample-timeout-seconds", type=float, default=1.25)
    parser.add_argument("--traffic-slots", type=int, default=5)
    return parser


def run(args: argparse.Namespace | None = None) -> None:
    parsed = build_arg_parser().parse_args() if args is None else args
    xplane_process: subprocess.Popen[bytes] | None = None
    try:
        if api_is_ready(parsed.api_base_url):
            print("[xplane12_web_autoflight] api_already_ready", flush=True)
        elif parsed.xplane_command:
            xplane_process = launch_xplane_process(
                parsed.xplane_command,
                parsed.xplane_working_directory,
            )
        else:
            print("[xplane12_web_autoflight] waiting_for_existing_xplane_process", flush=True)

        wait_for_api_ready(
            base_url=parsed.api_base_url,
            poll_seconds=parsed.api_ready_poll_seconds,
            timeout_seconds=parsed.api_ready_timeout_seconds,
            process=xplane_process,
        )

        if not parsed.skip_air_start:
            air_start_kwargs = {"base_url": parsed.api_base_url}
            if parsed.aircraft_path:
                air_start_kwargs["aircraft_path"] = parsed.aircraft_path
            start_air_session_once(**air_start_kwargs)

        xplane_remote_relay.run(build_relay_args(parsed))
    finally:
        if xplane_process is not None:
            stop_process(xplane_process)


if __name__ == "__main__":
    run()
