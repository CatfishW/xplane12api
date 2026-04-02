#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from xplane12.api import run_server


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local X-Plane 12 snapshot API")
    parser.add_argument("--bind-host", default="127.0.0.1")
    parser.add_argument("--bind-port", type=int, default=12678)
    parser.add_argument("--stream-host", default="127.0.0.1")
    parser.add_argument("--stream-port", type=int, default=37212)
    parser.add_argument("--xp-base-url", default="http://127.0.0.1:8086/api/v3")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    run_server(
        bind_host=args.bind_host,
        bind_port=args.bind_port,
        stream_host=args.stream_host,
        stream_port=args.stream_port,
        xp_base_url=args.xp_base_url,
    )


if __name__ == "__main__":
    main()
